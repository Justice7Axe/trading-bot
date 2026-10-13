"""주도주 스크리너 — 장중 실시간 포착 (1분마다).

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_intraday              # 08:00~20:00 반복 (NXT 프리·애프터마켓 포함)
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_intraday --once --force --no-telegram   # 1회 점검

- 매 주기: 실시간 조회 순위(1분, 당일 누적) + 거래대금 상위 100 → 후보 → 조건 판정
- 새로 조건을 만족한 종목만 텔레그램으로 알림 (같은 날 같은 종목은 1회)
- 텔레그램으로 '멈춰'(또는 중지/정지/stop)를 보내면 5초 안에 스캐너 종료
- 매수 신호: 전일 '다음 거래일 관심 종목' + 전일 '쉬어 가는 주도주' + 장중 포착 종목 + 조기 트리거 종목의
  1분봉에서 지지 반등/돌파 후 눌림 → 🎯 알림
- 조기 발굴(early_watch.py): ②조회 급등 → 감시 추가(30분마다 👀 요약), ③대금 가속 → 🚀, ⑤조기 주도주(09:20 전 500억&+3%) → 🏁 즉시 알림 + 감시 추가, ④08:50 🌅 프리마켓 주목
- 순위 스냅샷과 포착 기록, 장중 외국인·기관 잠정치(5분마다 확인, 바뀔 때만)는 data/screener.duckdb 에 저장 (추후 백테스트용)
- 로그: data/logs/screener_YYYYMMDD.log
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta
from typing import Optional

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import PROJECT_ROOT, load_env
from kiwoom_trading.common.keep_awake import prevent_sleep_until_exit
from kiwoom_trading.common.telegram import peek_messages, send_telegram_message
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.screener.conditions import format_evaluation
from kiwoom_trading.screener.early_watch import EarlyDetector, EarlyHit, format_premarket, format_watch_adds
from kiwoom_trading.screener.engine import Screener
from kiwoom_trading.screener.market_data import KiwoomMarket
from kiwoom_trading.screener.signal_watch import SignalWatcher, format_signals
from kiwoom_trading.screener.store import ScreenerStore


MARKET_OPEN = dtime(8, 0)          # NXT 프리마켓 시작 (KRX 정규장 09:00)
MARKET_SCAN_END = dtime(20, 0)     # NXT 애프터마켓 종료 (KRX 정규장 15:30)
HOLIDAY_CHECK_AFTER = dtime(8, 10)


def _setup_logging(now: datetime) -> None:
    log_dir = os.path.join(PROJECT_ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(log_dir, f"screener_{now:%Y%m%d}.log"), encoding="utf-8"), logging.StreamHandler()],
    )


STOP_WORDS = {"멈춰", "중지", "정지", "stop"}
STOP_CHECK_SECONDS = 5


class StopListener:
    """텔레그램 '멈춰' 명령 감지. 등록된 채팅방에서, 스캐너 시작 이후에 온 메시지만 본다."""

    def __init__(self, enabled: bool) -> None:
        load_env()
        self.enabled = enabled
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.started_at = time.time()
        self._last_check = 0.0

    def requested(self) -> Optional[str]:
        if not self.enabled or not self.chat_id or time.monotonic() - self._last_check < STOP_CHECK_SECONDS:
            return None
        self._last_check = time.monotonic()
        for msg in peek_messages():
            text = msg["text"].strip().lstrip("/").rstrip("!.~ ").lower()
            if msg["chat_id"] == self.chat_id and msg["date"] >= self.started_at and text in STOP_WORDS:
                return msg["text"]
        return None

    def sleep(self, seconds: float) -> Optional[str]:
        """seconds 동안 기다리되, 그 사이 '멈춰'가 오면 즉시 반환."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            command = self.requested()
            if command:
                return command
            time.sleep(min(STOP_CHECK_SECONDS, max(0.0, end - time.monotonic())))
        return self.requested()


INVESTOR_EVERY_MINUTES = 5          # 장중 외국인·기관 잠정치 확인 주기 (실제 갱신은 하루 5~6번)
INVESTOR_WINDOW = (dtime(9, 10), dtime(15, 45))


