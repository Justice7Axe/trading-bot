"""한 계좌 배분 시험 A~D → data/account_alloc/report.txt

A 1천만 지금 모의 배분 그대로 (복리): 돈·한도로 못 산 신호와 그 결과
B 배분 바꾸기 — 앞 6개월(~2026-04-17)로 고르고 뒤 6개월로 확인. 기대값 차등은 앞 6개월 단독 건당 수익률로만 정함.
C 실전 시드 10만~300만, 정수 주·+1% 지정가 — 지금 실전 규칙 / 하루 2종목 / B 에서 고른 규칙
D 매매 하나씩 빼기 (지금 배분, B 고른 배분)
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.account_alloc.experiments
"""
import os
import sys
from datetime import date, time

from kiwoom_trading.research.account_alloc import sim as S

OUT = os.path.join(S.OUT, "report.txt")
F = open(OUT, "w", encoding="utf-8")
FRONT = (date(2025, 10, 16), date(2026, 4, 17))
BACK = (S.SPLIT, date(2026, 10, 22))
HI = {"📕", "6️⃣", "2️⃣", "4️⃣", "☕", "5️⃣"}      # 앞 6개월 건당 +0.98~+2.33%
MID = {"1️⃣", "3️⃣", "🌙"}                        # +0.47~+0.71%
LOW = {"🔁"}                                      # +0.32%


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def amt(hi=0.10, mid=0.05, low=0.03, up=0.025):
    a = {k: (hi if k in HI else mid if k in MID else low) for k in S.KINDS}
    a["1️⃣"] = up
    return a


def miss_ratio(r, keys=None):
    sk = r["skip"]
    dup = sk.get("같은 종목 이미 보유(중복)", (0, 0))[0]
    bad = [k for k in sk if k != "같은 종목 이미 보유(중복)" and (keys is None or k in keys)]
    n = sum(sk[k][0] for k in bad)
    return n / max(1, r["sig_n"] - dup), sum(sk[k][1] for k in bad)


def line(lab, r, seed=10_000_000):
    mr, mv = miss_ratio(r)
    return (f"{lab:34s} 최종 {r['final']/1e4:8,.0f}만 ({r['ret']*100:+6.0f}%) 낙폭 {r['mdd']*100:4.1f}% "
            f"앞 {r['front']*100:+5.0f}% 뒤 {r['back']*100:+5.0f}% {'★' if r['star'] else ' '} 못 삼 {mr*100:3.0f}%")


