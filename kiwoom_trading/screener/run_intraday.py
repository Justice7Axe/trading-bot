"""주도주 스크리너 — 장중 실시간 포착 (1분마다).

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_intraday              # 08:00~15:20 반복 (NXT 프리마켓 포함)
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_intraday --once --force --no-telegram   # 1회 점검

- 매 주기: 실시간 조회 순위(1분, 당일 누적) + 거래대금 상위 100 → 후보 → 조건 판정
- 새로 조건을 만족한 종목만 텔레그램으로 알림 (같은 날 같은 종목은 1회)
- 순위 스냅샷과 포착 기록은 data/screener.duckdb 에 저장 (추후 백테스트용)
- 로그: data/logs/screener_YYYYMMDD.log
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, time as dtime

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.common.telegram import send_telegram_message
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.screener.conditions import format_evaluation
from kiwoom_trading.screener.engine import Screener
from kiwoom_trading.screener.market_data import KiwoomMarket
from kiwoom_trading.screener.store import ScreenerStore


MARKET_OPEN = dtime(8, 0)          # NXT 프리마켓 시작 (KRX 정규장 09:00)
MARKET_SCAN_END = dtime(15, 20)
HOLIDAY_CHECK_AFTER = dtime(8, 10)


def _setup_logging(now: datetime) -> None:
    log_dir = os.path.join(PROJECT_ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(log_dir, f"screener_{now:%Y%m%d}.log"), encoding="utf-8"), logging.StreamHandler()],
    )


def run_once(screener: Screener, market: KiwoomMarket, store: ScreenerStore, telegram: bool) -> int:
    now = datetime.now(KST)
    search_1m = market.search_rank("1")
    search_day = market.search_rank("4")
    value_top = market.value_rank(pages=1)
    store.save_ranks(now, "search_1m", search_1m)
    store.save_ranks(now, "search_day", search_day)
    store.save_ranks(now, "value", value_top)

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

    client = build_client()
    market = KiwoomMarket(client)
    screener = Screener(market, now.date())
    store = ScreenerStore()
    try:
        if not args.force:
            while datetime.now(KST).time() < MARKET_OPEN:
                time.sleep(15)
        while True:
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
                run_once(screener, market, store, telegram=not args.no_telegram)
            except Exception:
                logging.exception("스캔 실패 (다음 주기에 재시도)")
            if args.once:
                break
            time.sleep(max(1.0, args.interval - (time.monotonic() - started)))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
