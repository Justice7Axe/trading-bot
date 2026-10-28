"""B·D — 1️⃣ 상승장 장 초 1년: 추격 기준(+1%/+2%/+3%/제한 없음)과 손절 폭(−4/−6/−8%/없음) (2026-10-28 사용자 16종목 복기).

1️⃣ 고르기 = bt_up_exits.py 와 같음: u_cands.pkl (T=09:10, 강한 상승장 U 날, 09:10 누적 대금 40위 안, 시가 위, 전날 외인·기관 둘 다 − 제외).
1️⃣ 백테스트에는 추격 조건이 없다 → 신호 시점 가격 대비 실제 매수 시점 가격으로 흉내 낸다:
   (a) 신호가 = 09:10 봉 시가, 매수 = 09:11 봉 시가 (판단 뒤 1분)
   (b) 신호가 = 09:10 봉 종가, 매수 = 09:12 봉 시가 (오늘 실제: 신호 09:10:19 → 주문 09:11:50 에 가까움)
   매수가 > 신호가 × (1 + k) 면 '추격 안 함' 으로 안 삼.
매도: 손절 닿으면 그 가격(시가가 이미 아래면 시가), 아니면 다음 날 09:00 시가 (engine.next_day_exits, 1분봉 원가격·기준 맞춤). 익절 없음. 비용 0.25%.
1분봉 = engine (minute_history 가 잠겨 있으면 10-25 복사본 → 2025-10-15 ~ 2026-10-23).
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_capture.bt_chase_stop → data/leader_capture/bt_chase_stop.txt
"""
import os, sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "leader_capture"); os.makedirs(OUT, exist_ok=True)
UNTIL = time(15, 19)
F = open(os.path.join(OUT, "bt_chase_stop.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def run_exit(b, j, buy, nx, stop):
    """b[j] 이후 15:19 까지 손절 확인, 아니면 다음 날 09:00 (nx = 다음 날 시가 수익률, 비용 포함)."""
    if stop is not None:
        sp = buy * (1 - stop)
        for x in b[j:]:
            if x[0] > UNTIL: break
            if x[3] <= sp:
                return min(x[1], sp) / buy - 1 - E.COST
    return nx


def stats(tr, title):
    """tr = [(date, ret)]. 건당 25만 원 합계 + 날 평균(1,000만/일 균등) 합계·낙폭."""
    if len(tr) < 5:
        say(f"   {title:40s} {len(tr)}건 (적음)"); return
    ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; bb = [x for d, x in tr if d >= h]
    bd = defaultdict(list)
    for d, x in tr: bd[d].append(x)
    dr = {d: np.mean(x) for d, x in bd.items()}
    s = sorted(dr.values(), reverse=True)
    eq = np.cumsum([dr[d] for d in sorted(dr)]) * 1000
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    say(f" {star} {title:40s} {len(v):4d}건 {len(dr):2d}일 건당 {v.mean():+.2%} 25만씩 합계 {v.sum() * 25:+5.0f}만 | "
        f"1천만/일 합계 {sum(s) * 1000:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 1000:+5.0f}만 낙폭 {mdd:.0f}만 | 앞 {np.mean(a):+.2%} 뒤 {np.mean(bb):+.2%}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    say(f"1️⃣ 후보 {len(sel)}건 {len({r['date'] for r in sel})}일 ({min(r['date'] for r in sel)} ~ {max(r['date'] for r in sel)})")
    T = []   # dict per trade
    miss = 0
    for r in sel:
        d, c = r["date"], r["code"]
        b = E.regular(E.bars(c, d))
        idx = {x[0]: i for i, x in enumerate(b)}
        if not all(t in idx for t in (time(9, 10), time(9, 11), time(9, 12))):
            miss += 1; continue
        i10, i11, i12 = idx[time(9, 10)], idx[time(9, 11)], idx[time(9, 12)]
        pc = b[0][1] / (1 + r["gap"])            # 전일 종가 (1분봉 기준)
        out = dict(d=d, c=c)
        for tag, sig, j in (("a", b[i10][1], i11), ("b", b[i10][4], i12), ("0", b[i10][1], i10)):
            buy = b[j][1]
            if buy / pc - 1 >= 0.29:                # 상한가 근처는 못 삼
                out[tag] = None; continue
            nx = E.next_day_exits(c, d, buy).get("09:00 시가")
            if nx is None:
                out[tag] = None; continue
            out[tag] = dict(chase=buy / sig - 1, **{f"s{k}": run_exit(b, j, buy, nx, k) for k in (0.04, 0.06, 0.08, None)})
        T.append(out)
    say(f"1분봉 09:10~09:12 없음 {miss}건, 다음 날 09:00 못 구함 a {sum(t['a'] is None for t in T)} b {sum(t['b'] is None for t in T)}")

    say("\n" + "=" * 110)
    say("[D] 손절 폭 — 09:10 봉 시가 매수(bt_up_exits 와 같은 시점) / 09:11 봉 시가 매수, 익절 없음, 다음 날 09:00")
    say("=" * 110)
    for tag, nm in (("0", "09:10 시가"), ("a", "09:11 시가")):
        for k in (0.04, 0.06, 0.08, None):
            tr = [(t["d"], t[tag][f"s{k}"]) for t in T if t[tag]]
            stats(tr, f"{nm} 손절 {'없음' if k is None else f'−{k:.0%}'}")
        say("")

    say("=" * 110)
    say("[B] 추격 기준 — 매수가가 신호가보다 +k% 넘게 오르면 안 삼 (손절 −4%, 다음 날 09:00)")
    say("=" * 110)
    for tag, nm in (("a", "(a) 신호 09:10 시가 → 09:11 시가 매수"), ("b", "(b) 신호 09:10 종가 → 09:12 시가 매수")):
        tt = [t for t in T if t[tag]]
        ch = np.array([t[tag]["chase"] for t in tt])
        say(f"\n{nm}: {len(tt)}건, 추격 폭 분포 중앙 {np.median(ch):+.2%} / >+1% {np.mean(ch > 0.01):.0%} / >+2% {np.mean(ch > 0.02):.0%} / >+3% {np.mean(ch > 0.03):.0%}")
        for k in (0.01, 0.02, 0.03, None):
            keep = [(t["d"], t[tag]["s0.04"]) for t in tt if k is None or t[tag]["chase"] <= k]
            stats(keep, f"추격 기준 {'제한 없음' if k is None else f'+{k:.0%}'} (산 것)")
        for lo, hi in ((-1, 0.0), (0.0, 0.01), (0.01, 0.02), (0.02, 0.03), (0.03, 1)):
            grp = [(t["d"], t[tag]["s0.04"]) for t in tt if lo < t[tag]["chase"] <= hi]
            stats(grp, f"   추격 폭 {lo:+.0%}~{hi:+.0%} 구간만")
    F.close()


if __name__ == "__main__":
    main()
