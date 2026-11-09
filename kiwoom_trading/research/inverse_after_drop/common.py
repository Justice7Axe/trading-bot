"""급락 다음 날 인버스 검증 공용 (2026-11-09 사용자 '한번 급락하면 다음 날 기계적 반등 → 장 초 인버스는 손실 자초').

자료 (모두 읽기 전용):
- 지수 일봉 idx_daily (코스피 001·코스닥 101·코스피200 201, 2021-11~), 지수 1분봉 idx_min (2025-10~)
- TIGER 인버스(123310) 1분봉: data/backtest/playbook/inv_bars.pkl (2025-10-15~2026-10-20) + daily_ohlcv.duckdb minute_ohlcv KRX (10-23 뒤 일부 날)
- 1분봉이 없는 날은 코스피200 1분봉으로 만든 '대용 인버스'(1배 인버스 = 하루 안에서 코스피200 등락의 반대) — 있는 날로 맞는지 확인
- 시장 상황 4구분: backtest/playbook/regime.cls (regime_feat 2025-10-15~2026-10-23) + 10-23 뒤는 스캐너 기록(market_regime·paper_trades)
"""
import os
import pickle
from collections import defaultdict
from datetime import date, time

import duckdb
import numpy as np

ROOT = r"D:\Ellie\trading"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "inverse_after_drop")
os.makedirs(OUT, exist_ok=True)
COST = 0.0005          # ETF 왕복 (거래세 없음)
SPLIT = date(2026, 4, 20)


def ro(p):
    return duckdb.connect(p, read_only=True)


IDX = ro(os.path.join(DATA, "index.duckdb"))


