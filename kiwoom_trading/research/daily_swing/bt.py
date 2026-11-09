"""일봉 이평선·거래대금 스윙 — 2단계: 격자 백테스트 (2026-10-30, 사용자 '일봉 기준 이평선 거래대금 기반 트레이딩').

입력: build.py 가 만든 data/daily_swing/*.parquet (engine.daily_day 로 9-14 뒤 정규장 값으로 바로잡은 수정주가 일봉).
판단: d 일 장 마감까지 아는 정보만 (d 종가·대금·이평선). 대금 순위는 그날 주식(보통주) 전체에서.
매수:  open  = d+1 09:00 시가 (시가가 d 종가 대비 +15% 이상이면 쫓아 사지 않음 → 건너뜀 수 따로 셈)
       close = d 정규장 종가(15:30 단일가) — 신호가 d 종가를 쓰므로 근사(약간 미래 정보). 상한가(+29.5%) 마감이면 못 삼.
       close1519 = 15:19 봉 종가로 신호를 다시 판단하고 15:30 종가에 매수 (깔끔한 판, 1분봉 있는 2025-10-16 이후만).
         15:19 판에서도 대금 순위·대금 급증은 그날 전체 대금을 씀 (마지막 10분 + 9-14 뒤 애프터 대금 → 작은 미래 정보).
U (대상): a 대금 20위 / b 50위 / c 대금 ≥ 앞 20일 평균 ×2 & ≥100억 / d ×3 & ≥100억
S (자리): S1 정배열 눌림(d-1 5>20>60, d 저가 ≤ 20선×1.01, 종가 > 20선, 양봉) / S2 20선 돌파 / S3 60선 돌파 / S4 5·20 골든크로스
          S5_60 / S5_250 종가 ≥ 앞 60일·250일 최고가 (250일은 앞 200거래일 이상 있을 때만)
X (매도): 종가 < 5선(X1) 또는 20선(X2) → 다음 날 09:00 시가. 손절 −7%/−10% (저가가 닿으면 그 값, 시가가 이미 아래면 시가, 매수 날도),
          익절 없음 / +15% (닿으면 그 값, 시가가 이미 위면 시가, 매수 날은 안 함), 최대 20거래일 → 다음 날 시가. 같은 날 손절 먼저.
          같은 종목은 들고 있는 동안 다시 사지 않음. 동시 보유 제한 없음(건당 100만 원 가정, 합계 = 건당 % 합).
평가: engine.Report.stats 와 같은 계산 (★ = 앞 반·뒤 반 모두 + & 가장 좋은 5일(신호 날 기준)을 빼도 +), 비용 0.25%.
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/daily_swing/bt.py → data/daily_swing/report.txt, grid.csv, trades_*.csv
"""
import os, sys
from collections import defaultdict
from datetime import date
import numpy as np
import pandas as pd

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "daily_swing")
COST = 0.0025
W0, W1 = date(2025, 1, 2), date(2026, 10, 20)        # 신호 날 기간
M0 = date(2025, 10, 16)                              # 1분봉 시작 (15:19 판)
F = None


def say(s=""):
    print(s, flush=True)
    F.write(str(s) + "\n"); F.flush()


# ------------------------------------------------------------------ 자료
P = pd.read_parquet(os.path.join(OUT, "panel.parquet"))
P["date"] = pd.to_datetime(P.date)
wide = {k: P.pivot(index="date", columns="code", values=k).sort_index() for k in ["o", "h", "l", "c", "value"]}
DATES = wide["c"].index; CODES = wide["c"].columns
O, H, L, C, V = (wide[k].to_numpy(float) for k in ["o", "h", "l", "c", "value"])
T, N = C.shape
DI = {d.date(): i for i, d in enumerate(DATES)}
dts = np.array([d.date() for d in DATES])

Cdf = wide["c"]
MA = {n: Cdf.rolling(n, min_periods=n).mean().to_numpy() for n in (5, 20, 60)}
AVGV = wide["value"].shift(1).rolling(20, min_periods=20).mean().to_numpy()
RANK = wide["value"].rank(axis=1, ascending=False, method="first").to_numpy()
HI60 = wide["h"].shift(1).rolling(60, min_periods=60).max().to_numpy()
HI250 = wide["h"].shift(1).rolling(250, min_periods=200).max().to_numpy()
PREVC = Cdf.shift(1).to_numpy()

