"""상승 직전 찾기 4 — 체결 단위 프로그램 수급(program_tick, ka90008) + 1분봉 (2026-11-01 사용자 '시장 흐름과 상관없이 대금·수급이 몰리는 것을 일찍').

질문: 가격이 아직 덜 오른(전일 대비 −5~+5%, 최근 10분 ±1.5% 안) 종목에 프로그램 순매수가 먼저 몰리면 그 뒤 오르나? 시장 분위기와 상관없이?
표본: 날짜 D, 전날 대금 300위(우선주 제외) ∩ program_tick 있음 ∩ 1분봉 있음. 시점 09:10~14:30 5분마다, 그 분 전에 끝난 봉·체결만 씀.
특징: 프로그램 순매수 누적 ÷ 누적 대금(pg_r), 최근 5·15분 순매수 ÷ 그 사이 대금(pg5·pg15), 프로그램 매수 비중 증가, 대금 가속(acc5), 가격 변화.
결과: 다음 봉 시가 매수 → 60분 안 +5% 가 −2% 보다 먼저(y), 기대 손익 근사(edge), 실제 매도(+5/−2 → 다음 날 09:00).
시장 분위기: 그 시점 표본 전체 시가 대비 중앙값(mkt) 으로 강·약 나눠 따로 봄.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/early_rise/program_early.py
판단은 약 20거래일 쌓인 뒤 (2026-11-28 무렵).
"""
import os, sys
from datetime import time
import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "early_rise")
TOPN, HZ, UP, DN = 300, 60, 0.05, 0.02
SNAP = [time(h, m) for h in range(9, 15) for m in range(0, 60, 5) if time(9, 10) <= time(h, m) <= time(14, 30)]


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep("program_report.txt")


def auc(y, s):
    m = ~np.isnan(s); y, s = y[m], s[m]
    if y.sum() == 0 or y.sum() == len(y): return np.nan
    r = pd.Series(s).rank().values
    return (r[y == 1].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (len(y) - y.sum()))


def build():
    P = duckdb.connect(os.path.join(E.DATA, "program_tick.duckdb"), read_only=True)
    days = [d for (d,) in P.execute("SELECT DISTINCT date FROM program_tick_done ORDER BY 1").fetchall() if d in E.CIDX]
    rows = []
    for d in days:
        pdv = E.value_rank(E.prev_day(d))
        prev = sorted((c for c in pdv if E.is_common(c)), key=lambda c: pdv[c])[:TOPN]
        have = {c for (c,) in P.execute("SELECT code FROM program_tick_done WHERE date=? AND rows>0", [d]).fetchall()}
        codes = [c for c in prev if c in have and c in E._min_codes(d)]
        if not codes: continue
        tick = pd.DataFrame(P.execute(f"""SELECT code, tm, buy_amt, sell_amt, net_amt FROM program_tick WHERE date=? AND exchange='KRX'
                                AND tm BETWEEN '09:00:00' AND '15:30:00' AND code IN ({','.join('?' * len(codes))})""", [d, *codes]).fetchall(),
                            columns=["code", "tm", "buy", "sell", "net"])
        B = E.load_day(codes, d); pr = E.daily_day(E.prev_day(d))
        for c, g in tick.groupby("code"):
            b = E.regular(B[c])
            if len(b) < 300: continue
            f = E.factor(c, d)
            if not f or c not in pr: continue
            pc = pr[c][3] * f
            g = g.sort_values("tm")
            gt = g.tm.values; gn = g.net.values.astype(float) * 1e6; gb = g.buy.values.astype(float) * 1e6
            t = [x[0] for x in b]
            o, h, l, cl, v = (np.array([x[k] for x in b], float) for k in range(1, 6))
            val = cl * v; cval = np.cumsum(val)
            tix = {x: i for i, x in enumerate(t)}

            def net_at(tt):
                k = np.searchsorted(gt, tt.strftime("%H:%M:%S"), side="left") - 1     # 그 분 0초 전까지 체결
                return (gn[k], gb[k]) if k >= 0 else (0.0, 0.0)

            for s in SNAP:
                j = tix.get(s)
                if j is None or j < 20 or j + 1 >= len(b): continue
                j -= 1                                   # 그 분 전에 끝난 봉
                n0, b0 = net_at(s)
                n5, b5 = net_at(t[j - 4]); n15, b15 = net_at(t[j - 14])
                v5 = val[j - 4:j + 1].sum(); v15 = val[j - 14:j + 1].sum()
                base = val[max(0, j - 34):j - 4].mean() * 5 if j >= 10 else np.nan
                buy = o[j + 1]; y = 0
                for k in range(j + 1, min(len(b), j + 1 + HZ)):
                    if l[k] <= buy * (1 - DN): break
                    if h[k] >= buy * (1 + UP): y = 1; break
                end = min(len(b), j + 1 + HZ)
                k1519 = max(i for i, tt in enumerate(t) if tt <= time(15, 19))
                rows.append(dict(date=d, code=c, t=s.hour * 60 + s.minute, j=j, ret_prev=cl[j] / pc - 1, ret_open=cl[j] / o[0] - 1,
                                 ret10=cl[j] / cl[j - 10] - 1, acc5=v5 / base if base and base > 0 else np.nan,
                                 pg_r=n0 / cval[j], pg5=(n0 - n5) / v5 if v5 else np.nan, pg15=(n0 - n15) / v15 if v15 else np.nan,
                                 pgb15=(b0 - b15) / v15 if v15 else np.nan,
                                 y=y, mae60=l[j + 1:end].min() / buy - 1, r1519=cl[k1519] / buy - 1))
        print(d, len(codes), len(rows), file=sys.stderr)
    X = pd.DataFrame(rows)
    if X.empty: return X
    X["mkt"] = X.groupby(["date", "t"]).ret_open.transform("median")
    stop = (X.y == 0) & (X.mae60 <= -DN)
    X["edge"] = np.where(X.y == 1, UP, np.where(stop, -DN, X.r1519.clip(-DN, UP))) - E.COST
    return X


