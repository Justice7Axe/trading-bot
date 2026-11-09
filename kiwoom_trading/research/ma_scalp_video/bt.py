"""불장단타왕 '이평선 매매법' (ㄴ자 매매) 1년 검증 — 2026-11-06 사용자 텔레그램
영상: https://youtu.be/ho6Kx_L3yQo (2026-06-18, 14:33). 정리: docs/lectures/bulljang_ma_scalp.md

화면에서 읽은 것: 기본 차트 = SMA25(주황)·SMA50(초록)·VWMA100(흰색)·SMA200(빨강) + 볼린저 밴드 + RSI.
  기준 봉은 '시간봉(1시간)', 단타는 15분봉, 스윙은 4시간봉 (프랙탈).
ㄴ자 매매(롱만):
  ① 큰 하락으로 50선·200선이 가격 위로 멀리 벌어짐 (ㄴ의 세로획)
  ② 가격이 옆으로 가며 내려오는 50선과 붙음 (가로획) — 아래서 치고 올라와 선에 '박는' 자리는 안 함
  ③ 50선이 200선을 골든크로스(또는 이격이 좁아짐)하는 중
  ④ 50선 위에서 한 번 밟을 때 롱, 선 깨지면 손절, 1~3% 익절
숫자 정의(영상에 숫자 없음 → 우리가 정함, 2~3 값만):
  봉: 통합(AL) 1분봉 08:00~20:00 → 15분봉·60분봉. 선: 종가 단순 이평 50·200.
  ① 최근 150봉 안에 종가 ≤ 200선 × (1−6%) 이고 그때 50선 < 200선
  ② 직전 12봉 종가가 모두 50선 ±2% 안
  ③ GC: 50선 > 200선 이고 최근 30봉 안에 위로 교차 / NARROW: 50선 ≥ 200선 × 0.99 이고 50선이 5봉 전보다 높음
  ④ 신호 봉 저가 ≤ 50선 × 1.003, 종가 > 50선 → 다음 봉 시가 매수 (09:00~15:00 정규장 봉만)
  손절: 신호 봉 50선 × (1−1%) (기본) — 매수가 −3% 보다 넓으면 −3%. 익절 +2% / +3%.
  비교용 '박는 자리'(RAMP): 12봉 전 종가가 50선보다 4%↑ 아래였고 이번 봉 종가가 처음 50선 위로 → 같은 매도.
매도: 1분봉으로 손절 먼저·익절, 15:30 까지 못 닿으면 다음 날 09:00 시가. 비용 0.25%.
대상: 전날 통합(AL) 1분봉 대금(종가×거래량 합) 상위 100 (그날 정보 안 씀). 종목·날·변형마다 첫 신호 1번.
시장: 코스피 09:09 전일 대비 ÷ 최근 20일 등락 표준편차 ≥ +1 강한 상승 / ≤ −1 강한 하락 / 나머지 보통.
"""
import sys

import duckdb
import numpy as np
import pandas as pd

COST = 0.0025
mh = duckdb.connect('data/minute_history.duckdb', read_only=True)
days = [r[0] for r in mh.execute("select distinct ts::date from minute_ohlcv where exchange='AL' and code='005930' order by 1").fetchall()]
START = pd.Timestamp('2025-11-01').date()

# 전날 대금 상위 100 (통합 1분봉 대금)
val = mh.execute("""select ts::date d, code, sum(close*volume) v from minute_ohlcv where exchange='AL'
                    and ts::time between '08:00' and '20:00' group by 1,2""").df()
val['d'] = pd.to_datetime(val.d).dt.date
val['r'] = val.groupby('d').v.rank(ascending=False, method='first')
top = {d: set(g.code) for d, g in val[val.r <= 100].groupby('d')}
uni = sorted(set().union(*top.values()))
print('종목 수', len(uni), flush=True)
assert top.get(days[100]), '대상 비어 있음'