IV = pd.read_parquet(os.path.join(OUT, "inv.parquet")); IV["date"] = pd.to_datetime(IV.date)
FOR = IV.pivot_table(index="date", columns="code", values="foreign_").reindex(index=DATES, columns=CODES).to_numpy()
INS = IV.pivot_table(index="date", columns="code", values="institution").reindex(index=DATES, columns=CODES).to_numpy()

K = pd.read_parquet(os.path.join(OUT, "kospi.parquet")); K["date"] = pd.to_datetime(K.date)
ks = K.set_index("date").close.sort_index()
k_ma20 = ks.rolling(20).mean(); k_dd = ks / ks.rolling(250, min_periods=200).max() - 1
REG_MA = {d.date(): ("코스피 20선 위" if ks[d] >= k_ma20[d] else "코스피 20선 아래") for d in ks.index if not np.isnan(k_ma20[d])}
REG_DD = {d.date(): ("52주 고점 −10% 안" if k_dd[d] > -0.10 else "52주 고점 −10% 밖(약세장)") for d in ks.index if not np.isnan(k_dd[d])}

M15 = pd.read_parquet(os.path.join(OUT, "m1519.parquet")); M15["date"] = pd.to_datetime(M15.date)
P1519 = M15.pivot(index="date", columns="code", values="p1519").reindex(index=DATES, columns=CODES).to_numpy()

with np.errstate(invalid="ignore"):
    UNS = P.pivot(index="date", columns="code", values="unsure").reindex(index=DATES, columns=CODES).fillna(False).to_numpy(bool)
    UNIV = {"a대금20위": RANK <= 20, "b대금50위": RANK <= 50,
            "c대금2배·100억": (V >= 2 * AVGV) & (V >= 1e10), "d대금3배·100억": (V >= 3 * AVGV) & (V >= 1e10)}


def setups(c):
    """c = 그날 판단에 쓰는 '종가' (일봉 종가 또는 15:19 값). 이평선은 그날 값을 c 로 바꿔 다시 셈."""
    with np.errstate(invalid="ignore"):
        ma5 = MA[5] + (c - C) / 5; ma20 = MA[20] + (c - C) / 20; ma60 = MA[60] + (c - C) / 60
        p5, p20, p60 = (np.roll(MA[n], 1, axis=0) for n in (5, 20, 60)); pc = PREVC
        return {"S1정배열눌림": (p5 > p20) & (p20 > p60) & (L <= ma20 * 1.01) & (c > ma20) & (c > O),
                "S2_20선돌파": (pc < p20) & (c > ma20),
                "S3_60선돌파": (pc < p60) & (c > ma60),
                "S4골든크로스": (p5 <= p20) & (ma5 > ma20),
                "S5_60일신고가": c >= HI60,
                "S5_250일신고가": c >= HI250}


SET_D = setups(C)
SET_M = setups(P1519)
EXITS = [(x, st, tp) for x in (5, 20) for st in (0.07, 0.10) for tp in (None, 0.15)]


def xname(x, st, tp):
    return f"X{1 if x == 5 else 2}({x}선)·손절{int(st * 100)}·익절{'없음' if tp is None else int(tp * 100)}"


# ------------------------------------------------------------------ 한 건 매매
_memo = {}


def _next_open(k, j):
    k += 1
    while k < T and np.isnan(O[k, j]): k += 1
    return k


