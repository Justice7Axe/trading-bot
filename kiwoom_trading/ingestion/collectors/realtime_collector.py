import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

import websocket

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.storage import SupabaseWriter


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = str(value).strip().replace(",", "")
    if value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    value = str(value).strip().replace(",", "")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


class KiwoomRealtimeCollector:
    def __init__(
        self,
        ws_url: str,
        token: str,
        stock_codes: list[str],
        writer: SupabaseWriter,
        use_login_packet: bool,
        use_auth_header: bool,
        save_interval_seconds: int,
    ) -> None:
        self.ws_url = ws_url
        self.token = token
        self.stock_codes = stock_codes
        self.writer = writer
        self.use_login_packet = use_login_packet
        self.use_auth_header = use_auth_header
        self.save_interval_seconds = max(1, save_interval_seconds)

        self.ws_app: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.flush_thread: Optional[threading.Thread] = None
        self.logged_in = False
        self.subscribed = False
        self.running = False
        self.latest_by_stock: dict[str, dict[str, Any]] = {}
        self.last_saved_minute_by_stock: dict[str, str] = {}
        self.state_lock = threading.Lock()

    def _send_subscribe(self, ws: websocket.WebSocketApp) -> None:
        subscribe_payload = {
            "trnm": "REG",
            "grp_no": "1",
            "refresh": "1",
            "data": [{"item": self.stock_codes, "type": ["0B"]}],
        }
        ws.send(json.dumps(subscribe_payload, ensure_ascii=False))
        self.subscribed = True
        logging.info("구독 요청 전송 완료: %s", ",".join(self.stock_codes))

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        logging.info("키움 WebSocket 연결 성공")
        if self.use_login_packet:
            ws.send(json.dumps({"trnm": "LOGIN", "token": self.token}, ensure_ascii=False))
            logging.info("LOGIN 패킷 전송 완료")
            return
        self._send_subscribe(ws)

    def _on_close(self, _: websocket.WebSocketApp, close_status_code: Any, close_msg: Any) -> None:
        logging.warning("WebSocket 연결 종료 code=%s msg=%s", close_status_code, close_msg)

    def _on_error(self, _: websocket.WebSocketApp, error: Any) -> None:
        logging.error("WebSocket 오류: %s", error)

    def _handle_realtime_message(self, data_item: dict[str, Any]) -> None:
        values: dict[str, str] = data_item.get("values", {})
        payload: dict[str, Any] = {
            "collected_at": datetime.now(KST).isoformat(),
            "event_time": values.get("20"),
            "stock_code": data_item.get("item"),
            "current_price": _to_int(values.get("10")),
            "price_change": _to_int(values.get("11")),
            "change_rate": _to_float(values.get("12")),
            "trade_volume": _to_int(values.get("15")),
            "cum_trade_volume": _to_int(values.get("13")),
            "cum_trade_value": _to_int(values.get("14")),
            "open_price": _to_int(values.get("16")),
            "high_price": _to_int(values.get("17")),
            "low_price": _to_int(values.get("18")),
            "best_ask": _to_int(values.get("27")),
            "best_bid": _to_int(values.get("28")),
            "market_type": values.get("290"),
            "trade_strength": _to_float(values.get("228")),
            "raw_values": values,
        }
        stock_code = str(payload.get("stock_code") or "").strip()
        if stock_code == "":
            return
        with self.state_lock:
            self.latest_by_stock[stock_code] = payload

    def _flush_latest_snapshot(self) -> None:
        with self.state_lock:
            snapshot = dict(self.latest_by_stock)
            saved_minute_map = dict(self.last_saved_minute_by_stock)

        if not snapshot:
            logging.info("1분 저장 스킵: 아직 수신된 시세가 없습니다.")
            return

        minute_key = datetime.now(KST).strftime("%Y%m%d%H%M")
        for stock_code, payload in snapshot.items():
            if saved_minute_map.get(stock_code) == minute_key:
                continue
            save_payload = dict(payload)
            raw_values = dict(save_payload.get("raw_values") or {})
            raw_values["snapshot_minute"] = minute_key
            save_payload["raw_values"] = raw_values
            save_payload["collected_at"] = datetime.now(KST).isoformat()
            self.writer.insert_tick(save_payload)
            with self.state_lock:
                self.last_saved_minute_by_stock[stock_code] = minute_key
            logging.info(
                "1분 저장 완료: code=%s price=%s volume=%s",
                stock_code,
                save_payload["current_price"],
                save_payload["trade_volume"],
            )

    def _flush_loop(self) -> None:
        while self.running:
            now = time.time()
            wait_seconds = self.save_interval_seconds - (int(now) % self.save_interval_seconds)
            if wait_seconds <= 0:
                wait_seconds = self.save_interval_seconds
            time.sleep(wait_seconds)
            if not self.running:
                break
            try:
                self._flush_latest_snapshot()
            except Exception as exc:
                logging.exception("1분 저장 처리 실패: %s", exc)

    def _on_message(self, _: websocket.WebSocketApp, message: str) -> None:
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            logging.warning("JSON 파싱 실패, 원문 일부: %s", message[:120])
            return

        trnm = parsed.get("trnm")
        if trnm == "PING":
            if self.ws_app:
                self.ws_app.send(json.dumps(parsed, ensure_ascii=False))
            return

        if trnm == "LOGIN":
            if parsed.get("return_code") == 0:
                self.logged_in = True
                logging.info("LOGIN 성공")
                if self.ws_app and not self.subscribed:
                    self._send_subscribe(self.ws_app)
            else:
                logging.error("LOGIN 실패: %s", parsed)
            return

        if trnm != "REAL":
            logging.info("응답 수신: %s", parsed)
            return

        for item in parsed.get("data", []):
            if item.get("type") == "0B":
                try:
                    self._handle_realtime_message(item)
                except Exception as exc:
                    logging.exception("실시간 데이터 저장 실패: %s", exc)

    def start(self) -> None:
        self.running = True
        headers = []
        if self.use_auth_header:
            headers.append(f"authorization: Bearer {self.token}")

        self.ws_app = websocket.WebSocketApp(
            self.ws_url,
            header=headers or None,
            on_open=self._on_open,
            on_message=self._on_message,
            on_close=self._on_close,
            on_error=self._on_error,
        )
        self.ws_thread = threading.Thread(
            target=self.ws_app.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10},
            daemon=True,
        )
        self.ws_thread.start()
        self.flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self.flush_thread.start()

    def is_alive(self) -> bool:
        ws_alive = bool(self.ws_thread and self.ws_thread.is_alive())
        flush_alive = bool(self.flush_thread and self.flush_thread.is_alive())
        return ws_alive and flush_alive

    def stop(self) -> None:
        self.running = False
        if self.ws_app:
            self.ws_app.close()
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=5)
        if self.flush_thread and self.flush_thread.is_alive():
            self.flush_thread.join(timeout=5)
