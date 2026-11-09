"""종목/상품 규칙: 호가단위, 비용, 슬리피지, 가격제한폭, VI 근사.

표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.normpath(os.path.join(HERE, "..", "config"))
INSTRUMENTS_PATH = os.path.join(CONFIG_DIR, "instruments.json")
DEFAULTS_PATH = os.path.join(CONFIG_DIR, "backtest_defaults.json")


def krx_stock_tick(price: float) -> float:
    """KRX 주식 호가단위 (2023-01-25 이후 코스피/코스닥 통일 기준).

    제도 변경 시 references/30-kr-market-structure.md 와 함께 수정할 것.
    """
    if price < 2000:
        return 1
    if price < 5000:
        return 5
    if price < 20000:
        return 10
    if price < 50000:
        return 50
    if price < 200000:
        return 100
    if price < 500000:
        return 500
    return 1000


@dataclass
class Instrument:
    name: str
    kind: str  # "stock" | "future"
    tick: float | None
    multiplier: float
    fee_rate: float
    fee_per_contract: float
    sell_tax_rate: float
    slippage_ticks: float
    session_start: str
    session_end: str
    flat_time: str
    price_limit_pct: float | None
    currency: str
    vi_static_pct: float | None = None

    def tick_at(self, price: float) -> float:
        return self.tick if self.tick else krx_stock_tick(price)

    def round_tick(self, price: float, mode: str = "nearest") -> float:
        t = self.tick_at(price)
        q = price / t
        if mode == "down":
            q = math.floor(q + 1e-9)
        elif mode == "up":
            q = math.ceil(q - 1e-9)
        else:
            q = round(q)
        return round(q * t, 10)

    def slip(self, price: float, side_sign: int) -> float:
        """불리한 방향으로 슬리피지 적용. side_sign=+1 매수 체결, -1 매도 체결."""
        px = price + side_sign * self.slippage_ticks * self.tick_at(price)
        return self.round_tick(px, "up" if side_sign > 0 else "down")

    def cost(self, price: float, qty: float, is_sell: bool, closing_long: bool) -> float:
        notional = price * qty * self.multiplier
        c = notional * self.fee_rate + qty * self.fee_per_contract
        if self.kind == "stock" and is_sell:
            c += notional * self.sell_tax_rate
        return c

    def upper_limit(self, prev_close: float | None) -> float | None:
        if not prev_close or not self.price_limit_pct or self.kind != "stock":
            return None
        return self.round_tick(prev_close * (1 + self.price_limit_pct / 100), "down")

    def lower_limit(self, prev_close: float | None) -> float | None:
        if not prev_close or not self.price_limit_pct or self.kind != "stock":
            return None
        return self.round_tick(prev_close * (1 - self.price_limit_pct / 100), "up")


def load_instrument(name: str, path: str = INSTRUMENTS_PATH) -> Instrument:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if name not in cfg["instruments"]:
        raise KeyError(f"unknown instrument {name}; choose from {list(cfg['instruments'])}")
    d = {k: v for k, v in cfg["instruments"][name].items() if not k.startswith("_")}
    return Instrument(name=name, **d)


def load_portfolio_defaults(currency: str, path: str = DEFAULTS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {k: v for k, v in cfg[currency].items() if not k.startswith("_")}


def vi_blocked(bars, inst: Instrument, bar_minutes: int = 1) -> set[int]:
    """VI 단일가 구간(연속체결 불가) 바 인덱스 집합.

    1) 데이터에 vi 플래그(1)가 있으면 그것을 사용한다.
    2) 없으면 정적 VI만 근사한다: 참조가격(시가, 이후 직전 VI 단일가 근사치) 대비
       ±vi_static_pct% 도달 바의 다음 ceil(2/bar_minutes)개 바를 차단한다.
       동적 VI(직전 체결가 대비 3%/6%)는 1분봉으로 재현 불가하므로 슬리피지로 흡수한다.
    """
    flagged = {i for i, b in enumerate(bars) if getattr(b, "vi", 0)}
    if flagged:
        return flagged
    if inst.kind != "stock" or not inst.vi_static_pct or not bars or bar_minutes > 2:
        return set()
    p = inst.vi_static_pct / 100
    nblock = max(1, math.ceil(2 / bar_minutes))
    blocked: set[int] = set()
    ref = bars[0].o
    i = 0
    while i < len(bars):
        b = bars[i]
        if b.h >= ref * (1 + p) or b.l <= ref * (1 - p):
            for k in range(1, nblock + 1):
                if i + k < len(bars):
                    blocked.add(i + k)
            j = min(i + nblock, len(bars) - 1)
            ref = bars[j].c
            i = j + 1
            continue
        i += 1
    return blocked
