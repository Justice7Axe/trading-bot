"""11-04 1분봉(통합 AL 08:00~20:00) 60선이 120선을 다시 넘은 종목 찾기 + 그 순간 지표 비교 (사용자 '한화솔루션과 같이 골든크로스 된 종목·지표 차이')."""
import duckdb, pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40); pd.set_option('display.max_rows', 200)
o = duckdb.connect('data/ma120_cross/min_1104.duckdb', read_only=True)
s = duckdb.connect('data/screener.duckdb', read_only=True)
d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
bars = o.execute("select * from bars where ts::time between '08:00' and '20:00' order by code, ts").df()
names = dict(s.execute("select code, any_value(name) from rank_snapshots where date='2026-11-04' group by 1").fetchall())
rank = s.execute("select ts, code, rank, trade_value from rank_snapshots where date='2026-11-04' and source='value_krx'").df()
prog = s.execute("select ts, code, net_amount from program_intraday where date='2026-11-04'").df()
inv_i = s.execute("select ts, investor, code, net_amount from investor_intraday where date='2026-11-04'").df()
flow = {c: (f, i) for c, dt, f, i in d.execute("select code, date, foreign_, institution from investor_daily where date in ('2026-11-03','2026-11-04')").fetchall() for _ in [0] if dt.isoformat() == '2026-11-03'}
flow_t = {c: (f, i) for c, dt, f, i in d.execute("select code, date, foreign_, institution from investor_daily where date='2026-11-04'").fetchall()}
info = {c: (sh, sec) for c, sh, sec in d.execute("select code, listed_shares, sector from stocks").fetchall()}
hi52 = dict(d.execute("select code, max(high) from daily_ohlcv where date >= '2025-11-04' and date < '2026-11-04' group by 1").fetchall())
c5 = {c: v for c, v in d.execute("""select code, (max(close) filter (where date='2026-11-03')) / (max(close) filter (where date='2026-10-27')) - 1 from daily_ohlcv where date in ('2026-10-27','2026-11-03') group by 1""").fetchall()}
rows = []
for code, g in bars.groupby('code'):
    g = g.reset_index(drop=True)
    g['m60'] = g.close.rolling(60).mean(); g['m120'] = g.close.rolling(120).mean()
    g['val'] = g.close * g.volume
    t = g.ts.dt
    today = t.date == pd.Timestamp('2026-11-04').date()
    prevreg = g[(t.date == pd.Timestamp('2026-11-03').date()) & (t.time <= pd.Timestamp('15:30').time())]
    if not len(prevreg) or not today.any(): continue
    pc = prevreg.close.iloc[-1]
    up = g.m60 > g.m120
    win = today & (t.time >= pd.Timestamp('09:30').time()) & (t.time <= pd.Timestamp('14:30').time())
    cross = win & up & ~up.shift(fill_value=True) & (g.close > g.m120) & g.m120.notna()
    idx = cross[cross].index
    if not len(idx) or idx[0] + 1 >= len(g): continue
    k = idx[0]; T = g.ts[k]; b = g.open[k + 1]
    reg = g[today & (t.time >= pd.Timestamp('09:00').time()) & (t.time <= pd.Timestamp('15:30').time())]
    before = reg[reg.ts <= T]; after = reg[reg.ts > T]
    op = reg.open.iloc[0]; close = reg.close.iloc[-1]
    rk = rank[(rank.code == code) & (rank.ts <= T)].sort_values('ts')
    rk910 = rank[(rank.code == code) & (rank.ts <= pd.Timestamp('2026-11-04 09:10:59'))].sort_values('ts')
    rk60 = rank[(rank.code == code) & (rank.ts <= T - pd.Timedelta(minutes=60))].sort_values('ts')
    pg = prog[(prog.code == code) & (prog.ts <= T)].sort_values('ts')
    fi = inv_i[(inv_i.code == code) & (inv_i.ts <= T)].sort_values('ts')
    fi_f = fi[fi.investor.str.contains('외')].net_amount.iloc[-1] if len(fi[fi.investor.str.contains('외')]) else np.nan
    fi_i = fi[fi.investor.str.contains('기관')].net_amount.iloc[-1] if len(fi[fi.investor.str.contains('기관')]) else np.nan
    v30 = g.val[max(0, k - 29):k + 1].sum() / 30
    vday = before.val.mean() if len(before) else np.nan
    sh, sec = info.get(code, (None, None))
    f, i = flow.get(code, (np.nan, np.nan)); ft, it = flow_t.get(code, (np.nan, np.nan))
    rows.append(dict(
        종목=names.get(code, code), 시각=T.strftime('%H:%M'), 매수가=b,
        전일대비=b / pc - 1, 갭=op / pc - 1, 장중저점=before.low.min() / pc - 1 if len(before) else np.nan,
        고가대비=b / before.high.max() - 1 if len(before) else np.nan,
        순위=rk['rank'].iloc[-1] if len(rk) else np.nan, 순위_0910=rk910['rank'].iloc[-1] if len(rk910) else np.nan,
        순위_1시간전=rk60['rank'].iloc[-1] if len(rk60) else np.nan,
        누적대금억=rk.trade_value.iloc[-1] / 1e8 if len(rk) else np.nan,
        대금가속=v30 / vday if vday else np.nan,
        선120기울기=g.m120[k] / g.m120[k - 30] - 1 if k >= 30 else np.nan,
        프로그램억=pg.net_amount.iloc[-1] / 1e8 if len(pg) else np.nan,
        잠정외인억=fi_f / 1e8 if fi_f == fi_f else np.nan, 잠정기관억=fi_i / 1e8 if fi_i == fi_i else np.nan,
        전날외인억=f / 1e8, 전날기관억=i / 1e8,
        시총조=(sh or 0) * pc / 1e12, 고가52대비=pc / hi52[code] - 1 if hi52.get(code) else np.nan, 직전5일=c5.get(code, np.nan),
        업종=sec,
        결과_종가=close / b - 1, 결과_최고=after.high.max() / b - 1 if len(after) else np.nan, 결과_최저=after.low.min() / b - 1 if len(after) else np.nan,
        당일외인억=ft / 1e8, 당일기관억=it / 1e8,
    ))
df = pd.DataFrame(rows).sort_values('결과_종가', ascending=False)
pct = ['전일대비', '갭', '장중저점', '고가대비', '선120기울기', '고가52대비', '직전5일', '결과_종가', '결과_최고', '결과_최저']
show = df.copy()
for c in pct: show[c] = (show[c] * 100).round(1)
for c in ['누적대금억', '대금가속', '프로그램억', '잠정외인억', '잠정기관억', '전날외인억', '전날기관억', '시총조', '당일외인억', '당일기관억']: show[c] = show[c].round(1)
print(f"상위 100 중 09:30~14:30 재정배열 {len(df)}종목")
print(show.to_string(index=False))
df.to_csv('data/ma120_cross/today_1104.csv', index=False, encoding='utf-8-sig')
