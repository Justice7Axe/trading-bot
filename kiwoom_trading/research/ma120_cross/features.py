"""60·120선 재정배열 신호 순간의 지표를 넓게 계산 (2026-11-04 사용자 '한화솔루션만 보이는 신호를 찾아 보자').

대상: 전날 대금 상위 100 (일봉 daily_ohlcv), 1분봉: minute_history 통합(AL) 08:00~20:00. 지표는 모두 신호 봉(T)까지 정보.
결과: N(익절 없음·−3% 손절·못 닿으면 다음 날 09:00), D(60<120 역배열 다음 봉 시가 매도, 그날 20:00 까지 없으면 다음 날 09:00).
출력: data/ma120_cross/features.csv
"""
import duckdb
import numpy as np
import pandas as pd

TOP, COST = 100, 0.0025
d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
d.execute("attach 'data/index.duckdb' as ix (read_only)")
s = duckdb.connect('data/screener.duckdb', read_only=True)
themes = {}
for c, t in s.execute("select code, theme_code from theme_members where date = (select max(date) from theme_members)").fetchall():
    themes.setdefault(c, set()).add('T' + t)
info = {c: (sh or 0, sec) for c, sh, sec in d.execute("select code, listed_shares, sector from stocks").fetchall()}


def grp(c):
    return themes.get(c) or ({'S' + info[c][1]} if c in info and info[c][1] else set())


