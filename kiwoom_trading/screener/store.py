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
    source      VARCHAR,      -- 'search_1m' | 'search_day' | 'value_krx' (거래대금 KRX 기준)
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
CREATE TABLE IF NOT EXISTS buy_signals (      -- 1분봉 매수 신호 (지지 반등 / 돌파 후 눌림)
    date        DATE,
    code        VARCHAR,
    ts          TIMESTAMP,    -- 신호 봉 시각
    kind        VARCHAR,
    name        VARCHAR,
    price       DOUBLE,       -- 진입가 (신호 봉 종가)
    level       DOUBLE,       -- 기준선 (지지선 / 돌파선)
    stop        DOUBLE,
    reason      VARCHAR,
    source      VARCHAR,      -- '전일 관심' | '쉬는 주도주' | '장중 포착' | '조회 급등' | '대금 가속' | '프리마켓 주목'
    alerted     BOOLEAN,
    PRIMARY KEY (date, code, ts, kind)
);
CREATE TABLE IF NOT EXISTS rest_leaders (     -- ① 쉬어 가는 주도주 (date = 기준일, 다음 거래일에 감시)
    date        DATE,
    code        VARCHAR,
    name        VARCHAR,
    close       BIGINT,
    change_rate DOUBLE,
    run_10d     DOUBLE,
    trade_value BIGINT,
    reason      VARCHAR,
    PRIMARY KEY (date, code)
);
ALTER TABLE buy_signals ADD COLUMN IF NOT EXISTS reject_reason VARCHAR;   -- 품질 필터에 걸린 사유 (NULL = 통과)
CREATE TABLE IF NOT EXISTS early_alerts (       -- 🏁/🚀 즉시 알림 기록 (감시 목록 포함 여부와 무관하게 종목·출처별 하루 1회)
    date        DATE,
    source      VARCHAR,
    code        VARCHAR,
    ts          TIMESTAMP,
    name        VARCHAR,
    reason      VARCHAR,
    PRIMARY KEY (date, source, code)
);
CREATE TABLE IF NOT EXISTS investor_intraday (  -- 장중 외국인·기관 순매수 잠정치 스냅샷 (값이 바뀔 때만 저장, 과거분은 API 로 못 받음)
    ts          TIMESTAMP,
    date        DATE,
    investor    VARCHAR,      -- 'foreign' | 'institution'
    code        VARCHAR,
    net_amount  BIGINT        -- 원, 장 시작부터 누적
);
CREATE TABLE IF NOT EXISTS watch_adds (       -- ②③④ 장중 조기 감시 추가 (재시작해도 유지)
    date        DATE,
    code        VARCHAR,
    ts          TIMESTAMP,
    name        VARCHAR,
    source      VARCHAR,
    reason      VARCHAR,
    PRIMARY KEY (date, code)
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

    # ---------------------------------------------------------------- 매수 신호 감시 목록
    def previous_daily_watchlist(self, day: date) -> dict[str, str]:
        """day 직전 거래일의 '다음 거래일 관심 종목'(장 마감 후 리포트 통과 종목). 코드 → 이름"""
        row = self.conn.execute("SELECT max(date) FROM detections WHERE mode = 'daily' AND date < ?", [day]).fetchone()
        if not row or not row[0]:
            return {}
        return dict(self.conn.execute("SELECT code, name FROM detections WHERE mode = 'daily' AND date = ?", [row[0]]).fetchall())

    def intraday_watchlist(self, day: date) -> dict[str, str]:
        return dict(self.conn.execute("SELECT code, name FROM detections WHERE mode = 'intraday' AND date = ?", [day]).fetchall())

    def save_investor_intraday(self, ts: datetime, investor: str, values: dict[str, int]) -> None:
        if values:
            self.conn.executemany("INSERT INTO investor_intraday VALUES (?, ?, ?, ?, ?)",
                                  [(ts, ts.date(), investor, code, amount) for code, amount in values.items() if amount])

    def save_rest_leaders(self, day: date, leaders: list) -> None:
        """leaders: early_watch.RestLeader 목록 (그날 기준으로 통째로 교체)."""
        self.conn.execute("DELETE FROM rest_leaders WHERE date = ?", [day])
        if leaders:
            self.conn.executemany(
                "INSERT INTO rest_leaders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(day, x.code, x.name, x.close, x.change, x.run_10d, x.value, x.reason) for x in leaders],
            )

    def rest_leaders_since(self, start: date, day: date) -> list[tuple[date, str, str, int]]:
        """start ≤ 기준일 < day 의 쉬어 가는 주도주 [(기준일, 코드, 이름, 쉬는 날 종가)], 최신 기준일 우선."""
        return self.conn.execute(
            "SELECT date, code, name, close FROM rest_leaders WHERE date >= ? AND date < ? ORDER BY date DESC", [start, day]
        ).fetchall()

    def previous_rest_leaders(self, day: date) -> dict[str, str]:
        """day 에 감시할 쉬어 가는 주도주 (최근 REST_HOLD_DAYS 거래일, 이탈 종목 제외). 코드 → 이름"""
        from kiwoom_trading.screener.early_watch import active_rest_leaders

        return {code: name for code, (name, _) in active_rest_leaders(self, day).items()}

    def save_watch_add(self, day: date, ts: datetime, code: str, name: str, source: str, reason: str) -> None:
        self.conn.execute("INSERT INTO watch_adds VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", [day, code, ts, name, source, reason])

    def watch_adds(self, day: date) -> dict[str, tuple[str, str]]:
        """코드 → (이름, 출처)"""
        return {c: (n, s) for c, n, s in self.conn.execute("SELECT code, name, source FROM watch_adds WHERE date = ?", [day]).fetchall()}

    def signal_keys(self, day: date) -> set[tuple[str, datetime, str]]:
        return {(c, ts, k) for c, ts, k in self.conn.execute("SELECT code, ts, kind FROM buy_signals WHERE date = ?", [day]).fetchall()}

    def save_signal(self, day: date, code: str, name: str, signal, source: str, alerted: bool, reject: Optional[str] = None) -> None:
        self.conn.execute(
            "INSERT INTO buy_signals (date, code, ts, kind, name, price, level, stop, reason, source, alerted, reject_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            [day, code, signal.ts, signal.kind, name, signal.price, signal.level, signal.stop, signal.reason, source, alerted, reject],
        )

    def passed_signals(self, day: date) -> dict[str, list]:
        """오늘 품질 필터를 통과한 신호 (종목 → [Signal]) — 재시작해도 '손절 후 반복 금지' 판정 유지."""
        from kiwoom_trading.screener.intraday_signals import Signal

        out: dict[str, list] = {}
        for code, ts, kind, price, level, stop, reason in self.conn.execute(
                "SELECT code, ts, kind, price, level, stop, reason FROM buy_signals WHERE date = ? AND reject_reason IS NULL ORDER BY ts",
                [day]).fetchall():
            out.setdefault(code, []).append(Signal(ts, kind, price, level, stop, reason))
        return out

    def early_alerted(self, day: date) -> set[tuple[str, str]]:
        return {(s, c) for s, c in self.conn.execute("SELECT source, code FROM early_alerts WHERE date = ?", [day]).fetchall()}

    def save_early_alert(self, day: date, source: str, code: str, ts: datetime, name: str, reason: str) -> None:
        self.conn.execute("INSERT INTO early_alerts VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", [day, source, code, ts, name, reason])
