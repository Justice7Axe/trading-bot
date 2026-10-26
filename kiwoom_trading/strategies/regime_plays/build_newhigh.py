"""⑥ 주도주 신고가 백테스트 입력 np_cands.pkl 다시 만들기 (원래 data/research_archive/d9b9b62e/np_build.py, 2026-10-25).

대상: 시장 상황(U/N+/N-/D)이 있는 날마다 **전날** 일봉 대금 상위 200 주식(KOSPI·KOSDAQ, 그날 순위는 안 씀), 통합 AL 1분봉.
매수 자리 (종목당 종류별 하루 1번, 그 봉 종가에 매수):
  E10  09:10 봉 (09:12 까지 봉이 있을 때, 조건은 나중에 거름)
  EPH  전일 고가 돌파: 시가 ≤ 전일 고가, 09:01~14:30 첫 1분 종가 > 전일 고가
  E52  52주 신고가 돌파: 시가 ≤ 52주 고가(전날까지 250일), 09:01~14:30 첫 종가 > 52주 고가
  EOR  장 초 30분 고점 돌파: 09:30~14:30 첫 종가 > 09:00~09:29 고가
매도 ex[(tp, sl, fb)]: 익절 tp / 손절 sl (다음 봉부터, 같은 봉이면 손절 먼저), 못 닿으면 fb='c' 15:19 봉 종가 또는 'n' 다음날 시가. 비용 0.25%.
vrank = 그 분까지 누적 대금 순위 (그날 1분봉이 있는 대상 종목 안에서).
일봉(수정주가) 가격 레벨은 kraw = 1분봉 그날 마지막 정규장 종가 ÷ 일봉 그날 종가 로 1분봉 가격에 맞춘다 (0.5~2 밖이면 뺌).

매매표 계좌(full_bt.py)는 U·N+ 날 vrank ≤ 10 인 E52(11:00 전) 또는 E10(시가가 이미 52주 고가 위·시가 위)를
ex[(None, 0.04, 'n')] (익절 없음·−4% 손절·다음날 시가) 로 쓴다.

실행: python -m kiwoom_trading.strategies.regime_plays.build_newhigh [--daily-db 경로] [--end 2026-10-23] [--asof "2026-10-25 10:31"]
  --asof 없이 돌리면 보존본을 만든 뒤 더 받은 1분봉(2025-10-15 34종목, 2026-10-25 20:45 백필)이 들어가
  그날 행 48개가 늘고 145행의 vrank 가 바뀐다 (매매표가 쓰는 vrank ≤ 10 행은 그대로).
결과: data/backtest/playbook_rebuilt/np_cands.pkl
"""
import argparse
import pickle
import sys
import time as _time
from collections import defaultdict
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from kiwoom_trading.backtest.playbook.paths import MINUTE_DB, SNAPSHOT_DB, open_ro, rebuilt
from kiwoom_trading.backtest.playbook.regime import cls

COST = 0.0025
TPS = (0.03, 0.05, 0.07, 0.10, None)
SLS = (0.02, 0.03, 0.04, 0.05, None)


def _exits(seg, entry, i0, nxt_open):
    """seg: 그날 봉(정렬), i0: 매수 봉 위치. 반환 dict[(tp, sl, fb)] = 수익률."""
    hi = seg.high.values; lo = seg.low.values; op = seg.open.values; cl = seg.close.values; tt = seg.t.values
    out = {}
    end = next((j for j in range(i0 + 1, len(seg)) if tt[j] >= time(15, 19)), len(seg) - 1)
    for tp in TPS:
        for sl in SLS:
            r = None
            for j in range(i0 + 1, end + 1):
                if sl is not None and lo[j] <= entry * (1 - sl): r = min(op[j], entry * (1 - sl)) / entry - 1; break
                if tp is not None and hi[j] >= entry * (1 + tp): r = max(op[j], entry * (1 + tp)) / entry - 1; break
            if r is not None:
                out[(tp, sl, "c")] = out[(tp, sl, "n")] = r - COST
            else:
                out[(tp, sl, "c")] = cl[end] / entry - 1 - COST
                out[(tp, sl, "n")] = (nxt_open / entry - 1 - COST) if nxt_open else np.nan
    return out


