"""비교용: 전날 애프터장(15:30→20:00) 강세 종목을 골든크로스 없이 정해진 시각에 사면? (2026-11-04 한화솔루션 신호 세분화)

대상: 전날 대금 상위 100 중 전날 애프터 등락 ≥ 2%. 매수: 그날 HH:MM 봉 시가. 매도: −3% 손절, 못 닿으면 다음 날 09:00 시가. 비용 0.25%.
"""
import duckdb
import numpy as np
import pandas as pd

d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-11-01' order by 1").fetchall()]
TIMES = ('09:01', '09:30', '10:00', '10:40')
rows = []
for di in range(1, len(days) - 1):
    prev, day, nxt = days[di - 1], days[di], days[di + 1]
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit 100", [prev]).fetchall()]
    df = d.execute("select code, ts, open, high, low, close from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, prev, nxt]).df()
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall())
    for code, g in df.groupby('code'):
        t = g.ts.dt
        pv = g[t.date == prev]
        reg_prev = pv[pv.ts.dt.time <= pd.Timestamp('15:30').time()]
        if not len(reg_prev):
            continue
        after = pv.close.iloc[-1] / reg_prev.close.iloc[-1] - 1
        if after < 0.02:
            continue
        td = g[(t.date == day) & (t.time <= pd.Timestamp('15:30').time())].reset_index(drop=True)
        rec = dict(day=day, code=code, after=after)
        for hm in TIMES:
            ix = td.index[td.ts.dt.strftime('%H:%M') >= hm]
            if not len(ix):
                rec[hm] = np.nan
                continue
            i = ix[0]
            b = td.open[i]
            ex = None
            for j in range(i, len(td)):
                if td.low[j] <= b * 0.97:
                    ex = b * 0.97
                    break
            ex = ex or nopen.get(code)
            rec[hm] = ex / b - 1 - 0.0025 if ex else np.nan
        rows.append(rec)
R = pd.DataFrame(rows)
R.to_csv('data/ma120_cross/after_base.csv', index=False, encoding='utf-8-sig')
half = sorted(R.day.unique())[len(R.day.unique()) // 2]
for hm in TIMES:
    for a in (0.02, 0.03):
        x = R[R.after >= a]
        v = x[hm].dropna()
        top = v.sort_values(ascending=False)
        print(f"전날애프터≥{a:.0%} {hm} 매수: {len(v)}건 평균 {v.mean() * 100:+.2f}% 앞 {x[x.day < half][hm].mean() * 100:+.2f} "
              f"뒤 {x[x.day >= half][hm].mean() * 100:+.2f} 최고10뺀 {top.iloc[10:].mean() * 100:+.2f}")
