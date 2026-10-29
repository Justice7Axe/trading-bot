"""중심선 기법 + 거래대금 거르기 (2026-10-30 사용자 '거래대금 순위나 거래대금 가속도가 있는 종목만 추려서').

거르기 (모두 매수 전에 아는 정보):
  A 기준봉 날 거래대금 순위 ≤ 10/20/50/100
  B 기준봉 대금 가속 = 기준봉 대금 ÷ 직전 20일 평균 대금 ≥ 5/10/20배
  C 매수 전날 거래대금 순위 ≤ 20/50/100 (눌리는 동안에도 돈이 몰려 있나)
  A×B, A×C 조합
매수·매도는 backtest.py 의 simulate 그대로.
실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.centerline.backtest_filters → data/centerline/filters.txt
"""
import os
from itertools import product

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.centerline.backtest import OUT, bases, simulate

EXITS = list(product(("몸통", "봉"), (5, 10), (0.0, 0.03), (None, 0.05, 0.10), (1, 3, 5)))


def accel(c, d):
    hs = E.hist(c, d, 20); av = np.mean([x[6] or 0 for x in hs])
    return (E.daily_day(d)[c][5] or 0) / av if av else 0


def main():
    rep = E.Report.__new__(E.Report); rep.f = open(os.path.join(OUT, "filters.txt"), "w", encoding="utf-8")
    rep.say("중심선 기법 + 거래대금 거르기, 2024-11-15 ~ 2026-10-20, 비용 0.25%, 100만/건")
    rep.say(f"매도 조합 {len(EXITS)}개 (중심선 2 × 대기 5·10일 × 손절 종가만·−3% × 익절 없음·+5·+10 × 보유 1·3·5일) 중 거르기마다 가장 좋은 것과 전체 분포")
    B = bases(0.10)
    info = {(d, c): (E.value_rank(d).get(c, 9999), accel(c, d)) for d, c, *_ in B}
    # 매도 조합마다 모든 기준봉 결과를 한 번만 계산
    res = {ex: [(b, simulate(b, *ex)) for b in B] for ex in EXITS}
    filters = [("거르기 없음 (+10% 기준봉)", lambda b, x: True)]
    for g in (0.15,):
        filters.append((f"기준봉 +15%↑", lambda b, x, g=g: b[5] / E.daily_day(E.prev_day(b[0]))[b[1]][3] - 1 >= g))
    for r in (10, 20, 50, 100):
        filters.append((f"A 기준봉 대금 {r}위 안", lambda b, x, r=r: info[(b[0], b[1])][0] <= r))
    for k in (5, 10, 20):
        filters.append((f"B 대금 가속 {k}배↑", lambda b, x, k=k: info[(b[0], b[1])][1] >= k))
    for r in (20, 50, 100):
        filters.append((f"C 매수 전날 대금 {r}위 안", lambda b, x, r=r: E.value_rank(E.prev_day(x[0])).get(b[1], 9999) <= r))
    for r, k in product((20, 50), (5, 10)):
        filters.append((f"A{r}위 × B{k}배", lambda b, x, r=r, k=k: info[(b[0], b[1])][0] <= r and info[(b[0], b[1])][1] >= k))
    for r, r2 in ((20, 50), (50, 50), (50, 100)):
        filters.append((f"A{r}위 × C{r2}위", lambda b, x, r=r, r2=r2: info[(b[0], b[1])][0] <= r and E.value_rank(E.prev_day(x[0])).get(b[1], 9999) <= r2))
    for name, f in filters:
        rows = []
        for ex in EXITS:
            tr = [(x[0], x[1]) for b, x in res[ex] if x and f(b, x)]
            if len(tr) < 15: continue
            v = np.array([t for _, t in tr]); ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
            a = np.mean([t for d, t in tr if d < h]); bb = np.mean([t for d, t in tr if d >= h])
            rows.append((v.mean(), ex, tr, a > 0 and bb > 0))
        if not rows:
            rep.say(f"\n[{name}] 건수 적음"); continue
        rows.sort(key=lambda x: -x[0]); m = np.array([x[0] for x in rows])
        rep.say(f"\n[{name}] 매도 조합 중앙 {np.median(m):+.2%}, 플러스 {np.mean(m > 0):.0%}, 앞·뒤 둘 다 + {sum(x[3] for x in rows)}/{len(rows)}")
        for mean, (mk, w, s, tp, hold), tr, _ in rows[:3]:
            rep.stats(tr, f"  {mk} 대기{w} {'종가만' if not s else '−3%'} 익절{'없음' if not tp else f'+{tp:.0%}'} 보유{hold}", 34)


if __name__ == "__main__":
    main()
