import os
import sys
from collections import Counter
from typing import Any

import requests
from dotenv import load_dotenv


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


def _load_env() -> tuple[str, str, str]:
    load_dotenv(".env.local")
    supabase_url = (os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL") or "").rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    signal_table = os.getenv("KIWOOM_TOP_VALUE_SIGNAL_TABLE", "kiwoom_top_value_signals")
    if not supabase_url or not service_role_key:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수를 확인해주세요.")
    return supabase_url, service_role_key, signal_table


def _fetch_recent_signals(
    supabase_url: str,
    service_role_key: str,
    signal_table: str,
    limit: int,
) -> list[dict[str, Any]]:
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }
    params = {
        "select": (
            "analyzed_at,snapshot_minute,stock_code,signal_side,signal_reason,"
            "current_price,trade_value_rank,cum_trade_value"
        ),
        "order": "analyzed_at.desc",
        "limit": str(limit),
    }
    response = requests.get(
        f"{supabase_url}/rest/v1/{signal_table}",
        headers=headers,
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        return data
    return []


def _fetch_latest_names(
    supabase_url: str,
    service_role_key: str,
    source_table: str,
    stock_codes: list[str],
) -> dict[str, str]:
    if not stock_codes:
        return {}
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }
    code_list = ",".join(sorted(set(stock_codes)))
    params = {
        "select": "stock_code,stock_name,collected_at",
        "stock_code": f"in.({code_list})",
        "order": "collected_at.desc",
        "limit": str(len(stock_codes) * 5),
    }
    response = requests.get(
        f"{supabase_url}/rest/v1/{source_table}",
        headers=headers,
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        return {}
    names: dict[str, str] = {}
    for row in data:
        code = str(row.get("stock_code") or "").strip()
        name = str(row.get("stock_name") or "").strip()
        if code and name and code not in names:
            names[code] = name
    return names


def _is_etf_etn_spac(name: str) -> bool:
    upper = name.upper()
    if "ETF" in upper or "ETN" in upper:
        return True
    if "스팩" in name or "스펙" in name:
        return True
    return False


def main() -> None:
    _configure_utf8_console()
    supabase_url, service_role_key, signal_table = _load_env()
    limit = int(os.getenv("ANALYSIS_SIGNAL_LIMIT", "50"))
    rows = _fetch_recent_signals(
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        signal_table=signal_table,
        limit=limit,
    )

    print("=== 거래대금 상위 이평 신호 분석 ===")

    if not rows:
        print("최근 신호가 없습니다.")
        return

    side_counter = Counter(str(row.get("signal_side") or "unknown") for row in rows)
    all_codes = [str(row.get("stock_code") or "") for row in rows if str(row.get("stock_code") or "")]
    name_map = _fetch_latest_names(
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        source_table=os.getenv("KIWOOM_TOP_VALUE_SUPABASE_TABLE", "kiwoom_top_value_minute"),
        stock_codes=all_codes,
    )

    # ETF/ETN/스팩 종목 제외
    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("stock_code") or "")
        if not code:
            continue
        name = name_map.get(code, "")
        if name and _is_etf_etn_spac(name):
            continue
        filtered_rows.append(row)

    if not filtered_rows:
        print("ETF/ETN/스팩 제외 후 남는 신호가 없습니다.")
        return

    side_counter = Counter(str(row.get("signal_side") or "unknown") for row in filtered_rows)
    code_counter = Counter(str(row.get("stock_code") or "") for row in filtered_rows if str(row.get("stock_code") or ""))
    long_rows = [row for row in filtered_rows if str(row.get("signal_side") or "") == "long"][:1]
    short_rows = [row for row in filtered_rows if str(row.get("signal_side") or "") == "short"][:1]

    # 한 줄 요약
    print(
        f"요약 | table={signal_table} | 조회={len(rows)}/{limit} | "
        f"LONG={side_counter.get('long', 0)} | SHORT={side_counter.get('short', 0)} | "
        f"종목수={len(code_counter)}"
    )
    print("")

    print("[최근 LONG 1건]")
    if not long_rows:
        print("- 없음")
    for row in long_rows:
        code = str(row.get("stock_code") or "")
        name = name_map.get(code, "")
        print(
            f"- {row.get('analyzed_at')} | code={code} {name} | "
            f"rank={row.get('trade_value_rank')} | price={row.get('current_price')} | "
            f"reason={row.get('signal_reason')}"
        )

    print("")
    print("[최근 SHORT 1건]")
    if not short_rows:
        print("- 없음")
    for row in short_rows:
        code = str(row.get("stock_code") or "")
        name = name_map.get(code, "")
        print(
            f"- {row.get('analyzed_at')} | code={code} {name} | "
            f"rank={row.get('trade_value_rank')} | price={row.get('current_price')} | "
            f"reason={row.get('signal_reason')}"
        )


if __name__ == "__main__":
    main()