class InvestorRecorder:
    """장중 외국인·기관 순매수 잠정치(ka10063)를 5분마다 확인해서 바뀌었을 때만 저장 → 추후 수급 백테스트용."""

    def __init__(self) -> None:
        self.last_check: Optional[datetime] = None
        self.last_sum: dict[str, int] = {}

    def step(self, now: datetime, market: KiwoomMarket, store: ScreenerStore) -> None:
        if not (INVESTOR_WINDOW[0] <= now.time() <= INVESTOR_WINDOW[1]):
            return
        if self.last_check and now - self.last_check < timedelta(minutes=INVESTOR_EVERY_MINUTES):
            return
        self.last_check = now
        for investor, code in (("foreign", "6"), ("institution", "7")):
            values = market.investor_intraday(code)
            checksum = sum(abs(v) for v in values.values())
            if values and checksum != self.last_sum.get(investor):
                self.last_sum[investor] = checksum
                store.save_investor_intraday(now.replace(tzinfo=None), investor, values)
                logging.info("장중 %s 수급 스냅샷 저장: %s종목", investor, len(values))


ADD_SUMMARY_MINUTES = 30   # 조회 급등 감시 추가 알림은 30분마다 묶어서 (매수 신호 🎯 는 즉시)
URGENT_HEADERS = {         # 즉시 알림하는 조기 트리거
    "조기 주도주": "🏁 조기 주도주 {now:%H:%M} — 09:20 전 누적 대금 500억 & +3% (그날 주도주 적중 약 38%)",
    "대금 가속": "🚀 거래대금 가속 — 오늘의 주도주 {now:%H:%M} (그날 최종 대금 50위 적중 95%)",
}


class EarlyRunner:
    """조기 발굴 트리거(②조회 급등 ③대금 가속 ④프리마켓 주목 ⑤조기 주도주) → 매수 신호 감시 목록에 추가."""

    def __init__(self, screener: Screener, watcher: SignalWatcher, store: ScreenerStore, now: datetime) -> None:
        self.detector = EarlyDetector(screener.hist, screener.names)
        self.watcher = watcher
        self.rest = store.previous_rest_leaders(now.date())
        self.added_today = len(store.watch_adds(now.date()))
        self.pending: list[EarlyHit] = []
        self.last_summary = now
        # 08:50 이후에 (재)시작하면 프리마켓 요약은 건너뜀
        self.premarket_sent = now.time() >= self.detector.config.premarket_summary_at

    def step(self, now: datetime, market: KiwoomMarket, search_1m: list, value_top: list, telegram: bool) -> None:
        cfg = self.detector.config
        hits = self.detector.update(now, search_1m, value_top)
        if not self.premarket_sent and now.time() >= cfg.premarket_summary_at:
            self.premarket_sent = True
            focus = self.detector.premarket_focus(market, self.rest)
            for h in focus:
                self._add(h, now)
            if telegram:
                send_telegram_message(format_premarket(now, focus))
        urgent: dict[str, list[EarlyHit]] = {}
        for h in hits:
            if self.added_today >= cfg.max_watch_adds:
                break
            if self._add(h, now):
                if h.source in URGENT_HEADERS:
                    urgent.setdefault(h.source, []).append(h)
                else:
                    self.pending.append(h)
        if telegram:   # 조기 주도주·대금 가속은 하루 10건 안팎 → 즉시 알림 (매수 신호 아님)
            for source, items in urgent.items():
                send_telegram_message(URGENT_HEADERS[source].format(now=now) + "\n"
                                      + "\n".join(f"· {h.name}({h.code}) {h.reason}" for h in items)
                                      + "\n(진입 신호 아님: 포착 즉시 매수는 백테스트상 손실)")
        if self.pending and now - self.last_summary >= timedelta(minutes=ADD_SUMMARY_MINUTES):
            if telegram:
                send_telegram_message(format_watch_adds(now, self.pending))
            self.pending, self.last_summary = [], now

    def _add(self, h: EarlyHit, now: datetime) -> bool:
        added = self.watcher.add(h.code, h.name, h.source, h.reason, now.replace(tzinfo=None))
        self.added_today += added
        return added


