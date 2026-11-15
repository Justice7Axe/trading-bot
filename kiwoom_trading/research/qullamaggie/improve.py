"""🏄 쿨라매기 돌파 — 무엇을 바꾸면 '우연이 아닌' 수익이 나는지 찾기 (2026-11-15 사용자 텔레그램
'역으로 이 쿨라매기 매매 방법을 이용해서 수익을 내려 하면 이 매매 기법에서 무엇을 업데이트해야 하는지 찾아줘').

미국(us_bt.py 자료·규칙 재사용) — 과최적화 막는 순서
 1) 진단: B안(일봉) 고르는 기간 2017~2021 매매만 쪼갬 (손절폭·ADR·구간 길이·폭·선행 상승·갭·SPY 10/20/50일선·기울기·업종·거래량,
    산 뒤 최고·최저(MFE/MAE), 매도 규칙별 차이).
 2) 후보 시험: 고르는 기간(2017~2021)에서만 하나씩 바꿔 보고(단일 변경), 그중 좋은 것만 겹쳐 봄(욕심 쌓기). 시험한 조합 수를 모두 셈.
 3) 고른 규칙을 손대지 않고 확인 기간(2022~2026) B안, A안(1시간봉 2년), 한국(improve_kr.py)에 그대로 적용.
 고르는 기준: 고르는 기간 건수 ≥ 80 · ★(앞 반·뒤 반 모두 +, 최고 5건 빼도 +) · 건당 수익의 t값(평균 ÷ 표준오차) 최고.

실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv/Scripts/python.exe kiwoom_trading/research/qullamaggie/improve.py
출력: data/qullamaggie_us/improve.txt · improve_selected.json (한국 확인용 규칙) · improve_trades_*.csv · sectors.json(업종 캐시)
기존 backtest.txt·trades_*.csv 는 건드리지 않음.
"""
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\Ellie\trading")
from kiwoom_trading.research.qullamaggie import us_bt as U   # noqa: E402

OUT = U.OUT
COST = 0.001
IS_END = date(2021, 12, 31)          # 고르는 기간 끝 (B안)
MIN_N = 80


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = None      # main() 에서 만듦 (improve_kr.py 가 import 해도 결과 파일을 지우지 않게)


