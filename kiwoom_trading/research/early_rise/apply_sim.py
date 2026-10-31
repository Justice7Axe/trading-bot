"""신호 순간 '추격' 거르기를 지금 실전 규칙 10만 계좌 1년에 넣어 보기 (2026-10-31). 실전 매매 = 6️⃣2️⃣5️⃣📕1️⃣🌙 (4️⃣7️⃣ 뺌, PR #157), 엄격 선정 B."""
import os, sys
import pandas as pd
from kiwoom_trading.research.strict_select import choose as C
sys.stdout.reconfigure(encoding="utf-8")
F = pd.read_pickle(os.path.join(C.DATA, "early_rise", "trades_signal_feat.pkl"))
key = {(r.date, r.code, r.kind, r.t): (r.vwap, r.acc5, r.rng30, r.ret_open) for r in F.itertuples()}
T = C.apply(C.S.load() if hasattr(C.S, "load") else None, C.ALT) if False else None
import pickle
T0 = pickle.load(open(os.path.join(C.OUT, "trades_feat.pkl"), "rb"))
for t in T0:
    t["vwap"], t["acc5"], t["rng30"], t["ret_open"] = key.get((t["date"], t["code"], t["kind"], t["t"]), (None,) * 4)
T = C.apply(T0, C.ALT)
REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙"}
REAL = {k for k in REAL if k in C.S.KINDS}
def big(x, th): return x is not None and x == x and x >= th
FILT = {
    "기준 (지금 실전)": lambda t: True,
    "📕 5분 대금 가속 ≥0.53 빼기": lambda t: not (t["kind"] == "📕" and big(t["acc5"], 0.529)),
    "2️⃣ 시가 대비 +10.6%↑ 빼기": lambda t: not (t["kind"] == "2️⃣" and big(t["ret_open"], 0.106)),
    "6️⃣ 5분 대금 가속 ≥1.63 빼기": lambda t: not (t["kind"] == "6️⃣" and big(t["acc5"], 1.625)),
    "셋 다": lambda t: not ((t["kind"] == "📕" and big(t["acc5"], 0.529)) or (t["kind"] == "2️⃣" and big(t["ret_open"], 0.106)) or (t["kind"] == "6️⃣" and big(t["acc5"], 1.625))),
}
out = open(os.path.join(C.DATA, "early_rise", "apply_sim.txt"), "w", encoding="utf-8")
for nm, f in FILT.items():
    r = C.real_sim([t for t in T if f(t)], kinds=REAL)
    s = (f"{nm:28s} {r['final']:>9,.0f}원 낙폭 {r['mdd']:.1%} 앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} {'★' if r['star'] else ' '} | 건수 {sum(r['n'].values())} "
         + " ".join(f"{k}{v/1e4:+.1f}만" for k, v in r['pnl'].items()) + f" | 못 삼 {r['skip'].get('예수금 부족', 0)}")
    print(s); out.write(s + "\n")
