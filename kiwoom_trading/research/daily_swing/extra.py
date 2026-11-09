"""일봉 스윙 3단계: S5_250(250일 신고가) 뜯어보기 — ⑦ 과 겹침, 순위·수급 나눔, 손절·기간 없음, 동시 보유 수, 약세장 기간.
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/daily_swing/extra.py → data/daily_swing/extra.txt"""
import os, sys
from collections import defaultdict
from datetime import date
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import bt as B

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    B.F = open(os.path.join(B.OUT, "extra.txt"), "w", encoding="utf-8"); say = B.say
    # 약세장 기간
    bear = sorted(d for d, v in B.REG_DD.items() if "밖" in v and B.W0 <= d <= date(2026, 10, 29))
    say(f"코스피 52주 고점 −10% 밖 날: {len(bear)}일, 처음 {bear[0] if bear else '-'} 끝 {bear[-1] if bear else '-'}")
    runs = []; prev = None
    for d in bear:
        if prev is None or B.DI[d] != B.DI[prev] + 1: runs.append([d, d])
        else: runs[-1][1] = d
        prev = d
    say("  구간: " + ", ".join(f"{a}~{b}" for a, b in runs))
    S = B.SET_D["S5_250일신고가"]
    with np.errstate(invalid="ignore"):
        flow = (B.FOR > 0) & (B.INS > 0); r5 = B.RANK <= 5; r20 = B.RANK <= 20
    sig7 = S & r5 & flow
    nd = sum(1 for d in B.dts if B.W0 <= d <= B.W1)
    for mode in ("open", "close"):
        say(f"\n=== 매수 {mode} — 250일 신고가 & 대금 20위 나눠 보기")
        for nm, sig in (("20위 전체", S & r20), ("1~5위", S & r5), ("6~20위", S & r20 & ~r5),
                        ("외인·기관 둘 다 +", S & r20 & flow), ("둘 다 + 아님", S & r20 & ~flow),
                        ("⑦ 신호 뺀 20위", S & r20 & ~sig7), ("⑦ 신호(5위·양매수)", sig7)):
            for (x, st, mh) in ((20, 0.10, 20), (20, None, 20), (20, 0.10, 10 ** 6), (20, None, 10 ** 6), (5, 0.10, 20)):
                tr, _ = B.run(sig, mode, x, st, None, maxhold=mh)
                s = B.stats(tr)
                conc = sum(t["hold"] for t in tr) / max(1, sum(1 for d in B.dts if date(2025, 8, 6) <= d <= B.W1))
                say(B.line(f"{nm}·{x}선·손절{int(st * 100) if st else '없음'}·기간{'20' if mh == 20 else '없음'}", s, 44)
                    + (f"  평균 동시 {conc:.1f}종목" if not s.get("few") else ""))
    # 월별 (시가 매수 20위·20선·손절10)
    tr, _ = B.run(S & r20, "open", 20, 0.10, None)
    df = pd.DataFrame(tr); df["m"] = pd.to_datetime(df.d).dt.to_period("M")
    say("\n월별 (250일 신고가·20위·20선·손절10·시가): " + "  ".join(f"{m}:{g.ret.sum()*100:+.0f}만({len(g)})" for m, g in df.groupby("m")))
    df.to_csv(os.path.join(B.OUT, "trades_S5_250_a_X20_10_open.csv"), index=False, encoding="utf-8-sig")
    say("가장 큰 수익 5건: " + "; ".join(f"{r.d} {r.code} {r.ret:+.0%}" for r in df.nlargest(5, 'ret').itertuples()))
    say(f"종목 수 {df.code.nunique()}, 상위 3종목 합계 몫 " + ", ".join(f"{c}:{v*100:+.0f}만" for c, v in df.groupby('code').ret.sum().nlargest(3).items()))
    say(f"상위 3종목 빼면 합계 {(df.ret.sum() - df.groupby('code').ret.sum().nlargest(3).sum())*100:+.0f}만 / {len(df)}건")

main()
