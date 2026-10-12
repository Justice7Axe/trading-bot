"""일봉 DB에서 '오늘 이전' 이력 지표를 종목별로 미리 계산한다 (장중에는 하루 한 번만 계산)."""
from dataclasses import dataclass
from datetime import date
from typing import Optional

import duckdb


@dataclass(frozen=True)
class HistStats:
    code: str
    last_date: date
    last_close: int
    prior_high_250: Optional[int]      # 오늘 이전 249거래일 최고가 (오늘 고가와 합쳐 250일 고가)
    prior_high_60: Optional[int]       # 오늘 이전 60거래일 최고가
    atr14_pct: Optional[float]         # 최근 14일 평균 진폭(True Range) / 직전 종가
    avg_value_20: Optional[float]      # 최근 20일 평균 거래대금(원)
    value_rank_1: Optional[int]        # 1거래일 전 시장 거래대금 순위
    value_rank_2: Optional[int]        # 2거래일 전 시장 거래대금 순위


def load_history(conn: duckdb.DuckDBPyConnection, before: date) -> dict[str, HistStats]:
    """before 날짜 '이전' 데이터만 사용 (before 당일은 포함하지 않음)."""
    rows = conn.execute(
        """
        WITH d AS (
            SELECT o.code, o.date, o.high, o.low, o.close, o.value,
                   lag(o.close) OVER (PARTITION BY o.code ORDER BY o.date) AS prev_close,
                   row_number() OVER (PARTITION BY o.code ORDER BY o.date DESC) AS rn,
                   rank() OVER (PARTITION BY o.date ORDER BY o.value DESC) AS vrank
            FROM daily_ohlcv o JOIN stocks s USING (code)
            WHERE o.date < ? AND NOT s.delisted
        )
        SELECT code,
               max(date) FILTER (WHERE rn = 1),
               max(close) FILTER (WHERE rn = 1),
               max(high) FILTER (WHERE rn <= 249),
               max(high) FILTER (WHERE rn <= 60),
               avg(greatest(high, prev_close) - least(low, prev_close)) FILTER (WHERE rn <= 14),
               avg(value) FILTER (WHERE rn <= 20),
               max(vrank) FILTER (WHERE rn = 1),
               max(vrank) FILTER (WHERE rn = 2)
        FROM d WHERE rn <= 250
        GROUP BY code
        """,
        [before],
    ).fetchall()
    stats = {}
    for code, last_date, last_close, h250, h60, atr, avg_val, vr1, vr2 in rows:
        if not last_close:
            continue
        stats[code] = HistStats(
            code=code, last_date=last_date, last_close=last_close, prior_high_250=h250, prior_high_60=h60,
            atr14_pct=atr / last_close if atr else None, avg_value_20=avg_val, value_rank_1=vr1, value_rank_2=vr2,
        )
    return stats


def stock_names(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """선정 대상 종목(보통주, 상장 유지) 이름. ETF/ETN/스팩은 stocks 에 없으므로 자동 제외된다."""
    return dict(conn.execute("SELECT code, name FROM stocks WHERE NOT delisted").fetchall())
