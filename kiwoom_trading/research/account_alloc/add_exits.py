"""매매마다 '그날 장중에 다 팔렸으면 그 시각(xt)'을 붙인다 → 시뮬레이션에서 그 뒤 신호에 현금·자리를 다시 쓸 수 있게.

매도 규칙(실전·모의와 같음)으로 1분봉을 다시 따라가 첫 청산 시각만 찾는다 (수익률은 원래 백테스트 값 그대로 씀):
  1️⃣ −6% · 6️⃣ −4% (익절 없음) · 2️⃣ +7/−5 · 3️⃣ +7/−5(강한 상승장)·−3(그 밖) · 5️⃣ +5/−3 (인버스 1분봉)
  🔁 손절(흔들기 저가) 또는 +2R 절반 뒤 트레일 3% 로 '남은 절반'까지 다 팔린 시각 · ☕ −2% 또는 상한가 (절반 +2.5% 뒤 남은 것)
  📕·4️⃣·🌙·7️⃣ 는 장중 매도 없음.
장중에 안 팔리면 xt=None (다음 날 09:00). 같은 봉 손절 먼저, 15:19 까지.
점검: 장중 청산으로 찾은 매매의 '규칙 가격 수익률'과 원래 수익률이 얼마나 맞는지 출력.
"""
import os
import pickle
import sys
from collections import Counter
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.paths import pb
from kiwoom_trading.backtest.playbook.regime import cls

OUT = os.path.join(E.DATA, "account_alloc")
UNTIL = time(15, 19)


def first_exit(b, t0, e, sl=None, tp=None):
    """t0 봉부터. → (시각, 가격) 또는 None"""
    for x in b:
        if x[0] < t0: continue
        if x[0] > UNTIL: break
        if sl and x[3] <= e * (1 - sl):
            return x[0], min(x[1], e * (1 - sl))
        if tp and x[2] >= e * (1 + tp):
            return x[0], max(x[1], e * (1 + tp))
    return None


def reclaim_exit(b, t0, e, R):
    stop, hi, done = e - R, e, False
    for x in b:
        if x[0] < t0: continue
        if x[0] > UNTIL: break
        if x[3] <= stop:
            return x[0], None
        if not done and x[2] >= e + 2 * R:
            done = True
        hi = max(hi, x[2])
        if done:
            stop = max(stop, e, hi * 0.97)
    return None


def cafe_exit(b, t0, e, pc):
    lim = pc * 1.295 if pc else None
    for x in b:
        if x[0] <= t0: continue           # 지정가 체결 봉 다음부터
        if x[0] > UNTIL: break
        if x[3] <= e * 0.98:
            return x[0], None
        if lim and x[2] >= lim:
            return x[0], None
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = pickle.load(open(os.path.join(OUT, "trades.pkl"), "rb"))
    rec = {(r["date"], r["code"]): r for r in pickle.load(open(os.path.join(OUT, "reclaim.pkl"), "rb"))}
    inv = pickle.load(open(pb("inv_bars.pkl"), "rb"))
    chk = Counter(); err = []
    for t in T:
        k, d, c = t["kind"], t["date"], t["code"]
        t["xt"] = None
        if k in ("📕", "4️⃣", "🌙", "7️⃣"):
            continue
        if k == "5️⃣":
            b = [(x["ts"].time(), x["open"], x["high"], x["low"], x["close"]) for x in inv[d]]
        else:
            b = E.regular(E.bars(c, d))
        if not b:
            chk["1분봉 없음"] += 1; continue
        e = t["px"]
        if k == "🔁":
            r = rec[(d, c)]
            R = (r["ret"] + E.COST) * e / r["R"] if r["R"] else None
            hit = reclaim_exit(b, t["t"], e, R) if R and R > 0 else None
        elif k == "☕":
            pc = E.daily_day(E.prev_day(d)).get(c); f = E.factor(c, d)
            hit = cafe_exit(b, t["t"], e, pc[3] * f if pc and f else None)
        else:
            sl, tp = {"1️⃣": (0.06, None), "6️⃣": (0.04, None), "2️⃣": (0.05, 0.07), "5️⃣": (0.03, 0.05)}.get(k, (None, None))
            if k == "3️⃣":
                sl, tp = (0.05 if cls(d) == "U" else 0.03), 0.07
            # 3️⃣·2️⃣ 는 신호 봉 다음 봉에 삼
            t0 = t["t"] if k in ("1️⃣", "6️⃣", "5️⃣") else next((x[0] for x in b if x[0] > t["t"]), t["t"])
            hit = first_exit(b, t0, e, sl, tp)
            if hit:
                rr = hit[1] / e - 1 - (0.0005 if k == "5️⃣" else E.COST)
                err.append(abs(rr - t["ret"]))
        if hit:
            t["xt"] = hit[0]; chk[f"{k} 장중 청산"] += 1
        else:
            chk[f"{k} 다음 날"] += 1
    pickle.dump(T, open(os.path.join(OUT, "trades.pkl"), "wb"))
    for k, v in sorted(chk.items()):
        print(f"  {k} {v}")
    err = np.array(err)
    print(f"고정 익절·손절 매매 장중 청산 {len(err)}건: 원래 수익률과 차이 중앙 {np.median(err)*100:.2f}%p, 1%p 넘게 다름 {np.mean(err > 0.01)*100:.0f}%")


if __name__ == "__main__":
    main()
