"""상승 직전 찾기 3 — 장중 수급 (2026-10-31 사용자 '다음 단계 진행').

'가격은 아직 그대로인데 프로그램·외인·기관이 먼저 사는 종목' 이 그 뒤 오르는지.
자료 (과거 조회 불가 → 쌓인 날만): screener.program_intraday (10-26~, 10분마다 전 종목 하루 누적 프로그램 매수·매도·순매수),
  screener.investor_intraday (10-14~, 외인·기관 잠정치 하루 누적, 하루 5~9번, 기관은 약 500종목).
표본: 날짜 D, 전날 대금 300위 주식(우선주 제외) ∩ D 1분봉 있음. 시점 = 수급 기록 시각, 그 시각까지 끝난 1분봉만 씀 → 다음 봉 시가 매수.
특징: 프로그램 누적 순매수 ÷ 누적 대금(prog_r), 최근 30·10분 프로그램 순매수 ÷ 그 사이 대금(prog_d30·prog_d10),
  외인·기관 잠정 누적 ÷ 누적 대금(fr_r·ins_r), 가격(전일 대비·최근 30분), 누적 대금 ÷ 20일 평균.
결과: 60분 안 +5% 가 −2% 보다 먼저(y), 기대 손익 근사(edge), 15:19, 실제 매도(+5/−2 → 다음 날 09:00).
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/early_rise/flow_early.py
자료가 쌓일수록 다시 돌리면 됨 (약 4~6주 뒤 판단, 2026-12 초).
"""
import os, shutil, sys, tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta
import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "early_rise")
TOPN, HZ, UP, DN = 300, 60, 0.05, 0.02


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep("flow_report.txt")


def screener():
    dst = os.path.join(tempfile.gettempdir(), "fe_screener.duckdb")
    try:
        shutil.copy(os.path.join(E.DATA, "screener.duckdb"), dst)
    except OSError:
        if not os.path.exists(dst):
            dst = os.path.join(E.DATA, "screener_snapshot.duckdb")
    return duckdb.connect(dst, read_only=True)


def auc(y, s):
    m = ~np.isnan(s); y, s = y[m], s[m]
    if y.sum() == 0 or y.sum() == len(y): return np.nan
    r = pd.Series(s).rank().values
    return (r[y == 1].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (len(y) - y.sum()))


