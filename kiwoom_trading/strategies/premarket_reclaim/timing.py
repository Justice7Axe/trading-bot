"""🔁 시초 흔들기 뒤 회복 — 매수 '시점' 비교: 손절선(흔들기 저가)에 얼마나 가까이 사느냐가 손익비를 정한다 (2026-10-27).

사용자: "매매 대상을 선정만 해서는 안 되고, 빠른 타이밍에 잡아서 손익비가 좋은 매수 타점을 잡는 것이 중요."
backtest.py 결과: 정규장 고점 돌파 뒤 사면(삼성SDI 09:17 499,500) 흔들기 저가(484,500)까지 −3% — '절반 +2% 익절'로는 손익비 0.7 → 1년 전 변형 손실.
그래서 같은 날·같은 종목(① 프리장 갭 2%↑ ② 09:00~09:10 흔들기 2%↑, 전일 종가 −1% 지킴)에서 매수 시점만 바꿔 본다.
손절은 모두 '흔들기 저가 − 1틱(0.1%)' (그 아래면 흔들기가 아니라 하락). R = 매수가 − 손절가.
  E0 정규장 고점 돌파 + 20·60봉 위 + 대금 2배 (backtest.py 기본, SDI 09:16 → 09:17)
  E1 시가 회복: 흔들기 저가가 나온 뒤 1분봉 종가가 09:00 시가 위 + 대금 2배 (SDI 09:14 495,000 근처)
  E2 이평 회복: 흔들기 뒤 종가가 20·60봉 이평 위 + 대금 2배 (정규장 고점 돌파 없이, SDI 09:12 무렵)
  E3 첫 반등 확인: 흔들기 저가 봉 다음, 종가가 직전 봉 고가 위 + 대금 1.5배 (가장 이름, 바닥 근처)
  E4 E1 뒤 눌림 지정가: E1 신호 가격에서 −0.5% 지정가, 10분 안 체결 (추격 안 함)
매도:
  M1 절반 +2% → 나머지 트레일 3% (사용자 규칙)
  M2 절반 +1R → 나머지 트레일 3%
  M3 절반 +2R → 나머지 트레일 3%
  M0 손절만, 다음 날 09:00
  (트레일 스탑은 절반 익절 뒤 max(손절, 본전, 고점 × 0.97). 15:19 까지 남으면 다음 날 09:00. 같은 봉이면 손절 먼저. 비용 0.25%)
집계: 건당 %, 기대값 R, 손익비(평균 이익 ÷ 평균 손실), 승률, 앞·뒤 반, 최고 5일 빼기, 매수가→손절 거리(R%) 평균.
실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.premarket_reclaim.timing  → data/premarket_reclaim/timing.txt
"""
import os
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "premarket_reclaim")
os.makedirs(OUT, exist_ok=True)
GAP, SHAKE, HOLD = 0.02, 0.02, 0.01
VAL_MIN = 1e9
TRAIL = 0.03


def setup(b, prev_close):
    """조건 ①② → (프리장 고점, 09:00 시가, 흔들기 저가, 흔들기 저가 봉 index) 또는 None."""
    pre = [x for x in b if x[0] < time(9, 0)]
    reg = [i for i, x in enumerate(b) if x[0] >= time(9, 0)]
    if len(pre) < 10 or len(reg) < 60:
        return None
    pre_hi = max(x[2] for x in pre)
    if pre_hi < prev_close * (1 + GAP):
        return None
    early = [i for i in reg if b[i][0] <= time(9, 10)]
    if not early:
        return None
    k = min(early, key=lambda i: b[i][3])
    lo = b[k][3]
    if not (lo <= pre_hi * (1 - SHAKE) and lo >= prev_close * (1 - HOLD)):
        return None
    return pre_hi, b[reg[0]][1], lo, k, reg[0]


def entries(b, s):
    """매수 시점별 (이름 → (매수 봉 index, 매수가))."""
    pre_hi, op, lo, k, r0 = s
    closes = np.array([x[4] for x in b], float)
    vals = np.array([x[4] * x[5] for x in b], float)
    out = {}
    reg_hi = max(b[i][2] for i in range(r0, k + 1))
    for i in range(k + 1, len(b) - 1):
        x = b[i]
        if x[0] > time(10, 30):
            break
        if b[i][3] < lo:          # 흔들기 저가를 깨면 그날 끝
            break
        avg5 = vals[i - 5:i].mean()
        big = vals[i] >= VAL_MIN
        m20, m60 = closes[i - 19:i + 1].mean(), closes[i - 59:i + 1].mean()
        nb = b[i + 1]
        if "E3" not in out and i == k + 1 or ("E3" not in out and i > k and big and vals[i] >= 1.5 * avg5 and x[4] > b[i - 1][2]):
            if x[4] > b[i - 1][2] and vals[i] >= 1.5 * avg5 and big:
                out.setdefault("E3 첫 반등 확인", (i + 1, nb[1]))
        if x[4] > op and big and vals[i] >= 2 * avg5:
            if "E1 시가 회복" not in out:
                out["E1 시가 회복"] = (i + 1, nb[1])
                # E4: 신호가 −0.5% 지정가, 10봉 안
                lim = x[4] * 0.995
                for j in range(i + 1, min(i + 11, len(b))):
                    if b[j][3] <= lim:
                        out["E4 시가 회복 뒤 눌림 지정가"] = (j, min(lim, b[j][1]))
                        break
        if x[4] > m20 and x[4] > m60 and big and vals[i] >= 2 * avg5:
            out.setdefault("E2 이평 회복", (i + 1, nb[1]))
        if x[4] > reg_hi and x[4] > m20 and x[4] > m60 and big and vals[i] >= 2 * avg5:
            out.setdefault("E0 정규장 고점 돌파", (i + 1, nb[1]))
        reg_hi = max(reg_hi, x[2])
    return out


