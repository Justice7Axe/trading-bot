"""🔁 시초 흔들기 뒤 회복 매수 — 삼성SDI 2026-10-27 차트에서 정형화 (사용자: "이 차트에서 매수 타점을 찾아서 차트·거래대금 움직임에 맞춰 정형화").

삼성SDI 10-27 통합 1분봉:
  08:00~08:59 프리장 갭 상승 (전일 종가 483,500 → 프리장 고점 500,000, +3.4%)
  09:00 시초 흔들기: 첫 봉 대금 119억, 저가 484,500 (프리장 고점 −3.1%, 전일 종가는 지킴)
  09:01~09:15 거래 마르며 횡보 490~495 (봉 대금 9~37억)
  09:16 정규장 고점(495,500) 돌파 + 20·60분선 위 종가 + 봉 대금 48억 (직전 5봉 평균 17억의 2.9배) → 09:17 시가 499,500 매수 (사용자 타점)
  09:17 프리장 고점 500,000 돌파 (대금 73억)
규칙 (전날 대금 200위 안, 우선주 제외, 통합 1분봉 — minute_history):
  ① 프리장 갭: 08:00~08:59 고점 ≥ 전일 정규장 종가 × (1 + GAP)
  ② 시초 흔들기: 09:00~09:10 저가 ≤ 프리장 고점 × (1 − SHAKE), 저가 ≥ 전일 종가 × (1 − HOLD)
  ③ 회복 봉 (09:05~10:30, 하루 1번): 종가가 정규장 고점 돌파 & 20·60봉 이동평균(통합 1분봉, 프리장 포함) 위 & 봉 대금 ≥ 10억 & ≥ 직전 5봉 평균 × 2
     → 다음 봉 시가 매수. (변형 B: 종가가 프리장 고점 위일 때만)
매도 (2026-10-27 사용자: "익절은 1/2 을 2% 로, 나머지는 트레일링 스탑"):
  처음 손절 = max(09:00~매수 전 저가, 매수가 × 0.97)  (변형: −2%)
  +2% 닿으면 절반 익절 → 남은 절반 스탑 = max(처음 손절, 본전, 매수 뒤 고점 × (1 − TRAIL))
  15:19 까지 안 닿으면 남은 것 다음 날 09:00 시가 (backtest-rules: 종가 매도 금지). 같은 봉이면 손절 먼저. 비용 0.25%.
실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.premarket_reclaim.backtest  → data/premarket_reclaim/backtest.txt
"""
import os
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "premarket_reclaim")
os.makedirs(OUT, exist_ok=True)
VAL_MIN, MULT = 1e9, 2.0
HALF_TP = 0.02


def find_entry(b, prev_close, gap, shake, hold, need_pre_break):
    """b = 통합 1분봉 [(time,o,h,l,c,v)] → (매수 봉 index, 프리장 고점, 처음 손절 기준 저가) 또는 None."""
    pre = [x for x in b if x[0] < time(9, 0)]
    reg = [i for i, x in enumerate(b) if x[0] >= time(9, 0)]
    if len(pre) < 10 or len(reg) < 60:
        return None
    pre_hi = max(x[2] for x in pre)
    if pre_hi < prev_close * (1 + gap):
        return None
    early = [b[i] for i in reg if b[i][0] <= time(9, 10)]
    if not early:
        return None
    lo = min(x[3] for x in early)
    if not (lo <= pre_hi * (1 - shake) and lo >= prev_close * (1 - hold)):
        return None
    closes = [x[4] for x in b]
    vals = [x[4] * x[5] for x in b]
    reg_hi, day_lo = 0.0, float("inf")
    for i in reg:
        x = b[i]
        if x[0] > time(10, 30):
            break
        if x[0] >= time(9, 5) and i >= 60 and reg_hi:
            m20 = np.mean(closes[i - 19:i + 1]); m60 = np.mean(closes[i - 59:i + 1])
            avg5 = np.mean(vals[i - 5:i])
            ok = (x[4] > reg_hi and x[4] > m20 and x[4] > m60 and vals[i] >= VAL_MIN and vals[i] >= avg5 * MULT
                  and (not need_pre_break or x[4] > pre_hi))
            if ok and i + 1 < len(b) and b[i + 1][0] <= time(10, 31):
                return i + 1, pre_hi, min(day_lo, x[3])
        reg_hi = max(reg_hi, x[2]); day_lo = min(day_lo, x[3])
    return None


