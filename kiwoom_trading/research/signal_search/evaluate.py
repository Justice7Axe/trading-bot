"""매수 신호 탐색 5단계: 남은 후보를 매매 형태로 1년·A/B·분기·날 분위기·겹침까지 (2026-10-28).

후보 (search·hypo 결과에서 B 가 + 였던 것만, 모두 '많이 시도한 것 중 고른 것'):
  C1 아침 60일 고가 근처 + 전날 저가권 마감: 09:05 에 대금 상위 100 & 가격 ≥ 60일 고가 −3.3% & 전날 종가가 전날 고저 범위 아래 20% 안
     → 09:05 봉 시가 매수, −6% 손절, 아니면 다음 날 09:00 (L2)   [M1 규칙 탐색 L2 09:05 1위]
  C2 아침 강세 → 종가 매수: T 시각 상위 100 안 상승률 상위 10% & 당일 고가 −2% 안 → 그날 종가(15:30) 매수 → 다음 날 09:00 (Lc, 상한가 마감 제외)
  C3 릿지(Lc) 아침 모델 상위 3 → 종가 매수 → 다음 날 09:00
  C4 테마 후행주 10:30 → 종가 매수 → 다음 날 09:00
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/signal_search/evaluate.py → data/signal_search/evaluate.txt
"""
import os, sys, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import search as S
import hypo as H
from kiwoom_trading.backtest.playbook.build_regime import cls_of

F = None


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


def block(name, tr, OV):
    tr = tr[tr.ret.notna()].drop_duplicates(["date", "code"])
    say(f"\n  ■ {name}")
    for nm, part in (("1년", tr), ("A 앞 반", tr[tr.half == 0]), ("B 뒤 반", tr[tr.half == 1])):
        say(f"    {nm:7s} {S.fmt(S.acct(part))}")
    q = tr.groupby("qtr").ret.agg(["mean", "count"])
    say("    분기 " + " | ".join(f"Q{k + 1} {r['mean']:+.2%}({int(r['count'])})" for k, r in q.iterrows())
        + " · 중앙값 " + f"{tr.ret.median():+.2%}" + f" · ±15% 넘는 것 뺀 평균 {tr[tr.ret.abs() < 0.15].ret.mean():+.2%}")
    say("    날 분위기 " + " | ".join(f"{c} {tr[tr.cls == c].ret.mean():+.2%}({(tr.cls == c).sum()})" for c in ("U", "N+", "N-", "D")))
    say("    하루 건수 평균 " + f"{tr.groupby('date').size().mean():.1f} · 신호 난 날 {tr.date.nunique()}일")
    say("    B " + H.ov_text(tr[tr.half == 1], OV))


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(S.OUT, "evaluate.txt"), "w", encoding="utf-8")
    df, feats, days = S.load()
    df["cls"] = df.date.dt.date.map(lambda d: cls_of(H.FEAT[d]) if d in H.FEAT else None)
    OV = H.overlaps(df)
    say("후보 신호 매매 형태 평가 — 1천만/일 (그날 건수로 나눔), 비용 0.25%, ★ = 그 기간 앞·뒤 반 + & 최고 5일 빼도 +")

    d = df[(df["T"] == "09:05") & (df.hi60d >= -0.033) & (df.prev_pos <= 0.2)]
    block("C1 09:05 60일 고가 −3.3% 안 & 전날 저가권 마감(하위 20%) → 09:05 시가, −6%, 다음 날 09:00", d.assign(ret=d.L2), OV)
    d = df[(df["T"] == "09:05") & (df.hi60d >= -0.033) & (df.prev_pos <= 0.2) & (df.gap < 0.10)]
    block("C1' 위 + 시가 갭 +10% 미만", d.assign(ret=d.L2), OV)

    for T in ("09:15", "10:00"):
        x = df[df["T"] == T].copy(); x["q"] = x.groupby("grp").ret_pc.rank(pct=True)
        d = x[(x.q >= 0.9) & (x.dhi >= -0.02)]
        block(f"C2 {T} 상승률 상위 10% & 고가 −2% 안 → 종가 매수 → 다음 날 09:00 (상한가 마감 제외)", d.assign(ret=d.Lc), OV)

    rl = pickle.load(open(os.path.join(S.OUT, "ridge_lc.pkl"), "rb"))
    for T in ("09:15", "09:20"):
        t = rl[(T, 3, "모두")].merge(df[df["T"] == T][["date", "code", "half", "qtr", "cls"]], on=["date", "code"])
        block(f"C3 릿지 Lc {T} 상위 3 → 종가 매수 → 다음 날 09:00 (A 학습이라 B 만 의미)", t, OV)

    d = df[(df["T"] == "10:30") & (df.th_n5 >= 2) & (df.th_best >= 0.10) & (df.ret_pc >= 0) & (df.ret_pc <= 0.04)]
    block("C4 10:30 테마 후행주 → 종가 매수 → 다음 날 09:00", d.assign(ret=d.Lc), OV)

    # 유니버스 점검: 전날 대금 200 안 종목만 (그날 대금 200 으로 들어온 종목 = 미래 정보 선택)
    say("\n  [유니버스 점검] 전날 대금 200 안 종목만 / 그날 대금으로만 들어온 종목 (A | B 건당)")
    x = df[df["T"] == "10:00"].copy(); x["q"] = x.groupby("grp").ret_pc.rank(pct=True)
    for nm, d, lab in (("C2 10:00", x[(x.q >= 0.9) & (x.dhi >= -0.02)], "Lc"),
                       ("C4 10:30", df[(df["T"] == "10:30") & (df.th_n5 >= 2) & (df.th_best >= 0.10) & (df.ret_pc >= 0) & (df.ret_pc <= 0.04)], "Lc"),
                       ("C1 09:05", df[(df["T"] == "09:05") & (df.hi60d >= -0.033) & (df.prev_pos <= 0.2)], "L2")):
        for u, uu in (("전날200", d[d.in_prev200 == 1]), ("그날만", d[d.in_prev200 == 0])):
            say(f"    {nm} {u:6s} A {uu[uu.half == 0][lab].mean():+.2%}({(uu.half == 0).sum()}) | B {uu[uu.half == 1][lab].mean():+.2%}({(uu.half == 1).sum()})")
    # C4 민감도: 자기 상승률과 무관하게 '뜨거운 테마 소속'이면 비슷한지
    say("\n  [C4 민감도] 테마 조건(다른 종목 +5%↑ 수 n, 최고 b) × 자기 상승률 구간 → Lc B 건당 (A 건당) [B 건수]")
    for T in ("09:30", "10:30", "11:00", "13:00"):
        parts = []
        for n5, best, lo, hi in ((1, 0.05, 0, 0.04), (2, 0.10, 0, 0.04), (3, 0.10, 0, 0.04), (2, 0.10, 0.04, 0.10), (2, 0.10, 0.10, 0.29), (0, -9, -1, 1)):
            d = df[(df["T"] == T) & (df.th_n5 >= n5) & (df.th_best >= best) & (df.ret_pc >= lo) & (df.ret_pc <= hi)]
            parts.append(f"n{n5}·b{best:g}·자기{lo:g}~{hi:g} {d[d.half == 1].Lc.mean():+.2%}({d[d.half == 0].Lc.mean():+.2%})[{(d.half == 1).sum()}]")
        say(f"    {T} " + " | ".join(parts))
    d = df[(df["T"] == "10:30") & (df.th_n5 >= 2) & (df.th_best >= 0.10) & (df.ret_pc >= 0) & (df.ret_pc <= 0.04)]
    say("    C4 월별 " + " ".join(f"{str(k)[2:]} {v:+.2%}" for k, v in d.assign(m=d.date.dt.to_period("M")).groupby("m").Lc.mean().items()))
    say(f"    C4 강한 하락장(D) 빼면 A {d[(d.cls != 'D') & (d.half == 0)].Lc.mean():+.2%} B {d[(d.cls != 'D') & (d.half == 1)].Lc.mean():+.2%}")

    say("\n  참고 — 기존 매매 근사치 (같은 자료): ")
    o = df[(df.cls == "U") & (df["T"] == "09:10") & (df["rank"] <= 40) & (df.ret_open > 0)]
    block("1️⃣ 근사: U 날 09:10 대금 40위·시가 위 → 09:10 시가, −6%, 다음 날 09:00", o.assign(ret=o.L2), OV)


if __name__ == "__main__":
    main()
