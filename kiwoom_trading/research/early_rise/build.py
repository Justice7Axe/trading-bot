"""상승 직전 종목 찾기 — 자료 만들기 (2026-10-31 사용자 '키움 관심 종목 순위보다 믿을 만하게 상승 직전 종목을 찾자').

과거 연구(leader_early·leader_shape)는 '이미 오른 주도주처럼 보이는 종목'을 맞혔고 그 뒤 수익은 없었다.
여기서는 **아직 덜 오른 종목(전일 대비 −5% ~ +5%)** 이 **그 뒤 60분 안에 +5% 오를지**를 맞힌다.

표본: 날짜 D, 전날(D-1) 대금 순위 300위 안 주식(우선주 제외, stocks = ETF·ETN 없음) ∩ D 1분봉 있음.
  minute_history 의 D 종목에는 D 의 대금 상위도 섞여 있어(장 마감 뒤에야 아는 목록) 반드시 전날 순위로만 고른다.
시점: 09:05 ~ 14:30 5분마다, 그 봉까지의 자료만 씀 → 매수는 다음 봉 시가.
특징: 1분봉(대금·가속·VWAP·이평·MACD·RSI·볼린저·신고가), 일봉(D-1 까지: 이평·52주 고점·볼린저·RSI·MACD·대금), 전날 수급, 그 시점 시장 전체.
라벨: 다음 봉 시가 매수 → 60봉 안 +5% 가 −2% 보다 먼저(같은 봉이면 손절 먼저), 그 밖에 60봉 최고·최저, 15:19 종가 수익.
출력: data/early_rise/feat_YYYYMM.parquet
실행: PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/early_rise/build.py
"""
import os, sys
from collections import defaultdict
from datetime import date, time
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "early_rise"); os.makedirs(OUT, exist_ok=True)
D0, D1 = date(2025, 10, 16), date(2026, 10, 29)        # D+1 이 있어야 다음 날 매도 계산 가능
TOPN = 300
SNAP = [time(h, m) for h in range(9, 15) for m in range(0, 60, 5) if time(9, 5) <= time(h, m) <= time(14, 30)]
HZ, UP, DN = 60, 0.05, 0.02


# ---------------------------------------------------------------- 일봉 특징 (D-1 까지, 수정주가끼리만)
def daily_panel():
    ds = [d for d in E.CAL if d <= D1 and E.CIDX[d] >= E.CIDX[D0] - 270]
    rows = []
    for d in ds:
        for c, r in E.daily_day(d).items():
            if E.is_common(c):
                rows.append((d, c, *r))
    df = pd.DataFrame(rows, columns=["date", "code", "o", "h", "l", "c", "v", "val"])
    print("일봉", len(df), file=sys.stderr)
    return df


def daily_features(df):
    out = []
    for c, g in df.sort_values("date").groupby("code", sort=False):
        g = g.set_index("date")
        cl, hi, lo, val = g.c.astype(float), g.h.astype(float), g.l.astype(float), g.val.astype(float)
        f = pd.DataFrame(index=g.index)
        f["d_chg1"] = cl.pct_change()
        f["d_chg5"] = cl.pct_change(5)
        f["d_chg20"] = cl.pct_change(20)
        for n in (5, 20, 60, 120):
            f[f"d_ma{n}"] = cl / cl.rolling(n).mean() - 1
        f["d_hi52"] = cl / hi.rolling(250, min_periods=120).max() - 1
        f["d_hi20"] = cl / hi.rolling(20).max() - 1
        m20, s20 = cl.rolling(20).mean(), cl.rolling(20).std()
        f["d_bbw"] = 4 * s20 / m20
        f["d_bbw_rel"] = f["d_bbw"] / f["d_bbw"].rolling(120, min_periods=60).min()
        f["d_bbp"] = (cl - (m20 - 2 * s20)) / (4 * s20)
        dlt = cl.diff(); up = dlt.clip(lower=0).ewm(alpha=1 / 14).mean(); dn = (-dlt.clip(upper=0)).ewm(alpha=1 / 14).mean()
        f["d_rsi"] = 100 - 100 / (1 + up / dn)
        macd = cl.ewm(span=12).mean() - cl.ewm(span=26).mean()
        f["d_macdh"] = (macd - macd.ewm(span=9).mean()) / cl
        f["d_range20"] = (hi.rolling(20).max() / lo.rolling(20).min()) - 1
        f["d_val20"] = val.rolling(20).mean()
        f["d_valr"] = val / f["d_val20"]
        f["d_close_pos"] = (cl - lo) / (hi - lo).replace(0, np.nan)
        f["d_close"] = cl
        f["code"] = c
        # 이 줄들은 D-1 값 → 다음 거래일 D 에 붙인다
        f["date"] = [E.next_day(d) for d in f.index]
        out.append(f.reset_index(drop=True))
    return pd.concat(out)


