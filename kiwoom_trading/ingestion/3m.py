import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import KST, is_collection_window, next_collection_start
from kiwoom_trading.common.storage import SupabaseReader, SupabaseWriter
from kiwoom_trading.ingestion.collectors.kiwoom_login import fetch_kiwoom_access_token
from kiwoom_trading.ingestion.collectors.three_minute_signal_evaluator import evaluate_3m_signal
from kiwoom_trading.ingestion.collectors.top_value_snapshot_collector import (
    KiwoomTopValueSnapshotCollector,
)


def _configure_utf8_console() -> None:
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.SetConsoleCP(65001)
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


@dataclass(frozen=True)
class TopValueSettings:
    kiwoom_base_url: str
    kiwoom_app_key: str
    kiwoom_secret_key: str
    supabase_url: str
    supabase_service_role_key: str
    supabase_table: str
    mrkt_tp: str
    mang_stk_incls: str
    stex_tp: str
    interval_seconds: int
    top_n: int
    signal_table: str
    signal_scan_interval_seconds: int


def load_top_value_settings() -> TopValueSettings:
    load_dotenv(".env.local")
    kiwoom_base_url = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
    kiwoom_app_key = os.getenv("KIWOOM_APP_KEY", "")
    kiwoom_secret_key = os.getenv("KIWOOM_SECRET_KEY", "")
    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL") or ""
    supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_table = os.getenv("KIWOOM_TOP_VALUE_SUPABASE_TABLE") or os.getenv(
        "SUPABASE_TABLE",
        "kiwoom_top_value_minute",
    )
    mrkt_tp = os.getenv("KIWOOM_TOP_VALUE_MRKT_TP", "000")
    mang_stk_incls = os.getenv("KIWOOM_TOP_VALUE_MANAGEMENT_INCLS", "0")
    stex_tp = os.getenv("KIWOOM_TOP_VALUE_STEX_TP", "3")
    interval_seconds = int(os.getenv("KIWOOM_TOP_VALUE_INTERVAL_SECONDS", "60"))
    top_n = int(os.getenv("KIWOOM_TOP_VALUE_LIMIT", "100"))
    signal_table = os.getenv("KIWOOM_TOP_VALUE_SIGNAL_TABLE", "kiwoom_top_value_signals")
    signal_scan_interval_seconds = int(os.getenv("KIWOOM_TOP_VALUE_SIGNAL_SCAN_INTERVAL_SECONDS", "5"))

    if not kiwoom_app_key or not kiwoom_secret_key:
        raise RuntimeError("KIWOOM_APP_KEY / KIWOOM_SECRET_KEY 환경변수를 설정해주세요.")
    if not supabase_url or not supabase_service_role_key:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 환경변수를 확인해주세요.")

    return TopValueSettings(
        kiwoom_base_url=kiwoom_base_url,
        kiwoom_app_key=kiwoom_app_key,
        kiwoom_secret_key=kiwoom_secret_key,
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        supabase_table=supabase_table,
        mrkt_tp=mrkt_tp,
        mang_stk_incls=mang_stk_incls,
        stex_tp=stex_tp,
        interval_seconds=max(1, interval_seconds),
        top_n=max(1, top_n),
        signal_table=signal_table,
        signal_scan_interval_seconds=max(1, signal_scan_interval_seconds),
    )


def _normalize_snapshot_rows(rows: list[dict]) -> list[dict]:
    latest_minute = ""
    normalized: list[dict] = []
    for row in rows:
        snapshot_minute = str(row.get("snapshot_minute") or "")
        if snapshot_minute == "":
            continue
        if latest_minute == "":
            latest_minute = snapshot_minute
        if snapshot_minute != latest_minute:
            continue
        normalized.append(row)
    return normalized


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_etf_etn_spac(name: str) -> bool:
    upper = name.upper()
    if "ETF" in upper or "ETN" in upper:
        return True
    # 스팩/스펙(한국어 SPAC 표기 변형)
    if "스팩" in name or "스펙" in name:
        return True
    return False


