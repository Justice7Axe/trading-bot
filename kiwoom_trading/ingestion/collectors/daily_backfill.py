"""키움 REST ka10081(주식일봉차트조회)로 일봉 과거 데이터를 백필한다 (수정주가 기준).

실행(프로젝트 루트에서):
    python -m kiwoom_trading.ingestion.collectors.daily_backfill                 # 전 종목, 이어받기
    python -m kiwoom_trading.ingestion.collectors.daily_backfill --codes 005930,000660 --force
    python -m kiwoom_trading.ingestion.collectors.daily_backfill --refetch-queue # 권리락 감지 종목만
"""
import argparse
import logging
import os
import sys
import time
from datetime import date, datetime
from typing import Any, Optional

import requests

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import DailyStore, load_env
from kiwoom_trading.ingestion.collectors.kiwoom_login import fetch_kiwoom_access_token


DEFAULT_START = "20100101"
REQUEST_INTERVAL_SECONDS = 0.25  # 키움 REST 초당 호출 제한 대응
MAX_RETRIES = 5

MARKETS = {"0": "KOSPI", "10": "KOSDAQ"}


def _to_int(value: Any) -> Optional[int]:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text == "":
        return None
    try:
        # 키움은 등락 부호를 가격 앞에 붙여서 준다("-70100") → 절대값
        return abs(int(float(text)))
    except ValueError:
        return None


