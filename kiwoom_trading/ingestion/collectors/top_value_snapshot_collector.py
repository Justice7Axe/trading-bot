import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

import requests

from kiwoom_trading.common.config import KST, is_collection_window
from kiwoom_trading.common.storage import SupabaseWriter


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_code(code: Optional[str]) -> str:
    value = str(code or "").strip()
    if value.startswith("A"):
        return value[1:]
    return value


def _is_etf_etn_spac(name: Optional[str]) -> bool:
    if name is None:
        return False
    text = str(name).strip()
    if not text:
        return False
    upper = text.upper()
    if "ETF" in upper or "ETN" in upper:
        return True
    if "스팩" in text or "스펙" in text:
        return True
    return False


class KiwoomTopValueSnapshotCollector:
    def __init__(
        self,
        base_url: str,
        token: str,
        writer: SupabaseWriter,
        mrkt_tp: str,
        mang_stk_incls: str,
        stex_tp: str,
        interval_seconds: int,
        top_n: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/api/dostk/rkinfo"
        self.token = token
        self.writer = writer
        self.mrkt_tp = str(mrkt_tp).strip()
        self.mang_stk_incls = str(mang_stk_incls).strip()
        self.stex_tp = str(stex_tp).strip()
        self.interval_seconds = max(1, interval_seconds)
        self.top_n = max(1, top_n)

        self.poll_thread: Optional[threading.Thread] = None
        self.running = False
        self.state_lock = threading.Lock()  # reserved for future token refresh support

    def _fetch_top_trading_value(self) -> list[dict[str, Any]]:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token}",
            "api-id": "ka10032",
            "cont-yn": "N",
            "next-key": "",
        }
        body = {
            "mrkt_tp": self.mrkt_tp,
            "mang_stk_incls": self.mang_stk_incls,
            "stex_tp": self.stex_tp,
        }
        response = requests.post(self.endpoint, headers=headers, json=body, timeout=15)
        response.raise_for_status()
        payload = response.json()
        return_code = payload.get("return_code")
        if return_code not in (0, "0", None):
            raise RuntimeError(f"ka10032 실패: {payload}")
        data = payload.get("trde_prica_upper", [])
        if not isinstance(data, list):
            return []
        return data

    def _build_rows(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        snapshot_time = datetime.now(KST)
        snapshot_minute = snapshot_time.strftime("%Y%m%d%H%M")
        rows: list[dict[str, Any]] = []
        for fallback_rank, item in enumerate(data[: self.top_n], start=1):
            if not isinstance(item, dict):
                continue
            stock_code = _clean_code(item.get("stk_cd"))
            if stock_code == "":
                continue
            stock_name = item.get("stk_nm")
            if _is_etf_etn_spac(stock_name):
                continue
            rank = _to_int(item.get("now_rank")) or fallback_rank
            trade_value = _to_int(item.get("trde_prica")) or 0
            rows.append(
                {
                    "collected_at": snapshot_time.isoformat(),
                    "snapshot_minute": snapshot_minute,
                    "condition_seq": "ka10032",
                    "market_type": self.mrkt_tp,
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "current_price": _to_int(item.get("cur_prc")),
                    "change_rate": _to_float(item.get("flu_rt")),
                    "cum_trade_value": trade_value,
                    "trade_value_rank": rank,
                    "raw_item": item,
                }
            )
        return rows

    def _save_snapshot_once(self) -> None:
        data = self._fetch_top_trading_value()
        rows = self._build_rows(data)
        if not rows:
            logging.info("저장할 데이터가 없어 스킵")
            return
        self.writer.insert_rows(rows)
        logging.info("저장 완료: snapshot=%s rows=%s", rows[0]["snapshot_minute"], len(rows))

    def _poll_loop(self) -> None:
        if self.running and is_collection_window(datetime.now(KST)):
            try:
                self._save_snapshot_once()
            except Exception as exc:
                logging.exception("초기 스냅샷 저장 실패: %s", exc)
        while self.running:
            now = datetime.now(KST)
            if not is_collection_window(now):
                time.sleep(1)
                continue
            wait_seconds = self.interval_seconds - (int(time.time()) % self.interval_seconds)
            if wait_seconds <= 0:
                wait_seconds = self.interval_seconds
            time.sleep(wait_seconds)
            if not self.running:
                break
            try:
                self._save_snapshot_once()
            except Exception as exc:
                logging.exception("1분 스냅샷 저장 실패: %s", exc)

    def start(self) -> None:
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def is_alive(self) -> bool:
        return bool(self.poll_thread and self.poll_thread.is_alive())

    def stop(self) -> None:
        self.running = False
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=5)
