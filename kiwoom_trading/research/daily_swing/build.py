"""일봉 이평선·거래대금 스윙 — 1단계: 일봉 판 만들기 (2026-10-30).

engine.daily_day(d) 로 날짜별 일봉을 읽는다 (9-14 이후 정규장 값으로 바로잡음, 수정주가).
저장 data/daily_swing/panel.parquet  (date, code, o,h,l,c,value, unsure)
     data/daily_swing/inv.parquet    (date, code, foreign_, institution)  — ⑦ 기준용
     data/daily_swing/m1519.parquet  (date, code, p1519) — 15:19 봉 종가를 일봉 가격 기준으로 바꾼 값 (종가 매수 깔끔한 판)
       환산 k = 그날 일봉 정규장 종가 ÷ 그날 1분봉 정규장 마지막 봉 종가  (같은 날 기준 맞추기, 미래 정보 아님)
     data/daily_swing/kospi.parquet  (date, close)
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/daily_swing/build.py
"""
import os, sys
from datetime import date
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "daily_swing"); os.makedirs(OUT, exist_ok=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for d in E.CAL:
        for c, (o, h, l, cl, v, val) in E.daily_day(d).items():
            if not E.is_common(c): continue
            rows.append((d, c, o, h, l, cl, val, (c, d) in E.UNSURE))
    P = pd.DataFrame(rows, columns=["date", "code", "o", "h", "l", "c", "value", "unsure"])
    P.to_parquet(os.path.join(OUT, "panel.parquet"))
    print("panel", len(P), P.date.min(), P.date.max(), "9-14 뒤 못 바꾼 비율", P[P.date >= E.NXT_SWITCH].unsure.mean())

    I = E.DM.execute("SELECT date, code, foreign_, institution FROM investor_daily").df()
    I.to_parquet(os.path.join(OUT, "inv.parquet"))
    pd.DataFrame(sorted(E.KOSPI.items()), columns=["date", "close"]).to_parquet(os.path.join(OUT, "kospi.parquet"))

    # 15:19 봉 종가 + 정규장 마지막 봉 종가 (두 출처 중 정규장 봉이 많은 쪽)
    parts = []
    for si, src in enumerate(E.MIN_SRC):
        q = src.execute("""SELECT code, CAST(ts AS DATE) date,
                   arg_max(close, ts) FILTER (WHERE CAST(ts AS TIME) <= TIME '15:19:59') c1519,
                   max(CAST(ts AS TIME)) FILTER (WHERE CAST(ts AS TIME) <= TIME '15:19:59') t1519,
                   arg_max(close, ts) FILTER (WHERE CAST(ts AS TIME) <= TIME '15:30:59') creg,
                   count(*) nreg
            FROM minute_ohlcv WHERE exchange='AL' AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '15:30:59'
            GROUP BY 1, 2""").df()
        q["src"] = si; parts.append(q)
    M = pd.concat(parts).sort_values("nreg").drop_duplicates(["code", "date"], keep="last")
    M = M[(M.nreg >= 30) & (M.t1519 >= pd.Timestamp("15:10").time())]
    M["date"] = pd.to_datetime(M.date).dt.date
    M = M.merge(P[["date", "code", "c"]], on=["date", "code"])
    M["p1519"] = M.c1519 * M.c / M.creg
    M[["date", "code", "p1519", "nreg"]].to_parquet(os.path.join(OUT, "m1519.parquet"))
    print("m1519", len(M), M.date.min(), M.date.max())


if __name__ == "__main__":
    main()
