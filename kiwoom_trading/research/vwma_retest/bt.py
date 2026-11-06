"""거래량 가중 이동평균(VWMA) 돌파 뒤 다시 밟을 때 매수 — 1년 검증
(2026-11-06 사용자 텔레그램: 강민우 돈깡TV '코인, 주식 상관없이 무손실 매매 가능했던 이 지표' feat.불장단타왕, 2026-10-26).

영상 규칙(롱 쪽만, 국내 주식은 공매도 안 함):
  거래량 가중 이평선 = 거래량이 많이 터진 구간에 가중치를 둔 이평선 → '현실 매물대'.
  가격이 이 선을 뚫고 올라온 뒤 '한번 밟아주는' 자리에서 롱, 깨지면 손절이 짧다. 추세 확인은 200선.
  익절은 과매수 쪽(영상은 자체 지표) — 여기서는 +R 익절 / 다음 날 09:00 로 대신.
숫자 정의(영상에 기간 없음 → 여러 값 시험):
  봉: 통합(AL) 1분봉 08:00~20:00 → 15분봉·60분봉. VWMA(N) = Σ(종가×거래량)/Σ거래량 (최근 N봉).
  돌파: 종가가 VWMA 아래였다가 위로. 그 뒤 K봉 안에 저가 ≤ VWMA × (1 + 0.2%) 이고 종가 ≥ VWMA → '밟음' 봉.
  매수: 밟음 봉 다음 봉 시가 (매수는 09:00~15:00 정규장 봉만).
  추세: 200봉 단순 이평 위(종가 > MA200)일 때만 (TREND=True) / 조건 없음.
  손절: 밟음 봉 저가 −0.5% 또는 매수가 −3% 중 높은 쪽(짧은 손절). 익절: +5%. 못 닿으면 다음 날 09:00 시가. 비용 0.25%.
대상: 전날 대금 상위 100 (그날 정보 안 씀). 종목당 하루 첫 신호 1번.
"""
import sys

import duckdb
import numpy as np
import pandas as pd

d = duckdb.connect('data/daily_ohlcv.duckdb', read_only=True)
d.execute("attach 'data/minute_history.duckdb' as mh (read_only)")
days = [r[0] for r in d.execute("select distinct ts::date from mh.minute_ohlcv where exchange='AL' and code='005930' and ts>='2025-10-20' order by 1").fetchall()]
start = next(i for i, x in enumerate(days) if x >= pd.Timestamp('2025-11-01').date())
T0900, T1500, T1530 = (pd.Timestamp(x).time() for x in ('09:00', '15:00', '15:30'))
FRAMES = ('15min', '60min')
NS = (20, 50)
rows = []
for di in range(start, len(days) - 1):
    prev, day, nxt = days[di - 1], days[di], days[di + 1]
    back = days[max(0, di - 12)]
    codes = [c for (c,) in d.execute("select code from daily_ohlcv where date=? and value is not null order by value desc limit 100", [prev]).fetchall()]
    df = d.execute("select code, ts, open, high, low, close, volume from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) "
                   "and ts >= ? and ts < ? and ts::time between '08:00' and '20:00' order by code, ts", [codes, back, nxt]).df()
    if df.empty:
        continue
    nopen = dict(d.execute("select code, open from mh.minute_ohlcv where exchange='AL' and code in (select unnest(?)) and ts = ?",
                           [codes, pd.Timestamp(nxt) + pd.Timedelta(hours=9)]).fetchall())
    for code, g in df.groupby('code'):
        no = nopen.get(code)
        if not no:
            continue
        m = g.set_index('ts')
        for fr in FRAMES:
            b = m.resample(fr, label='left', closed='left').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
            b = b[b.volume > 0]
            if len(b) < 60:
                continue
            pv = b.close * b.volume
            b['ma200'] = b.close.rolling(200, min_periods=200).mean()
            for n in NS:
                vw = pv.rolling(n).sum() / b.volume.rolling(n).sum()
                above = b.close > vw
                brk = above & ~above.shift(fill_value=True)
                idx = b.index
                today = idx.date == day
                last_brk = None
                for i in range(1, len(b) - 1):
                    if brk.iloc[i]:
                        last_brk = i
                    if not today[i] or last_brk is None or i == last_brk or i - last_brk > 8:
                        continue
                    v = vw.iloc[i]
                    if not (b.low.iloc[i] <= v * 1.002 and b.close.iloc[i] >= v):
                        continue
                    t_buy = idx[i + 1]
                    if not (idx[i + 1].date() == day and T0900 <= t_buy.time() <= T1500):
                        continue
                    trend = bool(b.close.iloc[i] > b.ma200.iloc[i]) if not np.isnan(b.ma200.iloc[i]) else None
                    buy = b.open.iloc[i + 1]
                    stop = max(b.low.iloc[i] * 0.995, buy * 0.97)
                    if stop >= buy:
                        continue
                    # 매도는 1분봉으로 (매수 봉 시각부터)
                    mm = m[(m.index >= t_buy) & (m.index.date == day) & (m.index.time <= T1530)]
                    ex = None
                    for lo, hi in zip(mm.low.values, mm.high.values):
                        if lo <= stop:
                            ex = stop
                            break
                        if hi >= buy * 1.05:
                            ex = buy * 1.05
                            break
                    ex = ex or no
                    rows.append(dict(day=day, code=code, fr=fr, n=n, trend=trend, t=t_buy, risk=buy / stop - 1, ret=ex / buy - 1 - 0.0025))
                    break
    if di % 40 == 0:
        print(day, len(rows), flush=True)
R = pd.DataFrame(rows)
R.to_csv('data/vwma_retest.csv', index=False, encoding='utf-8-sig')
all_days = [x for x in days[start:-1]]
half, q3 = all_days[len(all_days) // 2], all_days[-64]
print("봉 | N | 200선 | 건수 | 날 | 평균 | 승률 | 앞/뒤 | 최근3달 | 최고10뺀 | 평균 손절폭")
for (fr, n), x0 in R.groupby(['fr', 'n']):
    for lbl, x in (('조건 없음', x0), ('200선 위', x0[x0.trend == True])):
        v = x.ret.sort_values(ascending=False)
        print(f"{fr} | {n} | {lbl} | {len(x)} | {x.day.nunique()} | {x.ret.mean() * 100:+.2f}% | {(x.ret > 0).mean() * 100:.0f}% | "
              f"{x[x.day < half].ret.mean() * 100:+.2f}/{x[x.day >= half].ret.mean() * 100:+.2f} | {x[x.day >= q3].ret.mean() * 100:+.2f} | "
              f"{v.iloc[10:].mean() * 100:+.2f} | {x.risk.mean() * 100:.1f}%")
