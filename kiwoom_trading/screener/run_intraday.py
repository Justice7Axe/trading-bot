"""주도주 스크리너 — 장중 실시간 포착 (1분마다).

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_intraday              # 08:00~20:00 반복 (NXT 프리·애프터마켓 포함)
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_intraday --once --force --no-telegram   # 1회 점검

- 매 주기: 실시간 조회 순위(1분, 당일 누적) + 거래대금 상위 100 → 후보 → 조건 판정
- 새로 조건을 만족한 종목만 텔레그램으로 알림 (같은 날 같은 종목은 1회)
- 텔레그램으로 '멈춰'(또는 중지/정지/stop)를 보내면 5초 안에 스캐너 종료
- 텔레그램으로 '정리'(또는 요약/현황)를 보내면 오늘 포착 종목·테마·매수 신호를 표로 전송 (daily_summary.py)
- 매수 신호: 전일 '다음 거래일 관심 종목' + 전일 '쉬어 가는 주도주' + 장중 포착 종목 + 조기 트리거 종목의
  1분봉에서 지지 반등/돌파 후 눌림 → 🎯 알림
- 테마 특징주 트랙(theme_track.py): 🔥 조회 상위 + 7% + 대금 100억 / 🧩 같은 테마 2종목↑ 급등 → 즉시 알림 + 감시
- 조기 발굴(early_watch.py): ②조회 급등 → 감시 추가(30분마다 👀 요약), ③대금 가속 → 🚀, ⑤조기 주도주(09:15 전 500억&+3%) → 🏁 즉시 알림 + 감시 추가 → 장중 외국인·기관 잠정치로 🏁✅ 수급 확인, ④08:50 🌅 프리마켓 주목
- 순위 스냅샷과 포착 기록, 장중 외국인·기관 잠정치(5분마다 확인, 바뀔 때만)는 data/screener.duckdb 에 저장 (추후 백테스트용)
- 🎯 신호 모의투자(paper_trader.py): 키움 모의 서버로 시장가 매수 → 손절·추적·15:19 정리 (NXT 프리·애프터장은 가상 체결) → 15:40·19:55 당일·누적 리포트
  (실주문은 KRX 정규장만, --once 또는 --no-paper 면 주문하지 않음)
- 로그: data/logs/screener_YYYYMMDD.log
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT, load_env
from kiwoom_trading.common.keep_awake import prevent_sleep_until_exit
from kiwoom_trading.common.telegram import peek_messages, send_telegram_message
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.screener.conditions import format_evaluation
from kiwoom_trading.screener.daily_summary import SUMMARY_WORDS, PriceBoard, build_summary
from kiwoom_trading.screener.early_watch import EarlyDetector, EarlyHit, format_premarket, format_watch_adds
from kiwoom_trading.screener.engine import Screener
from kiwoom_trading.screener.market_data import KiwoomMarket
from kiwoom_trading.screener.paper_trader import PaperTrader, build_mock_client, mock_configured
from kiwoom_trading.screener.intraday_signals import QualityConfig
from kiwoom_trading.screener.bigcap_flow import KIND as BIGCAP_KIND, BigcapFlowWatcher
from kiwoom_trading.screener.early_nine import KIND as NINE_KIND, EarlyNineWatcher
from kiwoom_trading.screener.inverse_gap import KIND as INVERSE_KIND, InverseGapWatcher
from kiwoom_trading.screener.market_regime import MarketRegime
from kiwoom_trading.screener.leader_shape import KIND as LEADER_KIND, LeaderShapeWatcher
from kiwoom_trading.screener.pullback_breakout import KIND as PULLBACK_KIND, PullbackWatcher
from kiwoom_trading.screener.signal_watch import SignalWatcher, format_signals
from kiwoom_trading.screener.store import ScreenerStore
from kiwoom_trading.screener.theme_track import ThemeTracker, build_peer_graph, format_clusters, format_features


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
    """텔레그램 명령 감지: '멈춰' → 스캐너 종료, '정리' → 오늘 포착 종목·테마·매수 신호 표 전송.

    등록된 채팅방에서, 스캐너 시작 이후에 온 메시지만 본다. '정리' 는 메시지(update_id)당 한 번만 답한다.
    """

    def __init__(self, enabled: bool, on_summary=None, on_tick=None) -> None:
        load_env()
        self.enabled = enabled
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.started_at = time.time()
        self._last_check = 0.0
        self.on_summary = on_summary
        self.on_tick = on_tick            # 기다리는 동안 5초마다 호출 (모의투자 보유 종목 감시)
        self._handled: set = set()

    def requested(self) -> Optional[str]:
        if not self.enabled or not self.chat_id or time.monotonic() - self._last_check < STOP_CHECK_SECONDS:
            return None
        self._last_check = time.monotonic()
        for msg in peek_messages():
            text = msg["text"].strip().lstrip("/").rstrip("!.~ ").lower()
            if msg["chat_id"] != self.chat_id or msg["date"] < self.started_at:
                continue
            if text in STOP_WORDS:
                return msg["text"]
            if text in SUMMARY_WORDS and self.on_summary and msg["update_id"] not in self._handled:
                self._handled.add(msg["update_id"])
                try:
                    self.on_summary()
                except Exception:
                    logging.exception("'정리' 응답 실패")
        return None

    def sleep(self, seconds: float) -> Optional[str]:
        """seconds 동안 기다리되, 그 사이 '멈춰'가 오면 즉시 반환."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.on_tick:
                try:
                    self.on_tick()
                except Exception:
                    logging.exception("기다리는 중 작업 실패")
            command = self.requested()
            if command:
                return command
            time.sleep(min(STOP_CHECK_SECONDS, max(0.0, end - time.monotonic())))
        return self.requested()


