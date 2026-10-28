"""매수 신호 탐색 3단계: '아침 특징 → 종가 매수 → 다음 날 09:00' (Lc) 후보 뜯어보기 (2026-10-28).

search.py 에서 릿지(Lc) 아침 시각 상위 k 가 B 기간 ★ → 진짜인지 확인:
  1) 모델 계수 (어떤 특징이 끄는지)  2) 이상값 빼고·중앙값·월별  3) 섞은 라벨 100번 (시각 묶음 전체 최대값 기준)
  4) 사람이 읽을 단순 규칙으로 바꿔 A·B·롤링  5) 기존 매매(1️⃣ 장 초 · 종가 계열 · ⑥ 신고가)와 겹침
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/signal_search/deep_lc.py → data/signal_search/deep_lc.txt
"""
import os, sys, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import search as S

F = None


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(S.OUT, "deep_lc.txt"), "w", encoding="utf-8")
    df, feats, days = S.load()
    A, B = (df.half == 0).values, (df.half == 1).values
    Ts = ["09:05", "09:10", "09:15", "09:20", "09:30", "10:00", "10:30", "11:00", "13:00", "14:30", "15:20"]
    lab = "Lc"
    say(f"Lc = 그날 15:30 종가 매수 → 다음 날 09:00 시가, 비용 0.25% 뺀 값. 상위 100 평균 A {df[A].Lc.mean():+.2%} B {df[B].Lc.mean():+.2%}")
    q = df.Lc.quantile([0.001, 0.01, 0.5, 0.99, 0.999]); say("Lc 분포 " + " ".join(f"{k:.3f}:{v:+.2%}" for k, v in q.items()))

    # 1) 계수
    res = S.ridge_eval(df, feats, lab, A, B, Ts, ks=(1, 3, 5))
    R, Mk = S.prep_X(df, feats)
    cols = list(R.columns) + S.MKT
    say("\n[1] 시각별 릿지 계수 (단면 백분위 −0.5~0.5 기준, 큰 순 8개)")
    for T in Ts:
        if (T, "w") not in res: continue
        w, L = res[(T, "w")]
        o = np.argsort(-np.abs(w[:-1]))[:8]
        say(f"  {T} λ={L:g}: " + ", ".join(f"{cols[i]} {w[i] * 100:+.2f}" for i in o))

    # 2) 이상값·중앙값·월별
    say("\n[2] B 기간 상위 3: 건당·중앙값·±15% 넘는 것 뺀 평균·승률 / 월별 건당 (기준 = 상위 100 평균)")
    for T in Ts:
        if (T, 3, "모두") not in res: continue
        t = res[(T, 3, "모두")]; base = res[(T, 0, "평균")]
        tt = t[t.ret.abs() < 0.15]
        m = t.assign(m=pd.to_datetime(t.date).dt.to_period("M")).groupby("m").ret.mean()
        mb = base.assign(m=pd.to_datetime(base.date).dt.to_period("M")).groupby("m").ret.mean()
        say(f"  {T} {t.ret.mean():+.2%} 중앙 {t.ret.median():+.2%} 이상값 빼 {tt.ret.mean():+.2%} 승률 {np.mean(t.ret > 0):.0%} | "
            + " ".join(f"{str(k)[2:]} {v:+.1%}/{mb[k]:+.1%}" for k, v in m.items()))

    # 3) 섞은 라벨 100번 — 시각 6개(09:05~10:00) 상위 3 B 평균의 최대값 / 평균
    say("\n[3] 우연 기준선: A 라벨 섞고 릿지 (λ=1000) 100번. 아침 6개 시각 상위 3 의 B 평균 — 6개 평균·최대값 분포")
    T6 = Ts[:6]
    realv = np.array([res[(T, 3, "모두")].ret.mean() for T in T6])
    nm, nx = [], []
    for it in range(100):
        r = S.ridge_eval(df, feats, lab, A, B, T6, ks=(3,), perm=True, lam=1000.0)
        v = np.array([r[(T, 3, "모두")].ret.mean() for T in T6]); nm.append(v.mean()); nx.append(v.max())
    nm, nx = np.array(nm), np.array(nx)
    say(f"  실제 6개 평균 {realv.mean():+.2%} · 최대 {realv.max():+.2%}")
    say(f"  섞음 6개 평균: 중앙 {np.median(nm):+.2%} 95% {np.quantile(nm, 0.95):+.2%} 99% {np.quantile(nm, 0.99):+.2%} → 실제보다 큰 비율 {np.mean(nm >= realv.mean()):.0%}")
    say(f"  섞음 최대값: 중앙 {np.median(nx):+.2%} 95% {np.quantile(nx, 0.95):+.2%} → 실제 최대보다 큰 비율 {np.mean(nx >= realv.max()):.0%}")
    pickle.dump(res, open(os.path.join(S.OUT, "ridge_lc.pkl"), "wb"))


if __name__ == "__main__":
    main()
