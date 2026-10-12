"""KRX Open API 일별매매정보로 전 종목 일봉을 증분 수집한다 (시장당 하루 1콜).

- 마지막 저장일 다음 날부터 오늘까지 비어 있는 거래일을 자동으로 채운다(휴장일/미공개일은 건너뜀).
- 기준가(종가 - 전일대비)와 저장된 전일 종가가 다르면 권리락/분할로 보고 refetch_queue에 넣은 뒤
  키움 ka10081(수정주가)로 해당 종목 이력을 다시 받는다.

환경변수는 프로젝트 루트의 .env.local 에서 읽는다.
- KRX_API_KEY 있음: KRX Open API 사용 (openapi.krx.co.kr 인증키 + '유가증권/코스닥 일별매매정보' 이용신청 필요)
- KRX_API_KEY 없음: KIWOOM_APP_KEY / KIWOOM_SECRET_KEY 로 키움 ka10081 종목별 수집

실행(평일 18시 이후 또는 다음 날 아침):
    python -m kiwoom_trading.ingestion.collectors.daily_krx_update
    python -m kiwoom_trading.ingestion.collectors.daily_krx_update --start 20261001 --end 20261010
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import DailyStore, load_env
from kiwoom_trading.ingestion.collectors.daily_backfill import (
    DEFAULT_START,
    _is_common_stock,
    _parse_ymd,
    build_client,
    refresh_stock_master,
    run_backfill,
)


KRX_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis/sto"
KRX_ENDPOINTS = {
    "KOSPI": "stk_bydd_trd",
    "KOSDAQ": "ksq_bydd_trd",
}


def _num(value: Any) -> Optional[int]:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in ("", "-"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def fetch_krx_daily(api_key: str, market: str, day: date) -> list[dict[str, Any]]:
    response = requests.get(
        f"{KRX_BASE_URL}/{KRX_ENDPOINTS[market]}",
        headers={"AUTH_KEY": api_key},
        params={"basDd": day.strftime("%Y%m%d")},
        timeout=30,
    )
    if response.status_code in (401, 403):
        raise RuntimeError(f"KRX 인증 실패({response.status_code}): 인증키와 '{market} 일별매매정보' 이용신청 승인 여부를 확인하세요.")
    response.raise_for_status()
    items = response.json().get("OutBlock_1") or []
    return items if isinstance(items, list) else []


def to_rows(items: list[dict[str, Any]], market: str, day: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """(ohlcv rows, stock master rows, 종목별 기준가)"""
    rows: list[dict[str, Any]] = []
    stocks: list[dict[str, Any]] = []
    base_prices: dict[str, int] = {}
    for item in items:
        code = str(item.get("ISU_CD") or "").strip()
        name = str(item.get("ISU_NM") or "").strip()
        close = _num(item.get("TDD_CLSPRC"))
        if not code or close is None or not _is_common_stock(name):
            continue

        # 거래정지일은 시/고/저가가 0으로 내려온다 → 종가로 채움
        open_, high, low = (_num(item.get(k)) for k in ("TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC"))
        rows.append(
            {
                "code": code,
                "date": day,
                "open": open_ or close,
                "high": high or close,
                "low": low or close,
                "close": close,
                "volume": _num(item.get("ACC_TRDVOL")),
                "value": _num(item.get("ACC_TRDVAL")),
                "market_cap": _num(item.get("MKTCAP")),
                "source": "krx",
            }
        )
        stocks.append({"code": code, "name": name, "market": market, "list_date": None, "listed_shares": _num(item.get("LIST_SHRS"))})

        change = _num(item.get("CMPPREVDD_PRC"))
        if change is not None:
            base_prices[code] = close - change
    return rows, stocks, base_prices


def detect_corporate_actions(store: DailyStore, day: date, base_prices: dict[str, int]) -> list[str]:
    prev = store.last_closes_before(day)
    flagged: list[str] = []
    for code, base in base_prices.items():
        if code not in prev:
            continue  # 신규 상장
        prev_date, prev_close = prev[code]
        if prev_close and base != prev_close:
            store.enqueue_refetch(code, day, f"기준가 {base} != {prev_date} 종가 {prev_close}")
            flagged.append(code)
    return flagged


def update_day(store: DailyStore, api_key: str, day: date) -> tuple[int, list[str]]:
    total = 0
    flagged: list[str] = []
    for market in KRX_ENDPOINTS:
        items = fetch_krx_daily(api_key, market, day)
        if not items:
            continue
        rows, stocks, base_prices = to_rows(items, market, day)
        flagged += detect_corporate_actions(store, day, base_prices)
        store.upsert_stocks(stocks)
        total += store.upsert_ohlcv(rows)
    return total, flagged


def update_via_kiwoom(store: DailyStore, start: date, end: date) -> None:
    """KRX_API_KEY가 없을 때의 대체 경로: 키움 ka10081을 종목마다 1콜(2,500종목 ≈ 10~15분).

    각 종목의 마지막 저장일부터 겹치게 받아서, 그날 수정종가가 저장값과 다르면
    그 사이 권리락/분할이 있었던 것이므로 refetch_queue에 넣는다.
    """
    client = build_client()
    codes = refresh_stock_master(client, store)
    prev = store.last_closes_before(start)
    base_dt = end.strftime("%Y%m%d")

    total = 0
    flagged: list[str] = []
    for idx, code in enumerate(codes, start=1):
        prev_date, prev_close = prev.get(code, (start, None))
        try:
            rows = client.fetch_daily_chart(code, prev_date, base_dt)
        except Exception as exc:
            logging.error("[%s/%s] %s 실패: %s", idx, len(codes), code, exc)
            continue
        overlap = next((r for r in rows if r["date"] == prev_date), None)
        if prev_close and overlap and overlap["close"] != prev_close:
            store.enqueue_refetch(code, end, f"{prev_date} 수정종가 {overlap['close']} != 저장값 {prev_close}")
            flagged.append(code)
        total += store.upsert_ohlcv([r for r in rows if r["date"] >= start])
        if idx % 200 == 0:
            logging.info("진행 %s/%s", idx, len(codes))
    logging.info("키움 증분 저장 %s행, 권리락 의심 %s종목 %s", total, len(flagged), ",".join(flagged))


def date_range(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="KRX Open API 일봉 증분 수집")
    parser.add_argument("--start", help="시작일 YYYYMMDD (기본: 저장된 마지막 날짜 다음 날)")
    parser.add_argument("--end", help="종료일 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--no-refetch", action="store_true", help="권리락 감지 종목의 키움 재백필을 건너뜀")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env()
    api_key = os.getenv("KRX_API_KEY", "")
    if not api_key:
        logging.info("KRX_API_KEY 없음 → 키움 REST(.env.local의 KIWOOM_APP_KEY)로 증분 수집")

    store = DailyStore()
    try:
        if args.start:
            start = _parse_ymd(args.start)
        else:
            last = store.last_date()
            if last is None:
                raise RuntimeError("저장된 데이터가 없습니다. daily_backfill 을 먼저 실행하거나 --start 를 지정하세요.")
            start = last + timedelta(days=1)
        end = _parse_ymd(args.end) if args.end else datetime.now(KST).date()

        if start > end:
            logging.info("이미 최신입니다 (마지막 저장일 %s)", start - timedelta(days=1))
        elif not api_key:
            update_via_kiwoom(store, start, end)
        else:
            for day in date_range(start, end):
                count, flagged = update_day(store, api_key, day)
                if count == 0:
                    logging.info("%s 데이터 없음 (휴장일 또는 아직 미공개)", day)
                    continue
                logging.info("%s 저장 %s행, 권리락 의심 %s종목 %s", day, count, len(flagged), ",".join(flagged))

        pending = store.refetch_codes()
        if pending and not args.no_refetch:
            logging.info("수정주가 재백필 %s종목: %s", len(pending), ",".join(pending))
            # 종목별로 처음 백필했던 시작일부터 다시 받는다 (기본값 2010년으로 받으면 종목마다 이력 길이가 달라짐)
            client = build_client()
            for code in pending:
                run_backfill([code], store.backfill_start(code) or _parse_ymd(DEFAULT_START), True, client, store)
        elif pending:
            logging.info("재백필 대기 %s종목 (daily_backfill --refetch-queue 로 처리)", len(pending))
    finally:
        store.close()


if __name__ == "__main__":
    main()