def flow_features():
    q = """SELECT code, date, foreign_, institution, individual FROM investor_daily WHERE date >= ? ORDER BY code, date"""
    fl = pd.DataFrame(E.DM.execute(q, [E.CAL[E.CIDX[D0] - 10]]).fetchall(), columns=["code", "date", "fr", "ins", "ind"])
    out = []
    for c, g in fl.groupby("code", sort=False):
        g = g.set_index("date")
        f = pd.DataFrame(index=g.index)
        f["fr1"], f["ins1"] = g.fr, g.ins
        f["fr5"], f["ins5"] = g.fr.rolling(5).sum(), g.ins.rolling(5).sum()
        f["code"] = c
        f["date"] = [E.next_day(d) if d in E.CIDX else None for d in f.index]
        out.append(f.reset_index(drop=True))
    return pd.concat(out)


# ---------------------------------------------------------------- 1분봉 특징
def ema(x, n):
    a = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def roll_mean(x, n):
    c = np.cumsum(np.r_[0.0, x]); out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def intraday(b, prev_close, snap_idx):
    """b = 정규장 1분봉 [(t,o,h,l,c,v)], prev_close = 1분봉 기준 전일 종가. snap_idx = {j: 시점}. → [(j, dict)]"""
    t = [x[0] for x in b]
    o, h, l, c, v = (np.array([x[k] for x in b], float) for k in range(1, 6))
    val = c * v
    cval = np.cumsum(val); cv = np.cumsum(v)
    vwap = cval / np.maximum(cv, 1)
    hmax = np.maximum.accumulate(h); lmin = np.minimum.accumulate(l)
    ma5, ma20, ma60 = roll_mean(c, 5), roll_mean(c, 20), roll_mean(c, 60)
    macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9); hist = macd - sig
    dlt = np.diff(c, prepend=c[0]); upm = ema(np.clip(dlt, 0, None), 27); dnm = ema(np.clip(-dlt, 0, None), 27)
    rsi = 100 - 100 / (1 + upm / np.maximum(dnm, 1e-9))
    m20 = ma20; s20 = np.sqrt(np.maximum(roll_mean(c * c, 20) - m20 * m20, 0))
    bbw = 4 * s20 / m20
    newhi = np.r_[0, (h[1:] > hmax[:-1]).astype(float)]
    out = []
    for j in snap_idx:
        if j < 20 or j + 1 >= len(b):
            continue
        p = c[j]
        a5 = val[max(0, j - 4):j + 1].sum(); a30 = val[max(0, j - 34):j - 4].mean() * 5 if j >= 10 else np.nan
        f = dict(
            ret_prev=p / prev_close - 1, ret_open=p / o[0] - 1, gap=o[0] / prev_close - 1,
            cval=cval[j], acc5=a5 / a30 if a30 and a30 > 0 else np.nan,
            acc15=val[j - 14:j + 1].sum() / (val[max(0, j - 74):j - 14].mean() * 15) if j >= 30 and val[max(0, j - 74):j - 14].mean() > 0 else np.nan,
            vwap=p / vwap[j] - 1, from_hi=p / hmax[j] - 1, from_lo=p / lmin[j] - 1,
            ma5=p / ma5[j] - 1, ma20=p / ma20[j] - 1, ma60=p / ma60[j] - 1 if j >= 59 else np.nan,
            ma_align=float(ma5[j] > ma20[j]) + (float(ma20[j] > ma60[j]) if j >= 59 else 0.0),
            macdh=hist[j] / p, macdh_d=(hist[j] - hist[j - 3]) / p, macd_z=macd[j] / p,
            rsi=rsi[j], bbw=bbw[j], bbw_rel=bbw[j] / np.nanmin(bbw[max(19, j - 60):j + 1]),
            bbp=(p - (m20[j] - 2 * s20[j])) / (4 * s20[j]) if s20[j] > 0 else np.nan,
            newhi30=newhi[max(0, j - 29):j + 1].sum(), ret5=p / c[j - 5] - 1, ret15=p / c[j - 15] - 1,
            rng30=h[max(0, j - 29):j + 1].max() / l[max(0, j - 29):j + 1].min() - 1,
            upbars10=float((c[j - 9:j + 1] > o[j - 9:j + 1]).sum()),
        )
        # 라벨
        buy = o[j + 1]; up, dn = buy * (1 + UP), buy * (1 - DN)
        y, hit = 0, -1
        end = min(len(b), j + 1 + HZ)
        for k in range(j + 1, end):
            if l[k] <= dn: y = 0; hit = k; break
            if h[k] >= up: y = 1; hit = k; break
        k1519 = max(i for i, tt in enumerate(t) if tt <= time(15, 19))
        f.update(buy=buy, y=y, mfe60=h[j + 1:end].max() / buy - 1, mae60=l[j + 1:end].min() / buy - 1,
                 r1519=c[k1519] / buy - 1 if k1519 > j else np.nan)
        out.append((j, f))
    return out