def run_once(screener: Screener, market: KiwoomMarket, store: ScreenerStore, telegram: bool,
             watcher: Optional[SignalWatcher] = None, early: Optional[EarlyRunner] = None,
             investors: Optional[InvestorRecorder] = None) -> int:
    now = datetime.now(KST)
    search_1m = market.search_rank("1")
    search_day = market.search_rank("4")
    value_top = market.value_rank(pages=2)   # 200위까지: 대금 가속(③)을 순위 100위 밖에서부터 보기 위해
    store.save_ranks(now, "search_1m", search_1m)
    store.save_ranks(now, "search_day", search_day)
    store.save_ranks(now, "value_krx", value_top)
    if early is not None:
        try:
            early.step(now, market, search_1m, value_top, telegram)
        except Exception:
            logging.exception("조기 발굴 트리거 실패")
    if investors is not None:
        try:
            investors.step(now, market, store)
        except Exception:
            logging.exception("장중 수급 스냅샷 실패")

    evaluations = screener.scan_intraday(search_1m, search_day, value_top)
    passed = sorted((e for e in evaluations if e.passed(screener.config)), key=lambda e: -e.score)
    already = store.detected_codes(screener.today, "intraday")
    new = [e for e in passed if e.candidate.code not in already]
    for e in passed:
        store.save_detection(screener.today, "intraday", now, e)
    logging.info("후보 %s → 통과 %s (신규 %s): %s", len(evaluations), len(passed), len(new),
                 ", ".join(f"{e.candidate.name}{'*' if e in new else ''}" for e in passed))
    if new and telegram:
        body = "\n\n".join(format_evaluation(e) for e in new)
        send_telegram_message(f"⚡ 장중 포착 {now:%H:%M} ({len(new)}종목)\n\n{body}")

    # 매수 신호: 전일 관심 + 장중 포착 종목의 1분봉 패턴
    if watcher is not None:
        for e in passed:
            watcher.add(e.candidate.code, e.candidate.name)
        signals = watcher.check(now)
        if signals:
            logging.info("매수 신호 %s건: %s", len(signals), ", ".join(f"{n} {s.kind} {s.ts:%H:%M}" for _, n, _, s in signals))
            if telegram:
                send_telegram_message(format_signals(now, signals))
    return len(new)


def main() -> int:
    parser = argparse.ArgumentParser(description="주도주 스크리너 장중 실시간 포착")
    parser.add_argument("--interval", type=int, default=60, help="확인 주기(초), 기본 60")
    parser.add_argument("--once", action="store_true", help="1회만 실행")
    parser.add_argument("--force", action="store_true", help="장 시간/주말과 무관하게 실행")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    now = datetime.now(KST)
    _setup_logging(now)
    if now.weekday() >= 5 and not args.force:
        logging.info("주말이라 종료")
        return 0
    prevent_sleep_until_exit()  # 08:00~20:00 실행 중 유휴 절전으로 멈추지 않도록

    client = build_client()
    market = KiwoomMarket(client)
    screener = Screener(market, now.date())
    store = ScreenerStore()
    watcher = SignalWatcher(client, store, now.date())
    early = EarlyRunner(screener, watcher, store, now)
    investors = InvestorRecorder()
    listener = StopListener(enabled=not args.no_telegram)
    stop_command: Optional[str] = None
    try:
        if not args.force:
            while datetime.now(KST).time() < MARKET_OPEN and not stop_command:
                stop_command = listener.sleep(15)
        while not stop_command:
            started = time.monotonic()
            now = datetime.now(KST)
            if not args.force and now.time() >= MARKET_SCAN_END:
                logging.info("장중 스캔 종료 시각")
                break
            try:
                if not args.force and now.time() >= HOLIDAY_CHECK_AFTER:
                    probe = market.search_rank("4")
                    if probe and probe[0].as_of and probe[0].as_of != now.strftime("%Y%m%d"):
                        logging.info("오늘 데이터가 없음(휴장일로 판단, 기준일 %s) → 종료", probe[0].as_of)
                        break
                run_once(screener, market, store, telegram=not args.no_telegram, watcher=watcher, early=early, investors=investors)
            except Exception:
                logging.exception("스캔 실패 (다음 주기에 재시도)")
            if args.once:
                break
            stop_command = listener.sleep(max(1.0, args.interval - (time.monotonic() - started)))
    finally:
        store.close()
    if stop_command:
        logging.info("텔레그램 '%s' 명령으로 장중 스캐너 종료", stop_command)
        send_telegram_message(
            f"🛑 장중 스캐너를 멈췄습니다 ({datetime.now(KST):%H:%M})\n"
            "다시 켜려면 PC에서: Start-ScheduledTask -TaskName EllieTrading_ScreenerIntraday\n"
            "(다음 평일 07:50에는 자동으로 다시 시작됩니다)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