# 시장 분위기
ix = duckdb.connect('data/index.duckdb', read_only=True)
kd = ix.execute("select date, close from idx_daily where code='001' order by date").df()
kd = kd.set_index(pd.to_datetime(kd.date).dt.date).close
km = ix.execute("select ts::date d, last(close order by ts) c from idx_min where code='001' and ts::time <= '09:09' group by 1").df()
km = km.set_index(pd.to_datetime(km.d).dt.date).c
kret = kd.pct_change()
sd20 = kret.rolling(20).std().shift(1)
regime = {}
for d in days:
    if d in km.index and d in kd.index:
        pi = kd.index.get_loc(d)
        if pi == 0:
            continue
        z = (km[d] / kd.iloc[pi - 1] - 1) / sd20.loc[d]
        regime[d] = 'U' if z >= 1 else ('D' if z <= -1 else 'N')

nxt_day = {days[i]: days[i + 1] for i in range(len(days) - 1)}
prev_day = {days[i + 1]: days[i] for i in range(len(days) - 1)}


def bars(code, minutes):
    return mh.execute(f"""select time_bucket(interval '{minutes} minutes', ts) t, first(open order by ts) o, max(high) h, min(low) l,
                          last(close order by ts) c, sum(volume) v from minute_ohlcv where exchange='AL' and code=?
                          and ts::time between '08:00' and '19:59' group by 1 having sum(volume)>0 order by 1""", [code]).df()


sigs = []
for k, code in enumerate(uni):
    for fr in (15, 60):
        b = bars(code, fr)
        if len(b) < 260:
            continue
        c, l, h, o = b.c.values.astype(float), b.l.values.astype(float), b.h.values.astype(float), b.o.values.astype(float)
        s50 = pd.Series(c).rolling(50).mean().values
        s200 = pd.Series(c).rolling(200).mean().values
        t = pd.to_datetime(b.t)
        dd = t.dt.date.values
        tt = t.dt.time.values
        # ① 큰 하락: 종가 ≤ 200선×0.94 & 50<200
        drop = (c <= s200 * 0.94) & (s50 < s200)
        drop150 = pd.Series(drop.astype(float)).rolling(150, min_periods=1).max().values > 0
        # ② 직전 12봉 종가 50선 ±2%
        near = np.abs(c / s50 - 1) <= 0.02
        near12 = pd.Series(near.astype(float)).shift(1).rolling(12).min().values == 1
        above = s50 > s200
        cross = above & ~np.roll(above, 1)
        cross30 = pd.Series(cross.astype(float)).rolling(30, min_periods=1).max().values > 0
        gc = above & cross30
        narrow = (s50 >= s200 * 0.99) & (s50 > np.roll(s50, 5))
        step = (l <= s50 * 1.003) & (c > s50)
        # 비교: 박는 자리
        far12 = np.roll(c / s50 - 1, 12) <= -0.04
        first_up = (c > s50) & (np.roll(c, 1) <= np.roll(s50, 1))
        ramp = far12 & first_up
        base = drop150 & near12 & step
        conds = {'GC': base & gc, 'NARROW': base & narrow, 'RAMP': ramp}
        n = len(b)
        for name, cond in conds.items():
            seen = set()
            for i in np.nonzero(cond)[0]:
                if i + 1 >= n or i < 200 or np.isnan(s200[i]):
                    continue
                d = dd[i]
                if d < START or d not in nxt_day or code not in top.get(prev_day.get(d), ()):
                    continue
                if dd[i + 1] != d or not (pd.Timestamp('09:00').time() <= tt[i + 1] <= pd.Timestamp('15:00').time()):
                    continue
                if (d, name) in seen:
                    continue
                seen.add((d, name))
                sigs.append(dict(code=code, fr=fr, var=name, day=d, t_buy=t.iloc[i + 1], buy=o[i + 1], line=s50[i]))
    if k % 100 == 0:
        print(k, len(sigs), flush=True)

S = pd.DataFrame(sigs)
print('신호', len(S), flush=True)

