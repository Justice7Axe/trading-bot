"""햄버거 검증용 과거 1분봉 백필 (키움 ka10080, 통합 AL) → data/minute_history.duckdb 의 minute_ohlcv.

    python -m kiwoom_trading.ingestion.collectors.minute_history_backfill                 # 최근 1년, 날짜별 대금 상위 200
    python -m kiwoom_trading.ingestion.collectors.minute_history_backfill --top 50 --since 2026-09-01
    python -m kiwoom_trading.ingestion.collectors.minute_history_backfill --dry-run       # 대상 건수만

대상 = (날짜별 거래대금 상위 N 종목, 그 날) ∪ (같은 종목, 다음 거래일).
  - 그 날: 기준일(장대양봉일)의 기준 햄버거 계산용
  - 다음 거래일: 전날 정보로 고른 종목의 당일 햄버거 감지·진입 검증용 (선택 편향 없이)
통합(AL = KRX+NXT)만 받는다. 카페 회원들이 말하는 햄버거 금액이 통합 기준이다
  (가온전선 2026-09-18 09:21: KRX 82억 + NXT 82억 = 163억, 통합 추정 165억 / 한화시스템 09-14 13:38: KRX 20억, 통합 32억 ≈ 회원 31억).
  하루치 약 690봉이 1페이지(900봉)에 들어가 1회 호출로 끝난다. 정규장 380봉은 ts 로 잘라 쓴다.

운영 안전장치:
  - 장중 스캐너·20:00 업데이트가 쓰는 daily_ohlcv.duckdb 를 잠그지 않도록 별도 DB 파일에 쓴다.
  - 같은 앱키의 호출 한도를 다투지 않도록 평일 07:30~20:40 에는 멈췄다가 이어서 받는다.
  - 오래된 날부터 받는다(키움은 약 1년치만 제공 → 오래된 날부터 사라짐).
  - 받은 (종목, 날짜)는 minute_backfill_done 에 기록해 재실행 시 건너뛴다(거래정지로 빈 날 포함).
"""
import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import PROJECT_ROOT, DailyStore
from kiwoom_trading.common.keep_awake import prevent_sleep_until_exit
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

HISTORY_DB = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
DAILY_DB = os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")
EXCHANGE = "AL"
PAUSE_START, PAUSE_END = dtime(7, 30), dtime(20, 40)   # 평일 이 시간에는 멈춤 (장중 스캐너 + 20:00 업데이트)


def targets(top: int, since: date) -> list[tuple[date, str]]:
    """(날짜, 종목) 목록, 오래된 날짜 순."""
    conn = duckdb.connect(DAILY_DB, read_only=True)
    try:
        rows = conn.execute(
            """
            WITH days AS (SELECT DISTINCT date FROM daily_ohlcv WHERE date >= ?),
            nxt AS (SELECT date, LEAD(date) OVER (ORDER BY date) AS next_date FROM days),
            ranked AS (
                SELECT code, date, ROW_NUMBER() OVER (PARTITION BY date ORDER BY value DESC) AS rk
                FROM daily_ohlcv WHERE date >= ? AND value > 0
            ),
            top_n AS (SELECT r.code, r.date, n.next_date FROM ranked r JOIN nxt n USING (date) WHERE r.rk <= ?)
            SELECT DISTINCT date, code FROM (
                SELECT date, code FROM top_n
                UNION SELECT next_date, code FROM top_n WHERE next_date IS NOT NULL
            ) ORDER BY date, code
            """,
            [since, since, top],
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], r[1]) for r in rows]


def wait_if_market_hours() -> None:
    while True:
        now = datetime.now(KST)
        if now.weekday() >= 5 or not (PAUSE_START <= now.time() < PAUSE_END):
            return
        resume = datetime.combine(now.date(), PAUSE_END, tzinfo=now.tzinfo)
        logging.info("장중 시간이라 멈춤 → %s 에 재개", resume.strftime("%H:%M"))
        time.sleep(min(600, max(30, (resume - now).total_seconds())))


def main() -> None:
    parser = argparse.ArgumentParser(description="햄버거 검증용 과거 1분봉 백필 (통합 AL)")
    parser.add_argument("--top", type=int, default=200, help="날짜별 거래대금 상위 N (기본 200)")
    parser.add_argument("--since", default=None, help="YYYY-MM-DD (기본: 오늘 - 365일)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    since = date.fromisoformat(args.since) if args.since else datetime.now(KST).date() - timedelta(days=365)
    todo = targets(args.top, since)

    store = DailyStore(HISTORY_DB)
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS minute_backfill_done (code VARCHAR, date DATE, bars INTEGER, done_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY (code, date))"
    )
    done = {(r[1], r[0]) for r in store.conn.execute("SELECT code, date FROM minute_backfill_done").fetchall()}
    remaining = [(d, c) for d, c in todo if (d, c) not in done]
    logging.info("대상 %s건 (상위 %s, %s~), 완료 %s, 남음 %s", f"{len(todo):,}", args.top, since, f"{len(done):,}", f"{len(remaining):,}")
    if args.dry_run:
        store.close()
        return

    prevent_sleep_until_exit()   # 2026-10-17 04:13 절전으로 3시간 멈춤 → 실행 중엔 자동 절전하지 않게
    client = build_client()
    started = time.monotonic()
    try:
        for idx, (day, code) in enumerate(remaining, start=1):
            wait_if_market_hours()
            try:
                bars = fetch_minute_bars(client, code, day, EXCHANGE)
            except Exception as exc:
                logging.warning("실패 %s %s: %s", day, code, exc)
                continue
            store.upsert_minutes(bars)
            store.conn.execute("INSERT OR REPLACE INTO minute_backfill_done (code, date, bars) VALUES (?, ?, ?)", [code, day, len(bars)])
            if idx % 200 == 0 or idx == len(remaining):
                rate = idx / max(1e-9, time.monotonic() - started)
                logging.info("[%s/%s] %s %s 봉 %s개 (%.1f건/초, 남은 예상 %.1f시간)",
                             f"{idx:,}", f"{len(remaining):,}", day, code, len(bars), rate, (len(remaining) - idx) / rate / 3600)
    finally:
        store.close()


if __name__ == "__main__":
    main()
