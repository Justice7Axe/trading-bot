"""🪜 애프터 정배열 + '전일 고가 넘을 때' 조건 1년 검증 (2026-11-04 사용자 '전일고가를 넘을 때 매매한다는 조건을 넣는다면?').

대상: 전날 대금 상위 100 중 전날 애프터(15:30→20:00) ≥ 2% (또는 3%). 1분봉 minute_history 통합(AL) 08:00~20:00.
전일 고가: R = 전날 정규장(09:00~15:30) 고가, A = 전날 08:00~20:00 전체 고가(애프터 포함).
방식:
  F  : 09:30~10:40 첫 GC(또는 GC/ALN) 봉 종가가 이미 전일 고가 위일 때만 다음 봉 매수 (거르기)
  W  : 첫 GC 이후(GC 봉 포함) ~ 15:00 사이 종가가 전일 고가를 처음 넘는 봉 → 다음 봉 매수 (기다렸다 돌파)
  B0 : 크로스 없이 09:30~15:00 종가가 전일 고가를 처음 넘는 봉 → 다음 봉 매수 (비교용)
매도: −3% 손절, 익절 없음, 못 닿으면 다음 날 09:00 시가. 비용 0.25%.
"""
import duckdb
import numpy as np
import pandas as pd

d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-11-01' order by 1").fetchall()]
T0900, T0930, T1040, T1500, T1530 = (pd.Timestamp(x).time() for x in ('09:00', '09:30', '10:40', '15:00', '15:30'))
rows = []


def sell(g, i, last_reg, no):
    b = g.open[i]
    for j in range(i, last_reg + 1):
        if g.low[j] <= b * 0.97:
            return b * 0.97 / b - 1 - 0.0025
    return no / b - 1 - 0.0025


for di in range(1, len(days) - 1):
    prev, day, nxt = days[di - 1], days[di], days[di + 1]
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit 100", [prev]).fetchall()]
    df = d.execute("select code, ts, open, high, low, close from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, prev, nxt]).df()
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall())
    for code, g in df.groupby('code'):
        no = nopen.get(code)
        if not no:
            continue
        g = g.reset_index(drop=True)
        tm, dt_ = g.ts.dt.time, g.ts.dt.date
        pv = g[dt_ == prev]
        rp = pv[(pv.ts.dt.time >= T0900) & (pv.ts.dt.time <= T1530)]
        if not len(rp):
            continue
        after = pv.close.iloc[-1] / rp.close.iloc[-1] - 1
        if after < 0.02:
            continue
        ph = {'R': rp.high.max(), 'A': pv.high.max()}
        g['m60'] = g.close.rolling(60).mean()
        g['m120'] = g.close.rolling(120).mean()
        up = g.m60 > g.m120
        gc = up & ~up.shift(fill_value=True) & (g.close > g.m120)
        aln = up & (g.m60 > g.m60.shift(10)) & (g.m120 > g.m120.shift(10)) & (g.close > g.m60)
        today = dt_ == day
        last_reg = g.index[today & (tm <= T1530)].max()
        win = today & (tm >= T0930) & (tm <= T1040) & g.m120.notna()
        upto15 = today & (tm >= T0930) & (tm <= T1500)
        base = dict(day=day, code=code, after=after)
        for sig_name, sig in (('GC', gc), ('GC+ALN', gc | aln)):
            idx = g.index[win & sig]
            if not len(idx):
                continue
            k = idx[0]
            rows.append({**base, 'way': f'{sig_name} 기준(전일고가 조건 없음)', 'ret': sell(g, k + 1, last_reg, no)})
            for hn, hv in ph.items():
                if g.close[k] > hv:
                    rows.append({**base, 'way': f'{sig_name} F 이미 전일고가({hn}) 위', 'ret': sell(g, k + 1, last_reg, no)})
                brk = g.index[upto15 & (g.index >= k) & (g.close > hv)]
                if len(brk) and brk[0] + 1 <= last_reg:
                    rows.append({**base, 'way': f'{sig_name} W 넘은 뒤 전일고가({hn}) 돌파', 'ret': sell(g, brk[0] + 1, last_reg, no)})
        for hn, hv in ph.items():
            prev_bar_below = g.close.shift(1) <= hv
            brk = g.index[upto15 & (g.close > hv) & prev_bar_below]
            if len(brk) and brk[0] + 1 <= last_reg:
                rows.append({**base, 'way': f'B0 크로스 없이 전일고가({hn}) 돌파', 'ret': sell(g, brk[0] + 1, last_reg, no)})
R = pd.DataFrame(rows)
R.to_csv('data/ma120_cross/prevhigh_bt.csv', index=False, encoding='utf-8-sig')
ds = sorted(R.day.unique())
half, q3 = ds[len(ds) // 2], ds[-63]
print("애프터 | 방식 | 건수 | 날 | 평균 | 승률 | 앞/뒤 | 최근3달 | 최고10뺀")
for a in (0.02, 0.03):
    for way, x in R[R.after >= a].groupby('way', sort=True):
        v = x.ret.sort_values(ascending=False)
        print(f"{a:.0%} | {way} | {len(x)} | {x.day.nunique()} | {x.ret.mean() * 100:+.2f}% | {(x.ret > 0).mean() * 100:.0f}% | "
              f"{x[x.day < half].ret.mean() * 100:+.2f}/{x[x.day >= half].ret.mean() * 100:+.2f} | {x[x.day >= q3].ret.mean() * 100:+.2f} | {v.iloc[10:].mean() * 100:+.2f}")