# 매도 시뮬 (1분봉)
STOPS = {'선-1%': 0.01, '선-0.5%': 0.005, '선-2%': 0.02}
TPS = (0.02, 0.03)
rows = []
for (code, day), g in S.groupby(['code', 'day']):
    m = mh.execute("""select ts, open, high, low from minute_ohlcv where exchange='AL' and code=? and ts>=? and ts<=?""",
                   [code, pd.Timestamp(day) + pd.Timedelta(hours=9), pd.Timestamp(day) + pd.Timedelta(hours=15, minutes=30)]).df()
    nd = nxt_day[day]
    no = mh.execute("select open from minute_ohlcv where exchange='AL' and code=? and ts=?", [code, pd.Timestamp(nd) + pd.Timedelta(hours=9)]).fetchone()
    if not no or m.empty:
        continue
    no = float(no[0])
    if abs(no / g.buy.iloc[0] - 1) > 0.35:  # 분할·병합 등 가격 단절
        continue
    for r in g.itertuples():
        mm = m[m.ts >= r.t_buy]
        for sname, sv in STOPS.items():
            stop = max(r.line * (1 - sv), r.buy * 0.97)
            if stop >= r.buy:
                stop = r.buy * (1 - sv)
            for tp in TPS:
                tgt = r.buy * (1 + tp)
                ex, why = None, '다음날'
                for op, hi, lo in zip(mm.open.values, mm.high.values, mm.low.values):
                    if lo <= stop:
                        ex, why = min(op, stop), '손절'
                        break
                    if hi >= tgt:
                        ex, why = max(op, tgt), '익절'
                        break
                ex = ex if ex is not None else no
                rows.append(dict(code=code, day=day, fr=r.fr, var=r.var, stop=sname, tp=tp, t=r.t_buy, why=why,
                                 risk=1 - stop / r.buy, ret=ex / r.buy - 1 - COST, reg=regime.get(day, '?')))
R = pd.DataFrame(rows)
R.to_csv('data/ma_scalp_video.csv', index=False, encoding='utf-8-sig')
alld = [d for d in days if d >= START][:-1]
half, q3 = alld[len(alld) // 2], alld[-64]


def line(x):
    v = x.ret.sort_values(ascending=False)
    byday = x.groupby('day').ret.sum().sort_values(ascending=False)
    a, bb = x[x.day < half].ret, x[x.day >= half].ret
    star = len(x) >= 20 and a.mean() > 0 and bb.mean() > 0 and byday.iloc[5:].sum() > 0
    return (f"{len(x)} | {x.ret.mean()*100:+.2f}% | {(x.ret>0).mean()*100:.0f}% | {x.ret.sum()*100:+.0f}% | {a.mean()*100:+.2f}/{bb.mean()*100:+.2f} | "
            f"{x[x.day>=q3].ret.mean()*100:+.2f} | {v.iloc[10:].mean()*100:+.2f} | {x.risk.mean()*100:.1f}% | "
            f"{(x.why=='손절').mean()*100:.0f}/{(x.why=='익절').mean()*100:.0f}/{(x.why=='다음날').mean()*100:.0f} | {'★' if star else ''}")


print("\n봉 | 자리 | 손절 | 익절 | 건수 | 건당 | 승률 | 합계 | 앞/뒤 반기 | 최근3달 | 최고10뺀 | 평균 손절폭 | 손절/익절/다음날 % | ★")
for (fr, var, st, tp), x in R.groupby(['fr', 'var', 'stop', 'tp']):
    if st != '선-1%' and var == 'RAMP':
        continue
    print(f"{fr}분 | {var} | {st} | +{tp*100:.0f}% | " + line(x))
print("\n시장 분위기별 (손절 선-1%, 익절 +3%)")
for (fr, var, rg), x in R[(R.stop == '선-1%') & (R.tp == 0.03)].groupby(['fr', 'var', 'reg']):
    print(f"{fr}분 | {var} | {rg} | " + line(x))