def build(S):
    prog = pd.DataFrame(S.execute("SELECT ts, date, code, net_amount FROM program_intraday").fetchall(), columns=["ts", "date", "code", "net"])
    inv = pd.DataFrame(S.execute("SELECT ts, date, investor, code, net_amount FROM investor_intraday").fetchall(),
                       columns=["ts", "date", "inv", "code", "net"])
    days = sorted(set(inv.date) | set(prog.date))
    days = [d for d in days if d in E.CIDX and d <= E.CAL[-1]]
    rows = []
    for d in days:
        pdv = E.value_rank(E.prev_day(d))
        prev = sorted((c for c in pdv if E.is_common(c)), key=lambda c: pdv[c])[:TOPN]
        codes = [c for c in prev if c in E._min_codes(d)]
        B = E.load_day(codes, d)
        P = prog[prog.date == d]; I = inv[inv.date == d]
        snaps = sorted(set(P.ts) | set(I.ts))
        pmap = {c: g.sort_values("ts")[["ts", "net"]].values for c, g in P.groupby("code")}
        imap = {(c, k): g.sort_values("ts")[["ts", "net"]].values for (c, k), g in I.groupby(["code", "inv"])}
        pr = E.daily_day(E.prev_day(d))
        for c in codes:
            b = E.regular(B[c])
            if len(b) < 300: continue
            f = E.factor(c, d)
            if not f or c not in pr: continue
            pc = pr[c][3] * f
            if abs(b[0][1] / pc - 1) > 0.31: continue
            t = [x[0] for x in b]
            o, h, l, cl, v = (np.array([x[k] for x in b], float) for k in range(1, 6))
            cval = np.cumsum(cl * v)
            avg20 = np.mean([r[5] for r in (E.daily_day(E.prev_day(d, k)).get(c) for k in range(1, 21)) if r]) or np.nan
            k1519 = max(i for i, tt in enumerate(t) if tt <= time(15, 19))

            def last(arr, ts):
                if arr is None: return np.nan, None
                x = arr[arr[:, 0] <= ts]
                return (x[-1][1], x[-1][0]) if len(x) else (np.nan, None)

            for ts in snaps:
                tt = ts.time()
                if not (time(9, 10) <= tt <= time(14, 40)): continue
                j = max((i for i, x in enumerate(t) if x < tt.replace(second=0, microsecond=0)), default=None)   # 그 분 전에 끝난 봉
                if j is None or j + 2 >= len(b): continue
                jb = j + 1 if t[j + 1] > tt.replace(second=0, microsecond=0) else j + 2 if j + 2 < len(b) else None   # 기록 시각이 든 분의 다음 봉 시가에 매수
                if j is None or j < 30 or jb is None or jb >= len(b): continue
                pa = pmap.get(c)
                pn, _ = last(pa, ts)
                pn30, _ = last(pa, ts - timedelta(minutes=30))
                pn10, _ = last(pa, ts - timedelta(minutes=10))
                fr, _ = last(imap.get((c, "foreign")), ts)
                ins, _ = last(imap.get((c, "institution")), ts)
                v30 = (cl[j - 29:j + 1] * v[j - 29:j + 1]).sum(); v10 = (cl[j - 9:j + 1] * v[j - 9:j + 1]).sum()
                buy = o[jb]; y = 0
                for k in range(jb, min(len(b), jb + HZ)):
                    if l[k] <= buy * (1 - DN): break
                    if h[k] >= buy * (1 + UP): y = 1; break
                end = min(len(b), jb + HZ)
                mae = l[jb:end].min() / buy - 1; r1519 = cl[k1519] / buy - 1 if k1519 >= jb else np.nan
                rows.append(dict(date=d, code=c, ts=ts, t=tt.hour * 60 + tt.minute, j=j, buy=buy,
                                 ret_prev=cl[j] / pc - 1, ret30=cl[j] / cl[j - 30] - 1, ret10=cl[j] / cl[j - 10] - 1,
                                 valr=cval[j] / avg20, rng30=h[j - 29:j + 1].max() / l[j - 29:j + 1].min() - 1,
                                 prog_r=pn / cval[j], prog_d30=(pn - pn30) / v30 if v30 else np.nan,
                                 prog_d10=(pn - pn10) / v10 if v10 else np.nan,
                                 fr_r=fr / cval[j], ins_r=ins / cval[j],
                                 y=y, mae60=mae, r1519=r1519))
        print(d, len(codes), len(rows), file=sys.stderr)
    X = pd.DataFrame(rows)
    stop = (X.y == 0) & (X.mae60 <= -0.02)
    X["edge"] = np.where(X.y == 1, 0.05, np.where(stop, -0.02, X.r1519.clip(-0.02, 0.05))) - E.COST
    return X


def trade(r):
    b = E.bars(r.code, r.date); tt = r.ts.time().replace(second=0, microsecond=0)
    j = next((i for i, x in enumerate(b) if x[0] > tt), None)
    if j is None: return np.nan
    ret, _ = E.intraday_exit(b, j, b[j][1], stop=DN, tp=UP, hold=lambda _: True, c=r.code, d=r.date)
    return ret


def bucket(P, col, title):
    x = P[col]
    if x.notna().sum() < 200:
        R.say(f"  {title}: 자료 적음 ({x.notna().sum()})"); return
    q = pd.qcut(x.rank(method="first"), 5, labels=False)
    R.say(f"  {title} (AUC {auc(P.y.values, x.values.astype(float)):.3f}) 5분위(0=낮음) 기대·15:19·+5%먼저:")
    R.say("    " + " | ".join(f"{k}: {g.edge.mean():+.2%} · {g.r1519.mean():+.2%} · {g.y.mean():.1%}" for k, g in P.groupby(q)))