def sell(b, j, e, stop0, nopen, half_at, limit_bar=False):
    """b[j] 에서 e 에 매수 → (수익률, R 배수). half_at = 절반 익절 가격(None = 없음)."""
    R = e - stop0
    stop, hi, done, got = stop0, e, False, 0.0
    for n, x in enumerate(b[j:]):
        if x[0] > time(15, 19):
            break
        if x[3] <= stop:
            px = min(x[1], stop) if not (limit_bar and n == 0) else stop
            r = got + (0.5 if done else 1.0) * (px / e - 1)
            return r - E.COST, (r * e) / R
        if half_at and not done and x[2] >= half_at and not (limit_bar and n == 0):
            got, done = 0.5 * (half_at / e - 1), True
        hi = max(hi, x[2])
        if done:
            stop = max(stop, e, hi * (1 - TRAIL))
    if nopen is None:
        return None, None
    r = got + (0.5 if done else 1.0) * (nopen / e - 1)
    return r - E.COST, (r * e) / R


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = open(os.path.join(OUT, "timing.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); out.write(s + "\n"); out.flush()

    res = defaultdict(list)       # (진입, 매도) → [(date, ret, R, risk%)]
    for d in E.days():
        p = E.prev_day(d)
        U = [c for c, r in E.value_rank(p).items() if r <= 200 and E.is_common(c)]
        B, P = E.load_day(U, d), E.load_day(U, p)
        for c in U:
            b = B.get(c) or []
            pr = E.regular(P.get(c) or [])
            if len(b) < 100 or len(pr) < 30:
                continue
            s = setup(b, pr[-1][4])
            if not s:
                continue
            stop0 = s[2] * 0.999
            for en, (j, e) in entries(b, s).items():
                if e <= stop0:
                    continue
                risk = e / stop0 - 1
                ex = E.next_day_exits(c, d, e)
                nopen = e * (1 + ex["09:00 시가"] + E.COST) if "09:00 시가" in ex else None
                R = e - stop0
                for mn, half in (("M1 절반 +2% · 트레일 3%", e * 1.02), ("M2 절반 +1R · 트레일 3%", e + R),
                                 ("M3 절반 +2R · 트레일 3%", e + 2 * R), ("M0 손절만 · 다음 날 09:00", None)):
                    r, rr = sell(b, j, e, stop0, nopen, half, limit_bar=en.startswith("E4"))
                    if r is not None and abs(r) < 0.35:
                        res[(en, mn)].append((d, r, rr, risk))
    say(f"🔁 시초 흔들기 뒤 회복 — 매수 시점 비교 1년 ({E.P0} ~ {E.P1}), 전날 대금 200위, 손절 = 흔들기 저가 −0.1%")
    days_all = sorted({d for v in res.values() for d, *_ in v}); half_d = days_all[len(days_all) // 2]
    for en in sorted({k[0] for k in res}):
        say(f"\n== {en} ==")
        for mn in sorted({k[1] for k in res if k[0] == en}):
            v = res[(en, mn)]
            r = np.array([x[1] for x in v]); R = np.array([x[2] for x in v]); risk = np.mean([x[3] for x in v])
            win, loss = r[r > 0], r[r <= 0]
            pf = (win.mean() / -loss.mean()) if len(win) and len(loss) else float("nan")
            a = np.mean([x[1] for x in v if x[0] < half_d]); bb = np.mean([x[1] for x in v if x[0] >= half_d])
            bd = defaultdict(float)
            for x in v: bd[x[0]] += x[1]
            top5 = sum(sorted(bd.values(), reverse=True)[5:])
            star = "★" if a > 0 and bb > 0 and top5 > 0 else " "
            say(f" {star}{mn:26s} {len(v):4d}건 건당 {r.mean():+.2%} 기대값 {R.mean():+.2f}R 손익비 {pf:.2f} 승률 {np.mean(r > 0):.0%} "
                f"| 앞 {a:+.2%} 뒤 {bb:+.2%} | 최고5일 빼면 {top5 * 100:+.0f}만 | 손절까지 평균 {risk:.1%}")
    say("\n== 손절까지 거리별 (손익비 = 손절이 가까울수록 좋은가) ==")
    for en in ("E1 시가 회복", "E3 첫 반등 확인", "E4 시가 회복 뒤 눌림 지정가"):
        for mn in ("M0 손절만 · 다음 날 09:00", "M1 절반 +2% · 트레일 3%", "M3 절반 +2R · 트레일 3%"):
            v = res.get((en, mn), [])
            for lo_, hi_ in ((0, 0.015), (0.015, 0.025), (0.025, 0.04), (0.04, 1)):
                w = [x for x in v if lo_ <= x[3] < hi_]
                if len(w) >= 30:
                    r = np.array([x[1] for x in w]); a = np.mean([x[1] for x in w if x[0] < half_d]); bb = np.mean([x[1] for x in w if x[0] >= half_d])
                    say(f"  {en[:8]} {mn[:14]} 손절 {lo_:.1%}~{hi_:.1%}: {len(w):4d}건 건당 {r.mean():+.2%} 기대값 {np.mean([x[2] for x in w]):+.2f}R 승률 {np.mean(r > 0):.0%} | 앞 {a:+.2%} 뒤 {bb:+.2%}")
    out.close()


if __name__ == "__main__":
    main()

