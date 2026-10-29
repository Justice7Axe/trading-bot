"""중심선 기법 — 일봉 장대양봉(기준봉) 몸통 가운데 가격에서 눌림 매수 (2026-10-29 사용자 '백테스트 해줘').

기준봉 (그날 장 마감 뒤 아는 정보만):
  양봉, 전날 대비 +X%↑, 거래량 ≥ 직전 20일 평균 × 3, 대금 ≥ 100억, 우선주 제외
중심선: 몸통 가운데 (시가+종가)/2  또는  봉 가운데 (고가+저가)/2
매수: 기준봉 다음 날부터 W일 안, 시가가 중심선 위인 날 저가가 중심선에 닿으면 중심선 가격에 지정가 체결
      (그 전에 종가가 중심선 아래로 마감하면 기준봉이 무너진 것 → 안 삼)
매도 (backtest-rules 3장): 손절가(중심선 −s%) 닿으면 즉시(시가가 이미 아래면 시가), 익절가 닿으면 그 가격(매수 날은 순서를 몰라 익절 안 함),
      종가가 중심선 아래로 마감하면 다음 날 09:00 시가, 최대 N일 보유 뒤 다음 날 09:00 시가.
기간: 일봉 2024-11 ~ 2026-10 (9-14 이후 일봉은 엔진 daily_day 로 정규장 값).
실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.centerline.backtest → data/centerline/backtest.txt
"""
import os
from collections import defaultdict
from datetime import date
from itertools import product

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "centerline"); os.makedirs(OUT, exist_ok=True)
D0, D1 = date(2024, 11, 15), date(2026, 10, 20)
DAYS = [d for d in E.CAL if D0 <= d <= D1]


def bases(min_gain):
    """[(d, code, o, h, l, c)] 기준봉."""
    out = []
    for d in DAYS:
        today, prev = E.daily_day(d), E.daily_day(E.prev_day(d))
        for c, (o, h, l, cl, v, val) in today.items():
            if not E.is_common(c) or not prev.get(c) or not prev[c][3] or cl <= o: continue
            if cl / prev[c][3] - 1 < min_gain or (val or 0) < 1e10: continue
            hs = E.hist(c, d, 20)
            if len(hs) < 20: continue
            av = np.mean([x[5] for x in hs])
            if not av or v < av * 3: continue
            out.append((d, c, o, h, l, cl))
    return out


def simulate(base, mid_kind, wait, stop, tp, hold):
    d0, c, o, h, l, cl = base
    C = (o + cl) / 2 if mid_kind == "몸통" else (h + l) / 2
    i0 = E.CIDX[d0]
    # 매수
    for k in range(1, wait + 1):
        if i0 + k >= len(E.CAL): return None
        d = E.CAL[i0 + k]; r = E.daily_day(d).get(c)
        if not r: return None
        ro, rh, rl, rc = r[:4]
        if ro < C: return None                      # 이미 중심선 아래에서 시작 → 무너짐
        if rl <= C:
            buy, bi = C, i0 + k; break
        if rc < C: return None
    else:
        return None
    sp = C * (1 - stop) if stop else None; tpp = buy * (1 + tp) if tp else None
    j = bi
    while True:
        if j >= len(E.CAL): return None
        d = E.CAL[j]; r = E.daily_day(d).get(c)
        if not r: return None
        ro, rh, rl, rc = r[:4]
        if sp and j > bi and ro <= sp: return E.CAL[bi], ro / buy - 1 - E.COST, "손절"
        if sp and rl <= sp: return E.CAL[bi], sp / buy - 1 - E.COST, "손절"
        if j > bi and tpp and rh >= tpp: return E.CAL[bi], max(ro, tpp) / buy - 1 - E.COST, "익절"
        if rc < C or j - bi + 1 >= hold:
            if j + 1 >= len(E.CAL): return None
            n = E.daily_day(E.CAL[j + 1]).get(c)
            if not n: return None
            return E.CAL[bi], n[0] / buy - 1 - E.COST, ("중심선 이탈" if rc < C else "보유 끝")
        j += 1


def main():
    rep = E.Report.__new__(E.Report); rep.f = open(os.path.join(OUT, "backtest.txt"), "w", encoding="utf-8")
    rep.say(f"중심선 기법 일봉 백테스트 {DAYS[0]} ~ {DAYS[-1]} ({len(DAYS)}거래일), 비용 0.25%, 100만/건")
    for g in (0.10, 0.15, 0.25):
        B = bases(g)
        rep.say(f"\n[기준봉 +{g:.0%}↑·거래량 3배·대금 100억↑] {len(B)}개")
        best = []
        for mk, wait, stop, tp, hold in product(("몸통", "봉"), (3, 5, 10), (0.0, 0.03), (None, 0.05, 0.10), (1, 3, 5, 10)):
            tr, why = [], defaultdict(int)
            for b in B:
                x = simulate(b, mk, wait, stop, tp, hold)
                if x: tr.append((x[0], x[1])); why[x[2]] += 1
            if len(tr) < 15: continue
            v = np.array([r for _, r in tr]); ds = sorted({d for d, _ in tr}); hlf = ds[len(ds) // 2]
            a = np.mean([r for d, r in tr if d < hlf]); bb = np.mean([r for d, r in tr if d >= hlf])
            best.append((v.mean(), mk, wait, stop, tp, hold, tr, dict(why), a, bb))
        best.sort(key=lambda x: -x[0])
        allv = [x[0] for x in best]
        rep.say(f"  조합 {len(best)}개: 건당 평균 중앙 {np.median(allv):+.2%}, 플러스 조합 {np.mean(np.array(allv) > 0):.0%}, 앞·뒤 둘 다 + {sum(1 for x in best if x[8] > 0 and x[9] > 0)}개")
        for m, mk, wait, stop, tp, hold, tr, why, a, bb in best[:8]:
            rep.stats(tr, f"{mk} 대기{wait}일 손절{'종가만' if not stop else f'−{stop:.0%}'} 익절{'없음' if not tp else f'+{tp:.0%}'} 보유{hold}일", 44)
            rep.say(f"      매도 이유 {why}")
        rep.say("  (기본형) 몸통·대기 5일·종가 이탈·익절 없음·보유 3일 / 10일:")
        for hold in (3, 10):
            tr = [(x[0], x[1]) for b in B if (x := simulate(b, "몸통", 5, 0.0, None, hold))]
            rep.stats(tr, f"기본 보유{hold}일", 44)


if __name__ == "__main__":
    main()
