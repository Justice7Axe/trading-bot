"""지표 함수 (리스트 기반, 표준 라이브러리만). 모든 값은 해당 바 '종가 시점'에 확정된 값이다."""
from __future__ import annotations

import math


def vwap(bars) -> list:
    out, pv, vv = [], 0.0, 0.0
    for b in bars:
        tp = (b.h + b.l + b.c) / 3
        pv += tp * b.v
        vv += b.v
        out.append(pv / vv if vv > 0 else b.c)
    return out


def sma(vals, n) -> list:
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(vals, n) -> list:
    out, k, e = [], 2 / (n + 1), None
    for v in vals:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def rsi(closes, n=14) -> list:
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    return out


def macd(closes, fast=12, slow=26, sig=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [a - b for a, b in zip(ef, es)]
    signal = ema(line, sig)
    hist = [a - b for a, b in zip(line, signal)]
    warm = slow + sig
    line = [None if i < warm else v for i, v in enumerate(line)]
    hist = [None if i < warm else v for i, v in enumerate(hist)]
    return line, signal, hist


def atr(bars, n=14) -> list:
    out, a = [], None
    for i, b in enumerate(bars):
        tr = b.h - b.l if i == 0 else max(b.h - b.l, abs(b.h - bars[i - 1].c), abs(b.l - bars[i - 1].c))
        a = tr if a is None else (a * (n - 1) + tr) / n
        out.append(a)
    return out


def pivot_lows(lows, left=3, right=3) -> list:
    """피벗 저점 인덱스 목록. 인덱스 k 의 피벗은 k+right 바 종가 시점에야 확정된다(룩어헤드 주의)."""
    res = []
    for k in range(left, len(lows) - right):
        w = lows[k - left:k + right + 1]
        if lows[k] == min(w) and w.count(lows[k]) == 1:
            res.append(k)
    return res


def pivot_highs(highs, left=3, right=3) -> list:
    res = []
    for k in range(left, len(highs) - right):
        w = highs[k - left:k + right + 1]
        if highs[k] == max(w) and w.count(highs[k]) == 1:
            res.append(k)
    return res


def bar_delta(b) -> float:
    """체결 델타. buy/sell 거래량이 있으면 실제값, 없으면 캔들 위치 기반 근사치(정확도 낮음)."""
    if b.buy_v is not None and b.sell_v is not None:
        return b.buy_v - b.sell_v
    rng = b.h - b.l
    return b.v * (b.c - b.o) / rng if rng > 0 else 0.0


def percentile(vals, q) -> float:
    s = sorted(vals)
    if not s:
        return math.inf
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class VolumeProfile:
    """가격대별 거래량. 각 바 거래량을 바의 고저 범위 bin 에 균등 분배(1분봉 근사)."""

    def __init__(self, bin_size: float):
        self.bin = bin_size
        self.vol: dict[int, float] = {}

    def key(self, price: float) -> int:
        return int(math.floor(price / self.bin + 1e-9))

    def add(self, b) -> None:
        lo, hi = self.key(b.l), self.key(b.h)
        n = hi - lo + 1
        for k in range(lo, hi + 1):
            self.vol[k] = self.vol.get(k, 0.0) + b.v / n

    def price(self, k: int) -> float:
        return (k + 0.5) * self.bin

    def poc(self):
        if not self.vol:
            return None
        return self.price(max(self.vol, key=lambda k: self.vol[k]))

    def value_area(self, pct=0.70):
        """(VAL, POC, VAH). POC 에서 양쪽으로 큰 쪽부터 확장."""
        if not self.vol:
            return None
        keys = sorted(self.vol)
        total = sum(self.vol.values())
        pk = max(self.vol, key=lambda k: self.vol[k])
        lo = hi = pk
        acc = self.vol[pk]
        kmin, kmax = keys[0], keys[-1]
        while acc < total * pct and (lo > kmin or hi < kmax):
            up = self.vol.get(hi + 1, 0.0) if hi < kmax else -1
            dn = self.vol.get(lo - 1, 0.0) if lo > kmin else -1
            if up >= dn:
                hi += 1
                acc += max(up, 0)
            else:
                lo -= 1
                acc += max(dn, 0)
        return self.price(lo) - self.bin / 2, self.price(pk), self.price(hi) + self.bin / 2

    def lvns(self, frac=0.35) -> list:
        """저거래량 노드 가격 목록: 중앙값*frac 미만이면서 양옆보다 작은 bin."""
        if len(self.vol) < 5:
            return []
        keys = sorted(self.vol)
        vals = sorted(self.vol.values())
        med = vals[len(vals) // 2]
        res = []
        for k in keys[1:-1]:
            v = self.vol.get(k, 0.0)
            if v < med * frac and v <= self.vol.get(k - 1, 0.0) and v <= self.vol.get(k + 1, 0.0):
                res.append(self.price(k))
        return res
