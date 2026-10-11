import os
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone

from dotenv import load_dotenv


KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class AppSettings:
    kiwoom_base_url: str
    kiwoom_ws_url: str
    kiwoom_app_key: str
    kiwoom_secret_key: str
    stock_codes: list[str]
    supabase_url: str
    supabase_service_role_key: str
    supabase_table: str
    use_login_packet: bool
    use_auth_header: bool
    save_interval_seconds: int


def load_settings() -> AppSettings:
    load_dotenv(".env.local")

    kiwoom_base_url = os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com")
    kiwoom_ws_url = os.getenv("KIWOOM_WS_URL", "wss://api.kiwoom.com:10000/api/dostk/websocket")
    kiwoom_app_key = os.getenv("KIWOOM_APP_KEY", "")
    kiwoom_secret_key = os.getenv("KIWOOM_SECRET_KEY", "")
    stock_codes = [code.strip() for code in os.getenv("KIWOOM_STOCK_CODES", "005930,000660").split(",") if code.strip()]
    supabase_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL") or ""
    supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_table = os.getenv("SUPABASE_TABLE", "kiwoom_realtime_ticks")
    use_login_packet = os.getenv("KIWOOM_WS_USE_LOGIN_PACKET", "true").lower() == "true"
    use_auth_header = os.getenv("KIWOOM_WS_USE_AUTH_HEADER", "false").lower() == "true"
    save_interval_seconds = int(os.getenv("KIWOOM_SAVE_INTERVAL_SECONDS", "60"))

    if not kiwoom_app_key or not kiwoom_secret_key:
        raise RuntimeError("KIWOOM_APP_KEY / KIWOOM_SECRET_KEY 환경변수를 설정해주세요.")
    if not supabase_url or not supabase_service_role_key:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 환경변수를 확인해주세요.")
    if not stock_codes:
        raise RuntimeError("KIWOOM_STOCK_CODES 환경변수에 최소 1개 이상의 종목코드가 필요합니다.")

    return AppSettings(
        kiwoom_base_url=kiwoom_base_url,
        kiwoom_ws_url=kiwoom_ws_url,
        kiwoom_app_key=kiwoom_app_key,
        kiwoom_secret_key=kiwoom_secret_key,
        stock_codes=stock_codes,
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        supabase_table=supabase_table,
        use_login_packet=use_login_packet,
        use_auth_header=use_auth_header,
        save_interval_seconds=save_interval_seconds,
    )


def is_business_day(now: datetime) -> bool:
    return now.weekday() < 5


def is_collection_window(now: datetime) -> bool:
    if os.getenv("KIWOOM_FORCE_RUN", "false").lower() == "true":
        return True
    return is_business_day(now) and dtime(9, 0, 0) <= now.time() < dtime(11, 0, 0)


def next_collection_start(now: datetime) -> datetime:
    candidate = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if is_business_day(now) and now.time() < dtime(9, 0, 0):
        return candidate

    candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate
