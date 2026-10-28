"""매수 신호 탐색 4단계: 미리 정한 가설 시험 + 계좌 형태 평가 + 기존 매매와 겹침 (2026-10-28).

가설 (결과 보기 전에 정함, 시도 수 적게):
  H0 선별 힘 vs 절대 수익: 릿지(A 학습)가 고른 상위 3 이 B 에서 '상위 100 평균'보다 얼마나 나은지 · 그래도 + 인지 · 날 분위기별
  Ha 연속성: 장중 라벨(L1s6) 모델이 아침에 고른 종목을 그날 종가에 사서 다음 날 09:00 (Lc)
       + 단순 규칙판: T 시각 '그날 상위 100 안 상승률 상위 10%·당일 고가 −2% 안' 종목을 종가 매수 → 다음 날 09:00
  Hb 조기판: 같은 모델의 시각별 성적 (09:05→14:30) 과 '나중 강한 종목'을 이른 시각에 몇 % 잡았나
  Hc 후행주: 같은 테마 다른 종목 ≥2 개가 +5%↑ 이고 가장 많이 오른 것 ≥ +10% 인데 자기는 0~+4% (덜 오름) → T 봉 시가 매수
계좌 = 1천만/일, 그날 건수로 나눔 · ★ = 기간 앞·뒤 반 모두 + & 최고 5일 빼도 +.
겹침: 1️⃣(U 날 09:10 대금 40위·시가 위) · ⑥(U/N+ 52주 신고가 & 그 시각 대금 10위) · 종가(14:30 대금 10위·52주 신고가) · 종가배팅(15:20 대금 10위·상승).
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/signal_search/hypo.py → data/signal_search/hypo.txt
"""
import os, sys, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import search as S
from kiwoom_trading.backtest.playbook.build_regime import cls_of

F = None
FEAT = pickle.load(open(os.path.join(S.DATA, "backtest", "playbook_rebuilt", "regime_feat.pkl"), "rb"))


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


def overlaps(df):
    d = df
    o1 = d[(d.cls == "U") & (d["T"] == "09:10") & (d["rank"] <= 40) & (d.ret_open > 0)]
    o6 = d[(d.hi250d >= 0) & (d["rank"] <= 10) & d.cls.isin(["U", "N+"])]
    oc = d[(d["T"] == "14:30") & (d["rank"] <= 10) & (d.hi250d >= 0)]
    ob = d[(d["T"] == "15:20") & (d["rank"] <= 10) & (d.ret_pc > 0)]
    key = lambda x: set(zip(x.date, x.code))
    return {"1️⃣": key(o1), "⑥": key(o6), "종가14:30": key(oc), "종가배팅": key(ob)}


def ov_text(tr, OV):
    k = list(zip(tr.date, tr.code))
    allk = set().union(*OV.values())
    parts = [f"{nm} {np.mean([x in s for x in k]):.0%}" for nm, s in OV.items()]
    rest = tr[[x not in allk for x in k]]
    s = S.acct(rest)
    return "겹침 " + " ".join(parts) + f" | 안 겹치는 몫 {len(rest)}건 " + (f"{s['mean']:+.2%} 합계 {s['tot']:+.0f}만" if s else "")


def show(name, tr, OV=None):
    s = S.acct(tr)
    say(f"  {name:46s} {S.fmt(s)}")
    if OV is not None and s: say(f"  {'':46s} {ov_text(tr, OV)}")
    return s


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(S.OUT, "hypo.txt"), "w", encoding="utf-8")
    df, feats, days = S.load()
    df["cls"] = df.date.dt.date.map(lambda d: cls_of(FEAT[d]) if d in FEAT else None)
    A, B = (df.half == 0).values, (df.half == 1).values
    OV = overlaps(df)
    Ts = ["09:05", "09:10", "09:15", "09:20", "09:30", "10:00", "10:30", "11:00", "13:00", "14:30"]
    say(f"B 기간 = {df[B].date.min().date()} ~ {df[B].date.max().date()} ({df[B].date.nunique()}일), 날 분위기 B: "
        + " ".join(f"{k} {v}" for k, v in df[B].groupby("cls").date.nunique().items()))

    # ---------------- H0
    say("\n" + "=" * 150)
    say("[H0] 선별 힘 vs 절대 수익 — 릿지 A 학습, B 상위 3. '나음' = 상위 3 − 상위 100 평균 (선별 힘). 날 분위기는 09:10 판정(09:15 이후 시각만 해당).")
    H0 = {}
    for lab in ("L1s6", "L2"):
        res = S.ridge_eval(df, feats, lab, A, B, Ts, ks=(3,))
        H0[lab] = res
        say(f"\n  라벨 {lab}")
        for T in Ts:
            t = res[(T, 3, "모두")].merge(df[["date", "code", "T", "cls"]][df["T"] == T], on=["date", "code"])
            b = res[(T, 0, "평균")].merge(df[["date", "code", "T", "cls"]][df["T"] == T], on=["date", "code"])
            line = f"    {T} 상위3 {t.ret.mean():+.2%} 기준 {b.ret.mean():+.2%} 나음 {t.ret.mean() - b.ret.mean():+.2%}p |"
            for c in ("U", "N+", "N-", "D"):
                tc, bc = t[t.cls == c], b[b.cls == c]
                if len(tc): line += f" {c} {tc.ret.mean():+.2%}/{bc.ret.mean():+.2%}({len(tc)})"
            say(line)

    # ---------------- Ha 연속성
    say("\n" + "=" * 150)
    say("[Ha] 연속성 — 장중 모델(L1s6, A 학습)이 T 시각에 고른 상위 3 을 그날 15:30 종가에 사서 다음 날 09:00 (Lc). 같은 종목을 T 봉에 샀을 때(L1s6)와 비교")
    res = H0["L1s6"]
    for T in Ts:
        t = res[(T, 3, "모두")][["date", "code"]].merge(df[df["T"] == T][["date", "code", "Lc", "L1s6", "rclose"]], on=["date", "code"])
        s = S.acct(t.assign(ret=t.Lc))
        say(f"   {T} 종가→다음날 {S.fmt(s)} | 같은 종목 T 매수→15:19 {t.L1s6.mean():+.2%} · T→종가 원값 {t.rclose.mean():+.2%}")
    say("\n  단순 규칙판 (A·B 모두 표시): T 시각 상위 100 안 상승률(전일 대비) 상위 10% & 당일 고가 −2% 안 → 그날 종가 매수 → 다음 날 09:00")
    for T in Ts + ["15:20"]:
        d = df[df["T"] == T].copy()
        d["q"] = d.groupby("grp").ret_pc.rank(pct=True)
        m = (d.q >= 0.9) & (d.dhi >= -0.02)
        tr = d[m].drop_duplicates(["date", "code"])
        sa, sb = S.acct(tr[tr.half == 0].assign(ret=tr.Lc)), S.acct(tr[tr.half == 1].assign(ret=tr.Lc))
        say(f"   {T} A {S.fmt(sa)}")
        say(f"   {'':5s} B {S.fmt(sb)}")
    say("  같은 규칙, B 기간 날 분위기별 (종가 매수라 날 분위기는 다 앎):")
    for T in ("10:00", "14:30", "15:20"):
        d = df[(df["T"] == T) & B].copy(); d["q"] = d.groupby("grp").ret_pc.rank(pct=True)
        tr = d[(d.q >= 0.9) & (d.dhi >= -0.02)]
        say(f"   {T} " + " | ".join(f"{c} {tr[tr.cls == c].Lc.mean():+.2%}({len(tr[tr.cls == c])})" for c in ("U", "N+", "N-", "D")))

    # ---------------- Hb 조기판
    say("\n" + "=" * 150)
    say("[Hb] 조기판 — 그날 '나중에 강한 종목'(14:30 에 상위 100 안 상승률 상위 10% & 고가 −2% 안)을 이른 시각 모델 상위 3/10 이 미리 잡은 비율과, 그 잡은 것의 결과 (B)")
    d14 = df[(df["T"] == "14:30")].copy(); d14["q"] = d14.groupby("grp").ret_pc.rank(pct=True)
    strong = set(zip(*d14[(d14.q >= 0.9) & (d14.dhi >= -0.02) & (d14.half == 1)][["date", "code"]].values.T))
    for T in Ts[:7]:
        r10 = S.ridge_eval(df, feats, "L1s6", A, B, [T], ks=(3, 10))
        for k in (3, 10):
            t = r10[(T, k, "모두")]
            hit = [x in strong for x in zip(t.date.dt.date if hasattr(t.date, "dt") else t.date, t.code)]
            kk = set(zip(pd.to_datetime(t.date), t.code)); st2 = {(pd.Timestamp(a), b) for a, b in strong}
            cap = len(kk & st2) / max(len(st2), 1)
            tt = t[[x in st2 for x in zip(pd.to_datetime(t.date), t.code)]]
            say(f"   {T} 상위{k:2d}: 나중 강한 종목 {len(st2)}개 중 미리 잡음 {cap:.0%} · 고른 것 중 적중 {len(tt) / max(len(t), 1):.0%} · "
                f"고른 것 전체 L1s6 {t.ret.mean():+.2%} (적중분 {tt.ret.mean():+.2%})")

    # ---------------- Hc 후행주
    say("\n" + "=" * 150)
    say("[Hc] 테마 후행주 — 같은 네이버 테마 다른 종목 ≥2개 +5%↑ (상위 100 안) & 그 중 최고 ≥ +10%, 자기는 전일 대비 0~+4% → T 봉 시가 매수")
    say("     (테마 목록은 지금 기준 → 과거에 없던 테마가 섞임, 근사)")
    for T in ("09:10", "09:30", "10:00", "10:30", "11:00", "13:00"):
        d = df[(df["T"] == T) & (df.th_n5 >= 2) & (df.th_best >= 0.10) & (df.ret_pc >= 0) & (df.ret_pc <= 0.04)]
        for lab in ("L1s6", "L2", "Lc"):
            sa = S.acct(d[d.half == 0].assign(ret=d[lab]).dropna(subset=["ret"]))
            sb = S.acct(d[d.half == 1].assign(ret=d[lab]).dropna(subset=["ret"]))
            say(f"   {T} {lab:4s} A {S.fmt(sa)}")
            say(f"   {'':5s} {'':4s} B {S.fmt(sb)}")
        base = df[(df["T"] == T) & B]
        say(f"   {T} 기준(상위 100 전체 B) L1s6 {base.L1s6.mean():+.2%} L2 {base.L2.mean():+.2%} Lc {base.Lc.mean():+.2%}")
    say("  대장(테마 안 상승률 1등 & +10%↑) 비교:")
    for T in ("09:30", "10:00", "11:00"):
        d = df[(df["T"] == T) & (df.th_lead == 1) & (df.ret_pc >= 0.10)]
        say(f"   {T} 대장 B L1s6 {d[d.half == 1].L1s6.mean():+.2%} L2 {d[d.half == 1].L2.mean():+.2%} Lc {d[d.half == 1].Lc.mean():+.2%} ({(d.half == 1).sum()}건)")

    # ---------------- 계좌 형태: search 에서 B 가 좋았던 후보
    say("\n" + "=" * 150)
    say("[계좌] 후보를 실제 매매 형태로 (B 기간, 1천만/일) + 기존 매매와 겹침")
    rl = pickle.load(open(os.path.join(S.OUT, "ridge_lc.pkl"), "rb")) if os.path.exists(os.path.join(S.OUT, "ridge_lc.pkl")) else None
    if rl:
        for T in ("09:15", "09:20", "09:30", "10:00"):
            t = rl[(T, 3, "모두")]
            show(f"릿지 Lc {T} 상위3 → 종가 매수·다음 날 09:00", t, OV)
    for lab, T in (("L2", "09:15"), ("L2", "09:20"), ("L2", "10:00"), ("L1s6", "09:05")):
        r = S.ridge_eval(df, feats, lab, A, B, [T], ks=(1, 3))
        for k in (1, 3):
            show(f"릿지 {lab} {T} 상위{k} 예측>0", r[(T, k, "예측>0")], OV)


if __name__ == "__main__":
    main()
