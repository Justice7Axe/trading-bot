"""합성(가짜) 1분봉 데이터 생성기. 코드가 돌아가는지 확인하는 용도이며, 수익성 판단에 쓰면 안 된다.

  python scripts/make_sample_data.py --out sample_data
생성물: sample_data/kr_1m.csv (가상 종목 6개, 코스닥형), sample_data/nq_1m.csv (ET 기준 RTH, buy/sell 거래량 포함)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import random


def _tick(p):
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < lim:
            return t
    return 1000


def _r(p, t=None):
    t = t or _tick(p)
    return round(p / t) * t


def weekdays(start, n):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def kr_day(rng, d, prev_close, regime):
    """regime: normal | inplay | capitulation_d"""
    rows = []
    gap = {"normal": rng.gauss(0, 0.01), "inplay": rng.uniform(0.04, 0.12),
           "capitulation_d": -rng.uniform(0.04, 0.08)}[regime]
    p = prev_close * (1 + gap)
    drift = {"normal": 0.0, "inplay": 0.0006, "capitulation_d": 0.0}[regime]
    vol_mult = {"normal": 1.0, "inplay": 6.0, "capitulation_d": 5.0}[regime]
    t = dt.datetime.combine(d, dt.time(9, 0))
    end = dt.datetime.combine(d, dt.time(15, 20))
    i = 0
    low_bar = rng.randint(10, 40)
    while t < end:
        sig = 0.002 if regime == "normal" else 0.004
        mu = drift
        if regime == "capitulation_d":
            mu = -0.002 if i < low_bar else 0.0012
        o = p
        c = o * math.exp(rng.gauss(mu, sig))
        h = max(o, c) * (1 + abs(rng.gauss(0, sig / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, sig / 2)))
        v = int(rng.lognormvariate(8, 0.6) * vol_mult * (2.5 if i < 30 else 1.0))
        if regime == "capitulation_d" and abs(i - low_bar) <= 1:
            v *= 8
        o, h, l, c = _r(o), _r(h), _r(l), _r(c)
        h, l = max(h, o, c), min(l, o, c)
        rows.append((t, o, h, l, c, v))
        p = c
        t += dt.timedelta(minutes=1)
        i += 1
    close_t = dt.datetime.combine(d, dt.time(15, 30))
    rows.append((close_t, p, p, p, p, int(rng.lognormvariate(9, 0.5))))
    return rows


def make_kr(path, n_sym=6, n_days=140, seed=7):
    rng = random.Random(seed)
    days = weekdays(dt.date(2025, 1, 2), n_days)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "symbol", "open", "high", "low", "close", "volume", "catalyst"])
        for s in range(n_sym):
            sym = f"SYM{s:02d}"
            pc = rng.choice([4500, 12000, 33000, 87000])
            cap_left = 0
            for d in days:
                if cap_left > 0:
                    regime = "capitulation_d" if cap_left == 1 else "normal"
                    rows = kr_day(rng, d, pc, regime)
                    if cap_left > 1:  # A,B,C 일: 대량 급락
                        drop = rng.uniform(0.05, 0.09)
                        k = len(rows)
                        rows = [(t, _r(o * (1 - drop * j / k)), _r(h * (1 - drop * j / k)), _r(l * (1 - drop * (j + 1) / k)),
                                 _r(c * (1 - drop * (j + 1) / k)), v * 3) for j, (t, o, h, l, c, v) in enumerate(rows)]
                        rows = [(t, o, max(o, h, c), min(o, l, c), c, v) for (t, o, h, l, c, v) in rows]
                    cap_left -= 1
                else:
                    x = rng.random()
                    if x < 0.03:
                        cap_left = 4
                        regime = "normal"
                    regime = "inplay" if x > 0.9 else "normal"
                    rows = kr_day(rng, d, pc, regime)
                cat = 1 if regime == "inplay" and rng.random() < 0.6 else 0
                for (t, o, h, l, c, v) in rows:
                    w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), sym, o, h, l, c, v, cat])
                pc = rows[-1][4]
                if pc > 150000 or pc < 1500:  # 합성 데이터 가격 폭주 방지(새 종목처럼 재시작)
                    pc = rng.choice([4500, 12000, 33000, 87000])


def make_nq(path, n_days=120, seed=11):
    rng = random.Random(seed)
    days = weekdays(dt.date(2025, 1, 2), n_days)
    p = 21000.0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["datetime", "symbol", "open", "high", "low", "close", "volume", "buy_volume", "sell_volume"])
        for d in days:
            t = dt.datetime.combine(d, dt.time(9, 30))
            trend = rng.choice([-1, 0, 0, 1]) * 0.00008
            p *= 1 + rng.gauss(0, 0.004)
            while t.time() < dt.time(16, 0):
                o = p
                c = o * (1 + rng.gauss(trend, 0.0007))
                h = max(o, c) + abs(rng.gauss(0, 3))
                l = min(o, c) - abs(rng.gauss(0, 3))
                o, h, l, c = (_r(x, 0.25) for x in (o, h, l, c))
                v = int(rng.lognormvariate(7, 0.5))
                share = min(max(0.5 + (c - o) / (h - l + 1e-9) * 0.4 + rng.gauss(0, 0.05), 0.05), 0.95)
                bv = int(v * share)
                w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), "NQ", o, h, l, c, v, bv, v - bv])
                p = c
                t += dt.timedelta(minutes=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sample_data")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    make_kr(os.path.join(a.out, "kr_1m.csv"))
    make_nq(os.path.join(a.out, "nq_1m.csv"))
    print("written:", a.out)
