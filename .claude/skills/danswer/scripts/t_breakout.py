"""디앤서 돌파 매매 (『실전 시황 트레이딩』 4장 p.144~165) — 공통 엔진 판.

책 규칙 (쪽수):
- 주도주 + 큰 거래대금일 때만 (p.145, 148~150). 대상 = 전날 14시·20시 조회 순위 당일 누적 10위 안 2-2-2 (p.153) → **전날 대금 10위**로 대신.
- 돌파할 가격 (p.150, 체크리스트 p.164): 전일 종가 · 전일 고가 · 라운드 피겨 · 단기 신고가 · 250일 신고가.
- 돌파할 힘: 돌파 직전 거래량·거래대금 증가 (p.164).
- 타이밍: 09:00~09:10 피함 (p.165, 본문은 10~15분 뒤), 이미 급등한 뒤 뒤늦은 추격 아님 (p.165). 하루 루틴: 13~14시 추격 매수 금지 (p.263).
- 손절: 산 가격에서 −2% 이내 (p.152). 익절: 다음 의미 있는 가격 (전일 종가 돌파 → 전일 고가). 신고가까지 뚫으면 종가 베팅으로 이어 감 (p.152).
숫자 정의 (미리 정함):
  레벨은 일봉(수정주가)값 × 환산 비율 f (engine.factor) 로 1분봉 가격에 맞춤. 라운드 피겨 = 1·2.5·5 × 10ⁿ (1분봉 가격 그대로).
  단기 신고가 = 전날까지 20일 고가, 250일 신고가 = 전날까지 250일 고가.
  '돌파' = 그날 09:00 시가가 레벨 아래였고, 창 안에서 처음으로 1분봉 종가 > 레벨. 매수 = 다음 봉 시가, 단 레벨 +1.5% 넘게 뜬 시가면 추격이라 안 삼.
  힘 = 돌파 봉 거래대금 ≥ 직전 20봉 평균 × 3 (있음/없음 둘 다 봄).
  창 = 오전 09:10~11:00 (책 주력) / 오후 13:00~14:30 (책: 추격 금지 — 확인용).
  매도 = 손절 −2% · 익절 = 그 레벨 위 다음 레벨(+1% 이상인 첫 레벨) · 아니면 15:19, 단 15:19 가격이 250일 고가 위면 다음 날 09:00 시가.
"""
import os, sys
from collections import defaultdict
from datetime import time
import numpy as np
from engine import *

R = Report("t_breakout.txt")
ROUND = sorted({m * 10 ** k for k in range(2, 8) for m in (1, 2.5, 5)})
WIN = {"오전 09:10~11:00": (time(9, 10), time(11, 0)), "오후 13:00~14:30": (time(13, 0), time(14, 30))}


def levels(c, d, f, o9):
    p = prev_day(d); pr = daily_day(p).get(c)
    if not pr: return {}
    L = {"전일 종가": pr[3] * f, "전일 고가": pr[1] * f}
    h20, h250 = hi_n(c, d, 20), hi_n(c, d, 250)
    if h20: L["단기 신고가(20일)"] = h20 * f
    if h250: L["250일 신고가"] = h250 * f
    rf = next((x for x in ROUND if x > o9), None)
    if rf: L["라운드 피겨"] = rf
    return {k: v for k, v in L.items() if v > o9}


def main():
    res = defaultdict(list); exits = defaultdict(lambda: defaultdict(int))
    case_log = []
    for d in days():
        p = prev_day(d)
        top = [c for c, r in value_rank(p).items() if r <= 10 and is_common(c)]
        load_day(top, d)
        for c in top:
            f = factor(c, d)
            if f is None: continue
            reg = regular(bars(c, d))
            if not reg or reg[0][0] > time(9, 1) or sum(1 for x in reg if x[0] <= time(11, 0)) < 100: continue   # 창 끝까지 봉 수로만 거름
            o9 = reg[0][1]
            L = levels(c, d, f, o9)
            h250 = hi_n(c, d, 250)
            allv = sorted(set(L.values()) | {x for x in ROUND if x > o9})
            hold = (lambda last, h=h250, f=f: h is not None and last > h * f)
            for wname, (t0, t1) in WIN.items():
                for lname, lv in L.items():
                    for j, x in enumerate(reg):
                        if x[0] < t0: continue
                        if x[0] > t1 or j + 1 >= len(reg): break
                        if x[4] <= lv: continue
                        if any(y[4] > lv for y in reg[:j]): break          # 창 전에 이미 넘었음 → 첫 돌파 아님
                        prior = reg[max(0, j - 20):j]
                        surge = len(prior) >= 10 and x[4] * x[5] >= 3 * np.mean([y[4] * y[5] for y in prior])
                        buy = reg[j + 1][1]
                        if buy > lv * 1.015: break                           # 추격 금지
                        tp = next((v for v in allv if v >= buy * 1.01 and v > lv), None)
                        for s in ((False, True) if surge else (False,)):
                            r, why = intraday_exit(reg, j + 1, buy, 0.02, tp / buy - 1 if tp else None, time(15, 19), hold, c, d)
                            key = (wname, lname, s)
                            res[key].append((d, r)); exits[key][why] += 1
                        case_log.append((d, c, wname, lname, x[0], buy))
                        break
        print(d, file=sys.stderr, flush=True)
    R.say(f"디앤서 돌파 매매 1년 ({P0}~{P1}) — 전날 대금 10위, 다음 봉 시가 매수, 손절 −2%, 익절 = 다음 레벨, 250일 고가 위 마감이면 다음 날 09:00")
    for wname in WIN:
        R.say(f"\n-- {wname}")
        for lname in ("전일 종가", "전일 고가", "라운드 피겨", "단기 신고가(20일)", "250일 신고가"):
            for s in (False, True):
                key = (wname, lname, s)
                st = R.stats(res[key], f"{lname} 돌파{' + 대금 3배' if s else ''}")
                if res[key]: R.say(f"      매도 사유: {dict(exits[key])}")
    R.say("\n-- 책 매매일지 사례 (그날 우리 규칙이 신호를 냈나)")
    from datetime import date as _d
    for nm, ds in (("LIG넥스원", "2026-04-22"), ("두산로보틱스", "2026-04-30"), ("HD현대에너지솔루션", "2026-05-13"),
                   ("HD현대에너지솔루션", "2026-05-14"), ("현대오토에버", "2026-05-08"), ("매드업", "2026-07-03"), ("아주IB투자", "2026-05-19")):
        c = code_by_name(nm); d = _d.fromisoformat(ds)
        hit = [x for x in case_log if x[0] == d and x[1] == c]
        rk = value_rank(prev_day(d)).get(c) if c and d in CIDX else None
        R.say(f"  {nm} {ds}: 전날 대금 {rk}위 → " + ("; ".join(f"{w} {l} {t} 매수 {b:,.0f}" for _, _, w, l, t, b in hit) if hit else "신호 없음"))


if __name__ == "__main__":
    main()