def sim(i, j, mode, x, st, tp, maxhold=20):
    """mode open: i+1 시가 매수 / close: i 종가 매수. → (청산 i, 수익률, 이유, 보유일) 또는 None"""
    key = (i, j, mode, x, st, tp, maxhold)
    if key in _memo: return _memo[key]
    if mode == "open":
        e = i + 1; buy = O[e, j]; k0 = e
    else:
        e = i; buy = C[i, j]; k0 = i + 1
    sp = buy * (1 - st) if st else None; tpp = buy * (1 + tp) if tp else None
    xm = MA[x] if x else None
    held, k, res = 0, k0, None
    while k < T:
        if np.isnan(O[k, j]): k += 1; continue           # 거래 정지 날
        if k > e:
            if sp and O[k, j] <= sp: res = (k, O[k, j], "손절"); break
            if sp and L[k, j] <= sp: res = (k, sp, "손절"); break
            if tpp and O[k, j] >= tpp: res = (k, O[k, j], "익절"); break
            if tpp and H[k, j] >= tpp: res = (k, tpp, "익절"); break
        elif sp and L[k, j] <= sp:                       # 매수 날(시가 매수) 손절
            res = (k, sp, "손절"); break
        held += 1
        if (xm is not None and C[k, j] < xm[k, j]) or held >= maxhold:
            n = _next_open(k, j)
            res = (n, O[n, j], "이평 이탈" if (xm is not None and C[k, j] < xm[k, j]) else "20일") if n < T else (T - 1, C[T - 1, j], "끝(평가)")
            break
        k += 1
    if res is None:
        last = np.where(~np.isnan(C[:, j]))[0][-1]; res = (last, C[last, j], "끝(평가)")
    out = (res[0], res[1] / buy - 1 - COST, res[2], res[0] - e)
    _memo[key] = out
    return out


def run(sig, mode, x, st, tp, w0=W0, w1=W1, need=None, maxhold=20):
    """sig: bool T×N. → trades list of dict, 건너뜀 수."""
    ii, jj = np.nonzero(sig)
    m = (dts[ii] >= w0) & (dts[ii] <= w1) & (ii + 1 < T)
    ii, jj = ii[m], jj[m]
    order = np.lexsort((ii, jj)); ii, jj = ii[order], jj[order]
    last_exit = {}; tr = []; skip = defaultdict(int)
    for i, j in zip(ii, jj):
        if need is not None and not need[i, j]: continue
        if i < last_exit.get(j, -1): continue
        if mode == "open":
            if np.isnan(O[i + 1, j]): skip["다음 날 거래 없음"] += 1; continue
            if O[i + 1, j] / C[i, j] - 1 >= 0.15: skip["시가 +15%↑"] += 1; continue
        else:
            if not np.isnan(PREVC[i, j]) and C[i, j] / PREVC[i, j] - 1 >= 0.295: skip["상한가 마감"] += 1; continue
        ex, r, why, hd = sim(i, j, mode, x, st, tp, maxhold)
        last_exit[j] = ex
        tr.append(dict(d=dts[i], code=CODES[j], i=i, ex_d=dts[ex], ret=r, why=why, hold=hd))
    return tr, skip