def sell(b, j, nopen, base_stop, trail, half=True):
    """b[j] 시가 매수 → 수익률 (비용 포함). nopen = 다음 날 09:00 시가 (같은 가격 기준)."""
    e = b[j][1]
    stop = base_stop
    hi, done, got = e, False, 0.0
    for x in b[j:]:
        if x[0] > time(15, 19):
            break
        if x[3] <= stop:
            px = min(x[1], stop)
            return got + (0.5 if done else 1.0) * (px / e - 1) - E.COST
        if half and not done and x[2] >= e * (1 + HALF_TP):
            got, done = 0.5 * HALF_TP, True
        hi = max(hi, x[2])
        if done and trail:
            stop = max(stop, e, hi * (1 - trail))
    if nopen is None:
        return None
    return got + (0.5 if done else 1.0) * (nopen / e - 1) - E.COST


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = open(os.path.join(OUT, "backtest.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); out.write(s + "\n"); out.flush()

    variants = {   # 이름: (GAP, SHAKE, HOLD, 프리장 고점 돌파 필요)
        "기본 (갭 2%·흔들기 2%·전일 종가 −1% 지킴)": (0.02, 0.02, 0.01, False),
        "B: 프리장 고점까지 돌파": (0.02, 0.02, 0.01, True),
        "느슨: 갭 1%·흔들기 1.5%·−2% 지킴": (0.01, 0.015, 0.02, False),
        "엄격: 갭 3%·흔들기 2.5%·전일 종가 지킴": (0.03, 0.025, 0.0, False),
    }
    trades = defaultdict(list)    # variant → [(date, code, bars, j, base_lo, nopen)]
    for d in E.days():
        p = E.prev_day(d)
        vr = E.value_rank(p)
        U = [c for c, r in vr.items() if r <= 200 and E.is_common(c)]
        B = E.load_day(U, d)
        P = E.load_day(U, p)
        for c in U:
            b = B.get(c) or []
            pr = E.regular(P.get(c) or [])
            if len(b) < 100 or len(pr) < 30:
                continue
            prev_close = pr[-1][4]
            for name, (g, s, h, nb) in variants.items():
                hit = find_entry(b, prev_close, g, s, h, nb)
                if not hit:
                    continue
                j, pre_hi, lo = hit
                ex = E.next_day_exits(c, d, b[j][1])
                nopen = b[j][1] * (1 + ex["09:00 시가"] + E.COST) if "09:00 시가" in ex else None
                trades[name].append((d, c, b, j, lo, nopen))
    say(f"🔁 시초 흔들기 뒤 회복 매수 1년 ({E.P0} ~ {E.P1}), 전날 대금 200위, 통합 1분봉. 건당 100만 원 합계")
    for name, tr in trades.items():
        say(f"\n== {name}: {len(tr)}건 ==")
        rows = []
        for label, stop_of, trail, half in (
                ("절반 +2% · 나머지 트레일 2%", "lo3", 0.02, True),
                ("절반 +2% · 나머지 트레일 3%", "lo3", 0.03, True),
                ("절반 +2% · 나머지 트레일 4%", "lo3", 0.04, True),
                ("절반 +2% · 트레일 3% · 손절 −2%", "m2", 0.03, True),
                ("(비교) 익절 없음 · 손절만 · 다음 날 09:00", "lo3", None, False)):
            v = []
            for d, c, b, j, lo, nopen in tr:
                e = b[j][1]
                base = max(lo, e * 0.97) if stop_of == "lo3" else e * 0.98
                r = sell(b, j, nopen, base, trail, half)
                if r is not None and abs(r) < 0.35:
                    v.append((d, r))
            st = E.Report.stats(type("X", (), {"say": staticmethod(say)})(), v, label, 40) if v else None
            rows.append(st)
        names = defaultdict(int)
        for d, c, *_ in tr:
            names[E.NAME.get(c, c)] += 1
        say("  자주 나온 종목: " + ", ".join(f"{n} {k}" for n, k in sorted(names.items(), key=lambda x: -x[1])[:12]))
    out.close()


if __name__ == "__main__":
    main()