INVESTOR_EVERY_MINUTES = 5          # 장중 외국인·기관 잠정치 확인 주기 (실제 갱신은 하루 5~6번)
INVESTOR_WINDOW = (dtime(9, 10), dtime(15, 45))


class InvestorRecorder:
    """장중 외국인·기관 순매수 잠정치(ka10063)를 5분마다 확인해서 바뀌었을 때만 저장 → 추후 수급 백테스트용."""

    def __init__(self, on_snapshot=None) -> None:
        self.last_check: Optional[datetime] = None
        self.last_sum: dict[str, int] = {}
        self.on_snapshot = on_snapshot          # (now, investor, values) — 새 잠정치가 들어오면 호출

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
                if self.on_snapshot:
                    self.on_snapshot(now, investor, values)


ADD_SUMMARY_MINUTES = 30   # 조회 급등 감시 추가 알림은 30분마다 묶어서 (매수 신호 🎯 는 즉시)
URGENT_HEADERS = {         # 즉시 알림하는 조기 트리거
    "조기 주도주": "🏁 조기 주도주 {now:%H:%M} — 09:15 전 누적 대금 500억 & +3% (그날 주도주 적중 약 38%, 수급 확인은 09:20 이후)",
    "대금 가속": "🚀 거래대금 가속 — 오늘의 주도주 {now:%H:%M} (그날 최종 대금 50위 적중 95%)",
}


class ThemeRunner:
    """테마 특징주 트랙: 🔥 테마 특징주 / 🧩 테마 형성 → 즉시 알림 + 감시 목록 추가 (대형 주도주 트랙과 별도)."""

    def __init__(self, screener: Screener, watcher: SignalWatcher, store: ScreenerStore, now: datetime,
                 board: Optional[PriceBoard] = None) -> None:
        self.board = board
        conn = duckdb.connect(DEFAULT_DB_PATH, read_only=True)
        try:
            peers = build_peer_graph(conn, now.date())
        finally:
            conn.close()
        self.tracker = ThemeTracker(screener.names, screener.sectors, peers, screener.theme_map, store.theme_names())
        self.watcher = watcher
        self.store = store
        self.today = now.date()
        self.tracker.featured = {c for src, c in store.early_alerted(self.today) if src == "테마 특징주"}
        # 재시작해도 오늘 이미 알린 🧩 묶음은 다시 알리지 않도록 (대장별 구성 복원)
        groups: dict[str, set[str]] = {}
        for leader, code in store.conn.execute("SELECT leader, code FROM theme_alerts WHERE date = ?", [self.today]).fetchall():
            groups.setdefault(leader, set()).add(code)
        self.tracker.clusters_alerted = list(groups.values())

    def step(self, now: datetime, market: KiwoomMarket, search_1m: list, telegram: bool) -> None:
        if not (THEME_WINDOW[0] <= now.time() <= THEME_WINDOW[1]):
            return
        movers = market.risers()
        if self.board is not None:
            self.board.update(movers)
        hits, clusters = self.tracker.update(now, search_1m, movers)
        naive = now.replace(tzinfo=None)
        for h in hits:
            self.store.save_early_alert(self.today, h.source, h.code, naive, h.name, h.reason)
            self.watcher.add(h.code, h.name, h.source, h.reason, naive)
        for c in clusters:
            self.store.save_theme_alert(self.today, naive, c.label, c.leader.code, list(c.members.values()))
            for m in c.members.values():
                self.watcher.add(m.code, m.name, "테마 형성", f"[{c.label}] {m.change_rate:+.1%}", naive)
        if hits:
            logging.info("🔥 테마 특징주: %s", ", ".join(h.name for h in hits))
        for c in clusters:
            logging.info("🧩 테마 형성 [%s]: %s", c.label, c.describe())
        if telegram and hits:
            send_telegram_message(format_features(now, hits))
        if telegram and clusters:
            send_telegram_message(format_clusters(now, clusters))