def _parse_ymd(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date()


class KiwoomDailyClient:
    def __init__(self, base_url: str, app_key: str, secret_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_key = app_key
        self.secret_key = secret_key
        self.token = fetch_kiwoom_access_token(self.base_url, app_key, secret_key)
        self._last_call = 0.0

    def _post(self, path: str, api_id: str, body: dict[str, Any], cont_yn: str = "N", next_key: str = "") -> tuple[dict[str, Any], str, str]:
        for attempt in range(1, MAX_RETRIES + 1):
            wait = REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {self.token}",
                "api-id": api_id,
                "cont-yn": cont_yn,
                "next-key": next_key,
            }
            try:
                response = requests.post(f"{self.base_url}{path}", headers=headers, json=body, timeout=20)
            except requests.RequestException as exc:
                logging.warning("%s 네트워크 오류(%s/%s): %s", api_id, attempt, MAX_RETRIES, exc)
                time.sleep(2 * attempt)
                continue

            if response.status_code == 401:
                logging.info("토큰 만료 → 재발급")
                self.token = fetch_kiwoom_access_token(self.base_url, self.app_key, self.secret_key)
                continue
            if response.status_code == 429:
                time.sleep(2 * attempt)
                continue
            response.raise_for_status()

            payload = response.json()
            return_code = payload.get("return_code")
            if return_code not in (0, "0", None):
                message = str(payload.get("return_msg", ""))
                if "8005" in message and attempt < MAX_RETRIES:
                    # 토큰 만료는 401 이 아니라 200 + return_code 3 [8005] 로 온다
                    # (2026-10-16 20:40 이후 1분봉 백필 전부 실패, 20:00 스캐너 1분봉 조회 실패)
                    logging.info("토큰 만료(8005) → 재발급")
                    self.token = fetch_kiwoom_access_token(self.base_url, self.app_key, self.secret_key)
                    continue
                if "초과" in message:  # 허용된 요청 개수 초과
                    time.sleep(2 * attempt)
                    continue
                raise RuntimeError(f"{api_id} 실패: {payload}")
            return payload, response.headers.get("cont-yn", "N"), response.headers.get("next-key", "")
        raise RuntimeError(f"{api_id} 재시도 {MAX_RETRIES}회 실패: body={body}")

    def fetch_stock_list(self, mrkt_tp: str) -> list[dict[str, Any]]:
        """ka10099 종목정보 리스트."""
        rows: list[dict[str, Any]] = []
        cont_yn, next_key = "N", ""
        while True:
            payload, cont_yn, next_key = self._post("/api/dostk/stkinfo", "ka10099", {"mrkt_tp": mrkt_tp}, cont_yn, next_key)
            rows.extend(payload.get("list") or [])
            if cont_yn != "Y" or not next_key:
                return rows

    def fetch_daily_chart(self, code: str, start: date, base_dt: Optional[str] = None) -> list[dict[str, Any]]:
        """ka10081 일봉(수정주가). base_dt부터 과거로 거슬러 start까지."""
        body = {
            "stk_cd": code,
            "base_dt": base_dt or datetime.now(KST).strftime("%Y%m%d"),
            "upd_stkpc_tp": "1",  # 수정주가
        }
        rows: list[dict[str, Any]] = []
        cont_yn, next_key = "N", ""
        while True:
            payload, cont_yn, next_key = self._post("/api/dostk/chart", "ka10081", body, cont_yn, next_key)
            items = payload.get("stk_dt_pole_chart_qry") or []
            reached_start = False
            for item in items:
                dt_text = str(item.get("dt") or "").strip()
                if not dt_text:
                    continue
                day = _parse_ymd(dt_text)
                if day < start:
                    reached_start = True
                    continue
                trade_value_mil = _to_int(item.get("trde_prica"))
                rows.append(
                    {
                        "code": code,
                        "date": day,
                        "open": _to_int(item.get("open_pric")),
                        "high": _to_int(item.get("high_pric")),
                        "low": _to_int(item.get("low_pric")),
                        "close": _to_int(item.get("cur_prc")),
                        "volume": _to_int(item.get("trde_qty")),
                        "value": trade_value_mil * 1_000_000 if trade_value_mil is not None else None,
                        "market_cap": None,
                        "source": "kiwoom",
                    }
                )
            if reached_start or not items or cont_yn != "Y" or not next_key:
                return rows


def _is_common_stock(name: str) -> bool:
    upper = name.upper()
    return not ("ETF" in upper or "ETN" in upper or "스팩" in name or "스펙" in name)


def _is_target_stock(item: dict[str, Any]) -> bool:
    """ka10099 항목 중 주식만. KOSPI 리스트에는 ETF/ETN/리츠가 섞여 오고(이름에 'ETF'가 없는 KODEX 등),
    KOSDAQ은 스팩이 companyClassName으로 구분된다."""
    market_name = str(item.get("marketName") or "").strip()
    if market_name not in ("거래소", "코스닥"):
        return False
    if str(item.get("companyClassName") or "").strip() == "스팩":
        return False
    return _is_common_stock(str(item.get("name") or ""))


def refresh_stock_master(client: KiwoomDailyClient, store: DailyStore, include_all: bool = False) -> list[str]:
    stocks: list[dict[str, Any]] = []
    for mrkt_tp, market in MARKETS.items():
        for item in client.fetch_stock_list(mrkt_tp):
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            if not code or (not include_all and not _is_target_stock(item)):
                continue
            reg_day = str(item.get("regDay") or "").strip()
            stocks.append(
                {
                    "code": code,
                    "name": name,
                    "market": market,
                    "list_date": _parse_ymd(reg_day) if len(reg_day) == 8 else None,
                    "listed_shares": _to_int(item.get("listCount")),
                    "sector": str(item.get("upName") or "").strip() or None,
                }
            )
    store.upsert_stocks(stocks)
    delisted = store.mark_delisted_except({s["code"] for s in stocks})
    logging.info("종목 마스터 갱신: %s종목 (신규 상장폐지 표시 %s)", len(stocks), delisted)
    return [s["code"] for s in stocks]


def backfill_stock(client: KiwoomDailyClient, store: DailyStore, code: str, start: date) -> int:
    rows = client.fetch_daily_chart(code, start)
    count = store.replace_stock_history(code, rows)
    store.mark_backfilled(code, start, count)
    return count


def run_backfill(codes: list[str], start: date, force: bool, client: KiwoomDailyClient, store: DailyStore) -> list[str]:
    done = set() if force else store.backfilled_codes()
    targets = [c for c in codes if c not in done]
    logging.info("백필 대상 %s종목 (건너뜀 %s)", len(targets), len(codes) - len(targets))

    failed: list[str] = []
    for idx, code in enumerate(targets, start=1):
        try:
            count = backfill_stock(client, store, code, start)
            store.dequeue_refetch(code)
            logging.info("[%s/%s] %s %s행", idx, len(targets), code, count)
        except Exception as exc:  # 한 종목 실패로 전체를 멈추지 않는다
            failed.append(code)
            logging.error("[%s/%s] %s 실패: %s", idx, len(targets), code, exc)
    if failed:
        logging.warning("실패 %s종목: %s", len(failed), ",".join(failed))
    return failed


def build_client() -> KiwoomDailyClient:
    load_env()
    app_key = os.getenv("KIWOOM_APP_KEY", "")
    secret_key = os.getenv("KIWOOM_SECRET_KEY", "")
    if not app_key or not secret_key:
        raise RuntimeError("KIWOOM_APP_KEY / KIWOOM_SECRET_KEY 환경변수를 설정해주세요.")
    return KiwoomDailyClient(os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com"), app_key, secret_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="키움 ka10081 일봉 백필(수정주가)")
    parser.add_argument("--start", default=DEFAULT_START, help="수집 시작일 YYYYMMDD (기본 20100101)")
    parser.add_argument("--codes", default="", help="쉼표 구분 종목코드. 비우면 KOSPI+KOSDAQ 전 종목")
    parser.add_argument("--force", action="store_true", help="이미 백필한 종목도 다시 받기")
    parser.add_argument("--refetch-queue", action="store_true", help="refetch_queue(권리락 감지) 종목만 재수집")
    parser.add_argument("--include-etf", action="store_true", help="ETF/ETN/스팩 포함")
    parser.add_argument("--master-only", action="store_true", help="종목 마스터(이름, 상장주식수)만 갱신")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start = _parse_ymd(args.start)
    client = build_client()
    store = DailyStore()
    try:
        if args.master_only:
            refresh_stock_master(client, store, args.include_etf)
            return
        if args.refetch_queue:
            codes, force = store.refetch_codes(), True
        elif args.codes:
            codes, force = [c.strip() for c in args.codes.split(",") if c.strip()], args.force
        else:
            codes, force = refresh_stock_master(client, store, args.include_etf), args.force
        run_backfill(codes, start, force, client, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
