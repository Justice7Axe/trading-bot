"""신호일 시점 주도 섹터(업종) 지표.

- 업종 거래대금 비중: 최근 5거래일 업종 거래대금 합 ÷ 시장 전체 거래대금 합 (신호 종목 자신 제외)
- 업종 내 장대양봉 비율: 최근 10거래일 안에 장대양봉(고가 +15%, 양봉, 거래대금 300억↑)이 나온 횟수
  ÷ 업종 종목 수 (신호 종목 자신 제외)
업종은 stocks.sector (키움 ka10099 upName). 종목 5개 미만 업종은 계산하지 않는다.
"""
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

import duckdb


BIG_CANDLE_RISE = 0.15
BIG_CANDLE_MIN_VALUE = 30_000_000_000  # 300억
SHARE_DAYS = 5
BIG_DAYS = 10
MIN_SECTOR_SIZE = 5


@dataclass(frozen=True)
class SectorMetrics:
    sector: str
    value_share: float      # 업종 거래대금 비중 (0.05 = 5%)
    big_ratio: float        # 업종 내 장대양봉 비율 (0.10 = 10%)
    members: int


def compute_sector_metrics(conn: duckdb.DuckDBPyConnection, keys: Iterable[tuple[str, date]]) -> dict[tuple[str, date], SectorMetrics]:
    keys = list(set(keys))
    if not keys:
        return {}
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _sec_daily AS
        SELECT o.code, o.date, s.sector, o.value,
               CASE WHEN lag(o.close) OVER w > 0
                         AND o.high / lag(o.close) OVER w - 1 >= {BIG_CANDLE_RISE}
                         AND o.close > o.open AND o.value >= {BIG_CANDLE_MIN_VALUE}
                    THEN 1 ELSE 0 END AS big
        FROM daily_ohlcv o JOIN stocks s USING (code)
        WHERE s.sector IS NOT NULL
        WINDOW w AS (PARTITION BY o.code ORDER BY o.date)
    """)
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _sec_roll AS
        WITH sd AS (
            SELECT sector, date, count(*) AS n, sum(value) AS val, sum(big) AS big FROM _sec_daily GROUP BY 1, 2
        ), md AS (
            SELECT date, sum(value) AS mval FROM _sec_daily GROUP BY 1
        )
        SELECT sd.sector, sd.date, sd.n,
               sum(sd.val) OVER ws AS val_s, sum(md.mval) OVER ws AS mval_s, sum(sd.big) OVER wb AS big_b
        FROM sd JOIN md USING (date)
        WINDOW ws AS (PARTITION BY sd.sector ORDER BY sd.date ROWS BETWEEN {SHARE_DAYS - 1} PRECEDING AND CURRENT ROW),
               wb AS (PARTITION BY sd.sector ORDER BY sd.date ROWS BETWEEN {BIG_DAYS - 1} PRECEDING AND CURRENT ROW)
    """)
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _sec_self AS
        SELECT code, date, sector,
               sum(value) OVER (PARTITION BY code ORDER BY date ROWS BETWEEN {SHARE_DAYS - 1} PRECEDING AND CURRENT ROW) AS sval_s,
               sum(big) OVER (PARTITION BY code ORDER BY date ROWS BETWEEN {BIG_DAYS - 1} PRECEDING AND CURRENT ROW) AS sbig_b
        FROM _sec_daily
    """)
    conn.execute("CREATE OR REPLACE TEMP TABLE _sec_keys (code VARCHAR, date DATE)")
    conn.executemany("INSERT INTO _sec_keys VALUES (?, ?)", keys)
    rows = conn.execute(f"""
        SELECT k.code, k.date, r.sector, r.n, (r.val_s - me.sval_s) / r.mval_s, (r.big_b - me.sbig_b) / r.n
        FROM _sec_keys k
        JOIN _sec_self me ON me.code = k.code AND me.date = k.date
        JOIN _sec_roll r ON r.sector = me.sector AND r.date = k.date
        WHERE r.n >= {MIN_SECTOR_SIZE}
    """).fetchall()
    return {(code, d): SectorMetrics(sector, share, ratio, n) for code, d, sector, n, share, ratio in rows}


def leading_sector_reason(metrics: Optional[SectorMetrics], min_share: Optional[float], min_big_ratio: Optional[float]) -> Optional[str]:
    """주도 섹터 조건 미달 사유. 통과면 None."""
    if min_share is None and min_big_ratio is None:
        return None
    if metrics is None:
        return "업종 정보 없음"
    if min_share is not None and metrics.value_share < min_share:
        return f"업종 거래대금 비중 {metrics.value_share:.1%}"
    if min_big_ratio is not None and metrics.big_ratio < min_big_ratio:
        return f"업종 내 장대양봉 비율 {metrics.big_ratio:.0%}"
    return None
