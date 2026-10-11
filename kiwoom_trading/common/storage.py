import json
import logging
from typing import Any

import requests


class SupabaseWriter:
    def __init__(self, supabase_url: str, service_role_key: str, table_name: str) -> None:
        self.endpoint = f"{supabase_url.rstrip('/')}/rest/v1/{table_name}"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def insert_rows(self, rows: list[dict[str, Any]]) -> None:
        response = requests.post(
            self.endpoint,
            headers=self.headers,
            data=json.dumps(rows),
            timeout=10,
        )
        response.raise_for_status()
        logging.info(
            "Supabase 행 저장 완료: endpoint=%s rows=%s status=%s",
            self.endpoint,
            len(rows),
            response.status_code,
        )

    def insert_tick(self, payload: dict[str, Any]) -> None:
        self.insert_rows([payload])


class SupabaseReader:
    def __init__(self, supabase_url: str, service_role_key: str, table_name: str) -> None:
        self.endpoint = f"{supabase_url.rstrip('/')}/rest/v1/{table_name}"
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        }

    def fetch_recent_by_stock(self, stock_code: str, limit: int = 500) -> list[dict[str, Any]]:
        params = {
            "select": (
                "id,collected_at,stock_code,current_price,open_price,high_price,low_price,"
                "cum_trade_volume,cum_trade_value,trade_volume,raw_values"
            ),
            "stock_code": f"eq.{stock_code}",
            "order": "collected_at.desc",
            "limit": str(limit),
        }
        response = requests.get(self.endpoint, headers=self.headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return []

    def fetch_recent_top_value_by_stock(self, stock_code: str, limit: int = 240) -> list[dict[str, Any]]:
        params = {
            "select": "id,collected_at,snapshot_minute,stock_code,stock_name,current_price,trade_value_rank,cum_trade_value,raw_item",
            "stock_code": f"eq.{stock_code}",
            "order": "snapshot_minute.desc,trade_value_rank.asc",
            "limit": str(limit),
        }
        response = requests.get(self.endpoint, headers=self.headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return []

    def fetch_latest_top_value_snapshot(self, top_n: int = 100) -> list[dict[str, Any]]:
        params = {
            "select": "collected_at,snapshot_minute,stock_code,stock_name,current_price,trade_value_rank,cum_trade_value",
            "order": "snapshot_minute.desc,trade_value_rank.asc",
            "limit": str(max(1, top_n)),
        }
        response = requests.get(self.endpoint, headers=self.headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        return []
