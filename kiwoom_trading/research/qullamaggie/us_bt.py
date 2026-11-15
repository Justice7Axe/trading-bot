"""🏄 쿨라매기 돌파 — 미국 주요 종목(S&P 500 + 나스닥 100 지금 구성 종목) 백테스트 (2026-11-15 사용자 텔레그램
'한국 종목이 아니라 해외 주요 종목 기준으로 백테스트하면 쿨라매기 매매법은 어떤 결과가 나올까?').

한국 가상 장부(.claude/skills/qullamaggie) 와 같은 규칙, 미국에 맞춘 것만 바꿈
- 후보(전날까지 일봉): 21·63·126거래일 상승률 중 하나라도 유니버스 안 상위 2%(비교 10%) & 63일 ≥ +30% & 전날 종가 > 20일선.
- 쉬는 구간: 최근 10~40거래일 중 가장 긴 구간 — 폭 ≤ 25% · 뒤 절반 폭 < 앞 절반 폭 · 뒤 절반 저점 > 앞 절반 저점 ·
  최근 5거래일 종가 모두 20일선 위. 윗선 = 구간 고가 최고값.
- 손절폭 (매수가 − 손절선) ÷ 매수가 > ADR20 이면 안 삼.
- A안 (1시간봉, 약 2년): 정규장 첫 1시간봉(09:30~10:30 ET) 고가 = 장 시작 60분 고점. 트리거 = max(윗선, 60분 고점).
  둘째 봉부터 고가가 트리거를 처음 넘는 봉에서 트리거(봉 시가가 이미 위면 시가)에 매수, 손절선 = min(앞 봉 저가, 매수 봉 시가).
  · 기본(한국 1분봉 판과 같음): 매수 봉 다음 봉부터 손절 확인.
  · 보수적: 매수 봉 저가가 손절선 아래면 그 봉에서 손절된 것으로 봄 (1시간봉 안 순서를 모르므로).
- B안 (일봉, 10년, 참고): 일봉 고가가 윗선을 넘는 날 max(윗선, 시가)에 매수, 손절선 = 전날 저가 (영상의 '그날 저가' 대신 —
  매수 전에 아는 값). 매수 당일 저가 ≤ 손절선이면 손절선에 손절(같은 날 순서 모름 → 손절 먼저).
- 매도(둘 다): ① 손절선 닿으면 바로(갭이면 시가) ② 산 날 포함 5거래일째 시가에 절반, 남은 손절선 = 매수가
  ③ 종가 < 10일선 마감 → 다음 거래일 시가에 나머지 전부. 같은 날 겹치면 손절 먼저. 비용 왕복 0.1% (0.25% 도 한 줄).
- 시장 분위기: 전날 SPY 종가 vs 50일선·200일선.

자료: 야후 차트 API (urllib, 키 없음). 일봉 range=10y (adjclose/close 비율로 시·고·저 보정), 1시간봉 interval=60m 최근 ~729일
(1시간봉은 분할만 반영 → 그날 일봉 adjclose/close 를 곱해 일봉과 같은 기준으로 맞춤). 캐시 data/qullamaggie_us/us.duckdb.
※ 지금 구성 종목을 과거에 적용 → 생존 편향(그 사이 크게 올라 편입된 종목이 들어 있고, 망해서 빠진 종목은 없음).

실행:
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe kiwoom_trading/research/qullamaggie/us_bt.py --fetch   # 자료 받기(이어 받기 됨)
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe kiwoom_trading/research/qullamaggie/us_bt.py           # 백테스트
출력: data/qullamaggie_us/backtest.txt · trades_*.csv
"""
import json
import math
import os
import re
import sys
import time as _time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, date

import duckdb
import numpy as np
import pandas as pd

