"""투자자별(외국인·기관 등) 일별 순매수 수집 (키움 ka10059) → daily_ohlcv.duckdb 의 investor_daily.

    python -m kiwoom_trading.ingestion.collectors.investor_flow --backfill            # 전 종목 2년 (약 2.5시간, 이어받기 가능)
    python -m kiwoom_trading.ingestion.collectors.investor_flow --today               # 오늘(마지막 거래일) 전 종목 1회 조회 (매일 20:00 자동, 약 10초)
    python -m kiwoom_trading.ingestion.collectors.investor_flow --update              # 종목별 마지막 저장일 이후 (빠진 날 보충, 느림)
    python -m kiwoom_trading.ingestion.collectors.investor_flow --codes 131970 --since 20250101

ka10059 응답: 1페이지 100거래일, 최신 → 과거. 금액 단위 백만원 → 원으로 저장. KRX 장 마감 확정치.
ka10066(장마감후투자자별매매): 오늘 전 종목 × 투자자 한 번에 (100종목/페이지) — 일일 업데이트용 (내외국인 컬럼 없음).
(장중 투자자 잠정치는 ka10063/ka10064 로 '오늘'만 조회 가능 → 장중 스캐너가 investor_intraday 로 쌓는다)
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Optional

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import DailyStore
from kiwoom_trading.common.keep_awake import prevent_sleep_until_exit
from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, build_client


FIELDS = [  # (응답 키, 컬럼)
    ("ind_invsr", "individual"), ("frgnr_invsr", "foreign_"), ("orgn", "institution"), ("fnnc_invt", "fin_invest"),
    ("insrnc", "insurance"), ("invtrt", "trust"), ("etc_fnnc", "etc_fin"), ("bank", "bank"), ("penfnd_etc", "pension"),
    ("samo_fund", "private_eq"), ("natn", "nation"), ("etc_corp", "etc_corp"), ("natfor", "foreign_etc"),
]
MAX_PAGES = 12


def _signed(value: Any) -> int:
    """순매수 금액은 부호가 의미(매도 우위 = 음수). 공용 _to_int 는 가격용이라 절대값을 돌려주므로 따로 파싱."""
    text = str(value if value is not None else "").strip().replace(",", "")
    try:
        return int(float(text)) if text else 0
    except ValueError:
        return 0


def fetch_investor_daily(client: KiwoomDailyClient, code: str, since: date, until: Optional[date] = None) -> list[tuple]:
    """since ~ until 의 일별 투자자 순매수 [(code, date, *FIELDS)] (원)."""
    body = {"dt": (until or datetime.now(KST).date()).strftime("%Y%m%d"), "stk_cd": code,
            "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1000"}
    rows: list[tuple] = []
    cont, next_key = "N", ""
    for _ in range(MAX_PAGES):
        payload, cont, next_key = client._post("/api/dostk/stkinfo", "ka10059", body, cont, next_key)
        items = payload.get("stk_invsr_orgn") or []
        oldest = None
        for item in items:
            try:
                d = datetime.strptime(str(item.get("dt")), "%Y%m%d").date()
            except ValueError:
                continue
            oldest = d
            if d < since:
                continue
            rows.append((code, d, *[_signed(item.get(k)) * 1_000_000 for k, _ in FIELDS]))
        if not items or (oldest and oldest < since) or cont != "Y" or not next_key:
            break
    return rows


def fetch_today_all(client: KiwoomDailyClient, day: date, max_pages: int = 60) -> list[tuple]:
    """ka10066: 오늘 장 마감 후 전 종목 투자자별 순매수 → [(code, day, *FIELDS)] (원). 장 마감 후에만 그날 확정치."""
    keys = {k for k, _ in FIELDS}
    rows: list[tuple] = []
    cont, next_key = "N", ""
    for _ in range(max_pages):
        payload, cont, next_key = client._post(
            "/api/dostk/mrkcond", "ka10066", {"mrkt_tp": "000", "amt_qty_tp": "1", "trde_tp": "0", "stex_tp": "1"}, cont, next_key)
        for item in payload.get("opaf_invsr_trde") or []:
            code = str(item.get("stk_cd") or "").split("_")[0]
            rows.append((code, day, *[_signed(item.get(k)) * 1_000_000 if k in item else 0 for k, _ in FIELDS]))
        if cont != "Y" or not next_key:
            break
    return rows


def update_today(day: Optional[date] = None) -> int:
    """일일 업데이트: 일봉 DB 의 마지막 거래일(=오늘) 전 종목 투자자 수급 저장."""
    client = build_client()
    store = DailyStore()
    try:
        day = day or store.conn.execute("SELECT max(date) FROM daily_ohlcv").fetchone()[0]
        listed = {r[0] for r in store.conn.execute("SELECT code FROM stocks WHERE NOT delisted").fetchall()}
        rows = [r for r in fetch_today_all(client, day) if r[0] in listed]
        n = upsert(store, rows)
    finally:
        store.close()
    logging.info("투자자 수급(%s) 전 종목 저장: %s종목", day, n)
    return n


def upsert(store: DailyStore, rows: list[tuple]) -> int:
    if rows:
        cols = ", ".join(c for _, c in FIELDS)
        store.conn.executemany(
            f"INSERT INTO investor_daily (code, date, {cols}) VALUES ({', '.join(['?'] * (len(FIELDS) + 2))}) "
            f"ON CONFLICT (code, date) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for _, c in FIELDS)}",
            rows,
        )
    return len(rows)


def run(codes: Optional[list[str]], since: Optional[date], update: bool, until: Optional[date] = None) -> int:
    client = build_client()
    store = DailyStore()
    total = 0
    try:
        if not codes:
            codes = [r[0] for r in store.conn.execute("SELECT code FROM stocks WHERE NOT delisted ORDER BY code").fetchall()]
        last = dict(store.conn.execute("SELECT code, max(date) FROM investor_daily GROUP BY code").fetchall())
        default_since = since or (datetime.now(KST).date() - timedelta(days=730))
        for k, code in enumerate(codes, 1):
            start = default_since
            if code in last and last[code]:
                if update:
                    start = last[code] + timedelta(days=1)
                elif not since:
                    continue                                   # 백필: 이미 받은 종목은 건너뜀 (이어받기)
            if start > datetime.now(KST).date():
                continue
            try:
                total += upsert(store, fetch_investor_daily(client, code, start, until))
            except Exception as exc:
                logging.warning("투자자 수급 수집 실패 %s: %s", code, exc)
            if k % 200 == 0:
                logging.info("투자자 수급 %s/%s 종목, %s행", k, len(codes), total)
    finally:
        store.close()
    logging.info("투자자 수급 저장 완료: %s행", total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="투자자별 일별 순매수 수집 (ka10059)")
    parser.add_argument("--backfill", action="store_true", help="전 종목 2년 (이미 받은 종목은 건너뜀)")
    parser.add_argument("--update", action="store_true", help="종목별 마지막 저장일 이후만")
    parser.add_argument("--today", action="store_true", help="마지막 거래일 전 종목 1회 조회 (ka10066)")
    parser.add_argument("--codes", default="", help="쉼표 구분 종목코드")
    parser.add_argument("--since", help="YYYYMMDD")
    parser.add_argument("--until", help="YYYYMMDD — 이 날부터 과거로 (더 오래된 기간 백필용, 2026-11-01)")
    parser.add_argument("--all-codes", action="store_true", help="--since 와 함께 전 종목 (이미 받은 종목도)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    prevent_sleep_until_exit()   # 백필은 수 시간 → 실행 중 유휴 절전 방지
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] or None
    since = datetime.strptime(args.since, "%Y%m%d").date() if args.since else None
    if args.today:
        update_today()
        return
    until = datetime.strptime(args.until, "%Y%m%d").date() if args.until else None
    if not (args.backfill or args.update or codes or args.all_codes):
        raise SystemExit("--backfill / --update / --codes 중 하나를 지정하세요.")
    run(codes, since, update=args.update, until=until)


if __name__ == "__main__":
    main()
