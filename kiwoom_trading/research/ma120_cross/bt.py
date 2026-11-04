"""1분봉 60선이 120선을 다시 넘는(재정배열) 순간 매수 — 1년 검증 (2026-11-04 사용자 '한화솔루션 1분봉 120선 매매').

대상: 전날 대금 상위 TOP (그날 정보 안 씀). 1분봉: minute_history 통합(AL) 08:00~20:00 이어 붙임(HTS 통합 차트와 같게).
신호: 09:30~14:30 에 60선이 120선 아래 → 위로 바뀐 첫 봉, 종가가 120선 위. 다음 봉 시가 매수(1종목 하루 1번).
매도 변형: A 데드크로스(60<120) 다음 봉 시가 / B +5% 익절·−3% 손절 / C 종가 120선 아래 마감 다음 봉 시가.
못 닿으면 다음 날 09:00 KRX 시가(=AL 09:00 봉 시가). 비용 0.25%.
"""
import duckdb, pandas as pd, statistics as st, sys
TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 50
MIN_UP = float(sys.argv[2]) if len(sys.argv) > 2 else None   # 신호 때 전날 정규장 종가 대비 최소 상승률 (예 0.03)
COST = 0.0025
d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-11-01' order by 1").fetchall()]
res = {k: [] for k in 'ABC'}
for di in range(1, len(days) - 1):
    prev, day, nxt = days[di - 1], days[di], days[di + 1]
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit ?", [prev, TOP]).fetchall()]
    if not codes: continue
    df = d.execute("select code, ts, open, high, low, close from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, prev, nxt]).df()
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall())
    for code, g in df.groupby('code'):
        g = g.reset_index(drop=True)
        g['m60'] = g.close.rolling(60).mean(); g['m120'] = g.close.rolling(120).mean()
        up = g.m60 > g.m120
        t = g.ts.dt
        today = (t.date == pd.Timestamp(day).date())
        win = today & (g.ts.dt.time >= pd.Timestamp('09:30').time()) & (g.ts.dt.time <= pd.Timestamp('14:30').time())
        cross = win & up & ~up.shift(fill_value=True) & (g.close > g.m120) & g.m120.notna()
        idx = cross[cross].index
        if not len(idx) or idx[0] + 1 >= len(g): continue
        if MIN_UP is not None:
            pc = g[(t.date == pd.Timestamp(prev).date()) & (g.ts.dt.time <= pd.Timestamp('15:30').time())].close
            if not len(pc) or g.close[idx[0]] < pc.iloc[-1] * (1 + MIN_UP): continue
        i = idx[0] + 1
        b = g.open[i]
        last = g[today].index.max()
        exit_nx = nopen.get(code)
        for k in 'ABC':
            ex = None
            for j in range(i, last + 1):
                if k == 'B':
                    if g.low[j] <= b * 0.97: ex = b * 0.97; break
                    if g.high[j] >= b * 1.05: ex = b * 1.05; break
                elif j > i and j + 1 <= last:
                    bad = (g.m60[j] < g.m120[j]) if k == 'A' else (g.close[j] < g.m120[j])
                    if bad: ex = g.open[j + 1]; break
            if ex is None:
                if not exit_nx: break
                ex = exit_nx
            res[k].append((day, code, ex / b - 1 - COST))
names = {'A': '데드크로스 매도', 'B': '+5% / −3%', 'C': '120선 아래 마감 매도'}
for k, r in res.items():
    v = [x[2] for x in r]
    if not v: continue
    v_sorted = sorted(v, reverse=True)
    half = sorted(r)[len(r) // 2][0]
    a = [x[2] for x in r if x[0] < half]; z = [x[2] for x in r if x[0] >= half]
    print(f"{names[k]:16s} {len(v)}건 평균 {st.mean(v)*100:+.2f}% 승 {sum(x>0 for x in v)/len(v)*100:.0f}% 합 {sum(v)*100:+.0f}% "
          f"앞 {st.mean(a)*100:+.2f} 뒤 {st.mean(z)*100:+.2f} 최고3 빼면 {st.mean(v_sorted[3:])*100:+.2f}%")
