import logging
import time
from datetime import datetime
from typing import Optional

from kiwoom_trading.common.config import KST, AppSettings, is_collection_window, load_settings, next_collection_start
from kiwoom_trading.common.storage import SupabaseWriter
from kiwoom_trading.ingestion.collectors.kiwoom_login import fetch_kiwoom_access_token
from kiwoom_trading.ingestion.collectors.realtime_collector import KiwoomRealtimeCollector


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def run_scheduler(settings: Optional[AppSettings] = None) -> None:
    config = settings or load_settings()

    writer = SupabaseWriter(
        supabase_url=config.supabase_url,
        service_role_key=config.supabase_service_role_key,
        table_name=config.supabase_table,
    )

    logging.info("수집 시작 대기 중. 대상 종목=%s", ",".join(config.stock_codes))

    collector: Optional[KiwoomRealtimeCollector] = None

    while True:
        now = datetime.now(KST)
        in_window = is_collection_window(now)

        if not in_window:
            if collector:
                collector.stop()
                collector = None
            next_start = next_collection_start(now)
            wait_seconds = int((next_start - now).total_seconds())
            logging.info("수집 시간 아님(09:00~11:00). 다음 시작까지 %s초", wait_seconds)
            time.sleep(min(wait_seconds, 60))
            continue

        if collector is None or not collector.is_alive():
            if collector is not None:
                collector.stop()
            token = fetch_kiwoom_access_token(
                base_url=config.kiwoom_base_url,
                app_key=config.kiwoom_app_key,
                secret_key=config.kiwoom_secret_key,
            )
            collector = KiwoomRealtimeCollector(
                ws_url=config.kiwoom_ws_url,
                token=token,
                stock_codes=config.stock_codes,
                writer=writer,
                use_login_packet=config.use_login_packet,
                use_auth_header=config.use_auth_header,
                save_interval_seconds=config.save_interval_seconds,
            )
            collector.start()

        time.sleep(3)