def trade(r):
    b = E.bars(r.code, r.date); tt = time(r.t // 60, r.t % 60)
    j = next((i for i, x in enumerate(b) if x[0] >= tt), None)
    if j is None: return np.nan
    ret, _ = E.intraday_exit(b, j, b[j][1], stop=DN, tp=UP, hold=lambda _: True, c=r.code, d=r.date)
    return ret


def picks(P, mask, title, k=3):
    t = P[mask].sort_values(["date", "t"]).drop_duplicates(["date", "code"]).groupby("date").head(k)
    if len(t) < 10:
        R.say(f"  {title}: {len(t)}건 (적음)"); return
    t = t.assign(rr=[trade(r) for r in t.itertuples()]).dropna(subset=["rr"])
    ds = sorted(t.date.unique()); h = ds[len(ds) // 2]
    dd = t.groupby("date").rr.sum()
    R.say(f"  {title}: {len(t)}건 {len(ds)}일 · 건당 {t.rr.mean():+.2%} (앞 {t[t.date < h].rr.mean():+.2%} 뒤 {t[t.date >= h].rr.mean():+.2%}) · 승률 {(t.rr > 0).mean():.0%} · 플러스 날 {(dd > 0).sum()}/{len(dd)}"
          + f" | 시장 강할 때 {t[t.mkt > 0].rr.mean():+.2%}({(t.mkt > 0).sum()}) 약할 때 {t[t.mkt <= 0].rr.mean():+.2%}({(t.mkt <= 0).sum()})")


def main():
    X = build()
    if X.empty:
        R.say("자료 없음"); return
    X.to_parquet(os.path.join(OUT, "program_feat.parquet"))
    P = X[(X.ret_prev > -0.05) & (X.ret_prev < 0.05)]
    R.say(f"체결 단위 프로그램 수급: {X.date.min()} ~ {X.date.max()} {X.date.nunique()}일, 덜 오른 시점 {len(P):,}")
    R.say(f"  기준 +5% 먼저 {P.y.mean():.2%} · 기대 손익 근사 {P.edge.mean():+.2%} · 15:19 {P.r1519.mean():+.2%}")
    R.say("\n## 1) 특징별 5분위 (기대 손익 근사 · +5% 먼저) — 시장 강/약 따로")
    for col in ("pg_r", "pg5", "pg15", "pgb15", "acc5", "ret10"):
        x = P[col]
        if x.notna().sum() < 300: continue
        q = pd.qcut(x.rank(method="first"), 5, labels=False)
        R.say(f"  {col} AUC {auc(P.y.values, x.values.astype(float)):.3f}: " + " | ".join(f"{k}:{g.edge.mean():+.2%}·{g.y.mean():.1%}" for k, g in P.groupby(q)))
        for nm, mk in (("강", P.mkt > 0), ("약", P.mkt <= 0)):
            S = P[mk]
            if S[col].notna().sum() < 100: continue
            qq = pd.qcut(S[col].rank(method="first"), 5, labels=False)
            R.say(f"     시장 {nm}: " + " | ".join(f"{k}:{g.edge.mean():+.2%}" for k, g in S.groupby(qq)))
    R.say("\n## 2) '가격 그대로 + 프로그램 먼저' 매수 (하루 3, 처음 걸린 시점)")
    flat = P.ret10.abs() < 0.015
    for q in (0.9, 0.95, 0.98):
        th = P.pg15.quantile(q)
        picks(P, flat & (P.pg15 >= th), f"10분 가격 ±1.5% & 15분 프로그램 순매수 상위 {1 - q:.0%}")
        picks(P, flat & (P.pg15 >= th) & (P.pg_r > 0), f"  + 누적 프로그램 +")
        picks(P, flat & (P.pg15 >= th) & (P.acc5 >= 1.5), f"  + 대금 가속 1.5배↑")
    rng = np.random.default_rng(0)
    picks(P, pd.Series(rng.random(len(P)) < 0.02, index=P.index), "(비교) 아무 종목 하루 3")
    R.say("\n※ 20거래일 전에는 판단 못 함.")


if __name__ == "__main__":
    main()