THEME_WINDOW = (dtime(8, 0), dtime(15, 30))


class EarlyRunner:
    """조기 발굴 트리거(②조회 급등 ③대금 가속 ④프리마켓 주목 ⑤조기 주도주) → 매수 신호 감시 목록에 추가."""

    def __init__(self, screener: Screener, watcher: SignalWatcher, store: ScreenerStore, now: datetime) -> None:
        self.detector = EarlyDetector(screener.hist, screener.names)
        self.watcher = watcher
        self.store = store
        self.today = now.date()
        self.alerted = store.early_alerted(self.today)          # (출처, 코드) — 감시 목록 포함 여부와 무관하게 하루 1회
        self.gate: dict[str, str] = {c: "" for src, c in self.alerted if src == "조기 주도주"}   # 조기 주도주 코드 → 이름
        self.flow_checked: set[tuple[str, str]] = set()          # (investor, code) 수급 확인 알림 보냄
        self.telegram = True
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
        self.telegram = telegram
        urgent: dict[str, list[EarlyHit]] = {}
        for h in hits:
            if h.source in URGENT_HEADERS:
                # 즉시 알림은 감시 목록에 이미 있어도(예: 08:50 프리마켓 주목으로 먼저 추가) 보낸다 — 2026-10-14 누락 버그 수정
                if (h.source, h.code) not in self.alerted:
                    self.alerted.add((h.source, h.code))
                    self.store.save_early_alert(self.today, h.source, h.code, now.replace(tzinfo=None), h.name, h.reason)
                    urgent.setdefault(h.source, []).append(h)
                    if h.source == "조기 주도주":
                        self.gate[h.code] = h.name
                if self.added_today < cfg.max_watch_adds:
                    self._add(h, now)
                continue
            if self.added_today >= cfg.max_watch_adds:
                continue
            if self._add(h, now):
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

    def on_investor_snapshot(self, now: datetime, investor: str, values: dict[str, int]) -> None:
        """장중 외국인(09:20 무렵 첫 갱신)·기관(09:50 무렵) 잠정치가 들어오면 🏁 종목의 수급을 확인해서 알림."""
        label = {"foreign": "외국인", "institution": "기관"}[investor]
        todo = [(c, n) for c, n in self.gate.items() if (investor, c) not in self.flow_checked]
        if not todo:
            return
        buy, sell = [], []
        for code, name in todo:
            self.flow_checked.add((investor, code))
            amount = values.get(code, 0)
            (buy if amount > 0 else sell).append(f"{name or code}({code}) {label} {amount / 1e8:+,.0f}억")
        logging.info("조기 주도주 %s 수급 확인: 순매수 %s / 아님 %s", label, buy, sell)
        if self.telegram:
            lines = [f"🏁✅ 조기 주도주 {label} 수급 확인 {now:%H:%M} (장중 잠정치)",
                     "순매수: " + (", ".join(buy) if buy else "없음")]
            if sell:
                lines.append("순매도/없음: " + ", ".join(sell))
            lines.append("(관문+당일 외국인·기관 순매수: 장 마감 확정치 기준 정밀도 38%→51%, 잠정치로는 검증 중)")
            send_telegram_message("\n".join(lines))

    def _add(self, h: EarlyHit, now: datetime) -> bool:
        added = self.watcher.add(h.code, h.name, h.source, h.reason, now.replace(tzinfo=None))
        self.added_today += added
        return added