def idx_daily(code):
    rows = IDX.execute("SELECT date, open, high, low, close FROM idx_daily WHERE code=? ORDER BY date", [code]).fetchall()
    return [dict(date=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in rows]


def idx_min(code):
    by = defaultdict(list)
    for ts, o, h, l, c in IDX.execute("SELECT ts, open, high, low, close FROM idx_min WHERE code=? ORDER BY ts", [code]).fetchall():
        by[ts.date()].append(dict(ts=ts, open=o, high=h, low=l, close=c))
    return by


def inv_real():
    """{날짜: 인버스 KRX 1분봉 list}"""
    inv = {d: v for d, v in pickle.load(open(os.path.join(DATA, "backtest", "playbook", "inv_bars.pkl"), "rb")).items() if v}
    c = ro(os.path.join(DATA, "daily_ohlcv.duckdb"))
    for ts, o, h, l, cl, v in c.execute("SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code='123310' AND exchange='KRX' "
                                        "AND ts >= '2026-10-21' ORDER BY ts").fetchall():
        inv.setdefault(ts.date(), []).append(dict(ts=ts, open=o, high=h, low=l, close=cl, volume=v))
    c.close()
    return inv


K200D = {r["date"]: r for r in idx_daily("201")}
K200DAYS = sorted(K200D)
K200M = idx_min("201")


def inv_proxy(d):
    """코스피200 1분봉 → 대용 인버스 (전날 종가 = 1.0). 고가·저가는 뒤집음."""
    i = K200DAYS.index(d)
    if i == 0 or d not in K200M:
        return None
    pc = K200D[K200DAYS[i - 1]]["close"]
    f = lambda x: 2 - x / pc
    return [dict(ts=b["ts"], open=f(b["open"]), high=f(b["low"]), low=f(b["high"]), close=f(b["close"])) for b in K200M[d]]


def proxy_next_open_ratio(d):
    """d 대용 인버스 종가 대비 다음 거래일 시가 비율 (코스피200 일봉)."""
    i = K200DAYS.index(d)
    if i + 1 >= len(K200DAYS):
        return None
    c, o = K200D[d]["close"], K200D[K200DAYS[i + 1]]["open"]
    return 2 - o / c


INV = inv_real()
INV_DAYS = sorted(INV)


def bars_for(d, use_real=True):
    if use_real and d in INV:
        return INV[d], "real"
    b = inv_proxy(d)
    return (b, "proxy") if b else (None, None)


def next_open_ratio(d, use_real=True):
    """d 매수분을 다음 거래일 09:00 시가에 팔 때: 다음 날 시가 ÷ d 의 마지막 정규장 봉 종가."""
    i = K200DAYS.index(d)
    if i + 1 >= len(K200DAYS):
        return None, None
    nd = K200DAYS[i + 1]
    if use_real and d in INV and nd in INV:
        last = [b for b in INV[d] if b["ts"].time() <= time(15, 30)][-1]["close"]
        return INV[nd][0]["open"] / last, "real"
    return proxy_next_open_ratio(d), "proxy"


def trade(d, entry=time(9, 11), tp=0.05, sl=0.03, use_real=True, exit_mode="next"):
    """⑤ 규칙 재현 (events_15._inv_trade 와 같음): entry 시각 첫 봉 시가 매수, 손절 먼저, 15:20 전까지 못 닿으면 다음 날 09:00.
    exit_mode='close' 면 15:19 봉 종가 정리 (인버스 갭 규칙). 반환 (수익률, 자료 종류, 청산 시각 or None)."""
    bars, src = bars_for(d, use_real)
    if not bars:
        return None, None, None
    k = next((j for j, b in enumerate(bars) if b["ts"].time() >= entry), None)
    if k is None:
        return None, None, None
    e = bars[k]["open"]
    hi = e * (1 + tp) if tp else None
    lo = e * (1 - sl) if sl else None
    last = None
    for b in bars[k:]:
        if b["ts"].time() >= time(15, 20):
            break
        last = b
        if lo and b["low"] <= lo:
            return min(b["open"], lo) / e - 1 - COST, src, b["ts"].time()
        if hi and b["high"] >= hi:
            return max(b["open"], hi) / e - 1 - COST, src, b["ts"].time()
    if exit_mode == "close":
        return last["close"] / e - 1 - COST, src, time(15, 19)
    r, s2 = next_open_ratio(d, use_real)
    if r is None:
        return None, None, None
    lastc = [b for b in bars if b["ts"].time() <= time(15, 30)][-1]["close"]
    return lastc * r / e - 1 - COST, (src if s2 == src else "mix"), None


def summ(tr):
    """tr = [(date, ret)] → 건수·건당·합계(100만/건, 만 원)·앞/뒤·승률·최고 5일 빼면·★"""
    if not tr:
        return dict(n=0, mean=0, sum=0, a=None, b=None, win=0, ex5=0, star=False, worst=0)
    v = np.array([x for _, x in tr])
    a = [x for d, x in tr if d < SPLIT]; b = [x for d, x in tr if d >= SPLIT]
    s = sorted(v, reverse=True)
    ex5 = float(sum(s[5:]))
    ma = float(np.mean(a)) if a else None; mb = float(np.mean(b)) if b else None
    return dict(n=len(v), mean=float(v.mean()), sum=float(v.sum() * 100), a=ma, b=mb, na=len(a), nb=len(b), win=float((v > 0).mean()),
                ex5=ex5 * 100, worst=float(v.min()), star=bool(ma and mb and ma > 0 and mb > 0 and ex5 > 0))


def fmt(s):
    if not s["n"]:
        return "0건"
    pa = f"{s['a']:+.2%}({s['na']})" if s["a"] is not None else "—"
    pb = f"{s['b']:+.2%}({s['nb']})" if s["b"] is not None else "—"
    return (f"{'★' if s['star'] else ' '} {s['n']:3d}건 건당 {s['mean']:+.2%} 합계 {s['sum']:+5.0f}만 | 앞 {pa} 뒤 {pb} | 승률 {s['win']:.0%} "
            f"| 최고5건 빼면 {s['ex5']:+4.0f}만 | 최악 {s['worst']:+.1%}")
