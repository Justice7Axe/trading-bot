"""1분봉 DB → daytrader-playbook-kr 스킬 CSV 변환.

- 날짜 D 의 매매 대상은 **전날 대금 상위 N(기본 200)** 만 쓴다 (validate_leader_shape 와 같은 규칙).
  minute_history 의 D 종목에는 'D 의 대금 상위 200' 도 섞여 있어, 그대로 쓰면 결과가 부푼다.
- 1분봉은 통합(AL), 정규장 09:00~15:19 만 내보낸다 (15:30 종가 단일가·애프터마켓 제외).
- prev_close: 전날 1분봉 15:30 종가 단일가 봉(없으면 15:30 이전 마지막 봉) 종가. 없으면 일봉 종가.
  일봉 종가가 애프터마켓 가격으로 들어간 날이 있어 1분봉을 우선한다.
- rvol_base(같은 시각 누적거래량 기준): 직전 20거래일 평균 정규장 거래량 × 시장 전체 평균 '시각별 누적 비중'.
  정규장 거래량은 1분봉(AL)이 있는 날은 그 값, 없는 날은 일봉(KRX) 거래량 × 종목별 AL/KRX 비율 중앙값.
  시각별 비중은 전체 기간 평균이라 약간의 미래 정보가 섞인다(모양만 쓰므로 영향 작음, 리포트에 명시).

출력 (--out, 기본 data/playbook_kr):
  minute/kr_1m_YYYY-MM.csv  datetime,symbol,open,high,low,close,volume,value,prev_close,rvol_base
  daily.csv                 date,symbol,open,high,low,close,volume,value (KRX 일봉, 지표·추세 판정용)
  universe.csv              date,symbol,rank

    .venv\\Scripts\\python.exe -m kiwoom_trading.analysis.playbook_export [--top 200] [--since 2025-10-15]
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile

import duckdb

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _copy(path: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), f"pbx_{os.getpid()}_" + os.path.basename(path))
    shutil.copy(path, dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--since", default="2025-10-15")
    ap.add_argument("--out", default=os.path.join(PROJECT_ROOT, "data", "playbook_kr"))
    ap.add_argument("--db", default="", help="1분봉 DB 경로 (원본이 잠겨 있으면 복사본 지정)")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "minute"), exist_ok=True)
    tmp = [a.db or _copy(os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")),
           _copy(os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb"))]
    c = duckdb.connect()
    c.execute(f"ATTACH '{tmp[0]}' AS m (READ_ONLY)")
    c.execute(f"ATTACH '{tmp[1]}' AS d (READ_ONLY)")
    c.execute("SET preserve_insertion_order=false")

    # 거래일 달력(일봉 기준)과 전날 대금 상위 N
    c.execute("CREATE TEMP TABLE cal AS SELECT date, lag(date) OVER (ORDER BY date) prev FROM "
              "(SELECT DISTINCT date FROM d.daily_ohlcv WHERE code='005930')")
    c.execute("CREATE TEMP TABLE mdays AS SELECT DISTINCT ts::date AS date FROM m.minute_ohlcv WHERE ts::date >= ?",
              [a.since])
    c.execute(f"""CREATE TEMP TABLE univ AS
        SELECT cal.date, r.code, r.rk FROM cal JOIN mdays USING (date)
        JOIN (SELECT date, code, rank() OVER (PARTITION BY date ORDER BY value DESC) rk
              FROM d.daily_ohlcv WHERE value > 0) r ON r.date = cal.prev
        WHERE r.rk <= {a.top}""")

    # 종목·날짜별 정규장 거래량(AL), 마감가
    c.execute("""CREATE TEMP TABLE sess AS
        SELECT code, ts::date AS date, sum(volume) AS vol,
               arg_max(close, ts) AS close_1530
        FROM m.minute_ohlcv WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30' GROUP BY 1, 2""")
    codes = "(SELECT DISTINCT code FROM univ)"
    c.execute(f"""CREATE TEMP TABLE ratio AS
        SELECT s.code, median(s.vol::DOUBLE / dd.volume) AS r FROM sess s
        JOIN d.daily_ohlcv dd ON dd.code = s.code AND dd.date = s.date WHERE dd.volume > 0 GROUP BY 1""")
    mkt_ratio = c.execute("SELECT median(r) FROM ratio").fetchone()[0]
    c.execute(f"""CREATE TEMP TABLE est AS
        SELECT dd.code, dd.date, coalesce(s.vol, dd.volume * coalesce(rt.r, {mkt_ratio})) AS vol
        FROM d.daily_ohlcv dd LEFT JOIN sess s USING (code, date) LEFT JOIN ratio rt USING (code)
        WHERE dd.code IN {codes}""")
    c.execute("""CREATE TEMP TABLE avg20 AS
        SELECT code, date, avg(vol) OVER (PARTITION BY code ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS v20
        FROM est""")
    # 시장 전체 평균 시각별 누적 비중 (정규장 거래량 대비)
    c.execute("""CREATE TEMP TABLE prof AS
        SELECT hm, avg(frac) AS frac FROM (
          SELECT strftime(x.ts, '%H:%M') hm,
                 sum(x.volume) OVER (PARTITION BY x.code, x.ts::date ORDER BY x.ts) / s.vol AS frac
          FROM m.minute_ohlcv x JOIN sess s ON s.code = x.code AND s.date = x.ts::date
          WHERE x.ts::time BETWEEN TIME '09:00' AND TIME '15:19' AND s.vol > 0) GROUP BY 1""")
    c.execute("""CREATE TEMP TABLE pc AS
        SELECT u.date, u.code, coalesce(s.close_1530, dd.close) AS prev_close
        FROM univ u JOIN cal USING (date)
        LEFT JOIN sess s ON s.code = u.code AND s.date = cal.prev
        LEFT JOIN d.daily_ohlcv dd ON dd.code = u.code AND dd.date = cal.prev""")

    months = [r[0] for r in c.execute("SELECT DISTINCT strftime(date, '%Y-%m') FROM univ ORDER BY 1").fetchall()]
    for ym in months:
        path = os.path.join(a.out, "minute", f"kr_1m_{ym}.csv").replace("\\", "/")
        c.execute(f"""COPY (
            SELECT strftime(x.ts, '%Y-%m-%d %H:%M:%S') AS datetime, x.code AS symbol,
                   x.open, x.high, x.low, x.close, x.volume,
                   round(x.volume * (x.high + x.low + x.close) / 3) AS value,
                   pc.prev_close, round(a20.v20 * p.frac) AS rvol_base
            FROM m.minute_ohlcv x
            JOIN univ u ON u.code = x.code AND u.date = x.ts::date
            JOIN pc ON pc.code = x.code AND pc.date = u.date
            LEFT JOIN avg20 a20 ON a20.code = x.code AND a20.date = u.date
            LEFT JOIN prof p ON p.hm = strftime(x.ts, '%H:%M')
            WHERE strftime(u.date, '%Y-%m') = '{ym}' AND x.ts::time BETWEEN TIME '09:00' AND TIME '15:19'
            ORDER BY symbol, x.ts) TO '{path}' (HEADER, DELIMITER ',')""")
        print("written", path)
    out = a.out.replace("\\", "/")
    c.execute(f"""COPY (SELECT strftime(date, '%Y-%m-%d') AS date, code AS symbol, open, high, low, close, volume, value
        FROM d.daily_ohlcv WHERE code IN {codes} AND date >= DATE '{a.since}' - INTERVAL 150 DAY ORDER BY 2, 1)
        TO '{out}/daily.csv' (HEADER, DELIMITER ',')""")
    c.execute(f"COPY (SELECT strftime(date, '%Y-%m-%d') AS date, code AS symbol, rk AS rank FROM univ ORDER BY 1, 3) "
              f"TO '{out}/universe.csv' (HEADER, DELIMITER ',')")
    n = c.execute("SELECT count(*), count(DISTINCT date), count(DISTINCT code) FROM univ").fetchone()
    print(f"universe rows={n[0]} days={n[1]} codes={n[2]}, AL/KRX 거래량 비율 중앙값={mkt_ratio:.3f}")
    c.close()
    for p in tmp:
        if p != a.db:
            os.remove(p)


if __name__ == "__main__":
    main()