ROOT = r"D:\Ellie\trading"
OUT = os.path.join(ROOT, "data", "qullamaggie_us"); os.makedirs(OUT, exist_ok=True)
DB = os.path.join(OUT, "us.duckdb")
UA = {"User-Agent": "Mozilla/5.0 (research script)"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"

# 나스닥 100 표를 위키백과에서 못 찾을 때 더할 종목(나스닥 100 중 S&P 500 에 없는 알려진 종목). 겹치면 자동으로 하나만.
NDX_EXTRA = ["ASML", "ARM", "AZN", "PDD", "MELI", "TEAM", "MDB", "CCEP", "GFS", "MRVL", "SHOP", "ZS", "DDOG", "TTD",
             "SIRI", "MSTR", "TRI", "FER", "INSM", "ALNY", "LIN", "CDW", "ON", "BIIB", "WDAY", "LULU", "KDP", "APP", "PLTR", "AXON"]


# ---------------------------------------------------------------- 자료 받기
def http(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        except Exception as e:                # noqa: BLE001
            if k == tries - 1:
                raise
            _time.sleep(2 + 3 * k)


def wiki_table(url, want=("Symbol", "Ticker"), min_rows=80):
    h = http(url)
    for m in re.finditer(r'<table class="[^"]*wikitable[^>]*>(.*?)</table>', h, re.S):
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S)
        if not trs:
            continue
        head = [re.sub("<[^>]+>", "", x).strip() for x in re.findall(r"<th[^>]*>(.*?)</th>", trs[0], re.S)]
        col = next((k for k, x in enumerate(head) if x in want), None)
        if col is None or len(trs) < min_rows:
            continue
        out = []
        for tr in trs[1:]:
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) > col:
                out.append(re.sub("<[^>]+>", "", tds[col]).strip())
        return out
    return []