def run_once(screener: Screener, market: KiwoomMarket, store: ScreenerStore, telegram: bool,
             watcher: Optional[SignalWatcher] = None, early: Optional[EarlyRunner] = None,
             investors: Optional[InvestorRecorder] = None, themes: Optional[ThemeRunner] = None,
             board: Optional[PriceBoard] = None, trader: Optional[PaperTrader] = None,
             leader: Optional[LeaderShapeWatcher] = None, pullback: Optional[PullbackWatcher] = None,
             nine: Optional[EarlyNineWatcher] = None, bigcap: Optional[BigcapFlowWatcher] = None,
             regime: Optional[MarketRegime] = None, inverse: Optional[InverseGapWatcher] = None) -> int:
    now = datetime.now(KST)
    if trader is not None:
        try:
            trader.tick(now, force=True)
        except Exception:
            logging.exception("모의투자 확인 실패")
    search_1m = market.search_rank("1")
    search_day = market.search_rank("4")
    value_top = market.value_rank(pages=2)   # 200위까지: 대금 가속(③)을 순위 100위 밖에서부터 보기 위해
    store.save_ranks(now, "search_1m", search_1m)
    store.save_ranks(now, "search_day", search_day)
    store.save_ranks(now, "value_krx", value_top)
    if regime is not None:
        try:
            regime.update(now, value_top)    # 강한 하락장 판정 (09:10~10:00) — 판정되면 모의투자가 보수적으로 산다
        except Exception:
            logging.exception("시장 분위기 판정 실패")
    if board is not None:
        board.update(search_1m + value_top)
    if early is not None:
        try:
            early.step(now, market, search_1m, value_top, telegram)
        except Exception:
            logging.exception("조기 발굴 트리거 실패")
    if themes is not None:
        try:
            themes.step(now, market, search_1m, telegram)
        except Exception:
            logging.exception("테마 특징주 트랙 실패")
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

    # 매수 신호: 전일 관심 + 장중 포착 종목의 1분봉 패턴 + 🎯 주도주 모양(09:30~10:30, 대금 100위 안)
    signals = []
    if watcher is not None:
        for e in passed:
            watcher.add(e.candidate.code, e.candidate.name)
        signals = watcher.check(now)
    shared_bars: dict = {}   # 같은 분에 받은 KRX 1분봉을 두 판정이 함께 쓴다
    for label, w in (("인버스 갭", inverse), ("장 초 공통점", nine), ("대형주 수급", bigcap), ("주도주 모양", leader), ("눌림 돌파", pullback)):
        if w is not None and hasattr(w, "cache"):
            w.cache = shared_bars
        if w is None:
            continue
        try:
            found = w.check(now, value_top)
        except Exception:
            logging.exception("%s 판정 실패", label)
            found = []
        for code, name, source, s in found:
            store.save_signal(screener.today, code, name, s, source, True)
        signals += found
    if watcher is not None or leader is not None or pullback is not None or nine is not None or bigcap is not None or inverse is not None:
        if signals:
            logging.info("매수 신호 %s건: %s", len(signals), ", ".join(f"{n} {s.kind} {s.ts:%H:%M}" for _, n, _, s in signals))
            flow = watcher.flow if watcher is not None else {}
            if telegram:
                send_telegram_message(format_signals(now, signals, flow))
            if trader is not None:
                trader.on_signals(now, signals, flow)
    return len(new)


