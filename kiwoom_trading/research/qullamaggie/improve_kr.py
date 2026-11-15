"""🏄 쿨라매기 돌파 — 미국 고르는 기간에서 고른 변경을 한국 1년에 손대지 않고 적용 (improve.py 다음 단계).

- 규칙은 data/qullamaggie_us/improve_selected.json 에서 읽음 (여기서 새로 고르지 않음).
- 자료 처리·진입은 bt.py 와 같음 (정규장 1분봉, g 보정, 상한가 근처 안 삼, 손절폭 > ADR20 안 삼). 매도는 improve.simulate (지금 규칙 = 5거래일째 절반).
- 대상 두 가지: ① 전날 대금 상위 50 ② 전날 대금 상위 500 (1분봉 백필 범위). 둘 다 전날 기준이라 미래 정보 없음.
- 지수 칸(m10·m20·m50·u10·u20)은 코스피(001) 전날 종가 기준.
- 장중 칸: 돌파 때 거래량 = 그날 09:00~돌파 봉 누적 거래량 ÷ (지난 20거래일 정규장 1분봉 거래량 평균 × 지난 시간 비율), 장 초 = 10:00 전 매수.

실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv/Scripts/python.exe kiwoom_trading/research/qullamaggie/improve_kr.py
출력: data/qullamaggie/improve_kr.txt · improve_kr_trades_*.csv (기존 backtest.txt·trades.csv 는 안 건드림)
"""
import bisect
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date, time, timedelta

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\Ellie\trading")
from kiwoom_trading.research.qullamaggie import improve as IM   # noqa: E402

ROOT = r"D:\Ellie\trading"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "qullamaggie")
COST = 0.0025
NXT_SWITCH = date(2026, 9, 14)
START, END = date(2025, 10, 15), date(2026, 11, 13)
LOAD_FROM = date(2024, 9, 1)
LIMIT = 0.295


def connect_ro(path):
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.IOException:
        dst = os.path.join(tempfile.gettempdir(), "qm_" + os.path.basename(path))
        if not os.path.exists(dst):
            shutil.copy(path, dst)
        return duckdb.connect(dst, read_only=True)


R = IM.Rep.__new__(IM.Rep)
R.f = open(os.path.join(OUT, "improve_kr.txt"), "w", encoding="utf-8")
DM = connect_ro(os.path.join(DATA, "daily_ohlcv.duckdb"))
MH = connect_ro(os.path.join(DATA, "minute_history.duckdb"))
IX = connect_ro(os.path.join(DATA, "index.duckdb"))
SEL = json.load(open(os.path.join(DATA, "qullamaggie_us", "improve_selected.json"), encoding="utf-8"))

