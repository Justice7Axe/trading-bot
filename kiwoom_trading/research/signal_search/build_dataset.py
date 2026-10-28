"""매수 신호 체계적 탐색 — 1단계: 데이터셋 만들기 (2026-10-28).

행 = (날짜, 결정 시각 T, 종목). T 마다 그때까지 누적 대금 상위 100 (우선주·스팩 제외).
특징은 T 이전에 끝난 1분봉(봉 시각 < T)과 전날까지 일봉·투자자·지수만 쓴다 (미래 정보 금지).
라벨 (체결 = T 봉 시가, 15:20 행은 15:30 종가 단일가, 비용 0.25%):
  L1s3 / L1s6 : T 봉 시가 매수 → 손절 −3% / −6% 닿으면 그 값(시가가 이미 아래면 시가), 아니면 15:19 봉 종가
  L2         : 손절 −6% (15:30 까지), 아니면 다음 날 09:00 시가
  mfe / mae  : 매수 뒤 15:19 까지 최고·최저 (손익비 관점)
  Lc         : 그날 15:30 종가 매수 → 다음 날 09:00 시가 (장중 신호 → 종가 매수 '연속성' 시험용, T 와 무관)
  lock       : 매수가가 전날 종가 +29% 이상 (상한가 잠김 근처 → 못 삼)
  close_pc   : 그날 종가 등락. Lc 는 close_pc ≥ +29% (상한가 마감)면 종가에 못 사므로 search.load 에서 뺀다
1분봉은 원가격(받은 날 기준) — 일봉 가격 레벨은 f = 그날 09:00 1분봉 시가 ÷ 일봉 시가 로 맞춘다(둘 다 09:00 에 아는 값).
유니버스: minute_history 중 2026-10-25 01:29 까지 백필된 (종목, 날짜) = 전날 대금 상위 200 ∪ 그날 대금 상위 200 (뒤쪽은 미래 정보 → in_prev200 칸으로 구분).
kang_minute 종목만 있는 것은 넣지 않는다(장중 +15% 로 고른 미래 정보).
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/signal_search/build_dataset.py → data/signal_search/dataset.parquet
"""
import os, sys, pickle, time as _clock
from collections import defaultdict
from datetime import date, datetime, time

import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

TMP = os.environ.get("TEMP", ".")
MDB = os.environ.get("SS_MINUTE_DB", os.path.join(TMP, "dsel_minute_history.duckdb"))
MH = duckdb.connect(MDB, read_only=True)
E.MIN_SRC[0] = MH
E._min_codes.cache_clear(); E.daily_day.cache_clear()
DONE_BY = datetime(2026, 10, 25, 1, 29)
OUT = os.path.join(E.DATA, "signal_search"); os.makedirs(OUT, exist_ok=True)

TIMES = [time(9, 5), time(9, 10), time(9, 15), time(9, 20), time(9, 30), time(10, 0), time(10, 30), time(11, 0),
         time(13, 0), time(14, 30), time(15, 20)]
NSLOT = 381          # 0..379 = 09:00..15:19, 380 = 15:30 종가 단일가
TOPN = 100


def slot(t):
    if t == time(15, 30): return 380
    m = (t.hour - 9) * 60 + t.minute
    return m if 0 <= m < 380 else None


def tix(T):
    return 380 if T == time(15, 20) else slot(T)


# ------------------------------------------------------------------ 일봉 패널 (수정주가끼리)
def daily_panel(days_all):
    codes = sorted(E.NAME); ci = {c: i for i, c in enumerate(codes)}
    nd, nc = len(days_all), len(codes)
    P = {k: np.full((nd, nc), np.nan) for k in ("o", "h", "l", "c", "val")}
    for i, d in enumerate(days_all):
        dd = E.daily_day(d)
        for c, r in dd.items():
            j = ci.get(c)
            if j is None: continue
            o, h, l, cl, v, val = r
            if not cl: continue
            P["o"][i, j], P["h"][i, j], P["l"][i, j], P["c"][i, j] = o or np.nan, h or np.nan, l or np.nan, cl
            P["val"][i, j] = val if val else np.nan
        E._bars_cache.clear()
        if i % 50 == 0: print(f"  일봉 {d}", file=sys.stderr, flush=True)
    return codes, ci, P