def run_top_value_scheduler(settings: Optional[TopValueSettings] = None) -> None:
    config = settings or load_top_value_settings()
    source_writer = SupabaseWriter(
        supabase_url=config.supabase_url,
        service_role_key=config.supabase_service_role_key,
        table_name=config.supabase_table,
    )
    source_reader = SupabaseReader(
        supabase_url=config.supabase_url,
        service_role_key=config.supabase_service_role_key,
        table_name=config.supabase_table,
    )
    signal_writer = SupabaseWriter(
        supabase_url=config.supabase_url,
        service_role_key=config.supabase_service_role_key,
        table_name=config.signal_table,
    )

    collector: Optional[KiwoomTopValueSnapshotCollector] = None
    next_scan_at = 0.0
    last_processed_snapshot = ""
    token = ""
    logging.info(
        "거래대금 상위+3분봉(중심선/RSI/거래량/지지) 신호 수집 대기: mrkt_tp=%s stex_tp=%s top_n=%s interval=%ss signal_table=%s",
        config.mrkt_tp,
        config.stex_tp,
        config.top_n,
        config.interval_seconds,
        config.signal_table,
    )

    while True:
        now = datetime.now(KST)
        in_window = is_collection_window(now)

        if not in_window:
            if collector:
                collector.stop()
                collector = None
            last_processed_snapshot = ""
            next_start = next_collection_start(now)
            wait_seconds = int((next_start - now).total_seconds())
            logging.info("수집 시간 아님(09:00~11:00). 다음 시작까지 %s초", wait_seconds)
            time.sleep(min(wait_seconds, 60))
            continue

        if collector is None or not collector.is_alive():
            if collector is not None:
                collector.stop()
            if token == "":
                token = fetch_kiwoom_access_token(
                    base_url=config.kiwoom_base_url,
                    app_key=config.kiwoom_app_key,
                    secret_key=config.kiwoom_secret_key,
                )
            collector = KiwoomTopValueSnapshotCollector(
                base_url=config.kiwoom_base_url,
                token=token,
                writer=source_writer,
                mrkt_tp=config.mrkt_tp,
                mang_stk_incls=config.mang_stk_incls,
                stex_tp=config.stex_tp,
                interval_seconds=config.interval_seconds,
                top_n=config.top_n,
            )
            collector.start()
            logging.info("거래대금 상위 수집기 시작")

        now_ts = time.time()
        if now_ts >= next_scan_at:
            try:
                snapshot_rows = _normalize_snapshot_rows(
                    source_reader.fetch_latest_top_value_snapshot(top_n=config.top_n)
                )
                if snapshot_rows:
                    snapshot_minute = str(snapshot_rows[0].get("snapshot_minute") or "")
                    if snapshot_minute != "" and snapshot_minute != last_processed_snapshot:
                        saved = 0
                        for row in snapshot_rows:
                            stock_code = str(row.get("stock_code") or "").strip()
                            if stock_code == "":
                                continue
                            stock_name = str(row.get("stock_name") or "").strip()
                            if stock_name and _is_etf_etn_spac(stock_name):
                                continue
                            recent_rows = source_reader.fetch_recent_top_value_by_stock(
                                stock_code=stock_code, limit=300
                            )
                            signal = evaluate_3m_signal(recent_rows)
                            side = signal.get("signal_side")
                            if side != "long":
                                continue

                            display_name = f"3M{stock_name}" if stock_name else "3M"
                            payload = {
                                "analyzed_at": datetime.now(KST).isoformat(),
                                "snapshot_minute": signal.get("latest_minute_key") or snapshot_minute,
                                "stock_code": stock_code,
                                "stock_name": display_name,
                                "signal_side": side,
                                "signal_reason": signal.get("reason"),
                                "current_price": signal.get("close"),
                                "ma_5": None,
                                "ma_25": signal.get("ma20"),
                                "ma_75": None,
                                "ma_75_prev": None,
                                "trade_value_rank": _safe_int(row.get("trade_value_rank")),
                                "cum_trade_value": _safe_int(row.get("cum_trade_value")),
                                "source_table": config.supabase_table,
                                "strategy_name": "3m_center_rsi_support",
                            }
                            try:
                                signal_writer.insert_tick(payload)
                                saved += 1
                                logging.info(
                                    "3M 신호 저장: minute=%s code=%s name=%s rank=%s",
                                    payload["snapshot_minute"],
                                    stock_code,
                                    display_name,
                                    payload["trade_value_rank"],
                                )
                            except requests.HTTPError as exc:
                                status_code = exc.response.status_code if exc.response is not None else None
                                if status_code == 409:
                                    logging.info(
                                        "3M 신호 중복 스킵: minute=%s code=%s",
                                        payload["snapshot_minute"],
                                        stock_code,
                                    )
                                else:
                                    logging.exception("3M 신호 저장 실패: code=%s err=%s", stock_code, exc)

                        last_processed_snapshot = snapshot_minute
                        logging.info("신호 스캔 완료: snapshot=%s top_n=%s saved=%s", snapshot_minute, len(snapshot_rows), saved)
            except Exception as exc:
                logging.exception("신호 스캔 실패: %s", exc)
            next_scan_at = now_ts + config.signal_scan_interval_seconds

        time.sleep(1)


if __name__ == "__main__":
    try:
        _configure_utf8_console()
        _configure_logging()
        run_top_value_scheduler()
    except KeyboardInterrupt:
        logging.info("수집 프로그램이 종료되었습니다.")