def kinds_line(r):
    return " · ".join(f"{k}{r['pnl_k'].get(k, 0)/1e4:+,.0f}만({r['n_k'].get(k, 0)})" for k in S.KINDS if k in r["n_k"] or k in r["pnl_k"])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    say(f"기간 {S.DAYS[0]} ~ {S.DAYS[-1]} ({len(S.DAYS)}거래일), 앞 {FRONT[0]}~{FRONT[1]} / 뒤 {BACK[0]}~{BACK[1]}")
    say("비용 주식 0.25%·ETF 0.05%, 다음 날 09:00 매도는 그날 아침 현금 복귀, 장중 손절 돈은 그날 다시 안 씀(보수적)\n")

    # ---------------- 0. 단독 확인
    say("[0] 매매별 단독 (100만/건, 기존 보고와 비교)")
    for k in S.KINDS:
        v = [t["ret"] for t in S.T_ALL if t["kind"] == k]
        a = [t["ret"] for t in S.T_ALL if t["kind"] == k and t["date"] < S.SPLIT]
        b = [t["ret"] for t in S.T_ALL if t["kind"] == k and t["date"] >= S.SPLIT]
        say(f"  {S.FULLNAME[k]:16s} {len(v):5d}건 건당 {sum(v)/len(v)*100:+5.2f}% 앞 {sum(a)/max(1,len(a))*100:+5.2f}% 뒤 {sum(b)/max(1,len(b))*100:+5.2f}% 합계 {sum(v)*100:+6,.0f}만")

    # ---------------- A
    say("\n[A] 1천만 지금 모의 배분 그대로 (종목당 100만·6️⃣ 대장 200만/아님 50만·1️⃣ 25만×40·동시 10·7️⃣ 몫 300만, 현금 모자라면 안 삼)")
    A = S.run({})
    say("  " + line("지금 배분", A)); say("  매매별: " + kinds_line(A))
    say("  못 산 이유 (건수 / 기본 금액으로 샀다면 손익):")
    for k, (n, v) in sorted(A["skip"].items(), key=lambda x: -x[1][0]):
        say(f"    {k:22s} {n:5d}건  {v/1e4:+8,.0f}만")
    # 매매별 못 산 비율
    say("  매매별 신호 → 산 것 (산 비율):")
    for k in S.KINDS:
        n = sum(1 for t in S.T_ALL if t["kind"] == k)
        say(f"    {S.FULLNAME[k]:16s} {n:5d} → {A['n_k'].get(k, 0):5d} ({A['n_k'].get(k, 0)/n*100:3.0f}%)")
    Ap = S.run({"partial": True})
    say("  (참고) " + line("현금 있는 만큼이라도 삼", Ap))
    Ar = S.run({"reuse": False})
    say("  (참고) " + line("장중에 판 돈 그날 다시 안 씀", Ar))
    say("  (참고) " + line("동시 한도 없음(현금만)", S.run({"max_pos": 999})))

    # ---------------- B
    say("\n[B] 배분 바꾸기 — 앞 6개월에서 고르고 뒤 6개월로 확인 (각 기간 1천만에서 새로 시작)")
    lim = {"max_pos": 20}
    rsv = (0.40, time(11, 0), {"6️⃣", "📕", "2️⃣"})
    B = [
        ("B0 지금 배분", {}),
        ("B1 모두 50만·한도 20", {"amt": amt(0.05, 0.05, 0.05), **lim}),
        ("B2 기대값 차등 100/50/30만·한도 20", {"amt": amt(), **lim}),
        ("B3 지금 + 🔁·3️⃣ 하루 2종목씩", {"kcap": {"🔁": 2, "3️⃣": 2}}),
        ("B4 지금 + 40% 를 11시까지 6️⃣📕2️⃣ 몫", {"reserve": rsv}),
        ("B5 지금 − 🔁", {"kinds": set(S.KINDS) - {"🔁"}}),
        ("B6 지금 − 🔁·3️⃣", {"kinds": set(S.KINDS) - {"🔁", "3️⃣"}}),
        ("B7 B2 + 30% 11시까지 6️⃣📕2️⃣ 몫", {"amt": amt(), **lim, "reserve": (0.30, time(11, 0), {"6️⃣", "📕", "2️⃣"})}),
        ("B8 B2 + 🔁·3️⃣ 하루 3종목씩", {"amt": amt(), **lim, "kcap": {"🔁": 3, "3️⃣": 3}}),
        ("B9 B2 + 6️⃣ 대장 배수 없음", {"amt": amt(), **lim, "lead": 1.0, "nonlead": 1.0}),
        ("B10 B2 + 1️⃣ 50만×20", {"amt": amt(up=0.05), **lim, "up_max": 20}),
        ("B11 상 150/중 50/하 30만·한도 20", {"amt": amt(0.15, 0.05, 0.03), **lim}),
    ]
    # 아래 둘은 위 결과(D: 7️⃣·🔁·3️⃣ 빼면 좋아짐)를 본 뒤 더한 것 — 고르는 데 결과를 한 번 더 본 셈
    B.append(("B13 B6 − 7️⃣ (+결과 본 뒤)", {"kinds": set(S.KINDS) - {"🔁", "3️⃣", "7️⃣"}}))
    B.append(("B14 B4 + 🔁·3️⃣ 하루 2종목 (+결과 본 뒤)", {"reserve": rsv, "kcap": {"🔁": 2, "3️⃣": 2}}))
    rank = {k: i for i, k in enumerate(sorted(S.KINDS, key=lambda k: -S.ev_front()[k][0]))}
    B.append(("B12 [미래 정보] 기대값 순 채우기", {"order": "ev", "ev_rank": rank}))
    rows = []
    say(f"  {'배분':34s} | 앞 6개월 수익 / 낙폭 | 뒤 6개월 수익 / 낙폭 | 1년 최종 · 낙폭 · ★ · 못 삼")
    for lab, cfg in B:
        f = S.window(cfg, *FRONT); b = S.window(cfg, *BACK); y = S.run(cfg)
        rows.append((lab, cfg, f, b, y))
        say(f"  {lab:34s} | {f['ret']*100:+6.0f}% / {f['mdd']*100:4.1f}% | {b['ret']*100:+6.0f}% / {b['mdd']*100:4.1f}% | "
            f"{y['final']/1e4:6,.0f}만 · {y['mdd']*100:4.1f}% · {'★' if y['star'] else '-'} · {miss_ratio(y)[0]*100:3.0f}%")
    cand = [r for r in rows if "미래" not in r[0]]
    best = max(cand, key=lambda r: r[2]["ret"] / max(r[2]["mdd"], 0.05))   # 앞 6개월: 수익 ÷ 낙폭 이 가장 좋은 것
    best_ret = max(cand, key=lambda r: r[2]["ret"])
    say(f"\n  앞 6개월 '수익÷낙폭' 1등: {best[0]} (앞 {best[2]['ret']*100:+.0f}%/{best[2]['mdd']*100:.1f}% → 뒤 {best[3]['ret']*100:+.0f}%/{best[3]['mdd']*100:.1f}%)")
    say(f"  앞 6개월 수익 1등: {best_ret[0]} (앞 {best_ret[2]['ret']*100:+.0f}% → 뒤 {best_ret[3]['ret']*100:+.0f}%)")
    fr = sorted(cand, key=lambda r: -r[2]["ret"]); bk = sorted(cand, key=lambda r: -r[3]["ret"])
    say("  앞 순위 → 뒤 순위: " + ", ".join(f"{r[0].split()[0]} {i+1}→{[x[0] for x in bk].index(r[0])+1}" for i, r in enumerate(fr)))
    say("  고른 배분 1년 매매별: " + kinds_line(best[4]))
    say("  지금 배분 1년 매매별: " + kinds_line(A))
    chosen = best[1]

    # ---------------- C
    say("\n[C] 실전 시드별 1년 (정수 주, 지정가 = 가격 +1% 호가 올림, 1주 값 > 쓸 돈이면 다음 신호, 복리)")
    say("  지금 실전 = 1️⃣6️⃣2️⃣5️⃣📕🔁☕ 중 그날 먼저 산 1종목 전액(1️⃣ 먼저면 1️⃣ 만 4종목 ×1/4). 주문 20만 상한(REAL_MAX_ORDER)은 뺐다(넣은 줄 따로).")
    real = {"real": True, "integer": True, "kinds": S.REAL_KINDS, "partial": True}
    rules = [
        ("지금 실전 (하루 1종목)", real),
        ("지금 실전 + 20만 상한", {**real, "cap": 200_000}),
        ("하루 2종목 (각 1/2)", {**real, "slots": 2}),
        ("하루 3종목 (각 1/3)", {**real, "slots": 3}),
        ("실전 7종 − 🔁 (하루 1종목)", {**real, "kinds": S.REAL_KINDS - {"🔁"}}),
        ("실전 7종 − 🔁 · 하루 2종목", {**real, "kinds": S.REAL_KINDS - {"🔁"}, "slots": 2}),
        ("실전 7종 − 🔁 · 하루 3종목", {**real, "kinds": S.REAL_KINDS - {"🔁"}, "slots": 3}),
        (f"B 고른 배분 ({best[0].split()[0]}, 정수 주)", {**chosen, "integer": True}),
    ]
    say(f"  {'규칙':30s} {'시드':>6s} | 최종 · 수익률 · 낙폭 · 앞/뒤 반기 · 산 건수 · 못 삼(1주 비쌈 / 그 밖 돈·한도)")
    for lab, cfg in rules:
        for seed in (100_000, 300_000, 500_000, 1_000_000, 3_000_000):
            r = S.run(cfg, seed=seed)
            sk = r["skip"]; dup = sk.get("같은 종목 이미 보유(중복)", (0, 0))[0]; base = r["sig_n"] - dup
            exp = sk.get("1주 값 > 종목당 금액", (0, 0))[0]
            oth = sum(v[0] for k, v in sk.items() if k not in ("같은 종목 이미 보유(중복)", "1주 값 > 종목당 금액"))
            say(f"  {lab:30s} {seed/1e4:5,.0f}만 | {r['final']/1e4:8,.1f}만 · {r['ret']*100:+6.0f}% · {r['mdd']*100:4.1f}% · "
                f"{r['front']*100:+5.0f}/{r['back']*100:+5.0f}% · {sum(r['n_k'].values()):4d}건 · {exp/base*100:3.0f}% / {oth/base*100:3.0f}%")
        say("")
    r = S.run(real, seed=100_000)
    say("  지금 실전 10만 매매별: " + kinds_line(r))
    say("  지금 실전 10만 못 산 이유: " + ", ".join(f"{k} {v[0]}" for k, v in sorted(r["skip"].items(), key=lambda x: -x[1][0])))

    # ---------------- D
    for lab, cfg in (("지금 배분(A)", {}), (f"고른 배분({best[0].split()[0]})", chosen), ("지금 실전 10만", {**real, "_seed": 100_000})):
        seed = cfg.pop("_seed", 10_000_000) if "_seed" in cfg else 10_000_000
        base = S.run(cfg, seed=seed)
        say(f"\n[D] 매매 하나씩 빼기 — {lab}: 기준 최종 {base['final']/1e4:,.1f}만 낙폭 {base['mdd']*100:.1f}%")
        ks = cfg.get("kinds", set(S.KINDS))
        for k in S.KINDS:
            if k not in ks: continue
            r = S.run({**cfg, "kinds": set(ks) - {k}}, seed=seed)
            f = S.window({**cfg, "kinds": set(ks) - {k}}, *FRONT, seed=seed); f0 = S.window(cfg, *FRONT, seed=seed)
            b = S.window({**cfg, "kinds": set(ks) - {k}}, *BACK, seed=seed); b0 = S.window(cfg, *BACK, seed=seed)
            say(f"  − {S.FULLNAME[k]:16s} 최종 {r['final']/1e4:8,.1f}만 ({(r['final']/base['final']-1)*100:+5.1f}%) 낙폭 {r['mdd']*100:4.1f}% "
                f"| 앞 {(f['final']/f0['final']-1)*100:+5.1f}% 뒤 {(b['final']/b0['final']-1)*100:+5.1f}%"
                + ("  ← 빼면 좋아짐" if r["final"] > base["final"] else ""))
    # ---------------- E 견고성
    say("\n[E] 견고성 — 장중에 판 돈 그날 다시 안 씀 / 정수 주 / 건당 추가 미끄러짐 0.3%·0.5%")
    nr = {**real, "kinds": S.REAL_KINDS - {"🔁"}}
    for lab, cfg, seed in (("B0 지금 배분", {}, 10_000_000), ("B4 11시 몫", {"reserve": rsv}, 10_000_000), ("B6 − 🔁·3️⃣", chosen, 10_000_000),
                           ("지금 실전", real, 300_000), ("실전 − 🔁 1종목", nr, 300_000), ("실전 − 🔁 3종목", {**nr, "slots": 3}, 300_000),
                           ("B6 정수 주", {**chosen, "integer": True}, 1_000_000)):
        parts = []
        for nm, extra in (("기본", {}), ("재사용 안 함", {"reuse": False}), ("정수 주", {"integer": True}), ("+0.3%", {"slip": 0.003}), ("+0.5%", {"slip": 0.005})):
            r = S.run({**cfg, **extra}, seed=seed)
            parts.append(f"{nm} {r['final']/1e4:,.0f}만/{r['mdd']*100:.0f}%")
        say(f"  {lab:14s} 시드 {seed/1e4:,.0f}만: " + " · ".join(parts))
    F.close()


if __name__ == "__main__":
    main()
