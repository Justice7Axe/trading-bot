"""실전 매매 손절 규칙 다시 보기 (2026-11-02 사용자 '원해' — 🔺 홍인기 D+ 연구에서 대장주는 장중 −3% 손절이 수익을 깎는다는 결과).

대상: 손절이 있는 실전 매매 6️⃣ 주도주 신고가(−4%) · 1️⃣ 상승장 장 초(−6%) · 2️⃣ 저항 돌파(+7%/−5%) · 5️⃣ 약세장 인버스(+5%/−3%).
매매 기록(research/strict_select trades_feat.pkl + 엄격 선정 B안)의 매수 시각·가격 그대로, 1분봉으로 매도만 바꿔 다시 계산:
  지금 규칙 / 손절 없이(익절은 그대로) 다음 날 09:00 / 손절 −8% / 손절 −10% / 손절·익절 모두 없이 다음 날 09:00.
같은 봉이면 손절 먼저, 종가 매도 없음, 비용 0.25%. 그다음 10만 계좌(종목당 3만) 1년·최근 3달로 바꾼 규칙을 넣어 본다.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.stop_rules.compare
  → data/stop_rules/report.txt
"""
import os
import pickle
import sys
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.research.strict_select import choose as C
from kiwoom_trading.strategies.hong_dplus.backtest import exit_path

OUT = os.path.join(E.DATA, "stop_rules")
os.makedirs(OUT, exist_ok=True)
RULES = {"6️⃣": (None, 0.04), "1️⃣": (None, 0.06), "2️⃣": (0.07, 0.05), "5️⃣": (0.05, 0.03)}   # (익절, 손절)
NAMES = {"6️⃣": "6️⃣ 주도주 신고가", "1️⃣": "1️⃣ 상승장 장 초", "2️⃣": "2️⃣ 저항 돌파", "5️⃣": "5️⃣ 약세장 인버스"}
VARS = {"지금 규칙": lambda tp, sp: (tp, sp), "손절 없이(익절 그대로)": lambda tp, sp: (tp, None), "손절 −8%": lambda tp, sp: (tp, 0.08),
        "손절 −10%": lambda tp, sp: (tp, 0.10), "손절·익절 모두 없이": lambda tp, sp: (None, None)}


def ret_of(t, tp, sp):
    reg = E.regular(E.bars(t["code"], t["date"]))
    k = next((n for n, x in enumerate(reg) if x[0] >= t["t"]), None)
    if k is None:
        return None, None
    buy = t["px"]
    r, why, xt = exit_path(reg, k, buy, tp=buy * (1 + tp) if tp else None, sp=buy * (1 - sp) if sp else None, until=time(15, 30),
                           skip_tp_first=False)
    if r is not None:
        return r, xt
    nx = E.next_day_exits(t["code"], t["date"], buy).get("09:00 시가")
    return nx, None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); f.write(s + "\n"); f.flush()

    base = [t for t in C.apply(pickle.load(open(os.path.join(C.OUT, "trades_feat.pkl"), "rb")), C.ALT) if t["kind"] != "7️⃣"]
    REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}
    S = C.S; days1 = list(S.DAYS); h = days1[len(days1) // 2]
    alt = {}
    say("실전 매매 손절 규칙 비교 — 매수는 그대로, 매도만 바꿈 (1년 매매 기록, 비용 0.25%)")
    for k, (tp0, sp0) in RULES.items():
        rows = [t for t in base if t["kind"] == k and S.DAYS[0] <= t["date"] <= S.DAYS[-1]]
        say(f"\n## {NAMES[k]} (지금: 익절 {tp0 or '없음'} · 손절 −{sp0:.0%}) {len(rows)}건")
        for vn, fn in VARS.items():
            tp, sp = fn(tp0, sp0)
            rs = [ret_of(t, tp, sp) for t in rows]
            ok = [(t, r) for t, r in zip(rows, rs) if r[0] is not None]
            v = np.array([r[0] for _, r in ok])
            if not len(v):
                say(f"  {vn:22s} 1분봉 없음"); continue
            a = np.mean([r[0] for t, r in ok if t["date"] < h]); b = np.mean([r[0] for t, r in ok if t["date"] >= h])
            say(f"  {vn:22s} {len(v):4d}건 건당 {v.mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%}) 승률 {(v > 0).mean():.0%} 최악 {v.min():+.1%}")
            alt[(k, vn)] = {id(t): r for t, r in ok}
        stored = np.mean([t["ret"] for t in rows])
        say(f"  (기록에 있던 값 건당 {stored:+.2%} — '지금 규칙' 재계산과 비교용)")

    say("\n## 10만 계좌 (종목당 3만, 정수 주) — 한 매매만 바꾸고 나머지는 지금 그대로")
    for lab, d_from in (("1년", days1[0]), ("최근 3달", days1[-63])):
        dd = [d for d in days1 if d >= d_from]; S.DAYS = dd; S.SPLIT = dd[len(dd) // 2]
        b0 = [t for t in base if t["date"] >= d_from]
        r0 = C.real_sim(b0, kinds=REAL)
        say(f"  [{lab}] 지금 그대로 10만 → {r0['final']:,.0f}원 낙폭 {r0['mdd']:.0%}")
        for k in RULES:
            for vn in list(VARS):
                m = alt.get((k, vn))
                if not m:
                    continue
                T = []
                for t in b0:
                    if t["kind"] == k and id(t) in m:
                        r, xt = m[id(t)]; t2 = dict(t); t2["ret"] = r; t2["xt"] = xt; T.append(t2)
                    elif t["kind"] == k:
                        continue
                    else:
                        T.append(t)
                r1 = C.real_sim(T, kinds=REAL)
                say(f"  [{lab}] {NAMES[k]} → {vn:22s} 10만 → {r1['final']:>12,.0f}원 낙폭 {r1['mdd']:.0%}")
    S.DAYS = days1; S.SPLIT = h


if __name__ == "__main__":
    main()