def daily_feats(P, i):
    """day index i 의 장 전 특징 (i 행은 안 씀)."""
    C, H, L, V = P["c"], P["h"], P["l"], P["val"]
    with np.errstate(all="ignore"):
        pcl = C[i - 1]
        f = dict(pcl=pcl,
                 r1=pcl / C[i - 2] - 1, r5d=pcl / C[i - 6] - 1, r20d=pcl / C[i - 21] - 1,
                 val1=V[i - 1], avg20=np.nanmean(V[i - 20:i], 0),
                 hi20=np.nanmax(H[i - 20:i], 0), hi60=np.nanmax(H[i - 60:i], 0),
                 ma20=np.nanmean(C[i - 20:i], 0), ma60=np.nanmean(C[i - 60:i], 0),
                 prev_rng=H[i - 1] / L[i - 1] - 1, prev_pos=(pcl - L[i - 1]) / (H[i - 1] - L[i - 1]))
        n250 = np.sum(~np.isnan(H[max(0, i - 250):i]), 0)
        hi250 = np.nanmax(H[max(0, i - 250):i], 0)
        f["hi250"] = np.where(n250 >= 60, hi250, np.nan)
        v1 = np.nan_to_num(V[i - 1], nan=-1)
        f["prank"] = (-v1).argsort().argsort() + 1.0
        st = np.zeros(C.shape[1])
        alive = np.ones(C.shape[1], bool)
        for k in range(1, 7):
            lu = (C[i - k] / C[i - k - 1] - 1) >= E.LIMIT
            alive &= np.nan_to_num(lu, nan=0).astype(bool)
            st += alive
        f["streak"] = st
    return f


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = _clock.time()
    days = [d for d in E.days() if E.next_day(d)]
    lim = os.environ.get("SS_DAYS")
    if lim: days = days[:int(lim)]
    i0 = max(0, E.CIDX[days[0]] - 262)
    days_all = E.CAL[i0:E.CIDX[days[-1]] + 2]
    codes_all, ci, P = daily_panel(days_all)
    di = {d: i for i, d in enumerate(days_all)}
    print(f"일봉 패널 {len(days_all)}일 × {len(codes_all)}종목 {_clock.time() - t0:.0f}s", file=sys.stderr, flush=True)

    # 투자자 (전날 확정치)
    INV = defaultdict(dict)
    for c, d, fr, ins in E.IB.execute("SELECT code, date, foreign_, institution FROM investor_daily WHERE date >= ?", [days_all[0]]).fetchall():
        INV[d][c] = (fr, ins)
    # 지수
    kmin = defaultdict(dict)
    for ts, o, cl in E.IX.execute("SELECT ts, open, close FROM idx_min WHERE code='001' AND ts >= ?", [datetime.combine(days[0], time(0))]).fetchall():
        s = slot(ts.time())
        if s is not None: kmin[ts.date()][s] = (o, cl)
    kd = sorted(E.KOSPI)
    # 네이버 업종·테마 (지금 목록 → 근사)
    ng = duckdb.connect(os.path.join(TMP, "q_naver_groups.duckdb"), read_only=True)
    SEC, THM = defaultdict(set), defaultdict(set)
    for kind, no, c in ng.execute("SELECT DISTINCT kind, no, code FROM naver_groups").fetchall():
        (SEC if kind == "업종" else THM)[c].add(no)
    try:
        from kiwoom_trading.strategies.regime_plays.build_up import _load
        BAD = _load("mismatch.pkl")
    except Exception:
        BAD = set()
    SH = E.SHARES

    rows = []
    for dn, d in enumerate(days):
        i = di[d]; p = days_all[i - 1]; n = E.next_day(d)
        F = daily_feats(P, i)
        ucodes = [c for (c,) in MH.execute("SELECT code FROM minute_backfill_done WHERE date=? AND done_at <= ?", [d, DONE_BY]).fetchall()]
        ucodes = [c for c in ucodes if E.is_common(c) and "스팩" not in (E.NAME.get(c) or "") and c in ci and (c, d) not in BAD]
        dd = E.daily_day(d)
        B = E.load_day(ucodes, d)
        cl, arr = [], []
        for c in ucodes:
            b = B.get(c) or []
            reg = [x for x in b if time(9, 0) <= x[0] <= time(15, 30)]
            if len(reg) < 30 or reg[0][0] > time(9, 5): continue
            j = ci[c]
            if np.isnan(F["pcl"][j]) or c not in dd or not dd[c][0]: continue
            pre = [x for x in b if x[0] < time(9, 0)]
            cl.append(c); arr.append((reg, pre))
        if len(cl) < 120:
            E._bars_cache.clear(); continue
        nC = len(cl); J = np.array([ci[c] for c in cl])
        O = np.full((nC, NSLOT), np.nan); H = O.copy(); L = O.copy(); C = O.copy(); V = np.zeros((nC, NSLOT))
        pm_last = np.full(nC, np.nan); pm_val = np.zeros(nC)
        for r, (reg, pre) in enumerate(arr):
            for t, o, h, l, c_, v in reg:
                s = slot(t)
                if s is None: continue
                O[r, s], H[r, s], L[r, s], C[r, s], V[r, s] = o, h, l, c_, v
            if pre:
                pm_last[r] = pre[-1][4]; pm_val[r] = sum(x[5] * (x[2] + x[3] + x[4]) / 3 for x in pre)
        # 종가 ffill
        Cf = pd.DataFrame(C.T).ffill().values.T
        O0 = np.array([reg[0][1] for reg, _ in arr], float)
        f = O0 / np.array([dd[c][0] for c in cl], float)          # 일봉 → 1분봉 가격 비율 (09:00 에 앎)
        pc = F["pcl"][J] * f
        bval = np.nan_to_num(V * (H + L + C) / 3)
        cum = np.cumsum(bval, 1); cumv = np.cumsum(V, 1)
        with np.errstate(all="ignore"):
            vw_run = cum / cumv
        ranks = (-cum).argsort(0).argsort(0) + 1.0                 # 슬롯별 누적 대금 순위
        closeD = np.where(~np.isnan(C[:, 380]), C[:, 380], Cf[:, 379])
        # 다음 날 09:00 시가 (D 기준 가격)
        E.load_day(cl, n)
        nopen = np.full(nC, np.nan)
        for r, c in enumerate(cl):
            if np.isnan(closeD[r]) or (c, n) in BAD: continue
            ex = E.next_day_exits(c, d, closeD[r]).get("09:00 시가")
            if ex is not None: nopen[r] = (ex + E.COST + 1) * closeD[r]
        Lc = nopen / closeD - 1 - E.COST
        # 지수
        km = kmin.get(d, {}); kp = E.KOSPI.get(p)
        kpos = kd.index(p) if p in E.KOSPI else None
        kdd52 = kp / max(E.KOSPI[x] for x in kd[max(0, kpos - 250):kpos + 1]) - 1 if kpos is not None else np.nan
        k0 = km.get(0, (np.nan, np.nan))[0]
        sec_l = [SEC.get(c, set()) for c in cl]; thm_l = [THM.get(c, set()) for c in cl]
        ret1 = np.full_like(Cf, np.nan); ret1[:, 1:] = Cf[:, 1:] / Cf[:, :-1] - 1
        for T in TIMES:
            ti = tix(T); k = ti - 1
            pcur = Cf[:, k]
            rk = ranks[:, k]
            top = np.flatnonzero((rk <= TOPN) & ~np.isnan(pcur))
            if len(top) < 50: continue
            with np.errstate(all="ignore"):
                ret_pc = pcur / pc - 1
                ksl = max(s for s in km if s <= k) if any(s <= k for s in km) else None
                k_ret = km[ksl][1] / kp - 1 if (ksl is not None and kp) else np.nan
                k_ropen = km[ksl][1] / k0 - 1 if ksl is not None else np.nan
                rp_top = ret_pc[top]
                mkt_med = np.nanmedian(rp_top); mkt_br = np.nanmean(rp_top > 0)
                top30 = np.flatnonzero(rk <= 30); mkt_med30 = np.nanmedian(ret_pc[top30])
                hiH = np.nanmax(H[:, :ti], 1); loL = np.nanmin(L[:, :ti], 1)
                r10 = np.nanmax(H[:, :10], 1) if ti > 10 else np.full(nC, np.nan)
                last_hi = ti - 1 - np.nanargmax(np.where(np.isnan(H[:, :ti]), -np.inf, H[:, :ti])[:, ::-1], 1)
                def back(m):
                    return Cf[:, k - m] if k - m >= 0 else np.full(nC, np.nan)
                def rkb(m):
                    return ranks[:, k - m] if k - m >= 0 else np.full(nC, np.nan)
                cv = cum[:, k]
                c5 = cv - (cum[:, k - 5] if k >= 5 else 0)
                c15p = (cum[:, k - 5] - cum[:, k - 20]) if k >= 20 else np.full(nC, np.nan)
                w15 = slice(max(0, ti - 15), ti); w30 = slice(max(0, ti - 30), ti)
                rng15 = (np.nanmax(H[:, w15], 1) - np.nanmin(L[:, w15], 1)) / pcur
                sd15 = np.nanstd(ret1[:, w15], 1); sdall = np.nanstd(ret1[:, 1:ti], 1)
                m5 = np.nanmean(Cf[:, max(0, ti - 5):ti], 1); m20 = np.nanmean(Cf[:, max(0, ti - 20):ti], 1)
                m60 = np.nanmean(Cf[:, max(0, ti - 60):ti], 1)
                abv = np.nanmean((Cf[:, w30] > vw_run[:, w30]).astype(float), 1)
                upb = np.nanmean(np.where(np.isnan(C[:, w15]), np.nan, (C[:, w15] > O[:, w15]).astype(float)), 1)
                fz = {
                    "ret_pc": ret_pc, "ret_open": pcur / O0 - 1, "gap": O0 / pc - 1,
                    "lcv": np.log1p(cv), "rank": rk, "drank5": np.log(rkb(5) / rk), "drank15": np.log(rkb(15) / rk),
                    "drank30": np.log(rkb(30) / rk),
                    "cv_prev": cv / F["val1"][J], "cv_avg20": cv / F["avg20"][J],
                    "r5": pcur / back(5) - 1, "r15": pcur / back(15) - 1, "r30": pcur / back(30) - 1,
                    "acc5": (c5 / 5) / (cv / ti), "acc5_15": c5 / (c15p / 3),
                    "vwap": pcur / vw_run[:, k] - 1, "pos_rng": (pcur - loL) / (hiH - loL), "dhi": pcur / hiH - 1,
                    "dlo": pcur / loL - 1, "maxgain": hiH / pc - 1, "since_hi": last_hi.astype(float),
                    "r10": pcur / r10 - 1, "rng15": rng15, "volc": sd15 / sdall,
                    "align": ((m5 > m20) & (m20 > m60)).astype(float), "p_m20": pcur / m20 - 1, "p_m60": pcur / m60 - 1,
                    "abv_vwap30": abv, "upbars15": upb,
                    "r1": F["r1"][J], "r5d": F["r5d"][J], "r20d": F["r20d"][J], "prank": F["prank"][J],
                    "lval1": np.log1p(F["val1"][J]), "hi20d": pcur / (F["hi20"][J] * f) - 1, "hi60d": pcur / (F["hi60"][J] * f) - 1,
                    "hi250d": pcur / (F["hi250"][J] * f) - 1, "ma20d": pcur / (F["ma20"][J] * f) - 1, "ma60d": pcur / (F["ma60"][J] * f) - 1,
                    "prev_lu": (F["r1"][J] >= E.LIMIT).astype(float), "streak": F["streak"][J],
                    "prev_rng": F["prev_rng"][J], "prev_pos": F["prev_pos"][J],
                    "lmcap": np.log1p(np.array([SH.get(c) or 0 for c in cl], float) * F["pcl"][J]), "lprice": np.log(pcur),
                    "pm_ret": np.where(np.isnan(pm_last), 0.0, pm_last / pc - 1), "pm_val": pm_val / F["val1"][J],
                    "has_pm": (~np.isnan(pm_last)).astype(float),
                    "k_ret": np.full(nC, k_ret), "k_ropen": np.full(nC, k_ropen), "kdd52": np.full(nC, kdd52),
                    "mkt_med": np.full(nC, mkt_med), "mkt_med30": np.full(nC, mkt_med30), "mkt_br": np.full(nC, mkt_br),
                }
            inv = INV.get(p, {})
            frv = np.array([(inv.get(c) or (np.nan, np.nan))[0] for c in cl], float)
            inv_ = np.array([(inv.get(c) or (np.nan, np.nan))[1] for c in cl], float)
            # 3일 외인 합
            fr3 = np.zeros(nC); okn = np.zeros(nC)
            for q in (1, 2, 3):
                iv = INV.get(days_all[i - q], {})
                x = np.array([(iv.get(c) or (np.nan, np.nan))[0] for c in cl], float)
                fr3 += np.nan_to_num(x); okn += ~np.isnan(x)
            with np.errstate(all="ignore"):
                fz["fr1"] = frv / F["val1"][J]; fz["in1"] = inv_ / F["val1"][J]
                fz["both1"] = np.where(np.isnan(frv), np.nan, ((frv > 0) & (inv_ > 0)).astype(float))
                fz["fr3"] = np.where(okn == 3, fr3 / F["avg20"][J], np.nan)
            # 업종·테마 (top 안에서)
            sec_n = np.zeros(nC); sec_med = np.full(nC, np.nan); sec_lead = np.zeros(nC)
            th_n = np.zeros(nC); th_best = np.full(nC, np.nan); th_cnt = np.zeros(nC)
            tops = set(top.tolist())
            gm = defaultdict(list); tm = defaultdict(list)
            for r in top:
                for g in sec_l[r]: gm[g].append(r)
                for g in thm_l[r]: tm[g].append(r)
            for r in top:
                mem = {q for g in sec_l[r] for q in gm[g] if q != r}
                if mem:
                    rr = ret_pc[list(mem)]
                    sec_n[r] = np.sum(rr >= 0.03); sec_med[r] = np.nanmedian(rr); sec_lead[r] = float(ret_pc[r] > np.nanmax(rr))
                best, cnt = -9, 0
                for g in thm_l[r]:
                    oth = [q for q in tm[g] if q != r]
                    if not oth: continue
                    rr = ret_pc[oth]
                    cnt = max(cnt, int(np.sum(rr >= 0.05))); best = max(best, np.nanmax(rr))
                th_n[r] = cnt; th_cnt[r] = len(thm_l[r])
                if best > -9: th_best[r] = best
            fz["sec_n3"] = sec_n; fz["sec_med"] = sec_med; fz["sec_lead"] = sec_lead
            fz["th_n5"] = th_n; fz["th_best"] = th_best; fz["th_gap"] = th_best - ret_pc
            fz["th_lead"] = np.where(np.isnan(th_best), np.nan, (ret_pc > th_best).astype(float))
            # 라벨
            for r in top:
                if T == time(15, 20):
                    e = closeD[r]; j = 380
                else:
                    js = np.flatnonzero(~np.isnan(O[r, ti:380]))
                    if not len(js): continue
                    j = ti + js[0]; e = O[r, j]
                if not e or np.isnan(e): continue
                row = dict(date=d, T=T.strftime("%H:%M"), code=c if False else cl[r], in_prev200=float(F["prank"][J[r]] <= 200))
                for kx, vx in fz.items(): row[kx] = float(vx[r])
                row["tmin"] = (ti if ti < 380 else 380.0)
                row["entry"] = e; row["lock"] = float(e / pc[r] - 1 >= 0.29)
                row["Lc"] = float(Lc[r])
                row["close_pc"] = float(closeD[r] / pc[r] - 1)      # 종가 등락 (≥ +29% = 상한가 마감 → 종가 매수 못 함)
                if j < 380:
                    Hs, Ls, Os = H[r, j:380], L[r, j:380], O[r, j:380]
                    c19 = Cf[r, 379]
                    for s in (0.03, 0.06):
                        sp = e * (1 - s); hit = np.flatnonzero(Ls <= sp)
                        row[f"L1s{int(s * 100)}"] = (min(Os[hit[0]], sp) if len(hit) else c19) / e - 1 - E.COST
                    Ls2 = L[r, j:381]; Os2 = O[r, j:381]; sp = e * 0.94; hit = np.flatnonzero(Ls2 <= sp)
                    row["L2"] = (min(Os2[hit[0]], sp) / e - 1 - E.COST) if len(hit) else nopen[r] / e - 1 - E.COST
                    row["mfe"] = np.nanmax(Hs) / e - 1; row["mae"] = np.nanmin(Ls) / e - 1
                    row["rclose"] = closeD[r] / e - 1
                else:
                    row["L1s3"] = row["L1s6"] = np.nan; row["L2"] = float(Lc[r]); row["mfe"] = row["mae"] = np.nan; row["rclose"] = 0.0
                rows.append(row)
        E._bars_cache.clear()
        if dn % 10 == 0:
            print(f"  {d} 종목 {nC} 행 {len(rows):,} {_clock.time() - t0:.0f}s", file=sys.stderr, flush=True)
    df = pd.DataFrame(rows)
    df["name"] = df.code.map(E.NAME)
    path = os.path.join(OUT, os.environ.get("SS_OUT", "dataset.parquet"))
    df.to_parquet(path)
    print(f"저장 {path} {len(df):,}행 {df.date.nunique()}일 {_clock.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
