"""4) 계좌 시뮬: 10만 원 실전 계좌(1년·최근 63거래일, 시드 여러 개) + 1천만 모의 계좌 — 5️⃣ 약세장 인버스 개선 후보 전/후.

기준 = regime_recheck 와 같음: strict_select trades_feat + B안(C.ALT), 7️⃣ 뺌, 실전 매매 6️⃣2️⃣5️⃣📕1️⃣🌙4️⃣, real_sim(종목당 3만 원).
5️⃣ 는 five.py 재현 값으로 바꿔 넣음 (10-22 는 대용 인버스, 가격 1,370원 근사). 계좌 기간 2025-10-16 ~ 2026-10-22.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.inverse_after_drop.account → data/inverse_after_drop/account.txt
"""
import os
import pickle
import sys
from datetime import date, time

from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.inverse_after_drop import common as C
from kiwoom_trading.research.strict_select import choose as CH

rep = open(os.path.join(C.OUT, "account.txt"), "w", encoding="utf-8")
REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}


def say(s=""):
    print(s); rep.write(s + "\n"); rep.flush()


def entry_px(d, t):
    if d in C.INV:
        b = next((b for b in C.INV[d] if b["ts"].time() >= t), None)
        if b:
            return float(b["open"])
    return 1370.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = pickle.load(open(os.path.join(C.OUT, "five.pkl"), "rb"))
    ent = pickle.load(open(os.path.join(C.OUT, "five_entry.pkl"), "rb"))
    prev = {r["date"]: r["prev"] for r in rows}
    late = {o["date"]: o for o in ent["10:00 +5/−3"]}
    T0 = pickle.load(open(os.path.join(S.DATA, "strict_select", "trades_feat.pkl"), "rb"))
    last = S.DAYS[-1]

    def five(skip=None, late_th=None):
        out = []
        for r in rows:
            d = r["date"]
            if d > last or r["ret"] is None:
                continue
            if skip is not None and prev[d] <= skip:
                continue
            if late_th is not None and prev[d] <= late_th:
                o = late[d]
                out.append(dict(date=d, t=time(10, 0), kind="5️⃣", code="123310", px=entry_px(d, time(10, 0)), ret=o["ret"], rk=0, xt=None, lead=False))
            else:
                out.append(dict(date=d, t=time(9, 11), kind="5️⃣", code="123310", px=entry_px(d, time(9, 11)), ret=r["ret"], rk=0, xt=None, lead=False))
        return out

    BASE = [t for t in CH.apply(T0, CH.ALT) if t["kind"] not in ("7️⃣", "5️⃣")]
    MOCK = [t for t in CH.apply(T0, CH.PICK) if t["kind"] != "5️⃣"]
    CANDS = [("지금 (09:11 매일)", dict()), ("전날 코스피 ≤ −2% 면 안 삼", dict(skip=-0.02)), ("전날 코스피 ≤ −3% 면 안 삼", dict(skip=-0.03)),
             ("전날 코스피 ≤ −2% 면 10:00 매수", dict(late_th=-0.02)), ("5️⃣ 아예 안 함", None)]
    DAYS1 = list(S.DAYS); SPLIT0 = S.SPLIT; d3 = DAYS1[-63]

    def acct(T, seed, d_from=None):
        if d_from:
            dd = [d for d in DAYS1 if d >= d_from]; S.DAYS = dd; S.SPLIT = dd[len(dd) // 2]
            T = [t for t in T if t["date"] >= d_from]
        r = CH.real_sim(T, kinds=REAL, seed=seed)
        S.DAYS = DAYS1; S.SPLIT = SPLIT0
        return r

    say(f"# 계좌 시뮬 ({DAYS1[0]} ~ {last}, 최근 3달 = {d3} 뒤 63거래일)")
    say("\n## 1. 10만 원 실전 계좌 (B안 선정, 종목당 3만 원·넘으면 1주, 실전 6️⃣ 주도주 신고가·2️⃣ 저항 돌파·5️⃣ 약세장 인버스·📕 상한가 풀림·1️⃣ 상승장 장 초·🌙 종가 재돌파·4️⃣ 역행 강세 종가)")
    for lab, kw in CANDS:
        T = BASE + (five(**kw) if kw is not None else [])
        a = acct(T, 100_000); b = acct(T, 100_000, d3)
        say(f"  {'★' if a['star'] else ' '} {lab:30s} 1년 {a['final']:>11,.0f}원 낙폭 {a['mdd']:.0%} 앞 {a['front']:+.0%} 뒤 {a['back']:+.0%} "
            f"| 5️⃣ {a['n'].get('5️⃣', 0):2d}건 {a['pnl'].get('5️⃣', 0):+8,.0f}원 | 3달 {b['final']:>9,.0f}원 (5️⃣ {b['n'].get('5️⃣', 0)}건 {b['pnl'].get('5️⃣', 0):+,.0f}원)")
    say("\n## 2. 시드별 (지금 대비 %) — 1년 / 3달")
    for seed in (70_000, 100_000, 150_000, 200_000, 300_000):
        base1 = acct(BASE + five(), seed)["final"]; base3 = acct(BASE + five(), seed, d3)["final"]
        xs = []
        for lab, kw in CANDS[1:]:
            T = BASE + (five(**kw) if kw is not None else [])
            xs.append(f"{acct(T, seed)['final'] / base1 - 1:+.1%}/{acct(T, seed, d3)['final'] / base3 - 1:+.1%}")
        say(f"  {seed // 10000:2d}만 지금 {base1:>11,.0f} / {base3:>9,.0f} | " + " | ".join(f"{CANDS[i + 1][0]} {x}" for i, x in enumerate(xs)))
    say("\n## 3. 5️⃣ 단독 10만 계좌 (다른 매매 없이)")
    for lab, kw in CANDS[:-1]:
        a = acct(five(**kw), 100_000); b = acct(five(**kw), 100_000, d3)
        say(f"  {lab:30s} 1년 {a['final']:>9,.0f}원 낙폭 {a['mdd']:.0%} | 3달 {b['final']:>9,.0f}원")
    say("\n## 4. 1천만 모의 계좌 (sim.run 지금 모의 배분, A안 선정, 3️⃣ 뺌)")
    for lab, kw in CANDS:
        T = MOCK + (five(**kw) if kw is not None else [])
        r = S.run({"kinds": set(S.KINDS) - {"3️⃣"}}, trades=T)
        say(f"  {'★' if r['star'] else ' '} {lab:30s} {r['final'] / 1e4:9,.0f}만 낙폭 {r['mdd']:.1%} 앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} | 5️⃣ {r['n_k'].get('5️⃣', 0)}건")


if __name__ == "__main__":
    main()