def stats(tr):
    """engine.Report.stats 와 같은 계산 + 합계·낙폭·최고 5일 뺀 합."""
    if len(tr) < 15: return dict(n=len(tr), mean=np.mean([t["ret"] for t in tr]) if tr else np.nan, star=False, few=True)
    ds = sorted({t["d"] for t in tr}); h = ds[len(ds) // 2]
    v = np.array([t["ret"] for t in tr]); a = [t["ret"] for t in tr if t["d"] < h]; b = [t["ret"] for t in tr if t["d"] >= h]
    bd = defaultdict(float)
    for t in tr: bd[t["d"]] += t["ret"]
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0
    return dict(n=len(v), days=len(bd), mean=v.mean(), sum=v.sum() * 100, ex5=sum(s[5:]) * 100, a=np.mean(a), b=np.mean(b),
                win=np.mean(v > 0), mdd=mdd * 100, hold=np.mean([t["hold"] for t in tr]), star=star, few=False,
                med=np.median(v))


def line(title, s, w=58):
    if s.get("few"): return f"  {title:{w}s} {s['n']}건 (적음)"
    return (f" {'★' if s['star'] else ' '}{title:{w}s} {s['n']:4d}건 건당 {s['mean']:+.2%} 합계 {s['sum']:+6.0f}만 최고5일 빼면 {s['ex5']:+6.0f}만"
            f" | 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%} | 승률 {s['win']:.0%} 낙폭 {s['mdd']:.0f}만 보유 {s['hold']:.1f}일")


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")
    say(f"일봉 이평선·거래대금 스윙 격자 — 신호 {W0}~{W1}, 매수 d+1 시가(+15% 갭 건너뜀), 비용 0.25%, 건당 100만 원")
    say(f"코스피 마지막 {ks.index[-1].date()} 종가 {ks.iloc[-1]:.0f}, 52주 고점 대비 {k_dd.iloc[-1]:+.1%}, 20선 {'위' if ks.iloc[-1] >= k_ma20.iloc[-1] else '아래'}")
    # S5_250 판단 가능 첫 날
    first250 = dts[np.where((~np.isnan(HI250)).sum(axis=1) > 500)[0][0]]
    say(f"250일 신고가 판단 가능 첫 날 ≈ {first250} (앞 200거래일 필요) → S5_250 은 그 뒤만")
    for un, um in UNIV.items():
        sel = um & (dts[:, None] >= date(2026, 9, 14))
        say(f"9-14 뒤 {un} 종목·일 중 정규장 값으로 못 바꾼(애프터 포함 값) 비율 {UNS[sel].mean():.1%}")
    yr_all = sum(1 for d in dts if W0 <= d <= W1) / 245
    yr250 = sum(1 for d in dts if first250 <= d <= W1) / 245

    rows = []; all_tr = {}
    for sname, sig in SET_D.items():
        for uname, um in UNIV.items():
            for (x, st, tp) in EXITS:
                for mode in ("open", "close"):
                    tr, skip = run(sig & um, mode, x, st, tp)
                    s = stats(tr); yr = yr250 if "250" in sname else yr_all
                    rows.append(dict(S=sname, U=uname, X=xname(x, st, tp), x=x, st=st, tp=tp or 0, mode=mode, per_year=s["n"] / yr,
                                     skip_gap=skip.get("시가 +15%↑", 0), skip_lock=skip.get("상한가 마감", 0), **s))
                    all_tr[(sname, uname, x, st, tp, mode)] = tr
    G = pd.DataFrame(rows)
    G.to_csv(os.path.join(OUT, "grid.csv"), index=False, encoding="utf-8-sig")

    for mode, mname in (("open", "다음 날 09:00 시가 매수"), ("close", "그날 종가 매수(근사)")):
        g = G[G["mode"] == mode]
        say(f"\n==================== {mname}: 조합 {len(g)}개, ★ {int(g.star.sum())}개, 건당 + {int((g['mean'] > 0).sum())}개")
        say("자리별 (모든 U·X 평균): ★ 수 / 조합 수, 건당 중앙값")
        for sname, gg in g.groupby("S", sort=False):
            say(f"   {sname:16s} ★ {int(gg.star.sum()):2d}/{len(gg)}  건당 중앙값 {gg['mean'].median():+.2%}  연 건수 {gg.per_year.median():.0f}  평균 보유 {gg.hold.median():.1f}일"
                f"  +15% 갭 건너뜀 {gg.skip_gap.median():.0f}")
        say("대상별: ")
        for un, gg in g.groupby("U", sort=False):
            say(f"   {un:16s} ★ {int(gg.star.sum()):2d}/{len(gg)}  건당 중앙값 {gg['mean'].median():+.2%}")
        say("매도별: ")
        for xn, gg in g.groupby("X", sort=False):
            say(f"   {xn:28s} ★ {int(gg.star.sum()):2d}/{len(gg)}  건당 중앙값 {gg['mean'].median():+.2%}")
        say("\n자리 × 대상 표 (건당 %, ★ 는 8개 매도 중 ★ 수) — 매도 X2·손절7·익절없음 기준값 / 8개 매도 평균")
        hdr = "".join(f"{u:>18s}" for u in UNIV)
        say(f"   {'':16s}{hdr}")
        for sname in SET_D:
            cells = []
            for un in UNIV:
                gg = g[(g.S == sname) & (g.U == un)]
                base = gg[(gg.x == 20) & (gg.st == 0.07) & (gg.tp == 0)].iloc[0]
                cells.append(f"{base['mean']:+.2%}/{gg['mean'].mean():+.2%} ★{int(gg.star.sum())}")
            say(f"   {sname:16s}" + "".join(f"{c:>18s}" for c in cells))
        gq = g[g.n >= 30].sort_values("mean", ascending=False).head(10)
        say("\n건당 상위 10 (30건 이상)")
        for _, r in gq.iterrows():
            say(line(f"{r.S}·{r.U}·{r.X}", r.to_dict()) + f"  연 {r.per_year:.0f}건")

    # 이웃 견고성: 한 칸 바꾼 이웃(U 한 칸·X 종류·손절·익절·매수 방식 제외) 중 ★ 비율
    say("\n==================== 이웃 견고성 (시가 매수) — ★ 조합 중 이웃(대상 한 칸·5/20선·손절·익절 하나만 바꿈)도 ★ 인 비율")
    g = G[G["mode"] == "open"].reset_index(drop=True)
    ul = list(UNIV)
    rob = []
    for _, r in g[g.star].iterrows():
        nb = []
        ui = ul.index(r.U)
        for u2 in [ul[k] for k in (ui - 1, ui + 1) if 0 <= k < len(ul)]:
            nb.append(g[(g.S == r.S) & (g.U == u2) & (g.x == r.x) & (g.st == r.st) & (g.tp == r.tp)])
        nb.append(g[(g.S == r.S) & (g.U == r.U) & (g.x != r.x) & (g.st == r.st) & (g.tp == r.tp)])
        nb.append(g[(g.S == r.S) & (g.U == r.U) & (g.x == r.x) & (g.st != r.st) & (g.tp == r.tp)])
        nb.append(g[(g.S == r.S) & (g.U == r.U) & (g.x == r.x) & (g.st == r.st) & (g.tp != r.tp)])
        nb = pd.concat(nb)
        rob.append(dict(idx=_, nstar=int(nb.star.sum()), nn=len(nb), npos=int((nb["mean"] > 0).sum())))
    R = pd.DataFrame(rob)
    if len(R):
        R = R.merge(g, left_on="idx", right_index=True).sort_values(["nstar", "mean"], ascending=False)
        for _, r in R.head(15).iterrows():
            say(line(f"{r.S}·{r.U}·{r.X}", r.to_dict()) + f"  연 {r.per_year:.0f}건 | 이웃 ★ {r.nstar}/{r.nn} +{r.npos}/{r.nn}")

    # 시장 상황별 (★ 조합 + 자리별 기준 매도)
    say("\n==================== 시장 상황별 (신호 날 코스피 기준, 시가 매수)")
    pick = list(R.head(8)[["S", "U", "x", "st", "tp"]].itertuples(index=False)) if len(R) else []
    for sname in SET_D:
        pick.append((sname, "b대금50위", 20, 0.07, 0))
    seen = set()
    for (sname, un, x, st, tp) in pick:
        key = (sname, un, x, st, None if not tp else tp, "open")
        if key in seen: continue
        seen.add(key)
        tr = all_tr[key]
        say(f" [{sname}·{un}·{xname(x, st, None if not tp else tp)}]")
        for tagname, TG in (("20선", REG_MA), ("고점", REG_DD)):
            grp = defaultdict(list)
            for t in tr: grp[TG.get(t["d"], "?")].append(t)
            for k2 in sorted(grp):
                say(line(f"    {k2}", stats(grp[k2]), 40))

    # ⑦ 기준
    say("\n==================== ⑦ 기준 (52주 신고가 & 대금 5위 & 외인·기관 둘 다 순매수 → 다음 날 시가, 종가 < 20선 → 다음 날 시가, 손절·익절·기간 없음)")
    with np.errstate(invalid="ignore"):
        sig7 = (C >= HI250) & (RANK <= 5) & (FOR > 0) & (INS > 0)
    for w0, w1, nm in ((W0, W1, "전체"), (M0, date(2026, 10, 22), "⑦ 원래 1년(2025-10-16~)")):
        tr, sk = run(sig7, "open", 20, None, None, w0, w1, maxhold=10 ** 6)
        say(line(f"⑦ 무제한 {nm}", stats(tr)) + f"  갭 건너뜀 {sk.get('시가 +15%↑', 0)}")
        for k2, TG in (("20선", REG_MA), ("고점", REG_DD)):
            grp = defaultdict(list)
            for t in tr: grp[TG.get(t["d"], "?")].append(t)
            for kk in sorted(grp): say(line(f"    {kk}", stats(grp[kk]), 40))
        # 동시 10종목 (신호 순서 = 대금 순위)
        tr10 = cap10(sig7, w0, w1)
        say(line(f"⑦ 동시 10종목 {nm}", stats(tr10)))
    pd.DataFrame(tr).to_csv(os.path.join(OUT, "trades_ref7.csv"), index=False, encoding="utf-8-sig")

    # 종가 매수 비교 (2025-10-16 이후 같은 기간): 시가 / 종가(근사) / 15:19 판단·종가 매수
    say(f"\n==================== 매수 방식 비교 ({M0}~{W1}, 1분봉 있는 기간) — 시가 vs 종가(근사) vs 15:19 판단→종가")
    say("  (15:19 판은 15:19 값이 있는 종목·일만; 같은 대상끼리 맞추려고 시가·종가 근사도 15:19 값이 있는 종목·일로 제한한 줄을 따로 냄)")
    has = ~np.isnan(P1519)
    cmp_rows = []
    for sname in SET_D:
        for un, um in UNIV.items():
            for (x, st, tp) in EXITS:
                r = dict(S=sname, U=un, X=xname(x, st, tp))
                for nm, sig, mode, need in (("open", SET_D[sname] & um, "open", has), ("close", SET_D[sname] & um, "close", has),
                                            ("c1519", SET_M[sname] & um, "close", has)):
                    s = stats(run(sig, mode, x, st, tp, M0, W1, need=need)[0])
                    r.update({f"{nm}_n": s["n"], f"{nm}_mean": s["mean"], f"{nm}_sum": s.get("sum", np.nan), f"{nm}_star": s["star"]})
                cmp_rows.append(r)
    CM = pd.DataFrame(cmp_rows); CM.to_csv(os.path.join(OUT, "entry_compare.csv"), index=False, encoding="utf-8-sig")
    for nm in ("open", "close", "c1519"):
        say(f"  {nm:6s}: ★ {int(CM[f'{nm}_star'].sum())}/{len(CM)}  건당 + {int((CM[f'{nm}_mean'] > 0).sum())}  건당 중앙값 {CM[f'{nm}_mean'].median():+.2%}")
    say("  자리별 건당 중앙값 (시가 / 종가 근사 / 15:19→종가):")
    for sname, gg in CM.groupby("S", sort=False):
        say(f"   {sname:16s} {gg.open_mean.median():+.2%} / {gg.close_mean.median():+.2%} / {gg.c1519_mean.median():+.2%}"
            f"   ★ {int(gg.open_star.sum())} / {int(gg.close_star.sum())} / {int(gg.c1519_star.sum())}  (각 {len(gg)}개)")
    say("  15:19→종가 상위 10 (30건 이상):")
    cq = CM[CM.c1519_n >= 30].sort_values("c1519_mean", ascending=False).head(10)
    for _, r in cq.iterrows():
        say(f"   {'★' if r.c1519_star else ' '}{r.S}·{r.U}·{r.X:28s} 15:19 {r.c1519_n:3d}건 {r.c1519_mean:+.2%} | 종가근사 {r.close_n:3d}건 {r.close_mean:+.2%}"
            f" | 시가 {r.open_n:3d}건 {r.open_mean:+.2%}")

    # 매매 목록 저장 (검산용)
    for key in list(seen)[:3]:
        pd.DataFrame(all_tr[key]).to_csv(os.path.join(OUT, f"trades_{key[0]}_{key[1]}_X{key[2]}_{int(key[3] * 100)}_{key[4] or 0}.csv"),
                                         index=False, encoding="utf-8-sig")
    say("\n끝.")


def cap10(sig, w0, w1):
    """⑦ 동시 10종목: 날마다 시가에 먼저 팔고, 전날 신호를 대금 순위 순서로 산다."""
    held = {}; tr = []
    for i in range(T - 1):
        if not (w0 <= dts[i] <= w1): continue
        js = [j for j in np.nonzero(sig[i])[0]]
        js.sort(key=lambda j: RANK[i, j])
        held = {j: ex for j, ex in held.items() if ex > i}
        for j in js:
            if j in held or len(held) >= 10: continue
            if np.isnan(O[i + 1, j]) or O[i + 1, j] / C[i, j] - 1 >= 0.15: continue
            ex, r, why, hd = sim(i, j, "open", 20, None, None, 10 ** 6)
            held[j] = ex
            tr.append(dict(d=dts[i], code=CODES[j], i=i, ex_d=dts[ex], ret=r, why=why, hold=hd))
    return tr


if __name__ == "__main__":
    main()
