"""1분봉 수집 (키움 ka10080, 수정주가) → daily_ohlcv.duckdb 의 minute_ohlcv 테이블.

    python -m kiwoom_trading.ingestion.collectors.minute_collector --codes 131970                 # 오늘, KRX/통합/NXT
    python -m kiwoom_trading.ingestion.collectors.minute_collector --codes 131970 --date 20261013
    python -m kiwoom_trading.ingestion.collectors.minute_collector --detected                     # 오늘 스크리너 포착 종목 전부
    python -m kiwoom_trading.ingestion.collectors.minute_collector --watchlist                    # 오늘 매수 신호 감시 종목 (20:00 자동)

키움은 약 1년 전까지 과거 1분봉을 제공한다. 하루치는 KRX 약 620개, 통합/NXT 약 690개 봉 (1페이지 900개).
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime
from typing import Any

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import PROJECT_ROOT, DailyStore
from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, _to_int, build_client


EXCHANGE_SUFFIX = {"KRX": "", "AL": "_AL", "NX": "_NX"}
MAX_PAGES = 5


def fetch_minute_bars(client: KiwoomDailyClient, code: str, day: date, exchange: str = "AL") -> list[dict[str, Any]]:
    """day 하루치 1분봉 (시간 오름차순)."""
    prefix = day.strftime("%Y%m%d")
    body = {"stk_cd": code + EXCHANGE_SUFFIX[exchange], "tic_scope": "1", "upd_stkpc_tp": "1", "base_dt": prefix}
    bars: list[dict[str, Any]] = []
    cont, next_key = "N", ""
    for _ in range(MAX_PAGES):
        payload, cont, next_key = client._post("/api/dostk/chart", "ka10080", body, cont, next_key)
        items = payload.get("stk_min_pole_chart_qry") or []
        for item in items:
            tm = str(item.get("cntr_tm") or "")
            if not tm.startswith(prefix):
                continue
            bars.append({
                "code": code, "exchange": exchange, "ts": datetime.strptime(tm, "%Y%m%d%H%M%S"),
                "open": _to_int(item.get("open_pric")), "high": _to_int(item.get("high_pric")),
                "low": _to_int(item.get("low_pric")), "close": _to_int(item.get("cur_prc")),
                "volume": _to_int(item.get("trde_qty")) or 0,
            })
        # 응답은 최신 → 과거 순. 마지막 봉이 대상일보다 이전이면 하루치를 다 받은 것
        if not items or not str(items[-1].get("cntr_tm", "")).startswith(prefix) or cont != "Y" or not next_key:
            break
    return sorted(bars, key=lambda b: b["ts"])


def detected_codes(day: date) -> list[str]:
    path = os.path.join(PROJECT_ROOT, "data", "screener.duckdb")
    if not os.path.exists(path):
        return []
    conn = duckdb.connect(path, read_only=True)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT code FROM detections WHERE date = ? ORDER BY code", [day]).fetchall()]
    finally:
        conn.close()


def watchlist_codes(day: date) -> list[str]:
    """day 의 매수 신호 감시 종목 = 직전 거래일 '다음 거래일 관심 종목' + day 장중 포착 종목."""
    path = os.path.join(PROJECT_ROOT, "data", "screener.duckdb")
    if not os.path.exists(path):
        return []
    conn = duckdb.connect(path, read_only=True)
    try:
        prev = conn.execute("SELECT max(date) FROM detections WHERE mode = 'daily' AND date < ?", [day]).fetchone()[0]
        rows = conn.execute(
            "SELECT DISTINCT code FROM detections WHERE (mode = 'daily' AND date = ?) OR (mode = 'intraday' AND date = ?) ORDER BY code",
            [prev, day],
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def collect_minutes(codes: list[str], day: date, exchanges: list[str]) -> int:
    """종목별 하루치 1분봉을 minute_ohlcv 에 저장. 반환: 저장한 봉 수."""
    client = build_client()
    store = DailyStore()
    total = 0
    try:
        for code in codes:
            for exchange in exchanges:
                try:
                    bars = fetch_minute_bars(client, code, day, exchange)
                except Exception as exc:
                    logging.warning("1분봉 수집 실패 %s %s: %s", code, exchange, exc)
                    continue
                total += store.upsert_minutes(bars)
                volume = sum(b["volume"] for b in bars)
                span = f"{bars[0]['ts']:%H:%M}~{bars[-1]['ts']:%H:%M}" if bars else "-"
                logging.info("%s %s %s: 1분봉 %s개 (%s), 거래량 %s", day, code, exchange, len(bars), span, f"{volume:,}")
    finally:
        store.close()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="1분봉 수집")
    parser.add_argument("--codes", default="", help="쉼표 구분 종목코드")
    parser.add_argument("--detected", action="store_true", help="해당 날짜 스크리너 포착 종목 포함")
    parser.add_argument("--watchlist", action="store_true", help="해당 날짜 매수 신호 감시 종목 포함 (전일 관심 + 장중 포착)")
    parser.add_argument("--date", help="YYYYMMDD (기본: 오늘)")
    parser.add_argument("--exchanges", default="KRX,AL,NX", help="KRX,AL,NX 중 쉼표 구분 (기본: 전부)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    day = datetime.strptime(args.date, "%Y%m%d").date() if args.date else datetime.now(KST).date()
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    if args.detected:
        codes += [c for c in detected_codes(day) if c not in codes]
    if args.watchlist:
        codes += [c for c in watchlist_codes(day) if c not in codes]
    if not codes:
        raise SystemExit("--codes / --detected / --watchlist 로 종목을 지정하세요.")
    exchanges = [e.strip().upper() for e in args.exchanges.split(",") if e.strip()]
    collect_minutes(codes, day, exchanges)


if __name__ == "__main__":
    main()