def universe():
    sp = wiki_table("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    ndx = wiki_table("https://en.wikipedia.org/wiki/Nasdaq-100")
    src = {"sp500": len(sp), "ndx_wiki": len(ndx)}
    if len(ndx) < 90:
        ndx = NDX_EXTRA; src["ndx_fallback"] = len(ndx)
    syms = sorted({s.replace(".", "-") for s in sp + ndx if s})
    return syms, src


def chart(sym, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    j = json.loads(http(CHART.format(sym) + "?" + q))
    res = j["chart"]["result"]
    if not res:
        return None
    return res[0]


def fetch():
    con = duckdb.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS daily(sym VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, adjclose DOUBLE, volume DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS hourly(sym VARCHAR, ts TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS meta(sym VARCHAR, kind VARCHAR, n INTEGER, note VARCHAR)")
    syms, src = universe()
    print(f"[유니버스] {len(syms)}종목 {src}", flush=True)
    con.execute("CREATE OR REPLACE TABLE universe AS SELECT unnest(?) AS sym", [syms])
    con.execute("CREATE OR REPLACE TABLE universe_src AS SELECT ? AS src", [json.dumps(src)])
    done = {(s, k) for s, k in con.execute("SELECT sym, kind FROM meta").fetchall()}
    now = int(_time.time())
    for i, s in enumerate(["SPY"] + syms):
        for kind in ("daily", "hourly"):
            if (s, kind) in done:
                continue
            try:
                if kind == "daily":
                    r = chart(s, range="10y", interval="1d", events="div%2Csplit")
                else:
                    r = chart(s, period1=now - 729 * 86400, period2=now, interval="60m")
            except Exception as e:            # noqa: BLE001
                con.execute("INSERT INTO meta VALUES (?,?,?,?)", [s, kind, 0, f"error {e}"[:200]])
                print(f"  {s} {kind} 실패 {e}", flush=True); _time.sleep(0.3); continue
            n = 0
            if r and r.get("timestamp"):
                q = r["indicators"]["quote"][0]
                ts = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
                df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"]})
                if kind == "daily":
                    df["adjclose"] = r["indicators"]["adjclose"][0]["adjclose"]
                    df["date"] = ts.date
                    df["sym"] = s
                    df = df.dropna(subset=["open", "high", "low", "close", "adjclose"])
                    df = df.drop_duplicates("date", keep="last")
                    con.execute("INSERT INTO daily SELECT sym, date, open, high, low, close, adjclose, volume FROM df")
                else:
                    df["ts"] = ts.tz_localize(None)
                    df["sym"] = s
                    df = df.dropna(subset=["open", "high", "low", "close"])
                    con.execute("INSERT INTO hourly SELECT sym, ts, open, high, low, close, volume FROM df")
                n = len(df)
            con.execute("INSERT INTO meta VALUES (?,?,?,?)", [s, kind, n, "ok"])
            _time.sleep(0.3)
        if i % 25 == 0:
            print(f"  {i}/{len(syms) + 1} {s}", flush=True)
    con.close()


if __name__ == "__main__" and "--fetch" in sys.argv:
    fetch()
    sys.exit(0)


# ================================================================ 백테스트
COST = float(os.environ.get("Q_COST", 0.001))
PERIODS = (21, 63, 126)
MIN_GAIN63 = 0.30
BASE_MIN, BASE_MAX, BASE_WIDTH = 10, 40, 0.25
HALF_DAY = 5


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


def load():
    con = duckdb.connect(DB, read_only=True)
    uni = [s for (s,) in con.execute("SELECT sym FROM universe").fetchall()]
    src = con.execute("SELECT src FROM universe_src").fetchone()[0]
    d = con.execute("SELECT * FROM daily ORDER BY sym, date").df()
    h = con.execute("SELECT * FROM hourly ORDER BY sym, ts").df()
    fails = con.execute("SELECT sym, kind, note FROM meta WHERE n=0").fetchall()
    con.close()
    d["date"] = pd.to_datetime(d.date).dt.date
    return uni, src, d, h, fails


def prepare(d):
    d = d.copy()
    f = d.adjclose / d.close
    d["f"] = f
    for c in ("open", "high", "low"):
        d[c] = d[c] * f
    d["close"] = d["adjclose"]
    g = d.groupby("sym", sort=False)
    d["ma10"] = g.close.transform(lambda s: s.rolling(10).mean())
    d["ma20"] = g.close.transform(lambda s: s.rolling(20).mean())
    d["ma50"] = g.close.transform(lambda s: s.rolling(50).mean())
    d["ma200"] = g.close.transform(lambda s: s.rolling(200).mean())
    for n in PERIODS:
        d[f"r{n}"] = g.close.transform(lambda s, n=n: s / s.shift(n) - 1)
    d["rng"] = (d.high - d.low) / d.close
    d["adr20"] = g.rng.transform(lambda s: s.rolling(20).mean())
    return d


class Px:
    """종목별 numpy 배열 + 날짜 → 위치."""
    def __init__(self, d):
        self.a = {}
        for s, g in d.groupby("sym", sort=False):
            g = g.reset_index(drop=True)
            self.a[s] = dict(date=list(g.date), pos={x: i for i, x in enumerate(g.date)},
                             O=g.open.values, H=g.high.values, L=g.low.values, C=g.close.values, F=g.f.values,
                             MA10=g.ma10.values, MA20=g.ma20.values, ADR=g.adr20.values)


def find_base(A, k):
    """k = 전날 위치. (구간 길이, 윗선) 또는 None. 홀수 길이면 뒤 절반이 하루 더 김 (한국 판과 같음)."""
    H, L, C, MA20 = A["H"], A["L"], A["C"], A["MA20"]
    if k < 45:
        return None
    if not all(C[i] > MA20[i] for i in range(k - 4, k + 1)):
        return None
    for Lb in range(BASE_MAX, BASE_MIN - 1, -1):
        s0 = k - Lb + 1
        hi, lo = H[s0:k + 1].max(), L[s0:k + 1].min()
        if hi / lo - 1 > BASE_WIDTH:
            continue
        m = s0 + Lb // 2
        la, lb_ = L[s0:m].min(), L[m:k + 1].min()
        wa = H[s0:m].max() / la - 1; wb = H[m:k + 1].max() / lb_ - 1
        if wb < wa and lb_ > la:
            return Lb, hi
    return None


def candidates(d, px, cal, top_pct, start, end):
    """매수일 D 별 후보 [(D, sym, 윗선, adr, 구간 길이)] — 전부 D 전날 일봉."""
    wide = {n: d.pivot(index="date", columns="sym", values=f"r{n}") for n in PERIODS}
    r63 = wide[63]
    c = d.pivot(index="date", columns="sym", values="close"); m20 = d.pivot(index="date", columns="sym", values="ma20")
    out, st = [], Counter()
    for i in range(1, len(cal)):
        D, p = cal[i], cal[i - 1]
        if D < start or D > end or p not in r63.index:
            continue
        ok = None
        for n in PERIODS:
            v = wide[n].loc[p].dropna()
            if len(v) < 50:
                continue
            k = int(math.ceil(len(v) * top_pct))
            thr = v.nlargest(k).min()
            sel = set(v[v >= thr].index)
            ok = sel if ok is None else ok | sel
        if not ok:
            continue
        row63, rc, rm = r63.loc[p], c.loc[p], m20.loc[p]
        ok = [s for s in ok if row63.get(s, np.nan) >= MIN_GAIN63 and rc.get(s, np.nan) > rm.get(s, np.nan)]
        st["상승률 상위·63일+30%·20일선 위"] += len(ok)
        for s in sorted(ok):
            A = px.a[s]; k = A["pos"].get(p)
            if k is None:
                continue
            b = find_base(A, k)
            if b is None:
                continue
            st["+ 쉬는 구간"] += 1
            out.append((D, s, b[1], float(A["ADR"][k]), b[0]))
    return out, st


# ---------------------------------------------------------------- 매도 경로 (A·B 공통)
def simulate(A, D, buy, stop, end, bars_of, buy_day_rest):
    """buy_day_rest: 산 날 매수 뒤 남은 봉 [(ts,o,h,l,c)] (손절 확인용).
    bars_of(dt) → 그날 봉 목록 또는 None(→ 일봉 한 줄로 대신, 손절 확인은 저가로).
    반환 legs [(ts, frac, price, reason)], open_end, 일봉으로 대신한 날 수."""
    legs = []; rem = 1.0; half = False; pend10 = False; cur = stop; nodata = 0
    k_day = 0
    i = A["pos"][D]
    while rem > 1e-9:
        if i >= len(A["date"]):
            break
        dt = A["date"][i]
        if dt > end:
            break
        k_day += 1
        if dt == D:
            for ts, o, h, l, c in buy_day_rest:
                if l <= cur:
                    legs.append((ts, rem, min(o, cur), "손절")); rem = 0; break
            if rem <= 0:
                break
        else:
            bb = bars_of(dt)
            if bb is None:
                nodata += 1
                bb = [(datetime.combine(dt, datetime.min.time()).replace(hour=9, minute=30), A["O"][i], A["H"][i], A["L"][i], A["C"][i])]
            ts0, o0 = bb[0][0], bb[0][1]
            # 시가: 손절(갭) → 10일선 이탈 → 5거래일째 절반
            if o0 <= cur:
                legs.append((ts0, rem, o0, "본전 손절(갭)" if half else "손절(갭)")); rem = 0; break
            if pend10:
                legs.append((ts0, rem, o0, "10일선 이탈")); rem = 0; break
            if k_day == HALF_DAY and not half:
                legs.append((ts0, 0.5, o0, f"{HALF_DAY}일째 절반")); rem -= 0.5; half = True; cur = buy
                if o0 <= cur:
                    legs.append((ts0, rem, o0, "본전 손절")); rem = 0; break
            hit = False
            for n, (ts, o, h, l, c) in enumerate(bb):
                if l <= cur:
                    px_ = cur if n == 0 else min(o, cur)      # 첫 봉은 시가가 손절선 위였음
                    legs.append((ts if n else ts.replace(hour=12, minute=0) if len(bb) == 1 else ts, rem, px_, "본전 손절" if half else "손절"))
                    rem = 0; hit = True; break
            if hit:
                break
        cl, m10 = A["C"][i], A["MA10"][i]
        if np.isfinite(m10) and cl < m10:
            pend10 = True
        i += 1
    open_end = rem > 1e-9
    if open_end:
        j = min(i, len(A["date"])) - 1
        while A["date"][j] > end:
            j -= 1
        legs.append((datetime.combine(A["date"][j], datetime.min.time()).replace(hour=16), rem, A["C"][j], "미청산(평가)"))
    return legs, open_end, nodata


def make_trade(s, D, buy, stop, adr, res, blen, legs, open_end, nodata, cal_idx, buy_ts, spy, orh=None):
    gross = sum(f * p / buy for _, f, p, _ in legs) - 1
    ex = pd.Timestamp(legs[-1][0]).date()
    return dict(date=D, sym=s, buy_ts=buy_ts, buy=buy, stop=stop, s=(buy - stop) / buy, adr=adr, res=res, orh=orh, blen=blen,
                gross=gross, exit_date=ex, hold=cal_idx[ex] - cal_idx[D], open_end=open_end, nodata=nodata,
                reason=" / ".join(f"{r_} {p / buy - 1:+.1%}" for _, _, p, r_ in legs), legs=legs,
                spy50=spy.get(D, {}).get("a50"), spy200=spy.get(D, {}).get("a200"))


def run_B(px, cands, cal_idx, end, spy):
    trades, skip = [], Counter(); held = {}
    for D, s, res, adr, blen in cands:
        if held.get(s) and held[s] >= D:
            skip["들고 있는 중"] += 1; continue
        A = px.a[s]; i = A["pos"].get(D)
        if i is None or i == 0:
            skip["그날 시세 없음"] += 1; continue
        if not A["H"][i] > res:
            skip["돌파 없음"] += 1; continue
        buy = max(res, A["O"][i]); stop = A["L"][i - 1]
        sz = (buy - stop) / buy
        if sz > adr:
            skip["손절폭 > ADR20"] += 1; continue
        ts = datetime.combine(D, datetime.min.time()).replace(hour=10)
        rest = [(ts.replace(hour=12), A["O"][i], A["H"][i], A["L"][i], A["C"][i])]   # 매수 당일 저가 ≤ 손절선 → 손절선 (손절 먼저)
        legs, oe, _ = simulate(A, D, buy, stop, end, lambda dt: None, rest)
        t = make_trade(s, D, buy, stop, adr, res, blen, legs, oe, 0, cal_idx, ts, spy)
        held[s] = t["exit_date"]; trades.append(t)
    return trades, skip


def run_A(px, cands, cal_idx, end, spy, H, conservative=False):
    trades, skip = [], Counter(); held = {}
    for D, s, res, adr, blen in cands:
        if held.get(s) and held[s] >= D:
            skip["들고 있는 중"] += 1; continue
        A = px.a[s]; i = A["pos"].get(D)
        hb = H.get(s, {}).get(D)
        if i is None or hb is None or len(hb) < 5:
            skip["그날 1시간봉 없음"] += 1; continue
        f = A["F"][i]
        bars = [(ts, o * f, h * f, l * f, c * f) for ts, o, h, l, c in hb]
        if bars[0][0].hour != 9 or bars[0][0].minute != 30:
            skip["첫 봉 09:30 아님"] += 1; continue
        orh = bars[0][2]; trig = max(res, orh)
        j = next((k for k in range(1, len(bars)) if bars[k][2] > trig), None)
        if j is None:
            skip["돌파 없음"] += 1; continue
        buy = max(bars[j][1], trig)
        stop = min(min(b[3] for b in bars[:j]), bars[j][1])
        sz = (buy - stop) / buy
        if sz > adr:
            skip["손절폭 > ADR20"] += 1; continue
        if sz <= 0:
            skip["손절폭 0"] += 1; continue
        rest = bars[j + 1:]
        if conservative and bars[j][3] < stop:
            rest = [(bars[j][0], stop, stop, bars[j][3], bars[j][4])] + rest     # 매수 봉 안에서 손절된 것으로

        def bars_of(dt, s=s, A=A):
            x = H.get(s, {}).get(dt)
            if x is None or len(x) < 5:
                return None
            ff = A["F"][A["pos"][dt]]
            return [(ts, o * ff, h * ff, l * ff, c * ff) for ts, o, h, l, c in x]
        legs, oe, nd = simulate(A, D, buy, stop, end, bars_of, rest)
        t = make_trade(s, D, buy, stop, adr, res, blen, legs, oe, nd, cal_idx, bars[j][0], spy, orh=orh)
        held[s] = t["exit_date"]; trades.append(t)
    return trades, skip


# ---------------------------------------------------------------- 집계
def summary(R, df, title, cost):
    if len(df) == 0:
        R.say(f"   {title:28s}    0건"); return None
    df = df.sort_values("date", kind="stable")
    v = (df.gross - cost).values; r = v / np.maximum(df.s.values, 0.005)
    ds = sorted(set(df.date)); h = ds[len(ds) // 2]
    a, b = v[(df.date < h).values], v[(df.date >= h).values]
    eq = np.cumsum(v)
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    win, loss = v[v > 0], v[v <= 0]
    payoff = win.mean() / -loss.mean() if len(win) and len(loss) else np.nan
    top5 = np.sort(v)[::-1][:5].sum()
    star = "★" if len(v) >= 15 and a.sum() > 0 and b.sum() > 0 and v.sum() - top5 > 0 else " "
    R.say(f" {star} {title:28s} {len(v):4d}건 건당 {v.mean():+.2%} 합계 {v.sum():+.0%}({r.sum():+.1f}R) 기대값 {r.mean():+.2f}R "
          f"손익비 {payoff:.2f} 승률 {np.mean(v > 0):.0%} 낙폭 {mdd:.0%} 보유 {df.hold.mean():.1f}일 "
          f"| 앞 {len(a)}건 {a.sum():+.0%} 뒤 {len(b)}건 {b.sum():+.0%} | 최고5건 빼면 {v.sum() - top5:+.0%}")
    return h


def account(T, cal, end, px, cost, spy_close, start_cash=100_000.0, slots=5):
    """10만 달러 · 동시 5종목 · 종목당 min(20%, 전날 평가잔고 1% ÷ 손절폭, 현금). 평가는 그날 종가(수정주가). 소수점 주 허용(미국 대형주라 정수 주 영향 작음)."""
    if len(T) == 0:
        return None
    ev = []
    for n, x in T.iterrows():
        bt = pd.Timestamp(x.buy_ts).to_pydatetime()
        ev.append((bt, 1, n))
        for li, (ts, f, p, r) in enumerate(x.legs):
            # 같은 봉 안 손절(보수적 판)은 매수와 같은 시각 → 자기 매수 뒤에 오도록 1초 뒤로
            ev.append((max(pd.Timestamp(ts).to_pydatetime(), bt + timedelta(seconds=1)), 0, (n, li)))
    ev.sort(key=lambda e: (e[0], e[1]))         # 같은 시각이면 (다른 종목) 매도 먼저
    first = min(T.date)
    days = [x for x in cal if first <= x <= end]
    cash = start_cash; pos = {}; curve = {}; skipped = Counter()

    def equity(dt):
        v = cash
        for n, (sh, bp) in pos.items():
            A = px.a[T.at[n, "sym"]]; i = A["pos"].get(dt)
            if i is None:
                i = max(j for j, x in enumerate(A["date"]) if x <= dt)
            v += sh * A["C"][i]
        return v
    di = 0
    for ts, kind, key in ev:
        while di < len(days) and days[di] < ts.date():
            curve[days[di]] = equity(days[di]); di += 1
        if kind == 1:
            n = key; x = T.loc[n]
            if len(pos) >= slots:
                skipped["동시 5종목 꽉 참"] += 1; continue
            eq = curve[days[di - 1]] if di > 0 else start_cash
            amt = min(0.20 * eq, eq * 0.01 / max(x.s, 0.005), cash)
            if amt <= 1:
                skipped["현금 부족"] += 1; continue
            sh = amt / x.buy / (1 + cost / 2)
            cash -= amt
            pos[n] = [sh, x.buy]
        else:
            n, li = key
            if n not in pos:
                continue
            x = T.loc[n]; ts_, f, p, r = x.legs[li]
            sh, bp = pos[n]
            remf = sum(l[1] for l in x.legs[li:])
            q = sh if li == len(x.legs) - 1 else sh * f / remf
            cash += q * p * (1 - cost / 2)
            pos[n][0] -= q
            if pos[n][0] <= 1e-12 or li == len(x.legs) - 1:
                pos.pop(n)
    while di < len(days):
        curve[days[di]] = equity(days[di]); di += 1
    s = pd.Series(curve).sort_index()
    mdd = (1 - s / s.cummax()).max()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] / start_cash) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sp = pd.Series(spy_close).loc[s.index[0]:s.index[-1]]
    sp_ret = sp.iloc[-1] / sp.iloc[0] - 1
    sp_cagr = (1 + sp_ret) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sp_mdd = (1 - sp / sp.cummax()).max()
    return dict(final=s.iloc[-1], ret=s.iloc[-1] / start_cash - 1, cagr=cagr, mdd=mdd, yrs=yrs, first=s.index[0], last=s.index[-1],
                sp_ret=sp_ret, sp_cagr=sp_cagr, sp_mdd=sp_mdd, skipped=dict(skipped), curve=s)


def main():
    R = Rep("backtest.txt")
    uni, src, d0, h0, fails = load()
    R.say(f"[자료] 유니버스 {len(uni)}종목 (위키백과 {src}) · 일봉 {d0.sym.nunique()}종목 {len(d0):,}행 · 1시간봉 {h0.sym.nunique()}종목 {len(h0):,}행 · 못 받음 {len(fails)}건")
    if fails:
        R.say(f"        못 받은 것: {fails[:12]}")
    bad = (d0[["open", "high", "low", "close", "adjclose"]] <= 0).any(axis=1)
    R.say(f"[자료] 일봉 시·고·저·종 0 이하 행 {int(bad.sum())} (뺌)")
    d0 = d0[~bad]
    d = prepare(d0)
    jump = d.groupby("sym").close.pct_change().abs()
    R.say(f"[자료] 수정주가 기준 하루 ±50% 넘게 움직인 종목·일 {(jump > 0.5).sum()} (분할 반영 오류 의심 점검용): "
          f"{d.loc[jump > 0.5, ['sym', 'date']].values.tolist()[:8]}")
    spyd = d[d.sym == "SPY"].set_index("date")
    cal = list(spyd.index); cal_idx = {x: i for i, x in enumerate(cal)}
    d = d[d.date.isin(set(cal))]
    spy = {}
    for k in range(1, len(cal)):                 # 매수일 D 의 전날 SPY 종가 vs 50·200일선
        p = spyd.iloc[k - 1]
        spy[cal[k]] = dict(a50=bool(p.close > p.ma50) if np.isfinite(p.ma50) else None,
                           a200=bool(p.close > p.ma200) if np.isfinite(p.ma200) else None)
    spy_close = spyd.close.to_dict()
    stocks_d = d[d.sym != "SPY"]
    px = Px(stocks_d)

    # 1시간봉: 정규장만 (봉 시작 09:30~15:30)
    h0 = h0.copy(); h0["date"] = h0.ts.dt.date
    mins = h0.ts.dt.hour * 60 + h0.ts.dt.minute
    h0 = h0[(mins >= 570) & (mins <= 930)]
    H = {}
    for (s, dt), g in h0.groupby(["sym", "date"], sort=False):
        H.setdefault(s, {})[dt] = list(zip(list(g.ts.dt.to_pydatetime()), g.open.values, g.high.values, g.low.values, g.close.values))
    hd = sorted(set(h0.date))
    a_start, a_end = hd[0], min(hd[-1], cal[-1])
    chk = h0.groupby(["sym", "date"]).agg(hc=("close", "last"), hh=("high", "max"), hl=("low", "min"), n=("close", "size")).reset_index()
    chk = chk.merge(d0[["sym", "date", "close", "high", "low"]], on=["sym", "date"], how="inner")
    dev = (chk.hc / chk.close - 1).abs()
    R.say(f"[자료] 1시간봉 {a_start}~{a_end} · 하루 봉 수 중앙 {chk.n.median():.0f} · 마지막 봉 종가 vs 일봉 원가격 종가 차이 >1% 종목·일 {(dev > 0.01).sum():,} / {len(chk):,}"
          f" · 고가 차이 >1% {((chk.hh / chk.high - 1).abs() > 0.01).sum():,} · 저가 차이 >1% {((chk.hl / chk.low - 1).abs() > 0.01).sum():,}")
    b_start, b_end = cal[130], cal[-1]                  # 126일 상승률이 생긴 뒤
    R.say(f"[기간] A안(1시간봉) 매수일 {a_start}~{a_end} · B안(일봉) 매수일 {b_start}~{b_end}")
    R.say("※ 생존 편향: 2026-11 지금 S&P 500·나스닥 100 구성 종목을 과거 전체에 적용함 — 그 사이 크게 올라 들어온 종목이 있고, "
          "떨어져 빠진 종목은 없음 → 실제보다 좋게 나올 쪽으로 기울어 있음 (특히 B안 10년).")

    results = {}
    for pct in (0.02, 0.10):
        cB, stB = candidates(stocks_d, px, cal, pct, b_start, b_end)
        cA = [c for c in cB if a_start <= c[0] <= a_end]
        R.say(f"\n[후보 상위 {pct:.0%}] B안 기간 {dict(stB)} · 그중 A안 기간 {len(cA)}")
        tA, skA = run_A(px, cA, cal_idx, a_end, spy, H)
        tAc, _ = run_A(px, cA, cal_idx, a_end, spy, H, conservative=True)
        tB, skB = run_B(px, cB, cal_idx, b_end, spy)
        R.say(f"  [A 못 삼] {dict(skA)}")
        R.say(f"  [B 못 삼] {dict(skB)}")
        results[pct] = dict(A=pd.DataFrame(tA), Ac=pd.DataFrame(tAc), B=pd.DataFrame(tB))
    R.say("\n=== 🏄 쿨라매기 돌파 미국 결과 (비용 왕복 0.1% 뺀 값, 합계 = 건당 % 단순 합, R = 손절폭(최소 0.5%) 대비, ★ = 15건↑ & 앞 반·뒤 반 모두 + & 최고 5건 빼도 +) ===")
    for pct in (0.02, 0.10):
        rs = results[pct]
        for key, nm in (("A", "A안 1시간봉"), ("Ac", "A안 보수적(매수 봉 안 손절 인정)"), ("B", "B안 일봉 10년")):
            T = rs[key]
            R.say(f"\n[상위 {pct:.0%} · {nm}]")
            if len(T) == 0:
                R.say("   0건"); continue
            h = summary(R, T, "전체", COST)
            summary(R, T, "비용 0.25%", 0.0025)
            summary(R, T[T.spy50 == True], "SPY 50일선 위 (=무너지는 시장 쉼)", COST)   # noqa: E712
            summary(R, T[T.spy50 == False], "SPY 50일선 아래", COST)   # noqa: E712
            summary(R, T[T.spy200 == True], "SPY 200일선 위", COST)    # noqa: E712
            summary(R, T[T.spy200 == False], "SPY 200일선 아래", COST)  # noqa: E712
            R.say(f"   (반 나눔 기준일 {h}) 마지막 매도 이유 {dict(Counter(x.split(' / ')[-1].rsplit(' ', 1)[0] for x in T.reason))} · "
                  f"산 날 손절 {(T.hold == 0).sum()} · 손절폭 중앙 {T.s.median():.2%} ADR 중앙 {T.adr.median():.2%} · 1시간봉 없어 일봉으로 대신한 보유일 {int(T.nodata.sum())}")
            if key == "B":
                for y, g in T.groupby(T.date.map(lambda x: x.year)):
                    v = g.gross - COST
                    R.say(f"     {y}: {len(g):3d}건 건당 {v.mean():+.2%} 합계 {v.sum():+.0%} 승률 {np.mean(v > 0):.0%}")
            T.drop(columns=["legs"]).to_csv(os.path.join(OUT, f"trades_{key}_{int(pct * 100)}.csv"), index=False, encoding="utf-8-sig")

    R.say("\n=== 계좌 시뮬: 10만 달러 · 동시 5종목 · 종목당 min(20%, 잔고 1% ÷ 손절폭) · 비용 0.1% · 같은 기간 SPY 그냥 보유와 비교 ===")
    for pct in (0.02, 0.10):
        for key, nm in (("A", "A안"), ("Ac", "A안 보수적"), ("B", "B안")):
            T = results[pct][key]
            for filt in (False, True):
                if len(T) == 0:
                    continue
                TT = (T[T.spy50 == True] if filt else T).reset_index(drop=True)   # noqa: E712
                end = a_end if key != "B" else b_end
                a = account(TT, cal, end, px, COST, spy_close)
                if a is None:
                    R.say(f"  상위 {pct:.0%} {nm}{' SPY50 위만' if filt else ''}: 0건"); continue
                R.say(f"  상위 {pct:.0%} {nm:6s}{' SPY50 위만' if filt else ' 전체     '}: {a['first']}~{a['last']} 최종 ${a['final']:,.0f} ({a['ret']:+.0%}, 연 {a['cagr']:+.1%}) "
                      f"최대 낙폭 {a['mdd']:.0%} | SPY 보유 {a['sp_ret']:+.0%} (연 {a['sp_cagr']:+.1%}, 낙폭 {a['sp_mdd']:.0%}) | 못 산 {a['skipped']}")
                if not filt:
                    a["curve"].to_csv(os.path.join(OUT, f"account_{key}_{int(pct * 100)}.csv"), encoding="utf-8-sig")

    R.say("\n=== 샘플 3건 (원자료 대조용: 가격은 수정 기준, 괄호는 야후 원가격) ===")
    T = results[0.02]["A"]
    if len(T):
        for _, x in T.sort_values("gross").iloc[[0, len(T) // 2, -1]].iterrows():
            A = px.a[x.sym]; i = A["pos"][x.date]; f = A["F"][i]
            R.say(f"  {x.date} {x.sym} 매수 {pd.Timestamp(x.buy_ts):%H:%M} {x.buy:.2f} (원 {x.buy / f:.2f}) 손절 {x.stop:.2f} (원 {x.stop / f:.2f}) "
                  f"윗선 {x.res:.2f} 60분고 {x.orh:.2f} (원 {x.orh / f:.2f}) 구간 {x.blen}일 → {x.exit_date} {x.gross - COST:+.1%} | {x.reason}")
            R.say("     그날 1시간봉(원가격): " + " ".join(f"{ts:%H:%M} o{o:.2f} h{h:.2f} l{l:.2f}" for ts, o, h, l, c in H[x.sym][x.date]))
            R.say(f"     adjclose/close = {f:.4f}")
    for pct in (0.02,):
        for key in ("A", "B"):
            T = results[pct][key]
            if not len(T):
                continue
            R.say(f"\n매매 목록 (상위 {pct:.0%} · {key}안{' — 최근 40건' if key == 'B' else ''})")
            TT = T.sort_values("date")
            if key == "B":
                TT = TT.tail(40)
            for _, x in TT.iterrows():
                o = f" 60분고 {x.orh:.2f}" if key == "A" else ""
                R.say(f"  {x.date} {x.sym:6s} {pd.Timestamp(x.buy_ts):%H:%M} 매수 {x.buy:.2f} 손절 {x.stop:.2f}({x.s:.1%}, ADR {x.adr:.1%}) 윗선 {x.res:.2f}{o} "
                      f"구간 {x.blen}일 SPY50 {'위' if x.spy50 else '아래'} → {x.exit_date} {x.gross - COST:+.1%} | {x.reason}")


if __name__ == "__main__":
    main()