days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-11-01' order by 1").fetchall()]
kospi = d.execute("select ts, close from ix.idx_min where code='001' and ts >= '2025-10-01' order by ts").df().set_index('ts').close
kd = d.execute("select date, close from ix.idx_daily where code='001' order by date").df().set_index('date').close
T0930, T1430, T0900, T1530 = (pd.Timestamp(x).time() for x in ('09:30', '14:30', '09:00', '15:30'))
recs = []
for di in range(1, len(days)):
    prev, day = days[di - 1], days[di]
    nxt = days[di + 1] if di + 1 < len(days) else None
    end = nxt or (pd.Timestamp(day) + pd.Timedelta(days=1)).date()
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit ?", [prev, TOP]).fetchall()]
    hist = d.execute("select code, date, close, value from daily_ohlcv where code in (select unnest(?)) and date < ? and date >= ?",
                     [codes, day, pd.Timestamp(day) - pd.Timedelta(days=400)]).df()
    fl = {c: (f, i) for c, f, i in d.execute("select code, foreign_, institution from investor_daily where date=? and code in (select unnest(?))", [prev, codes]).fetchall()}
    df = d.execute("select code, ts, open, high, low, close, volume from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, prev, end]).df()
    if df.empty:
        continue
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall()) if nxt else {}
    tday = df[df.ts.dt.date == day].copy()
    tday['val'] = tday.close * tday.volume
    piv = tday.pivot_table(index='ts', columns='code', values='val', aggfunc='sum').fillna(0).cumsum()
    rk = piv.rank(axis=1, ascending=False, method='min')
    kprev = kd[kd.index < pd.Timestamp(day)].iloc[-1] if (kd.index < pd.Timestamp(day)).any() else np.nan
    crosses = []
    for code, g in df.groupby('code'):
        g = g.reset_index(drop=True)
        g['m60'] = g.close.rolling(60).mean()
        g['m120'] = g.close.rolling(120).mean()
        g['val'] = g.close * g.volume
        t = g.ts.dt
        today = (t.date == day)
        up = g.m60 > g.m120
        cross = today & (t.time >= T0930) & (t.time <= T1430) & up & ~up.shift(fill_value=True) & (g.close > g.m120) & g.m120.notna()
        idx = cross[cross].index
        if not len(idx) or idx[0] + 1 >= len(g):
            continue
        k = idx[0]
        T = g.ts[k]
        i = k + 1
        b = g.open[i]
        prevreg = g[(t.date == prev) & (t.time <= T1530)]
        prevall = g[t.date == prev]
        reg = g[today & (t.time >= T0900) & (t.time <= T1530)]
        pre = g[today & (t.time < T0900)]
        upto = g[today & (g.index <= k)]
        before = reg[reg.ts <= T]
        if not len(prevreg) or not len(before):
            continue
        pc = prevreg.close.iloc[-1]
        h = hist[hist.code == code].sort_values('date')
        v20 = h.value.tail(20).mean()
        c20 = h.close.tail(20).mean()
        hi52 = h[pd.to_datetime(h.date) >= pd.Timestamp(day) - pd.Timedelta(days=365)].close.max()
        c_prev2 = h.close.iloc[-2] if len(h) >= 2 else np.nan
        c_5 = h.close.iloc[-6] if len(h) >= 6 else np.nan
        vw = (upto.close * upto.volume).sum() / max(upto.volume.sum(), 1)
        last_up = up[:k][up[:k]].index
        under_len = k - (last_up[-1] if len(last_up) else 0)
        depth = ((g.m60 - g.m120) / g.m120)[max(0, k - under_len):k].min()
        r_now = rk.at[T, code] if (T in rk.index and code in rk.columns) else np.nan

        def r_ago(m):
            ix_ = rk.index[rk.index <= T - pd.Timedelta(minutes=m)]
            return rk.at[ix_[-1], code] if len(ix_) and code in rk.columns else np.nan

        kk = kospi[(kospi.index <= T) & (kospi.index.date == day)]
        newhi = int((before.high.cummax().diff() > 0).iloc[-30:].sum())
        last_reg = reg.index.max()
        last_all = g[today].index.max()
        exN = None
        for j in range(i, last_reg + 1):
            if g.low[j] <= b * 0.97:
                exN = b * 0.97
                break
        if exN is None:
            exN = nopen.get(code)
        exD = None
        for j in range(i, last_all):
            if g.m60[j] < g.m120[j]:
                exD = g.open[j + 1]
                break
        if exD is None:
            exD = nopen.get(code)
        rec = dict(
            day=day, code=code, T=T, 분=T.hour * 60 + T.minute,
            전일대비=g.close[k] / pc - 1, 갭=reg.open.iloc[0] / pc - 1,
            프리장=(pre.close.iloc[-1] / pc - 1) if len(pre) else np.nan,
            전날애프터=prevall.close.iloc[-1] / pc - 1,
            시가대비=g.close[k] / reg.open.iloc[0] - 1, 저점반등=g.close[k] / before.low.min() - 1, 고가대비=g.close[k] / before.high.max() - 1,
            VWAP대비=g.close[k] / vw - 1, 이격120=g.close[k] / g.m120[k] - 1, 역배열깊이=depth, 역배열길이=under_len,
            최근5분대금배수=g.val[k - 4:k + 1].mean() / max(g.val[k - 64:k - 4].mean(), 1),
            누적대금_20일평균=upto.val.sum() / v20 if v20 else np.nan,
            순위=r_now, 순위상승30=r_ago(30) - r_now, 순위상승60=r_ago(60) - r_now,
            신고가횟수30=newhi, 전날등락=pc / c_prev2 - 1 if c_prev2 == c_prev2 else np.nan,
            직전5일=pc / c_5 - 1 if c_5 == c_5 else np.nan, 이격20일=pc / c20 - 1 if c20 else np.nan, 고가52=pc / hi52 - 1 if hi52 else np.nan,
            전날외인=fl.get(code, (np.nan, np.nan))[0], 전날기관=fl.get(code, (np.nan, np.nan))[1],
            시총조=info.get(code, (0, None))[0] * pc / 1e12,
            코스피=kk.iloc[-1] / kprev - 1 if len(kk) else np.nan, 코스피저점반등=kk.iloc[-1] / kk.min() - 1 if len(kk) else np.nan,
            grp=grp(code),
            N=exN / b - 1 - COST if exN else np.nan, D=exD / b - 1 - COST if exD else np.nan,
            종가=reg.close.iloc[-1] / b - 1 - COST,
        )
        recs.append(rec)
        crosses.append(rec)
    for c in crosses:
        c['무리'] = sum(1 for o in crosses if o['code'] != c['code'] and c['T'] - pd.Timedelta(minutes=30) <= o['T'] < c['T'] and (o['grp'] & c['grp']))
        c['무리순번'] = sum(1 for o in crosses if o['code'] != c['code'] and o['T'] < c['T'] and (o['grp'] & c['grp']))   # 같은 무리에서 먼저 넘은 종목 수
        c['그날교차수_지금까지'] = sum(1 for o in crosses if o['T'] < c['T'])
    if di % 40 == 0:
        print(day, len(recs), flush=True)
R = pd.DataFrame(recs).drop(columns=['grp'])
R.to_csv('data/ma120_cross/features.csv', index=False, encoding='utf-8-sig')
print('끝', len(R))
