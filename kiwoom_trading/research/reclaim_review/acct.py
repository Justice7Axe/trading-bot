"""🔁 시가 탈환 재점검 — 1천만 모의 계좌 전체 시뮬 (지금 규칙 vs 멈춤 vs 강화 후보).

research/account_alloc/sim.run 재사용. 다른 매매 = data/strict_select/trades_feat.pkl 에 엄격 선정 A안(choose.PICK) 적용 (3️⃣ 는 모의에서 뺌).
🔁 = data/reclaim_review/sets.pkl (analyze.py) — 전용 몫 = 자산의 10%(1천만 기준 100만), 종목당 10%, 보유 한도 칸 안 씀.
다른 매매 자료가 2026-10-22 까지라 계좌 시뮬도 그날까지 (🔁 몫만 따로 본 것은 analyze.py 5장, 11-05 까지).
실행: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m kiwoom_trading.research.reclaim_review.acct → data/reclaim_review/acct.txt
"""
import os
import pickle
import sys
from datetime import date

from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select.choose import PICK, apply

OUT = os.path.join(S.DATA, "reclaim_review")
M3 = date(2026, 8, 6)


def conv(rows):
    return [dict(date=t["date"], t=t["t"], kind="🔁", code=t["code"], px=t["px"], ret=t["ret"], rk=t["pvr"], xt=t["xt"]) for t in rows]


def run_win(cfg, T, d0=None, d1=None):
    keep = S.DAYS
    if d0:
        S.DAYS = [d for d in keep if d0 <= d <= (d1 or keep[-1])]
    try:
        return S.run(cfg, trades=[t for t in T if t["date"] in set(S.DAYS)])
    finally:
        S.DAYS = keep


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(os.path.join(OUT, "acct.txt"), "w", encoding="utf-8")
    say = lambda s="": (print(s, flush=True), f.write(s + "\n"))
    base = [t for t in apply(pickle.load(open(os.path.join(S.DATA, "strict_select", "trades_feat.pkl"), "rb")), PICK) if t["kind"] != "🔁"]
    old_r = [t for t in apply(pickle.load(open(os.path.join(S.DATA, "strict_select", "trades_feat.pkl"), "rb")), PICK) if t["kind"] == "🔁"]
    sets = pickle.load(open(os.path.join(OUT, "sets.pkl"), "rb"))
    kinds = set(S.KINDS) - {"3️⃣"}
    pool = {"rpool": 0.10, "amt": S.NOW["amt"] | {"🔁": 0.10}}
    rows = [("멈춤 (🔁 안 삼)", {"kinds": kinds - {"🔁"}}, base),
            ("(참고) 옛 백테스트 🔁 + 기관 +", dict(pool, kinds=kinds), base + old_r),
            ("지금 규칙", dict(pool, kinds=kinds), base + conv(sets["NOW"]))]
    for nm, rs in sets["res"].items():
        rows.append((nm, dict(pool, kinds=kinds), base + conv(rs)))
    say(f"1천만 모의 계좌 (sim.run 복리, 다른 매매 A안·3️⃣ 뺌), 기간 {S.DAYS[0]} ~ {S.DAYS[-1]}, 최근 3달 {M3}~")
    say(f"{'🔁 규칙':32s} | 1년 최종 · 낙폭 · 앞/뒤 | 🔁 건수·손익 | 다른 매매 손익 | 최근 3달 (1천만 시작) 최종 · 🔁 손익")
    for nm, cfg, T in rows:
        y = run_win(cfg, T); m = run_win(cfg, T, M3)
        rp = y["pnl_k"].get("🔁", 0); other = sum(v for k, v in y["pnl_k"].items() if k != "🔁")
        say(f"{nm:32s} | {y['final'] / 1e4:7,.0f}만 · {y['mdd']:.1%} · {y['front']:+.0%}/{y['back']:+.0%} | {y['n_k'].get('🔁', 0):4d}건 {rp / 1e4:+6,.0f}만 "
            f"| {other / 1e4:+7,.0f}만 | {m['final'] / 1e4:6,.0f}만 · 🔁 {m['pnl_k'].get('🔁', 0) / 1e4:+5,.0f}만 ({m['n_k'].get('🔁', 0)}건)")
    f.close()


if __name__ == "__main__":
    main()
