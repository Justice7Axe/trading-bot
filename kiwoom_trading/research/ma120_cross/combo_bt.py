"""1분봉 60·120선 재정배열 + '일찍 넘음 · 직전 1시간 대금 순위 급상승 · 같은 무리 여러 종목 함께 넘음' 1년 검증
(2026-11-04 사용자 '원해' — 한화솔루션 11-04 차이점 검증).

대상: 전날 대금 상위 TOP(그날 정보 안 씀). 1분봉: minute_history 통합(AL) 08:00~20:00 이어 붙임.
신호: 09:30~14:30 60선이 120선 아래→위 첫 봉, 종가 > 120선. 다음 봉 시가 매수.
신호 순간 지표(그 시각까지 정보만):
  분 = 넘은 시각, 순위상승 = 대상 안 누적 대금 순위(60분 전 → 지금) 오른 칸 수, 전일대비, 고가대비,
  무리 = 직전 30분 안에 같은 무리(키움 테마 theme_members 최근 날짜 기준 하나라도 같음 / 없으면 같은 업종)에서 넘은 다른 종목 수.
  ⚠️ 테마 소속은 지금 기준(과거엔 달랐을 수 있음).
매도: B +5% 익절 / −3% 손절, N 익절 없음 / −3% 손절, 못 닿으면 다음 날 09:00 시가. 비용 0.25%.
"""
import duckdb, pandas as pd, numpy as np, statistics as st, sys, itertools
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 100
COST = 0.0025
d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
s = duckdb.connect('data/screener.duckdb', read_only=True)
tm = s.execute("select code, theme_code from theme_members where date = (select max(date) from theme_members)").fetchall()
themes = {}
for c, t in tm: themes.setdefault(c, set()).add('T' + t)
sector = dict(d.execute("select code, sector from stocks").fetchall())
def groups(c):
    return themes.get(c) or ({'S' + sector[c]} if sector.get(c) else set())
days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-11-01' order by 1").fetchall()]
recs = []
for di in range(1, len(days) - 1):
    prev, day, nxt = days[di - 1], days[di], days[di + 1]
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit ?", [prev, TOP]).fetchall()]
    df = d.execute("select code, ts, open, high, low, close, volume from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, prev, nxt]).df()
    if df.empty: continue
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall())
    # 대상 안 누적 대금 순위 (오늘 08:00~ 분마다)
    tday = df[df.ts.dt.date == day].copy()
    tday['val'] = tday.close * tday.volume
    piv = tday.pivot_table(index='ts', columns='code', values='val', aggfunc='sum').fillna(0).cumsum()
    rk = piv.rank(axis=1, ascending=False, method='min')
    crosses = []
    for code, g in df.groupby('code'):
        g = g.reset_index(drop=True)
        g['m60'] = g.close.rolling(60).mean(); g['m120'] = g.close.rolling(120).mean()
        up = g.m60 > g.m120
        t = g.ts.dt
        today = (t.date == day)
        win = today & (t.time >= pd.Timestamp('09:30').time()) & (t.time <= pd.Timestamp('14:30').time())
        cross = win & up & ~up.shift(fill_value=True) & (g.close > g.m120) & g.m120.notna()
        idx = cross[cross].index
        if not len(idx) or idx[0] + 1 >= len(g): continue
        k = idx[0]; T = g.ts[k]; i = k + 1; b = g.open[i]
        prevreg = g[(t.date == prev) & (t.time <= pd.Timestamp('15:30').time())]
        reg = g[today & (t.time >= pd.Timestamp('09:00').time()) & (t.time <= pd.Timestamp('15:30').time())]
        if not len(prevreg) or not len(reg): continue
        pc = prevreg.close.iloc[-1]
        before = reg[reg.ts <= T]
        r_now = rk.at[T, code] if T in rk.index else np.nan
        T60 = rk.index[rk.index <= T - pd.Timedelta(minutes=60)]
        r_60 = rk.at[T60[-1], code] if len(T60) else np.nan
        last = reg.index.max()
        outs = {}
        for name, tp in (('B', 0.05), ('N', None)):
            ex = None
            for j in range(i, last + 1):
                if g.low[j] <= b * 0.97: ex = b * 0.97; break
                if tp and g.high[j] >= b * (1 + tp): ex = b * (1 + tp); break
            if ex is None: ex = nopen.get(code)
            outs[name] = ex / b - 1 - COST if ex else np.nan
        crosses.append(dict(day=day, code=code, T=T, 분=T.hour * 60 + T.minute, 순위상승=r_60 - r_now, 순위=r_now,
                            전일대비=g.close[k] / pc - 1, 고가대비=g.close[k] / before.high.max() - 1 if len(before) else np.nan,
                            grp=groups(code), **outs))
    for c in crosses:
        c['무리'] = sum(1 for o in crosses if o['code'] != c['code'] and o['T'] < c['T'] and o['T'] >= c['T'] - pd.Timedelta(minutes=30)
                      and (o['grp'] & c['grp']))
        c['그날교차수'] = len(crosses)
        recs.append(c)
    if di % 20 == 0: print(day, len(recs), flush=True)
R = pd.DataFrame(recs).drop(columns=['grp'])
R.to_csv('data/ma120_cross/combo_records.csv', index=False, encoding='utf-8-sig')
half = sorted(R.day.unique())[len(R.day.unique()) // 2]
def row(lbl, m):
    x = R[m]
    out = [lbl, len(x), x.day.nunique()]
    for k in ('B', 'N'):
        v = x[k].dropna()
        if len(v) < 5: out += ['-'] * 4; continue
        a = x[x.day < half][k].dropna(); z = x[x.day >= half][k].dropna()
        top3 = v.sort_values(ascending=False)
        out += [f"{v.mean()*100:+.2f}", f"{a.mean()*100:+.2f}/{z.mean()*100:+.2f}", f"{top3.iloc[3:].mean()*100:+.2f}", f"{v.sum()*100:+.0f}"]
    print(" | ".join(map(str, out)))
print("조건 | 건수 | 날 | B +5/−3 평균 | 앞/뒤 | 최고3 뺀 | 합% | N 익절없음/−3 평균 | 앞/뒤 | 최고3 뺀 | 합%")
E = R.분 <= 11 * 60 + 30; RU = R.순위상승 >= 10; G = R.무리 >= 2; P = (R.전일대비 > 0) & (R.고가대비 >= -0.02)
row('전체', R.분 > 0)
row('E 11:30 전 넘음', E); row('R 직전 1시간 순위 +10칸↑', RU); row('G 같은 무리 2종목↑ 직전 30분에 넘음', G); row('P 전일대비 + · 고가 −2% 안', P)
row('E+R', E & RU); row('E+G', E & G); row('R+G', RU & G); row('E+R+G', E & RU & G); row('E+R+G+P', E & RU & G & P); row('E+R+P', E & RU & P)
row('넓은 날(그날 교차 ≥ 대상의 60%)', R.그날교차수 >= 0.6 * TOP); row('좁은 날', R.그날교차수 < 0.6 * TOP)
row('E+R+G 넓은 날', E & RU & G & (R.그날교차수 >= 0.6 * TOP)); row('E+R+G 좁은 날', E & RU & G & (R.그날교차수 < 0.6 * TOP))
