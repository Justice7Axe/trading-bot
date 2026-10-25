"""디앤서 돌파 매매 — 대상을 넓힌 판 (t_breakout.py 는 전날 대금 10위만 봐서 책 사례 종목이 거의 빠졌다:
두산로보틱스 04-30 전날 118위, 현대오토에버 05-08 115위, HD현대에너지솔루션 05-13 65위, 매드업 07-03 36위).
책: 돌파는 '시장의 관심이 집중되는 주도주'(p.145), 장중엔 실시간 조회 순위를 30초로 보며 돈이 옮겨 가는 종목을 잡는다 (p.151~152).
대상 (미리 정함):
  U1 전날 대금 10위 · U2 전날 대금 30위 · U3 **그 분까지 누적 거래대금(가격×거래량) 20위** (장중 주도주 — 그 시각까지 정보만)
  U3 후보 모집단 = 그날 최종 대금 300위 안(누적 대금은 줄지 않으므로 그 분 20위는 거의 확실히 이 안에 있음) 중 1분봉 있는 종목.
레벨·진입·매도는 t_breakout.py 와 같음: 레벨(전일 종가·고가, 라운드 피겨, 20일·250일 고가 — 일봉값 × f), 09:00 시가가 레벨 아래였고
  09:10~11:00 처음 1분봉 종가 > 레벨 → 다음 봉 시가(레벨 +1.5% 넘게 뜨면 추격이라 안 삼), 손절 −2%, 익절 = 다음 레벨(+1% 이상),
  아니면 15:19, 15:19 가격이 250일 고가 위면 다음 날 09:00.
"""
import sys
from collections import defaultdict
from datetime import time
import numpy as np
from engine import *
from t_breakout import levels, ROUND

R = Report("t_breakout2.txt")
GRID = [time(9 + (m // 60), m % 60) for m in range(0, 391)]          # 09:00 ~ 15:30
GI = {t: i for i, t in enumerate(GRID)}


def main():
    res = defaultdict(list); ex_why = defaultdict(lambda: defaultdict(int)); hits = []
    for d in days():
        p = prev_day(d)
        vp = value_rank(p)
        pool = list({c for c, r in value_rank(d).items() if r <= 300} | {c for c, r in vp.items() if r <= 30})   # U1·U2 종목은 오늘 300위 밖이어도 포함
        B = load_day(pool, d)
        regs = {c: regular(B[c]) for c in pool}
        regs = {c: r for c, r in regs.items() if is_common(c) and r and r[0][0] <= time(9, 1) and sum(1 for x in r if x[0] <= time(11, 0)) >= 100}
        codes = list(regs)
        cum = np.zeros((len(codes), len(GRID)))
        for i, c in enumerate(codes):
            for x in regs[c]:
                if x[0] in GI: cum[i, GI[x[0]]] += x[4] * x[5]
        cum = np.cumsum(cum, axis=1)
        rank_at = {}                                                      # (분 index) → 20위 집합
        for k in range(GI[time(9, 10)], GI[time(11, 0)] + 1):
            top = np.argsort(-cum[:, k])[:20]
            rank_at[k] = {codes[i] for i in top}
        for c in codes:
            f = factor(c, d)
            if f is None or c not in daily_day(p): continue
            reg = regs[c]; o9 = reg[0][1]
            L = levels(c, d, f, o9)
            h250 = hi_n(c, d, 250)
            allv = sorted(set(L.values()) | {x for x in ROUND if x > o9})
            hold = (lambda last, h=h250, f=f: h is not None and last > h * f)
            for lname, lv in L.items():
                for j, x in enumerate(reg):
                    if x[0] < time(9, 10): continue
                    if x[0] > time(11, 0) or j + 1 >= len(reg): break
                    if x[4] <= lv: continue
                    if any(y[4] > lv for y in reg[:j]): break
                    buy = reg[j + 1][1]
                    if buy > lv * 1.015: break
                    tp = next((v for v in allv if v >= buy * 1.01 and v > lv), None)
                    r, why = intraday_exit(reg, j + 1, buy, 0.02, tp / buy - 1 if tp else None, time(15, 19), hold, c, d)
                    us = []
                    if vp.get(c, 9e9) <= 10: us.append("U1 전날 대금 10위")
                    if vp.get(c, 9e9) <= 30: us.append("U2 전날 대금 30위")
                    if c in rank_at.get(GI.get(x[0], -1), ()): us.append("U3 그 분 누적 대금 20위")
                    for u in us:
                        res[(u, lname)].append((d, r)); ex_why[(u, lname)][why] += 1
                    if us: hits.append((d, c, lname, x[0], buy, us, r))
                    break
        print(d, file=sys.stderr, flush=True)
    R.say(f"디앤서 돌파 매매 — 대상 넓힘 ({P0}~{P1}, 09:10~11:00, 손절 −2%, 다음 레벨 익절, 250일 고가 위 마감이면 다음 날)")
    for u in ("U1 전날 대금 10위", "U2 전날 대금 30위", "U3 그 분 누적 대금 20위"):
        R.say(f"\n-- {u}")
        for lname in ("전일 종가", "전일 고가", "라운드 피겨", "단기 신고가(20일)", "250일 신고가"):
            R.stats(res[(u, lname)], f"{lname} 돌파", 30)
            if res[(u, lname)]: R.say(f"      매도 사유 {dict(ex_why[(u, lname)])}")
    R.say("\n-- 책 매매일지 사례")
    from datetime import date as _d
    for nm, ds in (("LIG디펜스앤에어로스페이스", "2026-04-22"), ("LIG넥스원", "2026-04-22"), ("두산로보틱스", "2026-04-30"),
                   ("HD현대에너지솔루션", "2026-05-13"), ("HD현대에너지솔루션", "2026-05-14"), ("현대오토에버", "2026-05-08"),
                   ("매드업", "2026-07-03"), ("아주IB투자", "2026-05-19")):
        c = code_by_name(nm); d = _d.fromisoformat(ds)
        if not c: R.say(f"  {nm}: 종목 이름 없음"); continue
        h = [x for x in hits if x[0] == d and x[1] == c]
        R.say(f"  {nm} {ds}: 그날 최종 대금 {value_rank(d).get(c)}위 → " + ("; ".join(f"{l} {t} 매수 {b:,.0f} {u} 결과 {r:+.2%}" for _, _, l, t, b, u, r in h) if h else "신호 없음"))


if __name__ == "__main__":
    main()