def main() -> int:
    parser = argparse.ArgumentParser(description="주도주 스크리너 장중 실시간 포착")
    parser.add_argument("--interval", type=int, default=60, help="확인 주기(초), 기본 60")
    parser.add_argument("--once", action="store_true", help="1회만 실행")
    parser.add_argument("--force", action="store_true", help="장 시간/주말과 무관하게 실행")
    parser.add_argument("--no-telegram", action="store_true")
    parser.add_argument("--no-paper", action="store_true", help="모의투자 주문 안 함 (--once 도 주문 안 함)")
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
    watcher = SignalWatcher(client, store, now.date(), prev_close={c: h.last_close for c, h in screener.hist.items()},
                            avg_value={c: h.avg_value_20 for c, h in screener.hist.items() if h.avg_value_20},
                            quality=QualityConfig(allow_after=True))   # 애프터마켓 신호 → 모의투자 가상 체결
    early = EarlyRunner(screener, watcher, store, now)
    leader = LeaderShapeWatcher(client, now.date(), prev_close={c: h.last_close for c, h in screener.hist.items()},
                                done={c for c, _, k in store.signal_keys(now.date()) if k == LEADER_KIND})
    pullback = PullbackWatcher(client, now.date(), prev_close={c: h.last_close for c, h in screener.hist.items()},
                               seen={(c, ts) for c, ts, k in store.signal_keys(now.date()) if k == PULLBACK_KIND})
    try:
        nine: Optional[EarlyNineWatcher] = EarlyNineWatcher(
            client, now.date(), done={c for c, _, k in store.signal_keys(now.date()) if k == NINE_KIND})
    except Exception:
        logging.exception("장 초 공통점 준비 실패 (나머지 신호만 실행)")
        nine = None
    try:
        bigcap: Optional[BigcapFlowWatcher] = BigcapFlowWatcher(
            market, store, now.date(), done={c for c, _, k in store.signal_keys(now.date()) if k == BIGCAP_KIND})
    except Exception:
        logging.exception("대형주 수급 준비 실패 (나머지 신호만 실행)")
        bigcap = None
    board = PriceBoard()
    investors = InvestorRecorder(on_snapshot=early.on_investor_snapshot)
    try:
        themes: Optional[ThemeRunner] = ThemeRunner(screener, watcher, store, now, board)
    except Exception:
        logging.exception("테마 특징주 트랙 준비 실패 (대형 주도주 트랙만 실행)")
        themes = None
    trader: Optional[PaperTrader] = None
    if not args.once and not args.no_paper and mock_configured():
        notify = (lambda text: None) if args.no_telegram else (
            lambda text: send_telegram_message(text, parse_mode="HTML" if "<pre>" in text else ""))
        try:
            trader = PaperTrader(build_mock_client(), market, store, now.date(), notify)
        except Exception:
            logging.exception("모의투자 준비 실패 (알림만 실행)")
            if not args.no_telegram:
                send_telegram_message("⚠️ 모의투자 준비 실패 — 오늘은 🎯 알림만 보냅니다 (로그 확인)")
    regime = MarketRegime(screener.hist.keys(), notify=None if args.no_telegram else send_telegram_message)
    inverse = InverseGapWatcher(market, screener.hist.keys(), done=any(k == INVERSE_KIND for _, _, k in store.signal_keys(now.date())))
    if trader is not None:
        trader.regime = regime

    def send_summary() -> None:
        messages = build_summary(store, now.date(), board, market)
        if trader is not None:
            messages.append(trader.status_message())
        for message in messages:
            send_telegram_message(message, parse_mode="HTML" if "<pre>" in message else "")
        logging.info("텔레그램 '정리' 응답 전송")

    listener = StopListener(enabled=not args.no_telegram, on_summary=send_summary,
                            on_tick=(lambda: trader.tick(datetime.now(KST))) if trader else None)
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
                run_once(screener, market, store, telegram=not args.no_telegram, watcher=watcher, early=early, investors=investors,
                         themes=themes, board=board, trader=trader, leader=leader, pullback=pullback, nine=nine, bigcap=bigcap, regime=regime, inverse=inverse)
            except Exception:
                logging.exception("스캔 실패 (다음 주기에 재시도)")
            if args.once:
                break
            stop_command = listener.sleep(max(1.0, args.interval - (time.monotonic() - started)))
    finally:
        # 19:55 전에 꺼져도(멈춰·장애) 정규장이 끝났으면 그때까지 결과로 리포트
        if trader is not None and not trader.reported and datetime.now(KST).time() >= dtime(15, 30):
            try:
                trader.send_report(datetime.now(KST))
            except Exception:
                logging.exception("모의투자 리포트 실패")
        store.close()
    if stop_command:
        logging.info("텔레그램 '%s' 명령으로 장중 스캐너 종료", stop_command)
        held = [t.name for t in trader.active()] if trader else []
        send_telegram_message(
            f"🛑 장중 스캐너를 멈췄습니다 ({datetime.now(KST):%H:%M})\n"
            "다시 켜려면 PC에서: Start-ScheduledTask -TaskName EllieTrading_ScreenerIntraday\n"
            "(다음 평일 07:50에는 자동으로 다시 시작됩니다)"
            + (f"\n⚠️ 모의투자 보유 종목이 남아 있습니다: {', '.join(held)} — 손절·정리 감시도 멈춥니다 "
               "(다시 켜면 이어서 감시, 그대로 두면 다음 날 09:00 정리)" if held else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
