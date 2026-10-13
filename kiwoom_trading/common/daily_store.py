import os
from datetime import date
from typing import Any, Optional

import duckdb
from dotenv import load_dotenv


# 실행 위치(cwd)와 무관하게 프로젝트 루트(D:/Ellie/trading) 기준으로 경로를 잡는다 → 작업 스케줄러 실행 대비
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")


def load_env() -> None:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env.local"))

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stocks (
    code         VARCHAR PRIMARY KEY,
    name         VARCHAR,
    market       VARCHAR,
    list_date    DATE,
    delisted     BOOLEAN DEFAULT FALSE,
    updated_at   TIMESTAMP DEFAULT current_timestamp
);

-- 가격은 모두 '수정주가' 기준. 액면분할/증자 발생 시 해당 종목 전 구간을 키움 ka10081로 다시 받는다.
CREATE TABLE IF NOT EXISTS daily_ohlcv (
    code        VARCHAR,
    date        DATE,
    open        BIGINT,
    high        BIGINT,
    low         BIGINT,
    close       BIGINT,
    volume      BIGINT,
    value       BIGINT,      -- 거래대금(원). 키움 백필분은 백만원 단위를 환산한 근사값
    market_cap  BIGINT,      -- KRX 수집분만 존재
    source      VARCHAR,     -- 'kiwoom' | 'krx'
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS backfill_status (
    code        VARCHAR PRIMARY KEY,
    start_date  DATE,
    rows        INTEGER,
    done_at     TIMESTAMP DEFAULT current_timestamp
);

-- 권리락 등으로 재백필이 필요한 종목. 처리되면 삭제된다.
CREATE TABLE IF NOT EXISTS refetch_queue (
    code        VARCHAR PRIMARY KEY,
    detected_on DATE,
    reason      VARCHAR
);

-- 시가총액 계산용 상장주식수 (키움 ka10099 listCount / KRX LIST_SHRS)
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS listed_shares BIGINT;
-- 업종명 (키움 ka10099 upName, 예: 전기/전자, 화학)
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS sector VARCHAR;

-- 1분봉 (키움 ka10080, 수정주가). exchange: 'KRX'(09:00~, 일봉과 같은 기준) / 'AL'(KRX+NXT 통합, 08:00~20:00) / 'NX'(NXT)
CREATE TABLE IF NOT EXISTS minute_ohlcv (
    code        VARCHAR,
    exchange    VARCHAR,
    ts          TIMESTAMP,   -- 봉 시작 시각 (KST)
    open        BIGINT,
    high        BIGINT,
    low         BIGINT,
    close       BIGINT,
    volume      BIGINT,
    PRIMARY KEY (code, exchange, ts)
);
"""

OHLCV_COLUMNS = ("code", "date", "open", "high", "low", "close", "volume", "value", "market_cap", "source")


class DailyStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        load_env()
        self.db_path = db_path or os.getenv("DAILY_DB_PATH", DEFAULT_DB_PATH)
        if not os.path.isabs(self.db_path):
            self.db_path = os.path.join(PROJECT_ROOT, self.db_path)
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = duckdb.connect(self.db_path)
        self.conn.execute(SCHEMA_SQL)

    def close(self) -> None:
        self.conn.close()

    # --- stocks -------------------------------------------------------------
    def upsert_stocks(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT INTO stocks (code, name, market, list_date, listed_shares, sector, delisted, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, FALSE, current_timestamp)
            ON CONFLICT (code) DO UPDATE SET
                name = excluded.name,
                market = excluded.market,
                list_date = COALESCE(excluded.list_date, stocks.list_date),
                listed_shares = COALESCE(excluded.listed_shares, stocks.listed_shares),
                sector = COALESCE(excluded.sector, stocks.sector),
                delisted = FALSE,
                updated_at = excluded.updated_at
            """,
            [(r["code"], r.get("name"), r.get("market"), r.get("list_date"), r.get("listed_shares"), r.get("sector") or None) for r in rows],
        )

    def mark_delisted_except(self, active_codes: set[str]) -> int:
        """이번 종목 리스트에 없는 종목을 상장폐지로 표시(데이터는 삭제하지 않음 → 생존편향 방지)."""
        known = {row[0] for row in self.conn.execute("SELECT code FROM stocks WHERE NOT delisted").fetchall()}
        gone = sorted(known - active_codes)
        if gone:
            self.conn.executemany("UPDATE stocks SET delisted = TRUE, updated_at = now() WHERE code = ?", [(c,) for c in gone])
        return len(gone)

    # --- daily_ohlcv --------------------------------------------------------
    def upsert_ohlcv(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        placeholders = ", ".join("?" for _ in OHLCV_COLUMNS)
        updates = ", ".join(f"{col} = excluded.{col}" for col in OHLCV_COLUMNS if col not in ("code", "date"))
        self.conn.executemany(
            f"""
            INSERT INTO daily_ohlcv ({", ".join(OHLCV_COLUMNS)}) VALUES ({placeholders})
            ON CONFLICT (code, date) DO UPDATE SET {updates}
            """,
            [tuple(r.get(col) for col in OHLCV_COLUMNS) for r in rows],
        )
        return len(rows)

    def replace_stock_history(self, code: str, rows: list[dict[str, Any]]) -> int:
        """수정주가 재계산용: 종목 전체 이력을 원자적으로 교체한다.

        KRX에서만 받은 market_cap 값은 보존한다.
        """
        self.conn.execute("BEGIN TRANSACTION")
        try:
            caps = dict(self.conn.execute(
                "SELECT date, market_cap FROM daily_ohlcv WHERE code = ? AND market_cap IS NOT NULL", [code]
            ).fetchall())
            self.conn.execute("DELETE FROM daily_ohlcv WHERE code = ?", [code])
            for r in rows:
                if r.get("market_cap") is None and r["date"] in caps:
                    r["market_cap"] = caps[r["date"]]
            self.upsert_ohlcv(rows)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return len(rows)

    def last_date(self) -> Optional[date]:
        row = self.conn.execute("SELECT max(date) FROM daily_ohlcv").fetchone()
        return row[0] if row else None

    def last_closes_before(self, day: date) -> dict[str, tuple[date, int]]:
        """각 종목의 day 직전 거래일 종가."""
        rows = self.conn.execute(
            """
            SELECT code, date, close FROM (
                SELECT code, date, close,
                       row_number() OVER (PARTITION BY code ORDER BY date DESC) AS rn
                FROM daily_ohlcv WHERE date < ?
            ) WHERE rn = 1
            """,
            [day],
        ).fetchall()
        return {code: (d, close) for code, d, close in rows}

    # --- backfill_status / refetch_queue -------------------------------------
    def upsert_minutes(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.conn.executemany(
            """
            INSERT INTO minute_ohlcv (code, exchange, ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (code, exchange, ts) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low, close = excluded.close, volume = excluded.volume
            """,
            [(r["code"], r["exchange"], r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows],
        )
        return len(rows)

    def backfill_start(self, code: str) -> Optional[date]:
        """재수집 시작일: 처음 백필한 시작일, 없으면 저장된 가장 이른 날짜."""
        row = self.conn.execute("SELECT start_date FROM backfill_status WHERE code = ?", [code]).fetchone()
        if row and row[0]:
            return row[0]
        row = self.conn.execute("SELECT min(date) FROM daily_ohlcv WHERE code = ?", [code]).fetchone()
        return row[0] if row else None

    def backfilled_codes(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT code FROM backfill_status").fetchall()}

    def mark_backfilled(self, code: str, start_date: date, rows: int) -> None:
        self.conn.execute(
            """
            INSERT INTO backfill_status (code, start_date, rows, done_at) VALUES (?, ?, ?, current_timestamp)
            ON CONFLICT (code) DO UPDATE SET start_date = excluded.start_date, rows = excluded.rows, done_at = excluded.done_at
            """,
            [code, start_date, rows],
        )

    def enqueue_refetch(self, code: str, detected_on: date, reason: str) -> None:
        self.conn.execute(
            """
            INSERT INTO refetch_queue (code, detected_on, reason) VALUES (?, ?, ?)
            ON CONFLICT (code) DO UPDATE SET detected_on = excluded.detected_on, reason = excluded.reason
            """,
            [code, detected_on, reason],
        )

    def refetch_codes(self) -> list[str]:
        return [row[0] for row in self.conn.execute("SELECT code FROM refetch_queue ORDER BY detected_on").fetchall()]

    def dequeue_refetch(self, code: str) -> None:
        self.conn.execute("DELETE FROM refetch_queue WHERE code = ?", [code])
