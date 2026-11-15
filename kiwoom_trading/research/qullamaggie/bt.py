"""🏄 쿨라매기 돌파 1년 백테스트 (2026-11-15 사용자 텔레그램 '쿨라매기 매매 백테스트 해줘. 종목은 기존 일봉 캔들이 거래대금 상위 50위였던 종목 대상으로만').

규칙 (docs/lectures/qullamaggie_breakout.md 4장, 숫자는 사용자 지시대로)
- 대상: 매수일 D 의 전 거래일(D−1) 정규장 일봉 거래대금 상위 50위 안 주식 (우선주·상장 20거래일 안 제외; stocks 표엔 ETF·ETN·스팩이 없음).
- 후보 (D−1 까지 정규장 일봉): 21·63·126거래일 상승률 중 하나라도 전 종목 상위 2% & 63거래일 상승률 ≥ +30% & D−1 종가 > 20일선.
- 쉬는 구간: 최근 10~40거래일 중 조건을 만족하는 가장 긴 구간 — (고−저)/저 ≤ 25%, 뒤 절반 폭 < 앞 절반 폭,
  뒤 절반 저점 > 앞 절반 저점, 최근 5거래일 종가 모두 그날 20일선 위. 윗선 = 구간 최고가.
- 매수 (정규장 1분봉 09:00~15:30, 봉 시각 = 시작 시각): 09:05~15:19 봉 중 고가가 트리거 = max(윗선, 09:00~09:04 고가) 를 처음 넘는 봉,
  트리거 가격(봉 시가가 이미 위면 시가). 손절선 = 그 순간까지 오늘 저가 = min(앞 봉들 저가, 매수 봉 시가).
  손절폭 (매수가−손절선)/매수가 > ADR20 (최근 20일 (고−저)/종가 평균) 이면 안 삼. 매수가가 전날 종가 +29.5%↑ 면 상한가로 보고 안 삼.
  종목당 하루 1회, 들고 있는 동안 다시 안 삼.
- 매도: ① 1분봉 저가 ≤ 손절선 → 손절선(봉 시가가 아래면 시가), 매수 봉 다음 봉부터. ② 매수일 포함 3거래일째 09:00 시가 절반, 남은 손절선 = 매수가.
  ③ 정규장 종가 < 10일선 → 다음 거래일 09:00 시가 나머지 전부. 같은 날 여러 조건이면 손절 먼저. 비용 왕복 0.25% (엔진 COST 와 같음).
- 1분봉이 없는 보유일은 정규장 일봉(시가·저가·종가)으로 대신 (건수 보고).

자료 처리 (backtest-rules 2장)
- 일봉 daily_ohlcv = 수정주가. 2026-09-14 부터 일봉 시·고·저·종 = 통합(애프터 포함) → 1분봉 있는 종목·일은 1분봉 09:00~15:30 으로 다시 만들고
  가격 기준은 g = 일봉 종가 ÷ 그날 마지막 1분봉 종가 로 맞춤 (엔진 daily_day 와 같은 방법). 거래대금도 정규장 1분봉 Σ(종가×거래량).
  1분봉 없는 9-14 뒤 종목·일은 통합 값 그대로 (UNSURE 로 셈).
- 1분봉(받은 날 가격)은 날마다 g(9-14 전: 일봉 종가 ÷ 15:30 1분봉 종가) 를 곱해 수정주가 기준으로 맞춘 뒤 일봉 값과 비교.
- 공통 엔진(backtest/engine.py)은 import 때 1분봉 DB(5.8GB) 를 통째로 복사하고 전 종목 126일 순위 계산이 느려, 같은 규칙(COST·g 보정·손절 먼저)을 여기서 직접 씀.
- 시장 분위기: backtest/playbook/regime.py (U/N+/N-/D, ~2026-10-23) + 그 뒤 날짜는 build_regime 과 같은 계산(M0·K1z)으로 이어 붙임.

실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/qullamaggie/bt.py
출력: data/qullamaggie/backtest.txt · trades.csv · account_*.csv
"""
import os
import shutil
import sys
import tempfile
from collections import defaultdict, Counter
from datetime import date, datetime, time, timedelta

import duckdb
import numpy as np
import pandas as pd