def picks(P, mask, title, k=3):
    t = P[mask].sort_values(["date", "ts"])
    t = t.drop_duplicates(["date", "code"]).groupby("date").head(k)
    if len(t) < 10:
        R.say(f"  {title}: {len(t)}건 (적음)"); return
    rets = [trade(r) for r in t.itertuples()]
    t = t.assign(rr=rets).dropna(subset=["rr"])
    days = t.groupby("date").rr.sum()
    R.say(f"  {title}: {len(t)}건 {t.date.nunique()}일 · 실제 +5/−2→다음 날 09:00 건당 {t.rr.mean():+.2%} · 승률 {(t.rr > 0).mean():.0%} · 플러스 날 {(days > 0).sum()}/{len(days)} · 15:19 {t.r1519.mean():+.2%}")


def main():
    S = screener()
    X = build(S)
    X.to_parquet(os.path.join(OUT, "flow_feat.parquet"))
    P = X[(X.ret_prev > -0.05) & (X.ret_prev < 0.05)]
    R.say(f"장중 수급 표본: {X.date.min()} ~ {X.date.max()} {X.date.nunique()}일, 덜 오른 시점 {len(P):,} (전체 {len(X):,})")
    R.say(f"  프로그램 있는 날 {P[P.prog_r.notna()].date.nunique()}일 · 외인 잠정 있는 줄 {P.fr_r.notna().mean():.0%} · 기관 잠정 있는 줄 {P.ins_r.notna().mean():.0%}")
    R.say(f"  기준: +5% 먼저 {P.y.mean():.2%} · 기대 손익 근사 {P.edge.mean():+.2%} · 15:19 {P.r1519.mean():+.2%}")
    R.say("\n## 1) 특징별 5분위")
    for col, nm in (("prog_r", "프로그램 누적 순매수 ÷ 누적 대금"), ("prog_d30", "최근 30분 프로그램 순매수 ÷ 그 사이 대금"),
                    ("prog_d10", "최근 10분 프로그램 순매수 ÷ 그 사이 대금"), ("fr_r", "외인 잠정 ÷ 누적 대금"), ("ins_r", "기관 잠정 ÷ 누적 대금"),
                    ("ret30", "(비교) 최근 30분 가격"), ("rng30", "(비교) 최근 30분 출렁임"), ("valr", "(비교) 누적 대금 ÷ 20일 평균")):
        bucket(P, col, nm)
    R.say("\n## 2) '가격 그대로 + 수급 먼저' 매수 (하루 3, 처음 걸린 시점)")
    flat = P.ret30.abs() < 0.01
    for q in (0.8, 0.9):
        if P.prog_d30.notna().sum() > 200:
            th = P.prog_d30.quantile(q)
            picks(P, flat & (P.prog_d30 >= th), f"가격 30분 ±1% 안 & 30분 프로그램 상위 {1 - q:.0%}")
            picks(P, flat & (P.prog_d30 >= th) & (P.prog_r > 0) & (P.valr > 0.3), f"  + 누적 프로그램 + & 대금 평소 30%↑")
        th = P.fr_r.quantile(q)
        picks(P, flat & (P.fr_r >= th), f"가격 30분 ±1% 안 & 외인 잠정 상위 {1 - q:.0%}")
        th2 = P.ins_r.quantile(q)
        picks(P, flat & (P.ins_r >= th2), f"가격 30분 ±1% 안 & 기관 잠정 상위 {1 - q:.0%}")
        picks(P, flat & (P.fr_r >= th) & (P.ins_r > 0), f"가격 30분 ±1% 안 & 외인 상위 {1 - q:.0%} & 기관 +")
    rng = np.random.default_rng(0)
    picks(P, pd.Series(rng.random(len(P)) < 0.02, index=P.index), "(비교) 아무 종목 하루 3")
    R.say("\n※ 날 수가 적어 판단용이 아님 — 자료가 4~6주 쌓이면 다시 돌려 앞·뒤 반·★로 판단.")


if __name__ == "__main__":
    main()