# ---------------------------------------------------------------- 1. 일봉 (bt.py 와 같은 처리) + 거래량
stocks = DM.execute("SELECT code, name, list_date FROM stocks").df()
stocks = stocks[stocks.code.str[-1].isin(list("0123468")) & ~stocks.name.str.contains("스팩")]
NAME = dict(zip(stocks.code, stocks.name))
LIST = dict(zip(stocks.code, pd.to_datetime(stocks.list_date).dt.date))
CAL = [x for (x,) in DM.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date>=? ORDER BY 1", [LOAD_FROM]).fetchall()]
CIDX = {x: i for i, x in enumerate(CAL)}
dly = DM.execute("SELECT code, date, open, high, low, close, volume, value FROM daily_ohlcv WHERE date>=? AND volume>0", [LOAD_FROM]).df()
dly = dly[dly.code.isin(NAME)]
dly["date"] = pd.to_datetime(dly.date).dt.date
mag = MH.execute("""SELECT code, ts::date AS date,
        arg_min(open, ts) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS ro,
        max(high) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rh,
        min(low) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rl,
        arg_max(close, ts) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rc,
        count(*) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS nb,
        sum(close*volume) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rval,
        sum(volume) FILTER (WHERE ts::time BETWEEN TIME '09:00' AND TIME '15:30') AS rvolsum,
        arg_max(close, ts) AS lastc
    FROM minute_ohlcv WHERE exchange='AL' GROUP BY 1, 2""").df()
mag["date"] = pd.to_datetime(mag.date).dt.date
d = dly.merge(mag, on=["code", "date"], how="left")
d[["open", "high", "low", "close", "value", "volume"]] = d[["open", "high", "low", "close", "value", "volume"]].astype(float)
post = d.date >= NXT_SWITCH
has_m = d.nb.fillna(0) >= 30
d["g"] = np.where(post, d.close / d.lastc, d.close / d.rc)
d.loc[~has_m, "g"] = np.nan
fix = post & has_m
for a, b in (("open", "ro"), ("high", "rh"), ("low", "rl"), ("close", "rc")):
    d.loc[fix, a] = d.loc[fix, b] * d.loc[fix, "g"]
d.loc[fix, "value"] = d.loc[fix, "rval"]
d = d.sort_values(["code", "date"]).reset_index(drop=True)
grp = d.groupby("code", sort=False)
d["ma10"] = grp.close.transform(lambda s: s.rolling(10).mean())
d["ma20"] = grp.close.transform(lambda s: s.rolling(20).mean())
d["ma50"] = grp.close.transform(lambda s: s.rolling(50).mean())
d["ma50s"] = grp.ma50.transform(lambda s: s - s.shift(5))
for n in (21, 63, 126):
    d[f"r{n}"] = grp.close.transform(lambda s, n=n: s / s.shift(n) - 1)
d["rng"] = (d.high - d.low) / d.close
d["adr20"] = grp.rng.transform(lambda s: s.rolling(20).mean())
d["v5"] = grp.volume.transform(lambda s: s.rolling(5).mean())
d["v50"] = grp.volume.transform(lambda s: s.rolling(50).mean())
d["val20"] = grp.value.transform(lambda s: s.rolling(20).mean())
d["dvr"] = d.groupby("date").val20.rank(pct=True)
d["mv20"] = grp.rvolsum.transform(lambda s: s.rolling(20, min_periods=10).mean().shift(1))   # 지난 20일 정규장 1분봉 거래량 평균
R.say(f"[자료] 일봉 {len(d):,}행 {d.code.nunique()}종목 · 1분봉 있는 종목·일 {has_m.sum():,} · 9-14 뒤 정규장으로 바꿈 {fix.sum():,} · 비용 {COST:.2%}")

DAY = {(c, dt): i for i, (c, dt) in enumerate(zip(d.code.values, d.date.values))}


class KPx:
    def __init__(self):
        self.a = {}
        for c, g in d.groupby("code", sort=False):
            self.a[c] = dict(date=list(g.date), pos={x: i for i, x in enumerate(g.date)}, idx=g.index.values,
                             O=g.open.values, H=g.high.values, L=g.low.values, C=g.close.values, G=g.g.values,
                             MA10=g.ma10.values, MA20=g.ma20.values, MA50=g.ma50.values, MA50S=g.ma50s.values, ADR=g.adr20.values,
                             V5=g.v5.values, V50=g.v50.values, DVR=g.dvr.values, MV20=g.mv20.values,
                             R21=g.r21.values, R63=g.r63.values, R126=g.r126.values, VAL=g.value.values)


px = KPx()

# ---------------------------------------------------------------- 2. 코스피 상태 (전날 종가)
kx = IX.execute("SELECT date, close FROM idx_daily WHERE code='001' ORDER BY date").df()
kx["date"] = pd.to_datetime(kx.date).dt.date
for n in (10, 20, 50):
    kx[f"ma{n}"] = kx.close.rolling(n).mean()
kx = kx.set_index("date")
KF = {}
kd = list(kx.index)
for k in range(2, len(kd)):
    p, pp = kx.iloc[k - 1], kx.iloc[k - 2]
    KF[kd[k]] = dict(m10=bool(p.close > p.ma10), m20=bool(p.close > p.ma20), m50=bool(p.close > p.ma50),
                     u10=bool(p.ma10 > pp.ma10), u20=bool(p.ma20 > pp.ma20))

# ---------------------------------------------------------------- 3. 후보 (전 종목 상승률 상위 2%·10%) — 전날 일봉만
trade_days = [x for x in CAL if START <= x <= END]
LIDX = {c: bisect.bisect_left(CAL, ld) for c, ld in LIST.items() if isinstance(ld, date) and ld >= CAL[0]}
WIDTHS = sorted({0.25} | {r.get("width", 0.25) for r in SEL["chosen"]}, reverse=True)
cands = {(u, w): [] for u in (50, 500) for w in WIDTHS}
stat = Counter()
for D in trade_days:
    p = CAL[CIDX[D] - 1]
    day = d[d.date == p]
    day = day[[CIDX[D] - LIDX.get(c, -999) + 1 > 20 for c in day.code]]
    rank_val = day.value.rank(ascending=False, method="first")
    lvl = {}
    for pct in (0.10, 0.02):
        ok = np.zeros(len(day), bool)
        for n in (21, 63, 126):
            v = day[f"r{n}"].dropna()
            k = int(np.ceil(len(v) * pct))
            thr = v.nlargest(k).min()
            ok |= (day[f"r{n}"] >= thr).fillna(False).values
        for c in day.code.values[ok]:
            lvl[c] = int(pct * 100)
    sel = day[day.code.isin(lvl) & (day.r63 >= 0.30).values & (day.close > day.ma20).values]
    for _, r in sel.iterrows():
        rk = rank_val[r.name]
        if rk > 500:
            continue
        A = px.a[r.code]; k = A["pos"][p]
        for w in WIDTHS:
          b = IM.find_base(A, k, w)
          if b is None:
            continue
          c = dict(D=D, sym=r.code, res=b[1], blen=b[0], bw=b[1] / b[2] - 1, bwb=b[3], pool=lvl[r.code], k=k,
                 adr=float(A["ADR"][k]), r21=A["R21"][k], r63=A["R63"][k], r126=A["R126"][k],
                 volc=A["V5"][k] / A["V50"][k] if A["V50"][k] > 0 else np.nan, dvr=float(A["DVR"][k]),
                 ma50up=bool(A["MA50S"][k] > 0), ext10=A["C"][k] / A["MA10"][k] - 1, near=A["C"][k] / b[1] - 1,
                 pclose=float(A["C"][k]), vrank=int(rk))
          cands[(500, w)].append(c)
          stat[f"상위 500 · 상위 {lvl[r.code]}% · 쉬는 구간 폭≤{w:.0%}"] += 1
          if rk <= 50:
            cands[(50, w)].append(dict(c))
            stat[f"상위 50 · 상위 {lvl[r.code]}% · 쉬는 구간 폭≤{w:.0%}"] += 1
for k, v in sorted(stat.items()):
    R.say(f"[후보] {k}: {v}")

# ---------------------------------------------------------------- 4. 1분봉
_bars = {}


def load_code(c):
    if c not in _bars:
        df = MH.execute("""SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code=? AND exchange='AL'
                           AND ts::time BETWEEN TIME '09:00' AND TIME '15:30' ORDER BY ts""", [c]).df()
        df["date"] = df.ts.dt.date
        _bars[c] = {dt: (list(g.ts.dt.to_pydatetime()), g[["open", "high", "low", "close", "volume"]].values.astype(float))
                    for dt, g in df.groupby("date")}
    return _bars[c]


def day_bars(c, dt, vol=False):
    x = load_code(c).get(dt)
    A = px.a[c]; i = A["pos"].get(dt)
    if x is None or i is None or len(x[0]) < 30 or not np.isfinite(A["G"][i]):
        return None
    ts, v = x; gg = A["G"][i]
    if vol:
        return [(t, o * gg, h * gg, l * gg, cl * gg, vv) for t, (o, h, l, cl, vv) in zip(ts, v)]
    return [(t, o * gg, h * gg, l * gg, cl * gg) for t, (o, h, l, cl, vv) in zip(ts, v)]


def bars_maker(c):
    return lambda dt: day_bars(c, dt)


skip = Counter()


def entries(cl):
    out = []
    for c in cl:
        code, D = c["sym"], c["D"]
        b = day_bars(code, D, vol=True)
        if b is None:
            skip["그날 1분봉 없음"] += 1; continue
        orb = [x for x in b if x[0].time() <= time(9, 4)]
        if not orb:
            skip["09:00~09:04 봉 없음"] += 1; continue
        orh = max(x[2] for x in orb); trig = max(c["res"], orh)
        j = next((k for k, x in enumerate(b) if time(9, 5) <= x[0].time() <= time(15, 19) and x[2] > trig), None)
        if j is None:
            skip["돌파 없음"] += 1; continue
        buy = max(b[j][1], trig)
        if buy >= c["pclose"] * (1 + LIMIT):
            skip["상한가 근처"] += 1; continue
        stop = min(min(x[3] for x in b[:j]) if j > 0 else b[j][1], b[j][1])
        s = (buy - stop) / buy
        if s > c["adr"] or s <= 0:
            skip["손절폭 > ADR20"] += 1; continue
        A = px.a[code]; i = A["pos"][D]
        mins = (b[j][0].hour * 60 + b[j][0].minute) - 540 + 1
        cumv = sum(x[5] for x in b[:j + 1]); mv = A["MV20"][i]
        e = dict(c); e.update(buy=buy, stop=stop, s=s, i=i, gap=b[0][1] / c["pclose"] - 1, gap_above=bool(b[0][1] > c["res"]), dvol=np.nan,
                              buy_ts=b[j][0], sector="?", s_adr=s / c["adr"], btime=b[j][0].hour * 60 + b[j][0].minute,
                              rvol=cumv / (mv * min(1.0, mins / 390)) if np.isfinite(mv) and mv > 0 else np.nan,
                              early=b[j][0].time() < time(10, 0), orh=orh)
        e.update(KF.get(D, {}))
        e["mfe"], e["mae"] = IM.mfe_mae(A, i, buy)
        e["rest"] = [x[:5] for x in b[j + 1:]]
        out.append(e)
    return out


E = {k: entries(v) for k, v in cands.items()}
R.say(f"[진입 후보] { {f'{u}·{w:.0%}': len(v) for (u, w), v in E.items()} } (들고 있는 중 거르기 전) · 못 삼 {dict(skip)}")


# ---------------------------------------------------------------- 5. 계좌 (100만 · 동시 5 · 종목당 min(20만, 잔고 1% ÷ 손절폭), 정수 주, 원가격)
def account(T, start=1_000_000):
    if len(T) == 0:
        return None
    ev = []
    for n, x in T.iterrows():
        bt = pd.Timestamp(x.buy_ts).to_pydatetime()
        ev.append((bt, 1, n))
        for li, (ts, f, p, r) in enumerate(x.legs):
            ev.append((max(pd.Timestamp(ts).to_pydatetime(), bt + timedelta(seconds=1)), 0, (n, li)))
    ev.sort(key=lambda e: (e[0], e[1]))
    cash = start; pos = {}; curve = {}; skipped = Counter()
    days = [x for x in trade_days if x >= min(T.D)]

    def equity(dt):
        v = cash
        for n, (sh, bp_raw, badj) in pos.items():
            A = px.a[T.at[n, "sym"]]; i = A["pos"].get(dt)
            if i is None:
                i = max(j for j, x in enumerate(A["date"]) if x <= dt)
            v += sh * bp_raw * A["C"][i] / badj
        return v
    di = 0
    for ts, kind, key in ev:
        while di < len(days) and days[di] < ts.date():
            curve[days[di]] = equity(days[di]); di += 1
        if kind == 1:
            x = T.loc[key]
            if len(pos) >= 5:
                skipped["동시 5종목 꽉 참"] += 1; continue
            A = px.a[x.sym]; gg = A["G"][x.i]
            bp = x.buy / gg if np.isfinite(gg) else x.buy
            eq = curve[days[di - 1]] if di > 0 else start
            sh = int(min(200_000, eq * 0.01 / max(x.s, 0.005), cash) // bp)
            if sh <= 0:
                skipped["1주도 못 삼"] += 1; continue
            cash -= sh * bp
            pos[key] = [sh, bp, x.buy]
        else:
            n, li = key
            if n not in pos:
                continue
            x = T.loc[n]; ts_, f, p, r = x.legs[li]
            sh, bp, badj = pos[n]
            last = li == len(x.legs) - 1
            q = sh if last else min(sh, int(round(sh * f / sum(l[1] for l in x.legs[li:]))))
            cash += q * bp * (p / badj) - q * bp * COST
            pos[n][0] -= q
            if pos[n][0] <= 0 or last:
                pos.pop(n)
    while di < len(days):
        curve[days[di]] = equity(days[di]); di += 1
    s = pd.Series(curve).sort_index()
    full = pd.Series({x: np.nan for x in trade_days}); full.update(s); full = full.ffill().fillna(start)
    k0 = kx.close.loc[START:END]
    return dict(final=full.iloc[-1], ret=full.iloc[-1] / start - 1, mdd=(1 - full / full.cummax()).max(),
                k_ret=k0.iloc[-1] / k0.iloc[0] - 1, k_mdd=(1 - k0 / k0.cummax()).max(), skipped=dict(skipped))


# ---------------------------------------------------------------- 6. 규칙 적용 (손대지 않음)
rules = [dict(name="(기준) 지금 규칙 (5거래일째 절반)", filters=[], exit="E0 지금(5일째 절반·본전·10일선)", pool=2),
         dict(name="(참고) 옛 bt.py 와 같은 3거래일째 절반", filters=[], exit="E5 3일째 절반", pool=2)] + SEL["chosen"]
POSTHOC = [  # 사후: 미국 참고 표(확인 기간을 본 뒤)에서 세 곳 모두 좋았던 매도 변경 — 한국은 처음 보는 자료
    dict(name="사후: E4 절반 안 팖·20일선", filters=[], exit="E4 절반 안 팖·20일선", pool=2),
    dict(name="사후: E6 본전 없앰·20일선", filters=[], exit="E6 본전 없앰·20일선", pool=2),
    dict(name="사후: ADR ≥ 4% + E4 절반 안 팖·20일선", filters=["ADR ≥ 4%"], exit="E4 절반 안 팖·20일선", pool=2),
]
rules += POSTHOC
if SEL.get("intraday_pick"):
    rules.append(dict(name="장중 칸(A 앞 1년에서 고름): " + SEL["intraday_pick"], filters=[SEL["intraday_pick"]], exit="E0 지금(5일째 절반·본전·10일선)", pool=2))
R.say(f"\n규칙 출처: data/qullamaggie_us/improve_selected.json (미국 고르는 기간에서 {SEL.get('n_tested_total_us', SEL['n_tested'])}개 조합 시험 뒤 고름) — 한국에서는 새로 고르지 않음")
cache = {}
ALL = lambda e: True        # noqa: E731
for uni in (50, 500):
    R.say("\n" + "=" * 100)
    R.say(f"한국 1년 ({START}~{END}) · 대상 전날 대금 상위 {uni} · 비용 0.25%")
    R.say("=" * 100)
    for rl in rules:
        T = IM.run(E[(uni, rl.get("width", 0.25))], IM.compose(rl["filters"]), IM.EXITS[rl["exit"]], END, px, bars_maker, cache, rl["pool"])
        st = IM.stats(T, COST)
        R.say(IM.line(rl["name"][:60], st, 60))
        if len(T):
            a = account(T)
            R.say(f"       100만 계좌: 최종 {a['final']:,.0f}원 ({a['ret']:+.1%}) 낙폭 {a['mdd']:.1%} | 코스피 보유 {a['k_ret']:+.1%} (낙폭 {a['k_mdd']:.1%}) | 못 산 {a['skipped']}")
            R.say(f"       마지막 매도 {dict(Counter(T['last']))}")
            tag = re.sub(r"[^0-9A-Za-z가-힣]+", "_", rl["name"])[:30]
            T.drop(columns=["legs"]).to_csv(os.path.join(OUT, f"improve_kr_trades_{uni}_{tag}.csv"), index=False, encoding="utf-8-sig")
    # 진단 (참고, 고르는 데 안 씀)
    T = IM.run(E[(uni, 0.25)], ALL, IM.EXITS["E0 지금(5일째 절반·본전·10일선)"], END, px, bars_maker, cache)
    if len(T) >= 10:
        R.say("\n  [참고 진단 — 지금 규칙, 고르는 데 안 씀]")
        IM.R = R
        IM.bucket(R, T, "adr", [0, .035, .05, .07, 1], ["<3.5%", "3.5~5%", "5~7%", "7%↑"], "ADR20")
        IM.bucket(R, T, "bw", [0, .10, .15, .20, .26], ["≤10%", "10~15%", "15~20%", "20~25%"], "쉬는 구간 폭")
        IM.bucket(R, T, "rvol", [0, 1, 1.5, 2, 3, 999], ["<1배", "1~1.5배", "1.5~2배", "2~3배", "3배↑"], "돌파 때 거래량(시각 보정)")
        IM.bucket(R, T, "btime", [545, 570, 600, 660, 931], ["09:05~09:29", "09:30~09:59", "10:00~10:59", "11:00↑"], "돌파 시각")
        IM.cat(R, T, "m20", "코스피 > 20일선", [True, False])
        mfeR = T.mfe / T.s
        R.say(f"     20일 안 +2R↑ {np.mean(mfeR >= 2):.0%} · +5R↑ {np.mean(mfeR >= 5):.0%} · MFE 중앙 {T.mfe.median():+.1%} · MAE 중앙 {T.mae.median():+.1%}")
        R.say("\n  [같은 진입 · 매도만 바꿈 (참고)]")
        for nm, cfg in IM.EXITS.items():
            R.say(IM.line(nm, IM.stats(IM.run(E[(uni, 0.25)], ALL, cfg, END, px, bars_maker, cache), COST)))
