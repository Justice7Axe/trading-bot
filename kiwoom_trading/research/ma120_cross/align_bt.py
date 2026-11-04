"""전날 애프터장 강세 종목: 골든크로스 + '정배열 우상향' 포함 1년 검증 (2026-11-04 사용자 '골든 크로스도 포함하고 더하여 120선 60선 정배열 우상향 종목도 포함').

대상: 전날 대금 상위 100 중 전날 애프터(15:30→20:00) 등락 ≥ 1%. 1분봉 minute_history 통합(AL) 08:00~20:00 이어 붙임.
신호 (09:30 ~ LAST 사이 처음 맞는 봉, 다음 봉 시가 매수):
  GC  : 60선이 120선 아래 → 위로 바뀐 봉, 종가 > 120선
  ALN : 정배열 우상향 — 60선 > 120선, 60선·120선 모두 10봉 전보다 높음, 종가 > 60선
매도: −3% 손절, 익절 없음, 못 닿으면 다음 날 09:00 시가. 비용 0.25%.
"""
import duckdb
import numpy as np
import pandas as pd

d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-11-01' order by 1").fetchall()]
T0930, T1530 = pd.Timestamp('09:30').time(), pd.Timestamp('15:30').time()
LASTS = {'10:40': pd.Timestamp('10:40').time(), '11:30': pd.Timestamp('11:30').time()}
rows = []
for di in range(1, len(days) - 1):
    prev, day, nxt = days[di - 1], days[di], days[di + 1]
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit 100", [prev]).fetchall()]
    df = d.execute("select code, ts, open, high, low, close from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, prev, nxt]).df()
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall())
    for code, g in df.groupby('code'):
        g = g.reset_index(drop=True)
        tm = g.ts.dt.time
        dt_ = g.ts.dt.date
        pv = g[dt_ == prev]
        rp = pv[pv.ts.dt.time <= T1530]
        if not len(rp):
            continue
        after = pv.close.iloc[-1] / rp.close.iloc[-1] - 1
        if after < 0.01:
            continue
        g['m60'] = g.close.rolling(60).mean()
        g['m120'] = g.close.rolling(120).mean()
        up = g.m60 > g.m120
        gc = up & ~up.shift(fill_value=True) & (g.close > g.m120)
        aln = up & (g.m60 > g.m60.shift(10)) & (g.m120 > g.m120.shift(10)) & (g.close > g.m60)
        today = (dt_ == day)
        last_reg = g.index[today & (tm <= T1530)].max()
        for lname, LT in LASTS.items():
            win = today & (tm >= T0930) & (tm <= LT) & g.m120.notna()
            for kind, sig in (('GC', gc), ('ALN', aln), ('GC+ALN', gc | aln)):
                idx = g.index[win & sig]
                if not len(idx):
                    continue
                k = idx[0]
                i = k + 1
                b = g.open[i]
                ex = None
                for j in range(i, last_reg + 1):
                    if g.low[j] <= b * 0.97:
                        ex = b * 0.97
                        break
                ex = ex or nopen.get(code)
                if not ex:
                    continue
                how = 'GC' if gc[k] else 'ALN'
                rows.append(dict(day=day, code=code, after=after, last=lname, kind=kind, how=how, T=g.ts[k], ret=ex / b - 1 - 0.0025))
R = pd.DataFrame(rows)
R.to_csv('data/ma120_cross/align_bt.csv', index=False, encoding='utf-8-sig')
ds = sorted(R.day.unique())
half, q3 = ds[len(ds) // 2], ds[-63]
print("조건 | 건수 | 날 | 평균 | 승률 | 앞/뒤 | 최근3달 | 최고10뺀")
for a in (0.01, 0.02, 0.03):
    for lname in LASTS:
        for kind in ('GC', 'ALN', 'GC+ALN'):
            x = R[(R.after >= a) & (R['last'] == lname) & (R.kind == kind)]
            if len(x) < 10:
                continue
            v = x.ret.sort_values(ascending=False)
            print(f"애프터≥{a:.0%} ~{lname} {kind:6s} | {len(x)} | {x.day.nunique()} | {x.ret.mean() * 100:+.2f}% | {(x.ret > 0).mean() * 100:.0f}% | "
                  f"{x[x.day < half].ret.mean() * 100:+.2f}/{x[x.day >= half].ret.mean() * 100:+.2f} | {x[x.day >= q3].ret.mean() * 100:+.2f} | {v.iloc[10:].mean() * 100:+.2f}")
