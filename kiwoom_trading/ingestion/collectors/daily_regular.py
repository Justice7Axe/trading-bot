"""정규장 일봉 만들기 — 1분봉(통합 AL)의 09:00~15:30 봉으로 시가·고가·저가·종가·거래량·거래대금 → data/daily_regular.duckdb.

왜: 2026-09-14 NXT 전 종목 확대부터 키움 일봉(ka10081)·일별(ka10086)이 통합(정규장+애프터) 값을 준다.
  daily_ohlcv 종가 = 20:00 애프터 종가, 고가·저가에 애프터 가격이 섞임 (9-11 까지는 정규장 값).
  키움에는 정규장만의 일봉 API 가 없어, 정규장 값은 1분봉에서만 구할 수 있다 (메모리 daily-nxt-switch, 디앤서 스킬 7-0).
주의:
  - 1분봉이 있는 종목(minute_history = 날짜별 대금 상위 500 + 다음 날)만 만든다.
  - 가격은 1분봉을 받은 날 기준 — daily_ohlcv(수정주가)와 액면분할 등이 있으면 다를 수 있다. 등락률은 같은 표 안의 값끼리 계산할 것.
  - 거래대금 = Σ(1분봉 종가 × 거래량) 근사 (정규장 시간의 KRX+NXT 합).
  - daily_ohlcv 는 건드리지 않는다 (실전 매매가 쓰는 중 — 바꿔 쓸지는 따로 결정).

    python -m kiwoom_trading.ingestion.collectors.daily_regular                    # 2026-09-14 부터 아직 없는 것
    python -m kiwoom_trading.ingestion.collectors.daily_regular --since 2025-10-15 --all
minute_history_backfill 이 끝날 때 자동으로 부른다 (새로 받은 날짜만).
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, time

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.daily_store import PROJECT_ROOT

HISTORY_DB = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
REGULAR_DB = os.path.join(PROJECT_ROOT, "data", "daily_regular.duckdb")
NXT_SWITCH = date(2026, 9, 14)

SCHEMA = """CREATE TABLE IF NOT EXISTS daily_regular (
    code VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, value DOUBLE,
    bars INTEGER, has_after BOOLEAN, made_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY (code, date))"""


def build(since: date = NXT_SWITCH, redo: bool = False, history_db: str = HISTORY_DB, regular_db: str = REGULAR_DB) -> int:
    """minute_history 의 (종목, 날짜) 중 since 이후를 정규장 일봉으로 만든다. redo=False 면 이미 있는 것은 건너뜀. 만든 건수."""
    out = duckdb.connect(regular_db)
    try:
        out.execute(SCHEMA)
        have = set() if redo else {(c, d) for c, d in out.execute("SELECT code, date FROM daily_regular WHERE date >= ?", [since]).fetchall()}
        src = duckdb.connect(history_db, read_only=True)
        try:
            todo = [(c, d) for c, d in src.execute("SELECT code, date FROM minute_backfill_done WHERE date >= ? AND bars > 0", [since]).fetchall()
                    if (c, d) not in have]
            days = sorted({d for _, d in todo})
            n = 0
            for d in days:
                rows = src.execute(
                    """SELECT code,
                              arg_min(open, ts) FILTER (WHERE t BETWEEN ? AND ?)  AS o,
                              max(high)        FILTER (WHERE t BETWEEN ? AND ?)  AS h,
                              min(low)         FILTER (WHERE t BETWEEN ? AND ?)  AS l,
                              arg_max(close, ts) FILTER (WHERE t BETWEEN ? AND ?) AS c,
                              sum(volume)      FILTER (WHERE t BETWEEN ? AND ?)  AS v,
                              sum(close * volume) FILTER (WHERE t BETWEEN ? AND ?) AS val,
                              count(*)         FILTER (WHERE t BETWEEN ? AND ?)  AS nb,
                              bool_or(t >= ?) AS aft
                       FROM (SELECT *, CAST(ts AS TIME) t FROM minute_ohlcv WHERE exchange='AL' AND ts >= ? AND ts < ?)
                       GROUP BY code""",
                    [time(9, 0), time(15, 30)] * 7 + [time(15, 40), datetime.combine(d, time(0)), datetime.combine(d, time(23, 59))]).fetchall()
                want = {c for c, dd in todo if dd == d}
                vals = [(c, d, o, h, l, cl, int(v or 0), float(val or 0), nb, aft) for c, o, h, l, cl, v, val, nb, aft in rows
                        if c in want and nb and nb >= 30 and cl]
                if vals:
                    out.executemany("""INSERT OR REPLACE INTO daily_regular (code, date, open, high, low, close, volume, value, bars, has_after)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", vals)
                    n += len(vals)
                logging.info("정규장 일봉 %s: %s종목", d, len(vals))
            return n
        finally:
            src.close()
    finally:
        out.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="1분봉으로 정규장 일봉 만들기 (2026-09-14 NXT 확대 뒤 일봉이 통합 값이라서)")
    ap.add_argument("--since", default=NXT_SWITCH.isoformat())
    ap.add_argument("--all", action="store_true", help="이미 있는 것도 다시 만듦")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = build(date.fromisoformat(a.since), redo=a.all)
    logging.info("정규장 일봉 %s건 저장 → %s", n, REGULAR_DB)


if __name__ == "__main__":
    main()