# ---------------------------------------------------------------- 업종 (위키백과 S&P 500 표, 캐시)
def sectors():
    p = os.path.join(OUT, "sectors.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    out = {}
    try:
        h = U.http("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        m = re.search(r'<table class="[^"]*wikitable[^>]*>(.*?)</table>', h, re.S)
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S)
        head = [re.sub("<[^>]+>", "", x).strip() for x in re.findall(r"<th[^>]*>(.*?)</th>", trs[0], re.S)]
        cs, cg = head.index("Symbol"), next(k for k, x in enumerate(head) if "Sector" in x)
        for tr in trs[1:]:
            tds = [re.sub("<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) > max(cs, cg):
                out[tds[cs].replace(".", "-")] = tds[cg]
    except Exception as e:                    # noqa: BLE001
        print("업종 못 받음", e)
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return out


# ---------------------------------------------------------------- 자료 준비
def prepare(d):
    d = U.prepare(d)
    g = d.groupby("sym", sort=False)
    d["v50"] = g.volume.transform(lambda s: s.rolling(50).mean())
    d["v5"] = g.volume.transform(lambda s: s.rolling(5).mean())
    d["dvx"] = d.close * d.volume
    d["dv20"] = d.groupby("sym", sort=False).dvx.transform(lambda s: s.rolling(20).mean())
    d["ma50s"] = g.ma50.transform(lambda s: s - s.shift(5))          # 50일선 5일 기울기
    return d


class Px:
    def __init__(self, d):
        self.a = {}
        for s, g in d.groupby("sym", sort=False):
            g = g.reset_index(drop=True)
            self.a[s] = dict(date=list(g.date), pos={x: i for i, x in enumerate(g.date)},
                             O=g.open.values, H=g.high.values, L=g.low.values, C=g.close.values, F=g.f.values, V=g.volume.values,
                             MA10=g.ma10.values, MA20=g.ma20.values, MA50=g.ma50.values, MA50S=g.ma50s.values, ADR=g.adr20.values,
                             V50=g.v50.values, V5=g.v5.values, DV20=g.dv20.values,
                             R21=g.r21.values, R63=g.r63.values, R126=g.r126.values)


def find_base(A, k, width=U.BASE_WIDTH):
    """us_bt.find_base 와 같음 + (구간 길이, 윗선, 구간 저점, 뒤 절반 폭). width = 구간 폭 상한 (기본 25%)."""
    H, L, C, MA20 = A["H"], A["L"], A["C"], A["MA20"]
    if k < 45:
        return None
    if not all(C[i] > MA20[i] for i in range(k - 4, k + 1)):
        return None
    for Lb in range(U.BASE_MAX, U.BASE_MIN - 1, -1):
        s0 = k - Lb + 1
        hi, lo = H[s0:k + 1].max(), L[s0:k + 1].min()
        if hi / lo - 1 > width:
            continue
        m = s0 + Lb // 2
        la, lb_ = L[s0:m].min(), L[m:k + 1].min()
        wa = H[s0:m].max() / la - 1; wb = H[m:k + 1].max() / lb_ - 1
        if wb < wa and lb_ > la:
            return Lb, hi, lo, wb
    return None


def candidates(d, px, cal, start, end, width=U.BASE_WIDTH):
    """매수일 D 별 후보 (전날 일봉만). pool = 2 (상위 2%) / 10 (상위 10% 에만 듦)."""
    wide = {n: d.pivot(index="date", columns="sym", values=f"r{n}") for n in U.PERIODS}
    r63 = wide[63]
    c = d.pivot(index="date", columns="sym", values="close"); m20 = d.pivot(index="date", columns="sym", values="ma20")
    dvw = d.pivot(index="date", columns="sym", values="dv20")
    out = []
    for i in range(1, len(cal)):
        D, p = cal[i], cal[i - 1]
        if D < start or D > end or p not in r63.index:
            continue
        sel = {}
        for pct in (0.10, 0.02):
            ok = set()
            for n in U.PERIODS:
                v = wide[n].loc[p].dropna()
                if len(v) < 50:
                    continue
                k = int(math.ceil(len(v) * pct))
                thr = v.nlargest(k).min()
                ok |= set(v[v >= thr].index)
            for s in ok:
                sel[s] = int(pct * 100)
        row63, rc, rm = r63.loc[p], c.loc[p], m20.loc[p]
        dvr = dvw.loc[p].rank(pct=True)
        for s in sorted(sel):
            if not (row63.get(s, np.nan) >= U.MIN_GAIN63 and rc.get(s, np.nan) > rm.get(s, np.nan)):
                continue
            A = px.a[s]; k = A["pos"].get(p)
            if k is None:
                continue
            b = find_base(A, k, width)
            if b is None:
                continue
            out.append(dict(D=D, sym=s, res=b[1], blen=b[0], bw=b[1] / b[2] - 1, bwb=b[3], pool=sel[s], k=k,
                            adr=float(A["ADR"][k]), r21=A["R21"][k], r63=A["R63"][k], r126=A["R126"][k],
                            volc=A["V5"][k] / A["V50"][k] if A["V50"][k] > 0 else np.nan,
                            dvr=float(dvr.get(s, np.nan)), ma50up=bool(A["MA50S"][k] > 0),
                            ext10=A["C"][k] / A["MA10"][k] - 1, near=A["C"][k] / b[1] - 1))
    return out


# ---------------------------------------------------------------- 매도 (매도 규칙을 바꿀 수 있게 us_bt.simulate 를 넓힘)
EXITS = {
    "E0 지금(5일째 절반·본전·10일선)": dict(half=5, be=True, ma="MA10"),
    "E1 본전 손절 없앰": dict(half=5, be=False, ma="MA10"),
    "E2 절반 안 팖(10일선만)": dict(half=None, be=False, ma="MA10"),
    "E3 20일선 트레일": dict(half=5, be=True, ma="MA20"),
    "E4 절반 안 팖·20일선": dict(half=None, be=False, ma="MA20"),
    "E5 3일째 절반": dict(half=3, be=True, ma="MA10"),
    "E6 본전 없앰·20일선": dict(half=5, be=False, ma="MA20"),
    "E7 10일선은 절반 판 뒤부터": dict(half=5, be=True, ma="MA10", ma_from=5),
}


def simulate(A, D, buy, stop, end, bars_of, rest, cfg):
    half_day, be, ma, ma_from = cfg.get("half"), cfg.get("be", True), cfg.get("ma", "MA10"), cfg.get("ma_from", 1)
    legs = []; rem = 1.0; half = False; pend = False; cur = stop; k_day = 0
    i = A["pos"][D]
    while rem > 1e-9:
        if i >= len(A["date"]):
            break
        dt = A["date"][i]
        if dt > end:
            break
        k_day += 1
        if dt == D:
            for ts, o, h, l, c in rest:
                if l <= cur:
                    legs.append((ts, rem, min(o, cur), "손절")); rem = 0; break
            if rem <= 0:
                break
        else:
            bb = bars_of(dt)
            if bb is None:
                bb = [(datetime.combine(dt, datetime.min.time()).replace(hour=9, minute=30), A["O"][i], A["H"][i], A["L"][i], A["C"][i])]
            ts0, o0 = bb[0][0], bb[0][1]
            if o0 <= cur:
                legs.append((ts0, rem, o0, "본전 손절(갭)" if (half and be) else "손절(갭)")); rem = 0; break
            if pend:
                legs.append((ts0, rem, o0, "이평 이탈")); rem = 0; break
            if half_day and k_day == half_day and not half:
                legs.append((ts0, 0.5, o0, "절반")); rem -= 0.5; half = True
                if be:
                    cur = buy
                if o0 <= cur:
                    legs.append((ts0, rem, o0, "본전 손절")); rem = 0; break
            hit = False
            for n, (ts, o, h, l, c) in enumerate(bb):
                if l <= cur:
                    px_ = cur if n == 0 else min(o, cur)
                    legs.append((ts.replace(hour=12, minute=0) if len(bb) == 1 else ts, rem, px_, "본전 손절" if (half and be) else "손절"))
                    rem = 0; hit = True; break
            if hit:
                break
        m = A[ma][i]
        if k_day >= ma_from and np.isfinite(m) and A["C"][i] < m:
            pend = True
        i += 1
    if rem > 1e-9:
        j = min(i, len(A["date"])) - 1
        while A["date"][j] > end:
            j -= 1
        legs.append((datetime.combine(A["date"][j], datetime.min.time()).replace(hour=16), rem, A["C"][j], "미청산(평가)"))
    return legs


def mfe_mae(A, i, buy, n=20):
    """산 날 포함 n거래일 동안 최고가·최저가 (수정 기준, % ). 산 날 고·저는 매수 앞뒤 순서를 몰라 포함."""
    j = min(i + n, len(A["H"]))
    return A["H"][i:j].max() / buy - 1, A["L"][i:j].min() / buy - 1


# ---------------------------------------------------------------- 진입 (B: 일봉 / A: 1시간봉) — 거르기 전 한 번만 계산
def entries_B(px, cands, spyf, sec):
    out = []
    for c in cands:
        A = px.a[c["sym"]]; i = A["pos"].get(c["D"])
        if i is None or i == 0 or not A["H"][i] > c["res"]:
            continue
        buy = max(c["res"], A["O"][i]); stop = A["L"][i - 1]
        s = (buy - stop) / buy
        if s > c["adr"] or s <= 0:
            continue
        e = dict(c); e.update(buy=buy, stop=stop, s=s, i=i, gap=A["O"][i] / A["C"][i - 1] - 1, gap_above=bool(A["O"][i] > c["res"]),
                              dvol=A["V"][i] / A["V50"][i - 1] if A["V50"][i - 1] > 0 else np.nan,   # ※ 그날 전체 거래량 → 미래 정보, 진단만
                              buy_ts=datetime.combine(c["D"], datetime.min.time()).replace(hour=10), sector=sec.get(c["sym"], "?"),
                              s_adr=s / c["adr"], btime=None, rvol=np.nan)
        e.update(spyf.get(c["D"], {}))
        e["mfe"], e["mae"] = mfe_mae(A, i, buy)
        e["rest"] = [(e["buy_ts"].replace(hour=12), A["O"][i], A["H"][i], A["L"][i], A["C"][i])]
        out.append(e)
    return out


def entries_A(px, cands, spyf, sec, H, HV):
    out = []
    for c in cands:
        s_ = c["sym"]; A = px.a[s_]; i = A["pos"].get(c["D"])
        hb = H.get(s_, {}).get(c["D"])
        if i is None or hb is None or len(hb) < 5:
            continue
        f = A["F"][i]
        bars = [(ts, o * f, h * f, l * f, cl * f, v) for ts, o, h, l, cl, v in hb]
        if bars[0][0].hour != 9 or bars[0][0].minute != 30:
            continue
        orh = bars[0][2]; trig = max(c["res"], orh)
        j = next((k for k in range(1, len(bars)) if bars[k][2] > trig), None)
        if j is None:
            continue
        buy = max(bars[j][1], trig)
        stop = min(min(b[3] for b in bars[:j]), bars[j][1])
        s = (buy - stop) / buy
        if s > c["adr"] or s <= 0:
            continue
        adv = HV.get(s_, {}).get(c["D"])
        cumv = sum(b[5] for b in bars[:j + 1])
        frac = min(1.0, (j + 1) / 6.5)
        e = dict(c); e.update(buy=buy, stop=stop, s=s, i=i, gap=A["O"][i] / A["C"][i - 1] - 1, gap_above=bool(A["O"][i] > c["res"]),
                              dvol=np.nan, buy_ts=bars[j][0], sector=sec.get(s_, "?"), s_adr=s / c["adr"],
                              btime=bars[j][0].hour * 60 + bars[j][0].minute, rvol=cumv / (adv * frac) if adv else np.nan, orh=orh)
        e.update(spyf.get(c["D"], {}))
        e["mfe"], e["mae"] = mfe_mae(A, i, buy)
        e["rest"] = [b[:5] for b in bars[j + 1:]]
        out.append(e)
    return out


# ---------------------------------------------------------------- 거르기 규칙 (한국과 같은 이름·같은 칸)
FILTERS = {
    "ADR ≥ 3%": lambda e: e["adr"] >= 0.03,
    "ADR ≥ 3.5%": lambda e: e["adr"] >= 0.035,
    "ADR ≥ 4%": lambda e: e["adr"] >= 0.04,
    "ADR ≥ 5%": lambda e: e["adr"] >= 0.05,
    "손절폭 ≤ ADR×0.5": lambda e: e["s_adr"] <= 0.5,
    "손절폭 ≤ ADR×0.75": lambda e: e["s_adr"] <= 0.75,
    "손절폭 ≥ 1%": lambda e: e["s"] >= 0.01,
    "손절폭 ≥ 2%": lambda e: e["s"] >= 0.02,
    "구간 폭 ≤ 10%": lambda e: e["bw"] <= 0.10,
    "구간 폭 ≤ 15%": lambda e: e["bw"] <= 0.15,
    "구간 폭 ≤ 20%": lambda e: e["bw"] <= 0.20,
    "구간 뒤 절반 폭 ≤ 7%": lambda e: e["bwb"] <= 0.07,
    "구간 ≥ 15일": lambda e: e["blen"] >= 15,
    "구간 ≤ 20일": lambda e: e["blen"] <= 20,
    "63일 상승 ≥ 50%": lambda e: e["r63"] >= 0.50,
    "63일 상승 ≥ 75%": lambda e: e["r63"] >= 0.75,
    "63일 상승 ≤ 50%": lambda e: e["r63"] <= 0.50,
    "갭 상승 출발 뺌(시가 > 윗선)": lambda e: not e["gap_above"],
    "시가 갭 ≤ +2%": lambda e: e["gap"] <= 0.02,
    "지수 > 10·20일선": lambda e: bool(e.get("m10") and e.get("m20")),
    "지수 > 10·20일선 & 둘 다 오름": lambda e: bool(e.get("m10") and e.get("m20") and e.get("u10") and e.get("u20")),
    "지수 > 50일선": lambda e: bool(e.get("m50")),
    "지수 10일선 오름": lambda e: bool(e.get("u10")),
    "지수 < 50일선(반대 확인)": lambda e: e.get("m50") is False,
    "거래 대금 상위 절반": lambda e: e["dvr"] >= 0.5,
    "구간 거래량 마름(5일/50일 < 0.8)": lambda e: e["volc"] < 0.8,
    "종목 50일선 오름": lambda e: e["ma50up"],
    "10일선과 거리 ≤ 5%": lambda e: e["ext10"] <= 0.05,
}
INTRADAY = {     # 1시간봉·1분봉에만 있는 칸 (B안에서는 고를 수 없음 → A 앞 1년 고르고 A 뒤 1년·한국 확인)
    "돌파 때 거래량 ≥ 평소 1.5배(시각 보정)": lambda e: e["rvol"] >= 1.5,
    "돌파 때 거래량 ≥ 평소 2배(시각 보정)": lambda e: e["rvol"] >= 2.0,
    "돌파 때 거래량 ≥ 평소 3배(시각 보정)": lambda e: e["rvol"] >= 3.0,
    "장 초 돌파만(US 10:30봉·KR 10:00 전)": lambda e: e["early"],
}


def run(entries, filt, ecfg, end, px, bars_maker, cache, pool=2):
    """거르기 → 들고 있는 중 확인 → 매도 경로. cache[(id, exit)] = legs."""
    trades = []; held = {}
    for e in entries:
        if e["pool"] > pool or not filt(e):
            continue
        s = e["sym"]
        if held.get(s) and held[s] >= e["D"]:
            continue
        key = (id(e), json.dumps(ecfg, sort_keys=True), end)
        if key not in cache:
            cache[key] = simulate(px.a[s], e["D"], e["buy"], e["stop"], end, bars_maker(s), e["rest"], ecfg)
        legs = cache[key]
        gross = sum(f * p / e["buy"] for _, f, p, _ in legs) - 1
        ex = pd.Timestamp(legs[-1][0]).date()
        held[s] = ex
        t = {k: v for k, v in e.items() if k != "rest"}
        t.update(gross=gross, legs=legs, exit_date=ex, last=legs[-1][3])
        trades.append(t)
    return pd.DataFrame(trades)


def stats(T, cost=COST):
    if len(T) == 0:
        return dict(n=0)
    T = T.sort_values("D", kind="stable")
    v = (T.gross - cost).values; r = v / np.maximum(T.s.values, 0.005)
    ds = sorted(set(T.D)); h = ds[len(ds) // 2]
    a, b = v[(T.D < h).values], v[(T.D >= h).values]
    eq = np.cumsum(v); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    win, loss = v[v > 0], v[v <= 0]
    payoff = win.mean() / -loss.mean() if len(win) and len(loss) else np.nan
    top5 = np.sort(v)[::-1][:5].sum()
    star = len(v) >= 15 and a.sum() > 0 and b.sum() > 0 and v.sum() - top5 > 0
    t = v.mean() / (v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 2 and v.std() > 0 else 0
    return dict(n=len(v), mean=v.mean(), sum=v.sum(), sumR=r.sum(), expR=r.mean(), payoff=payoff, win=np.mean(v > 0), mdd=mdd,
                a=a.sum(), b=b.sum(), na=len(a), nb=len(b), ex5=v.sum() - top5, star=star, t=t)


def line(title, st, w=44):
    if st.get("n", 0) == 0:
        return f"   {title:{w}s}    0건"
    return (f" {'★' if st['star'] else ' '} {title:{w}s} {st['n']:4d}건 건당 {st['mean']:+.2%} 합계 {st['sum']:+.0%}({st['sumR']:+.1f}R) "
            f"기대값 {st['expR']:+.2f}R 손익비 {st['payoff']:.2f} 승률 {st['win']:.0%} 낙폭 {st['mdd']:.0%} | 앞 {st['a']:+.0%} 뒤 {st['b']:+.0%} "
            f"| 최고5건 빼면 {st['ex5']:+.0%} | t {st['t']:+.2f}")


def bucket(R, T, col, bins, labels, title):
    R.say(f"  [{title}]")
    x = T[col]
    for lo, hi, lab in zip(bins[:-1], bins[1:], labels):
        g = T[(x >= lo) & (x < hi)]
        st = stats(g)
        if st["n"]:
            R.say(f"     {lab:16s} {st['n']:4d}건 건당 {st['mean']:+.2%} 기대값 {st['expR']:+.2f}R 합계 {st['sum']:+.0%} 승률 {st['win']:.0%} 손익비 {st['payoff']:.2f}")


def cat(R, T, col, title, order=None):
    R.say(f"  [{title}]")
    keys = order or sorted(T[col].dropna().unique(), key=str)
    for k in keys:
        g = T[T[col] == k]
        st = stats(g)
        if st["n"]:
            R.say(f"     {str(k):24s} {st['n']:4d}건 건당 {st['mean']:+.2%} 기대값 {st['expR']:+.2f}R 합계 {st['sum']:+.0%} 승률 {st['win']:.0%} 손익비 {st['payoff']:.2f}")


def compose(names):
    fs = [FILTERS.get(n) or INTRADAY.get(n) for n in names if n in FILTERS or n in INTRADAY]
    return lambda e: all(f(e) for f in fs)


# ================================================================ main
def main():
    global R
    R = Rep("improve.txt")
    sec = sectors()
    uni, src, d0, h0, fails = U.load()
    bad = (d0[["open", "high", "low", "close", "adjclose"]] <= 0).any(axis=1)
    d0 = d0[~bad]
    d = prepare(d0)
    spyd = d[d.sym == "SPY"].set_index("date")
    cal = list(spyd.index); cal_idx = {x: i for i, x in enumerate(cal)}
    d = d[d.date.isin(set(cal))]
    spyf = {}
    for k in range(2, len(cal)):            # 매수일 D 의 전날 SPY 기준
        p, pp = spyd.iloc[k - 1], spyd.iloc[k - 2]
        spyf[cal[k]] = dict(m10=bool(p.close > p.ma10), m20=bool(p.close > p.ma20), m50=bool(p.close > p.ma50) if np.isfinite(p.ma50) else None,
                            u10=bool(p.ma10 > pp.ma10), u20=bool(p.ma20 > pp.ma20))
    spy_close = spyd.close.to_dict()
    stocks_d = d[d.sym != "SPY"]
    px = Px(stocks_d)
    R.say(f"[자료] 미국 {len(uni)}종목 일봉 {len(d0):,}행 · 업종 {len(sec)}종목 (나스닥 100 추가분은 '?') · 비용 왕복 {COST:.1%}")

    # 1시간봉 (us_bt.main 과 같은 처리) + 거래량
    h0 = h0.copy(); h0["date"] = h0.ts.dt.date
    mins = h0.ts.dt.hour * 60 + h0.ts.dt.minute
    h0 = h0[(mins >= 570) & (mins <= 930)]
    H, HV = {}, {}
    dayvol = h0.groupby(["sym", "date"]).volume.sum()
    for s_, g in dayvol.groupby(level=0):
        vv = g.droplevel(0)
        adv = vv.rolling(20, min_periods=10).mean().shift(1)
        HV[s_] = adv.dropna().to_dict()
    for (s_, dt), g in h0.groupby(["sym", "date"], sort=False):
        H.setdefault(s_, {})[dt] = list(zip(list(g.ts.dt.to_pydatetime()), g.open.values, g.high.values, g.low.values, g.close.values, g.volume.values))
    hd = sorted(set(h0.date)); a_start, a_end = hd[0], min(hd[-1], cal[-1])
    b_start, b_end = cal[130], cal[-1]

    def bars_B(s):
        return lambda dt: None

    def bars_A(s):
        A = px.a[s]

        def f(dt):
            x = H.get(s, {}).get(dt)
            if x is None or len(x) < 5:
                return None
            ff = A["F"][A["pos"][dt]]
            return [(ts, o * ff, h * ff, l * ff, c * ff) for ts, o, h, l, c, v in x]
        return f

    WIDTHS = (0.25, 0.15, 0.12)      # 쉬는 구간 '정의'의 폭 상한 (0.25 = 지금 규칙). 0.15·0.12 는 더 좁은 구간을 직접 찾음
    EBw, EAw = {}, {}
    for w in WIDTHS:
        cw = candidates(stocks_d, px, cal, b_start, b_end, w)
        EBw[w] = entries_B(px, cw, spyf, sec)
        EAw[w] = entries_A(px, [c for c in cw if a_start <= c["D"] <= a_end], spyf, sec, H, HV)
        for e in EAw[w]:
            e["early"] = e["btime"] <= 10 * 60 + 30
        for e in EBw[w]:
            e["early"] = True
    EB, EA = EBw[0.25], EAw[0.25]
    ISw = {w: [e for e in EBw[w] if e["D"] <= IS_END] for w in WIDTHS}
    OOSw = {w: [e for e in EBw[w] if e["D"] > IS_END] for w in WIDTHS}
    EB_is, EB_oos = ISw[0.25], OOSw[0.25]
    R.say(f"[기간] B 고르는 기간 {b_start}~{IS_END} · B 확인 기간 2022-01-03~{b_end} · A(1시간봉) {a_start}~{a_end}")
    R.say(f"[진입 후보] B {len(EB)}건(상위 2% {sum(e['pool'] == 2 for e in EB)}) · A {len(EA)}건(상위 2% {sum(e['pool'] == 2 for e in EA)}) — 들고 있는 중 거르기 전")
    R.say("※ 생존 편향: 지금 S&P 500·나스닥 100 종목을 과거에 적용. 쿨라매기 원래 대상(미국 전체·작은 종목 포함, ADR 5%↑ 흔함)보다 훨씬 큰 종목만이라 ADR 이 작음.")

    cache = {}
    E0 = EXITS["E0 지금(5일째 절반·본전·10일선)"]
    ALL = lambda e: True                      # noqa: E731
    base_is = run(EB_is, ALL, E0, IS_END, px, bars_B, cache)
    # 확인 기간 매매가 고르는 기간 끝을 넘겨 들고 가면 안 되므로 고르는 기간 매매는 IS_END 에서 평가 마감 (미청산(평가))

    # ============================ 1. 진단 (고르는 기간 B만)
    R.say("\n" + "=" * 100)
    R.say("1. 진단 — B안(일봉) 고르는 기간 2017-05~2021-12 지금 규칙 매매를 쪼갬 (비용 0.1% 뺀 값)")
    R.say("=" * 100)
    R.say(line("고르는 기간 지금 규칙", stats(base_is)))
    T = base_is
    bucket(R, T, "s", [0, .01, .02, .03, .04, 1], ["<1%", "1~2%", "2~3%", "3~4%", "4%↑"], "손절폭")
    bucket(R, T, "s_adr", [0, .25, .5, .75, 1.01], ["ADR의 0~25%", "25~50%", "50~75%", "75~100%"], "손절폭 ÷ ADR")
    bucket(R, T, "adr", [0, .025, .03, .035, .04, .05, 1], ["<2.5%", "2.5~3%", "3~3.5%", "3.5~4%", "4~5%", "5%↑"], "ADR20")
    bucket(R, T, "blen", [10, 13, 16, 21, 31, 41], ["10~12일", "13~15일", "16~20일", "21~30일", "31~40일"], "쉬는 구간 길이")
    bucket(R, T, "bw", [0, .10, .15, .20, .26], ["≤10%", "10~15%", "15~20%", "20~25%"], "쉬는 구간 폭")
    bucket(R, T, "r63", [.3, .4, .5, .75, 1, 99], ["30~40%", "40~50%", "50~75%", "75~100%", "100%↑"], "63일 선행 상승")
    bucket(R, T, "gap", [-1, 0, .01, .02, .04, 9], ["갭 하락", "0~1%", "1~2%", "2~4%", "4%↑"], "시가 갭 (전날 종가 대비)")
    cat(R, T, "gap_above", "시가가 이미 윗선 위 (갭으로 돌파)", [False, True])
    bucket(R, T, "dvol", [0, 1, 1.5, 2, 3, 99], ["<1배", "1~1.5배", "1.5~2배", "2~3배", "3배↑"],
           "돌파 날 거래량 ÷ 50일 평균 ※그날 전체 거래량=장 마감 뒤에 앎(미래 정보), 진단만")
    bucket(R, T, "volc", [0, .6, .8, 1, 1.3, 99], ["<0.6", "0.6~0.8", "0.8~1", "1~1.3", "1.3↑"], "구간 거래량 마름 (5일 ÷ 50일 평균)")
    bucket(R, T, "dvr", [0, .25, .5, .75, 1.01], ["하위 25%", "25~50%", "50~75%", "상위 25%"], "거래 대금 순위 (유니버스 안)")
    bucket(R, T, "ext10", [-1, 0, .03, .05, .08, 9], ["10일선 아래", "0~3%", "3~5%", "5~8%", "8%↑"], "전날 종가와 10일선 거리")
    cat(R, T, "m10", "SPY > 10일선", [True, False]); cat(R, T, "m20", "SPY > 20일선", [True, False])
    cat(R, T, "m50", "SPY > 50일선", [True, False]); cat(R, T, "u10", "SPY 10일선 오름", [True, False]); cat(R, T, "u20", "SPY 20일선 오름", [True, False])
    T = T.assign(mk=[("10·20 위&오름" if (m1 and m2 and a1 and a2) else "10·20 위" if (m1 and m2) else "그 밖") for m1, m2, a1, a2 in zip(T.m10, T.m20, T.u10, T.u20)])
    cat(R, T, "mk", "SPY 상태 묶음", ["10·20 위&오름", "10·20 위", "그 밖"])
    cat(R, T, "ma50up", "종목 50일선 오름", [True, False])
    cat(R, T, "sector", "업종 (S&P 분류, 참고 — 업종 고르기는 과최적화라 후보로 안 씀)")
    cat(R, T, "last", "마지막 매도 이유", ["손절", "손절(갭)", "본전 손절", "본전 손절(갭)", "이평 이탈", "미청산(평가)"])

    # MFE / MAE
    R.say("\n  [산 뒤 20거래일 최고·최저 (MFE/MAE, R = 손절폭 배수)]")
    mfeR = T.mfe / T.s; maeR = T.mae / T.s
    for k in (1, 2, 3, 5, 10):
        R.say(f"     20일 안에 +{k}R 이상 올라간 매매 {np.mean(mfeR >= k):.0%}")
    R.say(f"     MFE 중앙 {T.mfe.median():+.1%} ({mfeR.median():.1f}R) · MAE 중앙 {T.mae.median():+.1%} ({maeR.median():.1f}R)")
    R.say(f"     산 날 손절 {np.mean(T.exit_date == T.D):.0%} · 손절된 매매 중 20일 안에 +2R 넘게 간 것 {np.mean(mfeR[T['last'].str.startswith('손절')] >= 2):.0%}")
    rr = (T.gross - COST) / T.s
    big = T[mfeR >= 3]
    R.say(f"     +3R 넘게 갔던 {len(big)}건이 실제로 남긴 것: 평균 {((big.gross - COST) / big.s).mean():+.2f}R (최고점 평균 {(big.mfe / big.s).mean():.1f}R)")
    be_ = T[T["last"].str.startswith("본전")]
    if len(be_):
        R.say(f"     본전 손절로 끝난 {len(be_)}건: 평균 {((be_.gross - COST) / be_.s).mean():+.2f}R, 20일 안 최고 평균 {(be_.mfe / be_.s).mean():.1f}R")

    # 매도 규칙별 (같은 진입)
    R.say("\n  [같은 진입 · 매도 규칙만 바꿈 (고르는 기간)]")
    for nm, cfg in EXITS.items():
        R.say(line(nm, stats(run(EB_is, ALL, cfg, IS_END, px, bars_B, cache))))

    # ============================ 2. 후보 시험 (고르는 기간만)
    R.say("\n" + "=" * 100)
    R.say(f"2. 후보 시험 — 고르는 기간(2017-05~2021-12) B안만 보고 고름. 1차 기준: 건수 ≥ {MIN_N} · ★ · t값 최고")
    R.say("=" * 100)
    tested = []
    E0N = "E0 지금(5일째 절반·본전·10일선)"

    def key_of(f, ex, pool, w):
        return (tuple(sorted(f)), ex, pool, w)
    seen = {}

    def ev(f, ex, pool=2, w=0.25):
        k = key_of(f, ex, pool, w)
        if k not in seen:
            T_ = run(ISw[w], compose(list(f)), EXITS[ex], IS_END, px, bars_B, cache, pool=pool)
            seen[k] = stats(T_)
            tested.append(k)
        return seen[k]

    def label(f, ex, pool, w):
        parts = list(f)
        if not ex.startswith("E0"):
            parts.append(ex)
        if pool == 10:
            parts.append("상승률 상위 10%까지")
        if w != 0.25:
            parts.append(f"쉬는 구간 정의 폭 ≤ {w:.0%}")
        return " + ".join(parts) or "지금 규칙"
    base_st = ev((), E0N)
    R.say(line("(기준) 지금 규칙", base_st))
    singles = []
    R.say("\n  [단일 변경: 거르기 하나]")
    for nm in FILTERS:
        singles.append(((nm,), E0N, 2, 0.25)); R.say(line(nm, ev((nm,), E0N)))
    R.say("\n  [단일 변경: 매도 하나]")
    for ex in list(EXITS)[1:]:
        singles.append(((), ex, 2, 0.25)); R.say(line(ex, ev((), ex)))
    R.say("\n  [단일 변경: 후보 범위·쉬는 구간 정의]")
    singles.append(((), E0N, 10, 0.25)); R.say(line("상승률 상위 10%까지 넓힘", ev((), E0N, 10)))
    for w in WIDTHS[1:]:
        singles.append(((), E0N, 2, w)); R.say(line(f"쉬는 구간 정의 폭 ≤ {w:.0%} (더 좁은 구간을 직접 찾음)", ev((), E0N, 2, w)))

    def merge(a, b):
        f = tuple(dict.fromkeys(list(a[0]) + list(b[0])))
        ex = b[1] if not b[1].startswith("E0") else a[1]
        pool = 10 if 10 in (a[2], b[2]) else 2
        w = b[3] if b[3] != 0.25 else a[3]
        return (f, ex, pool, w)

    def select(okf, title):
        """okf(st) → 통과 여부. 통과한 단일 변경을 t값 순으로, 맨 위에서 시작해 겹치기."""
        good = sorted([x for x in singles if okf(ev(*x)) and ev(*x)["t"] > base_st["t"]], key=lambda x: -ev(*x)["t"])
        R.say(f"\n  [{title}] 기준 t {base_st['t']:+.2f} 보다 높고 통과한 단일 변경 {len(good)}개 (t값 순):")
        for x in good:
            st = ev(*x); R.say(f"     {label(*x)[:60]:60s} t {st['t']:+.2f} · {st['n']}건 · 기대값 {st['expR']:+.2f}R · {'★' if st['star'] else '★ 아님'}")
        stack = []
        if good:
            cur = good[0]
            for step in range(3):
                best = None
                for x in singles:
                    nx = merge(cur, x)
                    if key_of(*nx) == key_of(*cur):
                        continue
                    st = ev(*nx)
                    if okf(st) and st["t"] > ev(*cur)["t"] and (best is None or st["t"] > ev(*best)["t"]):
                        best = nx
                if best is None:
                    R.say(f"     겹치기 {step + 2}개째: 더해서 t값이 오르는 것 없음 → 멈춤"); break
                cur = best; stack.append(cur)
                R.say(line(f"겹치기 {step + 2}개: {label(*cur)}"[:70], ev(*cur), 70))
        return good, stack

    good1, stack1 = select(lambda st: st.get("n", 0) >= MIN_N and st["star"], f"1차 기준(건수 ≥ {MIN_N} · ★)")
    # 2차 기준: 1차에서 아무것도 안 남을 때를 위해 덧붙임 (★ 를 따지지 않음).
    # ※ 이 기준은 1차 결과(0개)와 확인 기간 참고 표를 본 뒤 덧붙인 것 — 고르는 방식 자체는 고르는 기간 t값만 씀.
    good2, stack2 = select(lambda st: st.get("n", 0) >= MIN_N, f"2차 기준(건수 ≥ {MIN_N}만, ★ 안 따짐)")
    R.say(f"\n  ▶ 고르는 기간에서 시험한 조합 수: {len(tested)}개 (단일 {len(singles)}개 + 기준 1개 + 겹치기 {len(tested) - len(singles) - 1}개)")

    chosen = []
    for tag, good, stack in (("1차", good1, stack1), ("2차", good2, stack2)):
        for x in good[:3]:
            chosen.append(dict(name=f"{tag} 단일: {label(*x)}", filters=list(x[0]), exit=x[1], pool=x[2], width=x[3], kind=f"{tag}-single"))
        if stack:
            x = stack[-1]
            chosen.append(dict(name=f"{tag} 겹침: {label(*x)}", filters=list(x[0]), exit=x[1], pool=x[2], width=x[3], kind=f"{tag}-stack"))
    pri = (("ADR ≥ 3.5%", "지수 > 10·20일선 & 둘 다 오름"), "E3 20일선 트레일", 2, 0.15)
    chosen.append(dict(name="원래 방식 묶음(미리 정함): " + label(*pri), filters=list(pri[0]), exit=pri[1], pool=pri[2], width=pri[3], kind="prior"))
    ev(*pri)
    n_tested = len(tested)
    json.dump(dict(chosen=chosen, n_tested=n_tested), open(os.path.join(OUT, "improve_selected.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ============================ 3. 확인 (손대지 않음)
    R.say("\n" + "=" * 100)
    R.say("3. 확인 — 고른 규칙을 그대로 적용 (확인 기간 결과로 다시 고르지 않음)")
    R.say("=" * 100)
    rules = [dict(name="(기준) 지금 규칙", filters=[], exit=E0N, pool=2, width=0.25)] + chosen
    res = {}
    for rl in rules:
        f = compose(rl["filters"]); ex = EXITS[rl["exit"]]; w = rl["width"]
        Tis = run(ISw[w], f, ex, IS_END, px, bars_B, cache, rl["pool"])
        Too = run(OOSw[w], f, ex, b_end, px, bars_B, cache, rl["pool"])
        Ta = run(EAw[w], f, ex, a_end, px, bars_A, cache, rl["pool"])
        res[rl["name"]] = (Tis, Too, Ta)
        R.say(f"\n[{rl['name']}]")
        R.say(line("B 고르는 기간 2017~2021", stats(Tis)))
        R.say(line("B 확인 기간 2022~2026", stats(Too)))
        R.say(line("B 확인 기간 비용 0.25%", stats(Too, 0.0025)))
        R.say(line("A 1시간봉 2년 (손대지 않은 확인)", stats(Ta)))
        R.say(line("A 비용 0.25%", stats(Ta, 0.0025)))
        if len(Too):
            R.say("     확인 기간 해마다: " + " · ".join(f"{y} {len(g)}건 {(g.gross - COST).sum():+.0%}" for y, g in Too.groupby(Too.D.map(lambda x: x.year))))
            v = np.sort((Too.gross - COST).values)[::-1]
            R.say(f"     확인 기간 최고 10건 합 {v[:10].sum():+.0%} · 나머지 {len(v) - 10}건 합 {v[10:].sum():+.0%} · 마지막 매도 {dict(Counter(Too['last']))}")

    R.say("\n=== 계좌 시뮬: 10만 달러 · 동시 5종목 · 종목당 min(20%, 잔고 1% ÷ 손절폭) · 비용 0.1% · 같은 기간 SPY 보유와 비교 ===")
    for rl in rules:
        Tis, Too, Ta = res[rl["name"]]
        for nm, TT, end in (("B 고르는 기간", Tis, IS_END), ("B 확인 기간", Too, b_end), ("A 1시간봉", Ta, a_end)):
            if len(TT) == 0:
                R.say(f"  {rl['name'][:44]:44s} {nm}: 0건"); continue
            TT = TT.rename(columns={"D": "date"}).reset_index(drop=True)
            a = U.account(TT, cal, end, px, COST, spy_close)
            R.say(f"  {rl['name'][:44]:44s} {nm:10s}: {a['first']}~{a['last']} ${a['final']:,.0f} ({a['ret']:+.0%}, 연 {a['cagr']:+.1%}) 낙폭 {a['mdd']:.0%} "
                  f"| SPY {a['sp_ret']:+.0%} (연 {a['sp_cagr']:+.1%}, 낙폭 {a['sp_mdd']:.0%})")
        tag = re.sub(r"[^0-9A-Za-z가-힣]+", "_", rl["name"])[:30]
        for nm, TT in (("Bis", Tis), ("Boos", Too), ("A", Ta)):
            if len(TT):
                TT.drop(columns=["legs"]).to_csv(os.path.join(OUT, f"improve_trades_{tag}_{nm}.csv"), index=False, encoding="utf-8-sig")

    # ============================ 참고: 모든 단일 변경의 확인 기간 결과 (고르는 데 안 씀)
    R.say("\n" + "=" * 100)
    R.say("참고 — 모든 단일 변경의 확인 기간 결과 (선택에 쓰지 않음. 고르는 기간 순위가 확인 기간에도 이어지는지 보는 용도)")
    R.say("=" * 100)
    R.say(f"   {'변경':40s} {'고르는 기간':>30s} | {'확인 기간 B':>30s} | {'A 1시간봉':>30s}")
    rows = []

    def c_(x):
        return f"{x['n']:4d}건 {x['mean']:+.2%} {x['expR']:+.2f}R {'★' if x['star'] else ' '}" if x.get("n") else "   0건"
    for x in singles:
        st = ev(*x)
        ff = compose(list(x[0])); e_ = EXITS[x[1]]
        so = stats(run(OOSw[x[3]], ff, e_, b_end, px, bars_B, cache, x[2])); sa = stats(run(EAw[x[3]], ff, e_, a_end, px, bars_A, cache, x[2]))
        rows.append((st, so, sa))
        R.say(f"   {label(*x)[:40]:40s} {c_(st):>30s} | {c_(so):>30s} | {c_(sa):>30s}")
    bo = stats(run(EB_oos, ALL, E0, b_end, px, bars_B, cache)); ba = stats(run(EA, ALL, E0, a_end, px, bars_A, cache))
    R.say(f"   {'(기준) 지금 규칙':40s} {c_(base_st):>30s} | {c_(bo):>30s} | {c_(ba):>30s}")
    ok_ = [x for x in rows if x[0].get("n") and x[1].get("n")]
    di = np.array([x[0]["expR"] - base_st["expR"] for x in ok_]); do = np.array([x[1]["expR"] - bo["expR"] for x in ok_])
    rho = pd.Series(di).rank().corr(pd.Series(do).rank())
    R.say(f"\n   단일 변경 {len(di)}개의 '기준 대비 기대값 변화' 순위 상관 (고르는 기간 vs 확인 기간) = {rho:+.2f}  (1 에 가까우면 고르는 기간에서 좋던 것이 확인 기간에도 좋음)")
    R.say(f"   고르는 기간에서 기대값이 오른 변경 {int((di > 0).sum())}개 중 확인 기간에도 오른 것 {int(((di > 0) & (do > 0)).sum())}개")
    allp = [label(*singles[k]) for k, x in enumerate(rows) if x[0].get("n") and x[1].get("n") and x[2].get("n")
            and x[0]["expR"] > base_st["expR"] and x[1]["expR"] > bo["expR"] and x[2]["expR"] > ba["expR"] and min(x[0]["n"], x[1]["n"]) >= MIN_N]
    R.say(f"   세 곳(고르는 기간·확인 기간·A) 모두 기준보다 기대값이 높은 단일 변경(건수 ≥ {MIN_N}): {allp}")

    # ============================ 참고: 장중에만 있는 칸 (거래량·돌파 시각) — A 앞 1년에서 고르고 A 뒤 1년·한국에서 확인
    R.say("\n" + "=" * 100)
    R.say("참고 — 장중에만 아는 칸(돌파 때 거래량·돌파 시각): 일봉 10년에 없어 A 앞 1년(고름)·A 뒤 1년(확인)으로 나눔 (증거 약함)")
    R.say("=" * 100)
    a_mid = date(2025, 11, 14)
    EA1 = [e for e in EA if e["D"] < a_mid]; EA2 = [e for e in EA if e["D"] >= a_mid]
    TAall = run(EA, ALL, E0, a_end, px, bars_A, cache)
    bucket(R, TAall[TAall.D < a_mid], "rvol", [0, 1, 1.5, 2, 3, 99], ["<1배", "1~1.5배", "1.5~2배", "2~3배", "3배↑"], "A 앞 1년: 돌파 때 거래량 (시각 보정, ÷ 20일 평균)")
    bucket(R, TAall[TAall.D < a_mid], "btime", [600, 660, 720, 840, 990], ["10:30봉", "11:30봉", "12:30~13:30봉", "14:30~15:30봉"], "A 앞 1년: 돌파 봉 시각")
    intr_best = None
    for nm in INTRADAY:
        s1 = stats(run(EA1, compose([nm]), E0, a_mid, px, bars_A, cache)); s2 = stats(run(EA2, compose([nm]), E0, a_end, px, bars_A, cache))
        n_tested += 1
        R.say(line(f"{nm} — A 앞 1년", s1, 50)); R.say(line(f"{nm} — A 뒤 1년", s2, 50))
        if s1.get("n", 0) >= 30 and s1["star"] and (intr_best is None or s1["t"] > intr_best[1]["t"]):
            intr_best = (nm, s1)
    s1 = stats(run(EA1, ALL, E0, a_mid, px, bars_A, cache)); s2 = stats(run(EA2, ALL, E0, a_end, px, bars_A, cache))
    R.say(line("(기준) A 앞 1년", s1, 50)); R.say(line("(기준) A 뒤 1년", s2, 50))
    R.say(f"   A 앞 1년에서 고른 장중 칸: {intr_best[0] if intr_best else '없음 (30건↑·★ 인 것 없음)'}")
    sel = json.load(open(os.path.join(OUT, "improve_selected.json"), encoding="utf-8"))
    sel["intraday_pick"] = intr_best[0] if intr_best else None
    sel["n_tested_total_us"] = n_tested
    json.dump(sel, open(os.path.join(OUT, "improve_selected.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    R.say(f"\n▶ 미국에서 시험한 조합 수 합계 (참고 표 빼고 고르는 데 쓴 것): {n_tested}개")


if __name__ == "__main__":
    main()
