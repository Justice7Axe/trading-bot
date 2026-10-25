"""디앤서 종가 베팅 — 대상까지 판단 시각 정보로 뽑는 판 (미래 정보 없음).

t_closebet2.py 는 대상을 '그날 최종 대금 10위·상승 마감'으로 먼저 걸러 14:30 판단에 미래 정보가 섞였다.
이 판: 판단 시각 T(14:30 / 15:19)까지의 1분봉 누적 거래대금(가격×거래량)으로 순위를 매겨 10위, T 시각 가격이 전일 종가 위·+29.5% 미만.
  후보 모집단 = 그날 최종 대금 상위 300 (그 안에 T 시각 10위가 거의 확실히 들어감 — 누적 대금은 줄지 않으므로) 중 1분봉 있는 종목.
  애프터 거래 여부(NXT 종목)는 그날 19:30 이후 봉 유무로 봄 (종목 속성이라 결과와 무관).
조건 (책 체크리스트 p.142, 유형 p.117~121): 고가 근처 = (T가격−그날 저가)/(그날 고가−저가) ≥ 0.8 (T까지) · 250일 신고가 = T가격 ≥ 전날까지 250일 고가×f
  · 라운드 피겨 = T가격이 1·2.5·5×10ⁿ 의 ±3% · 250일 고가 95%.
매수: T=14:30 → 14:31 시가 / T=15:19 → 15:30 정규장 종가(동시호가). 매도: 다음 날 08:00 NXT 시가 / 프리 3분할 / 09:00 시가.
"""
import os, pickle, sys
from collections import defaultdict
from datetime import time
from engine import *

R = Report("t_closebet3.txt")
ROUND = sorted({m * 10 ** k for k in range(2, 8) for m in (1, 2.5, 5)})
near_round = lambda p: any(0.97 <= p / x <= 1.03 for x in ROUND)
TS = {"14:30 판단·14:31 시가 매수": time(14, 30), "15:19 판단·15:30 종가 매수": time(15, 19)}
CONDS = ("시각 10위·상승 전부", "고가 근처(≥0.8)", "250일 신고가", "250일 고가 95%↑", "라운드 피겨 ±3%", "신고가 또는 라운드 피겨",
         "고가 근처 + 신고가 (① 주도주)", "고가 근처 + (신고가 또는 라운드)")


def main():
    res = defaultdict(list); picks = []
    for d in days():
        vr = value_rank(d)
        pool = [c for c, r in vr.items() if r <= 300 and is_common(c)]
        B = load_day(pool, d)
        nd = next_day(d)
        for tname, T in TS.items():
            cum = {}
            for c in pool:
                reg = [x for x in regular(B[c]) if x[0] <= T]
                if len(reg) >= 60: cum[c] = sum(x[4] * x[5] for x in reg)
            top = sorted(cum, key=lambda c: -cum[c])[:10]
            for rank, c in enumerate(top, 1):
                f = factor(c, d)
                if f is None: continue
                reg = regular(B[c]); upto = [x for x in reg if x[0] <= T]
                prd = daily_day(prev_day(d)).get(c)
                if not prd: continue                                              # 신규 상장 (전날 없음)
                p = upto[-1][4]; pc = prd[3] * f
                r = p / pc - 1
                if not (0 < r < LIMIT): continue
                if not nxt_known(c, d): continue                                  # 애프터 거래 종목만 (p.142) — 전날 애프터 봉으로 판단
                hi, lo = max(x[2] for x in upto), min(x[3] for x in upto)
                h250 = hi_n(c, d, 250)
                pos = (p - lo) / (hi - lo) if hi > lo else 1.0
                nh = bool(h250) and p >= h250 * f; h95 = bool(h250) and p >= h250 * f * 0.95; rd = near_round(p)
                if T == time(14, 30):
                    if len(upto) >= len(reg): continue
                    buy = reg[len(upto)][1]
                else:
                    if reg[-1][0] != time(15, 30): continue                         # 15:30 동시호가 봉이 없으면 종가 매수 불가
                    buy = reg[-1][4]
                if nd: load_day([c], nd)
                ex = next_day_exits(c, d, buy)
                ok = {CONDS[0]: True, CONDS[1]: pos >= 0.8, CONDS[2]: nh, CONDS[3]: h95, CONDS[4]: rd, CONDS[5]: nh or rd,
                      CONDS[6]: pos >= 0.8 and nh, CONDS[7]: pos >= 0.8 and (nh or rd)}
                for nm, o in ok.items():
                    if o:
                        for k, v in ex.items(): res[(tname, nm, k)].append((d, v))
                picks.append(dict(date=d, code=c, t=tname, rank=rank, chg=r, pos=pos, newhi=nh, rnd=rd, buy=buy, ex=ex))
        print(d, file=sys.stderr, flush=True)
    pickle.dump(picks, open(os.path.join(OUT, "t_closebet3_picks.pkl"), "wb"))
    R.say(f"디앤서 종가 베팅 — 판단 시각 대금 10위·상승·애프터 거래 종목 ({P0}~{P1}, 미래 정보 없음)")
    for tname in TS:
        R.say(f"\n== {tname}")
        for nm in CONDS:
            R.say(f" -- {nm}")
            for k in ("08:00 NXT 시가", "프리 3분할", "09:00 시가"):
                R.stats(res[(tname, nm, k)], "   " + k)


if __name__ == "__main__":
    main()
