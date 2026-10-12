"""스크리너 기록 저장 (data/screener.duckdb).

메인 일봉 DB 와 분리해서, 장중 1분마다 쓰더라도 일봉 DB 를 잠그지 않는다.
- rank_snapshots: 조회 순위/거래대금 순위 스냅샷 (과거 데이터를 API로 받을 수 없어 직접 쌓는다 → 추후 백테스트용)
- detections: 포착 기록 (같은 날 같은 모드·종목은 1회만 알림)
"""
import json
import os
from datetime import date, datetime
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT, load_env
from kiwoom_trading.screener.conditions import Evaluation
from kiwoom_trading.screener.market_data import RankItem


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rank_snapshots (
    ts          TIMESTAMP,
    date        DATE,
    source      VARCHAR,      -- 'search_1m' | 'search_day' | 'value'
    rank        INTEGER,
    code        VARCHAR,
    name        VARCHAR,
    change_rate DOUBLE,
    price       BIGINT,
    trade_value BIGINT
);
CREATE TABLE IF NOT EXISTS theme_members (   -- 종목→테마 매핑 (하루 1회 갱신)
    date        DATE,
    theme_code  VARCHAR,
    theme_name  VARCHAR,
    code        VARCHAR
);
CREATE TABLE IF NOT EXISTS detections (
    date        DATE,
    mode        VARCHAR,      -- 'intraday' | 'daily'
    code        VARCHAR,
    ts          TIMESTAMP,
    name        VARCHAR,
    price       BIGINT,
    change_rate DOUBLE,
    trade_value BIGINT,
    score       INTEGER,
    checks      VARCHAR,      -- JSON {조건: [통과, 사유]}
    scenarios   VARCHAR,      -- JSON [{name, entry, stop, target}]
    theme       VARCHAR,
    PRIMARY KEY (date, mode, code)
);
"""


class ScreenerStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        load_env()
        self.db_path = db_path or os.getenv("SCREENER_DB_PATH", os.path.join(PROJECT_ROOT, "data", "screener.duckdb"))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = duckdb.connect(self.db_path)
        self.conn.execute(SCHEMA_SQL)

    def close(self) -> None:
        self.conn.close()

    def save_ranks(self, ts: datetime, source: str, items: list[RankItem]) -> None:
        if items:
            self.conn.executemany(
                "INSERT INTO rank_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(ts, ts.date(), source, i.rank, i.code, i.name, i.change_rate, i.price, i.trade_value) for i in items],
            )

    def theme_mapping(self, day: date) -> dict[str, list[str]]:
        """종목코드 → 테마코드 목록 (해당 날짜에 저장된 매핑)."""
        mapping: dict[str, list[str]] = {}
        for theme_code, code in self.conn.execute("SELECT theme_code, code FROM theme_members WHERE date = ?", [day]).fetchall():
            mapping.setdefault(code, []).append(theme_code)
        return mapping

    def save_theme_mapping(self, day: date, rows: list[tuple[str, str, str]]) -> None:
        """rows: (theme_code, theme_name, code)"""
        self.conn.execute("DELETE FROM theme_members WHERE date = ?", [day])
        if rows:
            self.conn.executemany("INSERT INTO theme_members VALUES (?, ?, ?, ?)", [(day, *r) for r in rows])

    def detected_codes(self, day: date, mode: str) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT code FROM detections WHERE date = ? AND mode = ?", [day, mode]).fetchall()}

    def save_detection(self, day: date, mode: str, ts: datetime, e: Evaluation) -> None:
        c = e.candidate
        self.conn.execute(
            """
            INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date, mode, code) DO UPDATE SET
                ts = excluded.ts, price = excluded.price, change_rate = excluded.change_rate,
                trade_value = excluded.trade_value, score = excluded.score, checks = excluded.checks,
                scenarios = excluded.scenarios, theme = excluded.theme
            """,
            [
                day, mode, c.code, ts, c.name, c.price, c.change_rate, c.trade_value, e.score,
                json.dumps(e.checks, ensure_ascii=False),
                json.dumps([{"name": s.name, "entry": s.entry, "stop": s.stop, "target": s.target} for s in e.scenarios], ensure_ascii=False),
                e.best_theme.name if e.best_theme else None,
            ],
        )