def build(daily_db=SNAPSHOT_DB, minute_db=MINUTE_DB, end=date(2026, 10, 23), asof=None):
    """asof(datetime) 를 주면 그 시각 전에 백필이 끝난 (종목, 날짜) 1분봉만 쓴다 — 나중에 더 받은 종목이 vrank 를 바꾸지 않게."""
    dd = open_ro(daily_db)
    mh = open_ro(minute_db)
    stocks = dd.execute("select code, listed_shares from stocks where market in ('KOSPI','KOSDAQ')").df().set_index("code")["listed_shares"]
    daily = dd.execute("select code, date, open, high, low, close, value from daily_ohlcv where date >= '2024-09-01' order by code, date").df()
    daily = daily[daily.code.isin(stocks.index)]
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    g = daily.groupby("code")
    daily["hi52"] = g["high"].transform(lambda s: s.rolling(250, min_periods=120).max())
    daily["hi20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=20).max())
    daily["v20"] = g["value"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    daily["nopen"] = g["open"].shift(-1)
    inv = dd.execute("select code, date, foreign_, institution from investor_daily where date >= '2025-09-01'").df()
    inv["date"] = pd.to_datetime(inv["date"]).dt.date
    inv = inv.set_index(["code", "date"])
    D = daily.set_index(["date", "code"]).sort_index()
    dlv = set(D.index.get_level_values(0))
    days = [r[0] for r in mh.execute("select distinct date from minute_backfill_done where date <= ? order by 1", [end]).fetchall()]
    days = [d for d in days if cls(d)]
    alld = sorted(set(daily.date))

    done = None
    if asof is not None:
        done = defaultdict(set)
        for c, d in mh.execute("select code, date from minute_backfill_done where done_at < ?", [asof]).fetchall():
            done[d].add(c)

    def bars_for(day, codes):
        if done is not None:
            codes = [c for c in codes if c in done[day]] or ["-"]
        q = f"""select code, ts, open, high, low, close, volume from minute_ohlcv
                where exchange='AL' and ts >= '{day} 09:00' and ts < '{day} 15:31' and code in ({",".join("'" + c + "'" for c in codes)}) order by code, ts"""
        return mh.execute(q).df()

    rows = []
    for di, day in enumerate(days):
        if day not in alld:
            continue
        k = alld.index(day)
        prev = alld[k - 1]; nxt = alld[k + 1] if k + 1 < len(alld) else None
        try:
            P = D.loc[prev]
        except KeyError:
            continue
        P = P[P.index.isin(stocks.index)].copy()
        P["mcap"] = P["close"] * stocks.reindex(P.index).values
        P = P.sort_values("value", ascending=False).head(200)
        P["prank"] = np.arange(1, len(P) + 1)
        P["mrank"] = P["mcap"].rank(ascending=False, method="first").astype(int)
        codes = list(P.index)
        b = bars_for(day, codes)
        if b.empty:
            continue
        b["t"] = b.ts.dt.time; b["val"] = b.volume * (b.high + b.low + b.close) / 3
        # 장중 누적 대금 순위 (분 단위, 대상 안)
        piv = b.pivot_table(index="t", columns="code", values="val", aggfunc="sum").fillna(0).cumsum()
        vrank = piv.rank(axis=1, ascending=False, method="first")
        Dd = D.loc[day] if day in dlv else None
        for code, seg in b.groupby("code", sort=False):
            seg = seg.reset_index(drop=True)
            if len(seg) < 200 or seg.t.iloc[0] > time(9, 5):
                continue
            p = P.loc[code]
            try:
                today = Dd.loc[code]
            except Exception:
                continue
            kraw = seg.close.iloc[-1] / today["close"]          # 원가격 ÷ 수정주가 (그날 종가로 맞춤)
            if not (0.5 < kraw < 2.0):
                continue
            pc = p["close"] * kraw; ph = p["high"] * kraw; h52 = p["hi52"] * kraw if p["hi52"] == p["hi52"] else np.nan
            op0 = seg.open.iloc[0]
            nxt_open = (today["nopen"] * kraw) if nxt and today["nopen"] == today["nopen"] else None
            try:
                fr, ins = inv.loc[(code, prev)][["foreign_", "institution"]]
            except KeyError:
                fr = ins = None
            base = dict(date=day, code=code, prank=int(p["prank"]), mrank=int(p["mrank"]), mcap=float(p["mcap"]), gap=op0 / pc - 1,
                        near52=p["close"] / p["hi52"] if p["hi52"] == p["hi52"] else np.nan, near20=p["close"] / p["hi20"],
                        open_over52=bool(h52 == h52 and op0 > h52), open_over_ph=bool(op0 > ph), fr=fr, ins=ins, v20=p["v20"])
            tt = seg.t.values; cl = seg.close.values

            def add(kind, j):
                e = cl[j]
                rows.append(dict(base, kind=kind, t=tt[j], entry=e, chg=e / pc - 1, from_open=e / op0 - 1,
                                 vrank=int(vrank.at[tt[j], code]) if tt[j] in vrank.index else 999,
                                 cumval=float(piv.at[tt[j], code]) if tt[j] in piv.index else 0, ex=_exits(seg, e, j, nxt_open)))
            j10 = next((j for j in range(len(seg)) if tt[j] >= time(9, 10)), None)
            if j10 is not None and tt[j10] <= time(9, 12):
                add("E10", j10)
            last = next((j for j in range(len(seg)) if tt[j] > time(14, 30)), len(seg))
            for kind, lvl in (("EPH", ph), ("E52", h52)):
                if lvl == lvl and op0 <= lvl:
                    j = next((j for j in range(1, last) if cl[j] > lvl), None)
                    if j is not None:
                        add(kind, j)
            orh = seg.loc[seg.t < time(9, 30), "high"].max()
            j = next((j for j in range(len(seg)) if time(9, 30) <= tt[j] <= time(14, 30) and cl[j] > orh), None)
            if j is not None:
                add("EOR", j)
        if di % 20 == 0:
            print(day, len(rows), file=sys.stderr, flush=True)
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="⑥ 주도주 신고가 np_cands.pkl 다시 만들기")
    ap.add_argument("--daily-db", default=SNAPSHOT_DB)
    ap.add_argument("--minute-db", default=MINUTE_DB)
    ap.add_argument("--end", default="2026-10-23", help="1분봉 날짜 끝")
    ap.add_argument("--asof", default="", help="이 시각 전에 받은 1분봉만 (보존본과 맞출 땐 '2026-10-25 10:31')")
    ap.add_argument("--out", default=rebuilt("np_cands.pkl"))
    a = ap.parse_args()
    t0 = _time.time()
    rows = build(a.daily_db, a.minute_db, date.fromisoformat(a.end), datetime.fromisoformat(a.asof) if a.asof else None)
    pickle.dump(rows, open(a.out, "wb"))
    print(f"np_cands {len(rows):,}행 {len({r['date'] for r in rows})}일 → {a.out} ({_time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