ROOT = r"D:\Ellie\trading"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "qullamaggie"); os.makedirs(OUT, exist_ok=True)
COST = 0.0025
NXT_SWITCH = date(2026, 9, 14)
START, END = date(2025, 10, 15), date(2026, 11, 13)     # 1분봉 기간 = 매수일 범위
LOAD_FROM = date(2024, 9, 1)                            # 126일 상승률·20일선 계산용 앞 기간
TOP_VALUE = int(os.environ.get("Q_TOP", 50))
TOP_PCT = 0.02
LIMIT = 0.295


def connect_ro(path):
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.IOException:
        dst = os.path.join(tempfile.gettempdir(), "qm_" + os.path.basename(path))
        if not os.path.exists(dst):
            shutil.copy(path, dst)
        print(f"[잠김] {path} → 복사본 {dst}", file=sys.stderr)
        return duckdb.connect(dst, read_only=True)


DM = connect_ro(os.path.join(DATA, "daily_ohlcv.duckdb"))
MH = connect_ro(os.path.join(DATA, "minute_history.duckdb"))


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep("backtest.txt")

# ---------------------------------------------------------------- 1. 일봉 (수정주가) + 9-14 뒤 정규장 값
stocks = DM.execute("SELECT code, name, list_date FROM stocks").df()
stocks = stocks[stocks.code.str[-1].isin(list("0123468")) & ~stocks.name.str.contains("스팩")]   # 우선주(5·7·9·K) 빼기
NAME = dict(zip(stocks.code, stocks.name))
LIST = dict(zip(stocks.code, pd.to_datetime(stocks.list_date).dt.date))
CAL = [d for (d,) in DM.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date>=? ORDER BY 1", [LOAD_FROM]).fetchall()]
CIDX = {d: i for i, d in enumerate(CAL)}

dly = DM.execute("SELECT code, date, open, high, low, close, volume, value FROM daily_ohlcv WHERE date>=? AND volume>0", [LOAD_FROM]).df()
dly = dly[dly.code.isin(NAME)]
dly["date"] = pd.to_datetime(dly.date).dt.date

# 1분봉 하루 요약: 정규장 시·고·저·종·봉수·대금, 그날 마지막 봉 종가
mag = MH.execute("""SELECT code, ts::date AS date,
        arg_min(open, ts) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS ro,
        max(high) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rh,
        min(low) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rl,
        arg_max(close, ts) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rc,
        count(*) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS nb,
        sum(close*volume) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rval,
        arg_max(close, ts) AS lastc
    FROM minute_ohlcv WHERE exchange='AL' GROUP BY 1, 2""").df()
mag["date"] = pd.to_datetime(mag.date).dt.date
d = dly.merge(mag, on=["code", "date"], how="left")
d[["open", "high", "low", "close", "value"]] = d[["open", "high", "low", "close", "value"]].astype(float)
post = d.date >= NXT_SWITCH
has_m = d.nb.fillna(0) >= 30
# g = 1분봉 가격 → 수정주가 비율
d["g"] = np.where(post, d.close / d.lastc, d.close / d.rc)
d.loc[~has_m, "g"] = np.nan
fix = post & has_m
for a, b in (("open", "ro"), ("high", "rh"), ("low", "rl"), ("close", "rc")):
    d.loc[fix, a] = d.loc[fix, b] * d.loc[fix, "g"]
d.loc[fix, "value"] = d.loc[fix, "rval"]
d["unsure"] = post & ~has_m
d = d.sort_values(["code", "date"]).reset_index(drop=True)
gdev = d.loc[has_m & ~post, "g"]
R.say(f"[자료] 일봉 {len(d):,}행 {d.code.nunique()}종목 · 1분봉 있는 종목·일 {has_m.sum():,} · 9-14 뒤 정규장으로 바꿈 {fix.sum():,} · 9-14 뒤 1분봉 없어 통합 값 {d.unsure.sum():,}")
R.say(f"[자료] 9-14 전 g(일봉÷1분봉 종가) |g−1|>0.3% 종목·일 {(abs(gdev - 1) > 0.003).sum():,} / {len(gdev):,} (수정주가 차이 — g 로 맞춤)")
NULLS = d[["open", "high", "low", "close"]].isna().sum().sum() + (d[["open", "high", "low", "close"]] <= 0).sum().sum()
R.say(f"[자료] 시·고·저·종 NULL·0 칸 {NULLS}")

# 지표 (종목별 자기 거래일 기준)
grp = d.groupby("code", sort=False)
d["ma20"] = grp.close.transform(lambda s: s.rolling(20).mean())
d["ma10"] = grp.close.transform(lambda s: s.rolling(10).mean())
for n in (21, 63, 126):
    d[f"r{n}"] = grp.close.transform(lambda s, n=n: s / s.shift(n) - 1)
d["rng"] = (d.high - d.low) / d.close
d["adr20"] = grp.rng.transform(lambda s: s.rolling(20).mean())
d["above20"] = d.close > d.ma20

DAY = {}                                 # (code, date) → row index
for i, (c, dt) in enumerate(zip(d.code.values, d.date.values)):
    DAY[(c, dt)] = i
ROWS = {c: g.index.values for c, g in grp}
POS = {}
for c, idx in ROWS.items():
    for k, i in enumerate(idx):
        POS[i] = k
O, H, L, C = d.open.values, d.high.values, d.low.values, d.close.values
MA10, MA20, G, UNS = d.ma10.values, d.ma20.values, d.g.values, d.unsure.values


def prev_cal(dt, n=1):
    return CAL[CIDX[dt] - n]


# ---------------------------------------------------------------- 2. 시장 분위기
sys.path.insert(0, ROOT)
from kiwoom_trading.backtest.playbook import regime as RG   # noqa: E402
from kiwoom_trading.backtest.playbook import build_regime as BR   # noqa: E402

FEAT = dict(RG.feat)


def extend_regime():
    """보존본 뒤 날짜(2026-10-24~)를 build_regime 과 같은 계산으로 (M0: 전날 대금 상위 200 의 09:09 봉 전일 대비 중앙값, K1z 지수)."""
    last = max(FEAT)
    days = [x for x in CAL if last < x <= END]
    if not days:
        return []
    BR.LAST_DAY = END
    ix = connect_ro(os.path.join(DATA, "index.duckdb"))
    ctx, snap = BR.index_parts(ix)
    for dd in days:
        p = prev_cal(dd)
        uni = DM.execute("""SELECT d.code, d.close FROM daily_ohlcv d JOIN stocks s USING(code)
                            WHERE d.date=? AND d.value IS NOT NULL QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200""", [p]).fetchall()
        pc = dict(uni); codes = list(pc)
        by = defaultdict(list)
        for c, ts, cl in MH.execute(f"""SELECT code, ts, close FROM minute_ohlcv WHERE exchange='AL' AND ts >= ? AND ts < ?
                AND code IN ({','.join('?' * len(codes))}) ORDER BY code, ts""",
                [datetime.combine(dd, time(9, 0)), datetime.combine(dd, time(15, 20)), *codes]).fetchall():
            by[c].append((ts.time(), cl))
        by = {c: b for c, b in by.items() if len(b) >= 60 and b[0][0] <= time(9, 1)}
        chg = []
        for c, b in by.items():
            k = next((i for i, x in enumerate(b) if x[0] >= time(9, 10)), None)
            if k:
                chg.append(b[k - 1][1] / pc[c] - 1)
        if dd not in snap["001"] or dd not in ctx["001"] or len(chg) < 100:
            continue
        kk = snap["001"][dd] / ctx["001"][dd]["prev"] - 1
        FEAT[dd] = dict(M0=float(np.median(chg)), K1z=kk / ctx["001"][dd]["sd20"], dd52=ctx["001"][dd]["dd52"])
    return days


ext = extend_regime()


def regime(dt):
    x = FEAT.get(dt)
    return BR.cls_of(x) if x else None


R.say(f"[분위기] 보존본 ~{max(RG.feat)} + 이어 붙임 {len([x for x in ext if x in FEAT])}일 (~{max(FEAT)}) · 분위기 없는 매수 후보일은 '?'")

# ---------------------------------------------------------------- 3. 날마다 후보
trade_days = [x for x in CAL if START <= x <= END]
import bisect
LIDX = {c: bisect.bisect_left(CAL, ld) for c, ld in LIST.items() if isinstance(ld, date) and ld >= CAL[0]}   # 상장일 이후 첫 거래일 위치
cands = []          # (D, code, resistance, adr, base_len)
stat = Counter()
for D in trade_days:
    p = prev_cal(D)
    day = d[d.date == p]
    # 상장 20거래일 안 빼기 (D 가 상장 몇 거래일째인지, 상장일 = 1거래일째)
    day = day[[CIDX[D] - LIDX.get(c, -999) + 1 > 20 for c in day.code]]
    top = set(day.nlargest(TOP_VALUE, "value").code)
    ok = np.zeros(len(day), bool)
    for n in (21, 63, 126):
        v = day[f"r{n}"].dropna()
        k = int(np.ceil(len(v) * TOP_PCT))
        thr = v.nlargest(k).min()
        ok |= (day[f"r{n}"] >= thr).fillna(False).values
    sel = day[ok & (day.r63 >= 0.30).values & (day.close > day.ma20).values]
    stat["상승률 상위·63일+30%·20일선 위 (전 종목)"] += len(sel)
    sel = sel[sel.code.isin(top)]
    stat["+ 전날 대금 상위 50"] += len(sel)
    for _, r in sel.iterrows():
        idx = ROWS[r.code]; k = POS[DAY[(r.code, p)]]
        if k < 45:
            continue
        # 최근 5거래일 종가 모두 20일선 위
        last5 = idx[k - 4:k + 1]
        if not all(C[i] > MA20[i] for i in last5):
            continue
        best = None
        for Lb in range(40, 9, -1):
            w = idx[k - Lb + 1:k + 1]
            hi, lo = H[w].max(), L[w].min()
            if (hi - lo) / lo > 0.25:
                continue
            a, b = w[:Lb // 2], w[Lb // 2:]
            wa = (H[a].max() - L[a].min()) / L[a].min(); wb = (H[b].max() - L[b].min()) / L[b].min()
            if not (wb < wa and L[b].min() > L[a].min()):
                continue
            best = (Lb, hi); break
        if best is None:
            continue
        stat["+ 쉬는 구간"] += 1
        cands.append((D, r.code, best[1], float(r.adr20), best[0], float(C[DAY[(r.code, p)]])))
for k, v in stat.items():
    R.say(f"[후보] {k}: {v:,} 종목·일")

# ---------------------------------------------------------------- 4. 1분봉
_bars = {}


def load_code(c):
    if c not in _bars:
        df = MH.execute("""SELECT ts, open, high, low, close FROM minute_ohlcv WHERE code=? AND exchange='AL'
                           AND ts::time BETWEEN TIME '09:00' AND TIME '15:30' ORDER BY ts""", [c]).df()
        df["date"] = df.ts.dt.date
        _bars[c] = {dt: g[["ts", "open", "high", "low", "close"]].values for dt, g in df.groupby("date")}
    return _bars[c]


def day_bars(c, dt):
    """정규장 1분봉, 수정주가 기준 (×g). 없거나 g 를 모르면 None."""
    b = load_code(c).get(dt)
    i = DAY.get((c, dt))
    if b is None or i is None or len(b) < 30 or not np.isfinite(G[i]):
        return None
    out = b.copy(); out[:, 1:5] = out[:, 1:5].astype(float) * G[i]
    return out


# ---------------------------------------------------------------- 5. 매수·매도
trades, skip = [], Counter()
held_until = {}        # code → 마지막 보유일
DAILY_SUB = Counter()
for D, c, res, adr, blen, pclose in cands:
    if c in held_until and held_until[c] >= D:
        skip["들고 있는 중"] += 1; continue
    b = day_bars(c, D)
    if b is None:
        skip["그날 1분봉 없음"] += 1; continue
    t = np.array([x.time() for x in b[:, 0]])
    orb = b[t <= time(9, 4)]
    if len(orb) == 0:
        skip["09:00~09:04 봉 없음"] += 1; continue
    orh = orb[:, 2].max()
    trig = max(res, orh)
    j = next((k for k in range(len(b)) if time(9, 5) <= t[k] <= time(15, 19) and b[k, 2] > trig), None)
    if j is None:
        skip["돌파 없음"] += 1; continue
    buy = max(b[j, 1], trig)
    if buy >= pclose * (1 + LIMIT):
        skip["상한가 근처"] += 1; continue
    stop = min(b[:j, 3].min() if j > 0 else b[j, 1], b[j, 1])
    s = (buy - stop) / buy
    if s > adr:
        skip["손절폭 > ADR20"] += 1; continue
    # --- 매도 경로
    legs = []          # (datetime, fraction, price, reason)
    rem, half_done, pend10, cur_stop = 1.0, False, False, stop
    di = CIDX[D]; k_day = 0; nodata = 0; sub_days = []
    ma10_days = []
    while rem > 1e-9:
        dt = CAL[di] if di < len(CAL) else None
        if dt is None or dt > END:
            break
        i = DAY.get((c, dt))
        if i is None:              # 거래 정지 등
            di += 1; continue
        k_day += 1
        bb = b if dt == D else day_bars(c, dt)
        if dt != D:
            if bb is None:
                nodata += 1; sub_days.append(dt)
                o, lo, cl = O[i], L[i], C[i]
                tsx = datetime.combine(dt, time(9, 0))
            else:
                o = bb[0, 1]; tsx = bb[0, 0]
            # 09:00 시가: 손절(갭) → 10일선 이탈 → 3거래일째 절반
            if o <= cur_stop:
                legs.append((tsx, rem, o, "손절(갭)" if not half_done else "본전 손절(갭)")); rem = 0; break
            if pend10:
                legs.append((tsx, rem, o, "10일선 이탈")); rem = 0; break
            if k_day == 3 and not half_done:
                legs.append((tsx, 0.5, o, "3일째 절반")); rem -= 0.5; half_done = True; cur_stop = buy
                if o <= cur_stop:
                    legs.append((tsx, rem, o, "본전 손절")); rem = 0; break
            if bb is None:
                if lo <= cur_stop:
                    legs.append((datetime.combine(dt, time(12, 0)), rem, cur_stop, "손절" if not half_done else "본전 손절")); rem = 0; break
                close = cl
            else:
                hit = False
                for x in bb[1:]:
                    if x[3] <= cur_stop:
                        legs.append((x[0], rem, min(x[1], cur_stop), "손절" if not half_done else "본전 손절")); rem = 0; hit = True; break
                if hit:
                    break
                close = C[i]
        else:
            hit = False
            for x in b[j + 1:]:
                if x[3] <= cur_stop:
                    legs.append((x[0], rem, min(x[1], cur_stop), "손절")); rem = 0; hit = True; break
            if hit:
                break
            close = C[i]
        if np.isfinite(MA10[i]) and close < MA10[i]:
            pend10 = True
        di += 1
    last_dt = CAL[min(di, len(CAL) - 1)]
    open_end = rem > 1e-9
    if open_end:      # 기간 끝까지 보유 → 마지막 정규장 종가로 평가
        i = DAY.get((c, END)) or DAY.get((c, last_dt))
        legs.append((datetime.combine(END, time(15, 30)), rem, C[i], "미청산(평가)"))
    exit_dt = legs[-1][0].date() if hasattr(legs[-1][0], "date") else legs[-1][0]
    held_until[c] = exit_dt
    gross = sum(f * p / buy for _, f, p, _ in legs) - 1
    ret = gross - COST
    DAILY_SUB[c] += nodata
    trades.append(dict(date=D, code=c, name=NAME.get(c, c), regime=regime(D) or "?", buy_ts=b[j, 0], buy=buy, stop=stop, s=s, adr=adr,
                       res=res, orh=orh, blen=blen, ret=ret, R=ret / max(s, 0.005), exit_date=pd.Timestamp(legs[-1][0]).date(),
                       hold=CIDX[pd.Timestamp(legs[-1][0]).date()] - CIDX[D], reason=" / ".join(f"{r} {p / buy - 1:+.1%}" for _, _, p, r in legs),
                       legs=legs, nodata=nodata, open_end=open_end, g=G[DAY[(c, D)]]))

for k, v in skip.items():
    R.say(f"[매수 못 함] {k}: {v}")
T = pd.DataFrame(trades)
T.drop(columns=["legs"]).to_csv(os.path.join(OUT, "trades.csv"), index=False, encoding="utf-8-sig")


# ---------------------------------------------------------------- 6. 집계
def summary(df, title):
    if len(df) == 0:
        R.say(f"  {title}: 0건"); return
    v = df.ret.values; r = df.R.values
    ds = sorted(set(df.date)); h = ds[len(ds) // 2]
    a, bq = df[df.date < h], df[df.date >= h]
    byday = df.groupby("date").ret.sum().sort_values(ascending=False)
    eq = np.cumsum(df.sort_values("date").ret.values)
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    win, loss = v[v > 0], v[v <= 0]
    pf = win.sum() / -loss.sum() if loss.sum() < 0 else np.inf
    payoff = win.mean() / -loss.mean() if len(win) and len(loss) else np.nan
    top5 = np.sort(v)[::-1][:5].sum()
    star = "★" if len(df) >= 15 and a.ret.mean() > 0 and bq.ret.mean() > 0 and byday.values[5:].sum() > 0 else " "
    R.say(f" {star}{title:22s} {len(v):4d}건 건당 {v.mean():+.2%} 합계 {v.sum():+.1%}({r.sum():+.1f}R) 기대값 {r.mean():+.2f}R "
          f"손익비 {payoff:.2f} PF {pf:.2f} 승률 {np.mean(v > 0):.0%} 낙폭 {mdd:.1%} 보유 {df.hold.mean():.1f}일 "
          f"| 앞 {len(a)}건 {a.ret.sum():+.1%} 뒤 {len(bq)}건 {bq.ret.sum():+.1%} | 최고5건 빼면 {v.sum() - top5:+.1%} 최고5일 빼면 {byday.values[5:].sum():+.1%}")
    return h


R.say("\n=== 🏄 쿨라매기 돌파 결과 (수익률은 비용 0.25% 뺀 값, 합계 = 건당 % 단순 합, R = 손절폭(최소 0.5%) 대비) ===")
if len(T):
    h = summary(T, "전체")
    summary(T[T.regime != "D"], "강한 하락장 제외")
    R.say(f"  (기간 반 나눔 기준일 {h})")
    R.say("\n시장 분위기별 (U 강한 상승장 · N+ 상승 흐름 보통 · N- 하락 흐름 보통(약세장) · D 강한 하락장)")
    for g in ("U", "N+", "N-", "D", "?"):
        summary(T[T.regime == g], g)
    R.say(f"\n매도 이유별 마지막 다리: {Counter(x.split(' / ')[-1].rsplit(' ', 1)[0] for x in T.reason)}")
    R.say(f"절반 매도까지 간 건 {T.reason.str.contains('3일째 절반').sum()} · 산 날 손절 {(T.hold == 0).sum()} · 미청산 {T.open_end.sum()}")
    R.say(f"보유 중 1분봉 없어 일봉으로 대신한 날 {T.nodata.sum()}일 ({(T.nodata > 0).sum()}건) · 손절폭 0.5% 미만 {(T.s < 0.005).sum()}건 · 손절폭 중앙 {T.s.median():.2%} ADR 중앙 {T.adr.median():.2%}")
    R.say(f"매수 시각 분포: 09:05~09:30 {sum(x.time() <= time(9, 30) for x in T.buy_ts)} · ~11:00 {sum(time(9, 30) < x.time() <= time(11, 0) for x in T.buy_ts)} · 그 뒤 {sum(x.time() > time(11, 0) for x in T.buy_ts)}")
    R.say(f"매수 09:05~09:10 (실전은 09:10 시장 판정 전이라 못 삼) {sum(x.time() < time(9, 10) for x in T.buy_ts)}건")
    R.say("\n매매 목록")
    for _, x in T.sort_values("date").iterrows():
        R.say(f"  {x.date} {x.code} {x["name"][:10]:10s} {x.regime:2s} {pd.Timestamp(x.buy_ts):%H:%M} 매수 {x.buy:,.0f} 손절 {x.stop:,.0f}({x.s:.1%}, ADR {x.adr:.1%}) "
              f"윗선 {x.res:,.0f} 5분고 {x.orh:,.0f} 구간 {x.blen}일 → {x.exit_date} {x.ret:+.1%} {x.R:+.1f}R | {x.reason}")


# ---------------------------------------------------------------- 7. 계좌 시뮬
def raw_price(c, dt, adj):
    i = DAY.get((c, dt))
    return adj / G[i] if i is not None and np.isfinite(G[i]) else adj


def account(start, mode, excl_d=False):
    """mode 'A': 100만·동시 5종목·종목당 min(20만, 평가잔고 1% ÷ 손절폭) / 'B': 10만·종목당 3만(가격이 넘으면 1주)."""
    df = T[T.regime != "D"] if excl_d else T
    ev = []
    for n, x in df.iterrows():
        ev.append((pd.Timestamp(x.buy_ts).to_pydatetime(), 0, n))
        for li, (ts, f, p, r) in enumerate(x.legs):
            ev.append((pd.Timestamp(ts).to_pydatetime(), 1, (n, li)))
    ev.sort(key=lambda e: (e[0], -e[1]))      # 같은 시각이면 매도 먼저
    cash = start; pos = {}; skipped = Counter(); curve = {}
    def equity(dt):
        v = cash
        for n, (sh, bp_raw, badj) in pos.items():
            x = df.loc[n]; i = DAY.get((x.code, dt))
            px = C[i] / badj if i is not None else 1.0
            v += sh * bp_raw * px
        return v
    days = sorted(set(e[0].date() for e in ev))
    di = 0
    for ts, kind, key in ev:
        while di < len(days) and days[di] < ts.date():
            curve[days[di]] = equity(days[di]); di += 1
        if kind == 0:
            n = key; x = df.loc[n]
            bp = raw_price(x.code, x.date, x.buy)
            if mode == "A":
                if len(pos) >= 5:
                    skipped["동시 5종목 꽉 참"] += 1; continue
                eq = equity(prev_cal(x.date))
                amt = min(200000, eq * 0.01 / max(x.s, 0.005))
                sh = int(amt // bp)
            else:
                sh = max(1, int(30000 // bp))
            if sh == 0:
                skipped["1주도 못 삼(금액 부족)"] += 1; continue
            if sh * bp > cash:
                sh = int(cash // bp)
                if sh == 0:
                    skipped["현금 부족"] += 1; continue
            cash -= sh * bp
            pos[n] = [sh, bp, x.buy]
        else:
            n, li = key
            if n not in pos:
                continue
            x = df.loc[n]; ts_, f, p, r = x.legs[li]
            sh, bp, badj = pos[n]
            last = li == len(x.legs) - 1
            q = sh if last else int(round(sh * f / (sum(l[1] for l in x.legs[li:]))))
            q = min(q, sh)
            cash += q * bp * (p / badj) - q * bp * COST
            pos[n][0] -= q
            if pos[n][0] <= 0 or last:
                pos.pop(n)
    while di < len(days):
        curve[days[di]] = equity(days[di]); di += 1
    s = pd.Series(curve).sort_index()
    full = pd.Series({dd: np.nan for dd in trade_days}); full.update(s); full = full.ffill().fillna(start)
    mdd = (1 - full / full.cummax()).max()
    m3 = date(2026, 8, 13)
    base3 = full[full.index < m3].iloc[-1] if (full.index < m3).any() else start
    return full, mdd, base3, skipped


if len(T):
    R.say("\n=== 계좌 시뮬 (매수일 2025-10-15~2026-11-13, 미청산은 11-13 정규장 종가 평가, 비용 0.25%) ===")
    for mode, start, nm in (("A", 1_000_000, "100만 · 동시 5 · 종목당 min(20만, 잔고1%÷손절폭)"), ("B", 100_000, "10만 · 종목당 3만(넘으면 1주)")):
        for ex in (False, True):
            full, mdd, base3, sk = account(start, mode, ex)
            fin = full.iloc[-1]
            R.say(f"  {nm} {'[강한 하락장 제외]' if ex else '[전체]'}: 최종 {fin:,.0f}원 ({fin / start - 1:+.1%}) 최대 낙폭 {mdd:.1%} "
                  f"최근 3달(8-13~) {base3:,.0f} → {fin:,.0f} ({fin / base3 - 1:+.1%}) | 못 산 {dict(sk)}")
            full.to_csv(os.path.join(OUT, f"account_{mode}{'_exD' if ex else ''}.csv"), encoding="utf-8-sig")