def run():
    dp = daily_panel()
    dfe = daily_features(dp)
    ffe = flow_features()
    dfe = dfe[(dfe.date >= D0) & (dfe.date <= D1)]
    dfe = dfe.merge(ffe, on=["code", "date"], how="left")
    dfe = dfe.set_index(["date", "code"])
    print("일봉 특징", len(dfe), file=sys.stderr)
    days = [d for d in E.CAL if D0 <= d <= D1]
    month, buf = None, []
    for d in days:
        if month and d.strftime("%Y%m") != month:
            pd.DataFrame(buf).to_parquet(os.path.join(OUT, f"feat_{month}.parquet")); buf = []
        month = d.strftime("%Y%m")
        pdv = E.value_rank(E.prev_day(d))
        prev = sorted((c for c in pdv if E.is_common(c)), key=lambda c: pdv[c])[:TOPN]
        have = E._min_codes(d)
        codes = [c for c in prev if c in have]
        B = E.load_day(codes, d)
        rows_day = []
        for c in codes:
            b = E.regular(B[c])
            if len(b) < 300: continue
            f = E.factor(c, d); pr = E.daily_day(E.prev_day(d)).get(c)
            if not f or not pr: continue
            prev_close = pr[3] * f
            if abs(b[0][1] / prev_close - 1) > 0.31: continue        # 가격 기준 어긋남
            tix = {x[0]: i for i, x in enumerate(b)}
            snap_idx = [tix[s] for s in SNAP if s in tix]
            try:
                key = dfe.loc[(d, c)]
            except KeyError:
                continue
            dfeat = key.to_dict()
            for j, ff in intraday(b, prev_close, snap_idx):
                ff.update(dfeat); ff.update(date=d, code=c, t=b[j][0].hour * 60 + b[j][0].minute, prank=pdv[c],
                                         mcap=np.log10(max(E.mcap(c, E.prev_day(d)), 1)))
                rows_day.append(ff)
        if not rows_day:
            continue
        X = pd.DataFrame(rows_day)
        # 그 시점 단면: 누적 대금 순위·15분 전 대비 순위 변화·시장 중앙값
        X["crank"] = X.groupby("t").cval.rank(ascending=False)
        X["valr_now"] = X.cval / X.d_val20
        prevr = X[["code", "t", "crank"]].copy(); prevr["t"] += 15
        X = X.merge(prevr.rename(columns={"crank": "crank15"}), on=["code", "t"], how="left")
        X["rank_jump"] = X.crank15 - X.crank
        g = X.groupby("t")
        X["mkt_open"] = g.ret_open.transform("median"); X["mkt_prev"] = g.ret_prev.transform("median")
        X["rel_open"] = X.ret_open - X.mkt_open
        X["breadth"] = g.ret_open.transform(lambda s: (s > 0).mean())
        for k in ("fr1", "ins1", "fr5", "ins5"):
            X[k + "_r"] = X[k] / X.d_val20
        buf.extend(X.to_dict("records"))
        print(d, len(codes), len(X), file=sys.stderr)
    if buf:
        pd.DataFrame(buf).to_parquet(os.path.join(OUT, f"feat_{month}.parquet"))


if __name__ == "__main__":
    run()
