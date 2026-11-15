"""🪜 이평선 재정배열 (코인 선물 15분봉) — 시세 받기·판정 엔진.

규칙 (2026-11-15 사용자 'SOXLUSDT 🪜 재정배열로 모의매매'):
- 15분봉 종가 60봉·120봉 단순 평균. 직전 봉 60선 ≤ 120선 → 이 봉 60선 > 120선, 종가 > 60선 이면 신호.
- 신호 봉 다음 봉 시가에 롱 매수 (모의, 레버리지 1배).
- 손절 매수가 −3% (봉 저가가 닿으면 그 가격, 시가가 이미 아래면 시가). 매수한 봉 안에서도 손절은 봄.
- 익절 없음. 손절이 안 걸리면 다음 날 00:00 UTC(한국 09:00) 첫 봉 시가에 매도.
- 매도한 봉에서는 새 신호를 보지 않음 (다음 봉부터).
- 비용 시장가 수수료 0.05% × 2 + 펀딩비(8시간마다, 보유 중 지난 펀딩 시각의 비율 × 진입가 기준 물량).
- 같은 매매를 1배·2배 두 가상 잔고로 함께 적음 (2026-11-15 사용자 '선물이니까 2배수로도 가능하지?').
  2배 = 손익·수수료·펀딩 모두 2배. −3% 손절이면 잔고 −6% 남짓.

`replay` 하나로 과거 타점(리포트)과 실시간 모의(live)를 같은 계산으로 돌린다.
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field, asdict

from kiwoom_trading.common.daily_store import PROJECT_ROOT

KIND = "🪜 이평선 재정배열"
FAST, SLOW = 60, 120
STOP_PCT = 0.03
FEE_SIDE = 0.0005
BAR_MS = 15 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
FAPI = "https://fapi.binance.com/fapi/v1"


def data_dir(symbol: str) -> str:
    d = os.path.join(PROJECT_ROOT, "data", "crypto_paper", symbol)
    os.makedirs(d, exist_ok=True)
    return d


# ── 시세 ────────────────────────────────────────────────────────────
def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "kline-client"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def listing_ms(symbol: str) -> int:
    info = _get(f"{FAPI}/exchangeInfo")
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            return int(s["onboardDate"])
    raise ValueError(f"바이낸스 선물에 {symbol} 없음")


def fetch_klines(symbol: str, start_ms: int) -> list[list]:
    """start_ms 부터 지금까지 15분봉 (마지막 줄은 아직 안 끝난 봉일 수 있음)."""
    rows: list[list] = []
    while True:
        d = _get(f"{FAPI}/klines?symbol={symbol}&interval=15m&limit=1500&startTime={start_ms}")
        if not d:
            break
        rows += d
        start_ms = d[-1][0] + 1
        if len(d) < 1500:
            break
        time.sleep(0.3)
    return rows


def load_funding(symbol: str) -> list[tuple[int, float]]:
    """펀딩 기록 (시각 ms, 비율). 캐시 funding.csv 에 이어 받음. 받기 실패하면 캐시만."""
    path = os.path.join(data_dir(symbol), "funding.csv")
    rows: list[tuple[int, float]] = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = [(int(r["t"]), float(r["rate"])) for r in csv.DictReader(f)]
    start = rows[-1][0] + 1 if rows else 0
    try:
        new = []
        while True:
            q = f"{FAPI}/fundingRate?symbol={symbol}&limit=1000" + (f"&startTime={start}" if start else "")
            d = _get(q)
            new += [(int(x["fundingTime"]), float(x["fundingRate"])) for x in d if int(x["fundingTime"]) >= start]
            if len(d) < 1000:
                break
            start = int(d[-1]["fundingTime"]) + 1
        if new:
            rows += new
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["t", "rate"])
                w.writerows(rows)
    except Exception:
        pass
    return rows


def funding_sum(rates: list[tuple[int, float]], entry_t: int, exit_t: int) -> float:
    """entry_t < 펀딩 시각 < exit_t 인 펀딩 비율 합 (롱은 + 면 냄)."""
    return sum(r for t, r in rates if entry_t < t < exit_t)


def nets(entry: float, exit_px: float, fund: float) -> tuple[float, float]:
    """(1배 잔고 수익률, 2배 잔고 수익률) — 수수료 진입·청산 물량 기준, 펀딩은 진입 물량 기준."""
    g = exit_px / entry - 1
    fee = FEE_SIDE * (1 + exit_px / entry)
    return g - fee - fund, 2 * (g - fee - fund)


@dataclass
class Bar:
    t: int      # 봉 시작 ms (UTC)
    o: float
    h: float
    l: float
    c: float
    v: float


def load_bars(symbol: str, now_ms: int | None = None) -> tuple[list[Bar], Bar | None]:
    """캐시(klines_15m.csv)에 이어 받아 (끝난 봉 목록, 지금 만들어지는 봉) 을 돌려준다."""
    now_ms = now_ms or int(time.time() * 1000)
    path = os.path.join(data_dir(symbol), "klines_15m.csv")
    bars: list[Bar] = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                bars.append(Bar(int(r["t"]), float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]), float(r["v"])))
    start = bars[-1].t + 1 if bars else listing_ms(symbol)
    new = [Bar(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in fetch_klines(symbol, start)]
    forming = None
    closed_new = []
    for b in new:
        if b.t + BAR_MS <= now_ms:
            closed_new.append(b)
        else:
            forming = b
    if closed_new:
        bars += closed_new
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "o", "h", "l", "c", "v"])
            for b in bars:
                w.writerow([b.t, b.o, b.h, b.l, b.c, b.v])
    return bars, forming


# ── 판정 엔진 ──────────────────────────────────────────────────────
def sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


@dataclass
class Position:
    entry_t: int
    entry: float
    stop: float
    signal_t: int
    fast: float
    slow: float
    low: float = 0.0          # 보유 중 가장 낮았던 가격 (손절선 접근 복기용)
    high: float = 0.0         # 보유 중 가장 높았던 가격


@dataclass
class State:
    last_t: int = 0                       # 판정을 끝낸 마지막 '끝난 봉' 시작 ms
    cash: float = 1000.0                  # 가상 USDT (1배)
    pos: Position | None = None
    pending: dict | None = None           # 신호는 났고 다음 봉 시가를 기다리는 중
    cash2: float = 1000.0                 # 가상 USDT (2배)
    journal_day: str = ""                 # 매매일지를 마지막으로 쓴 날 (YYYY-MM-DD, 한국 09시 기준 하루)
    events: list = field(default_factory=list)   # 이번 실행에서 새로 생긴 일 (알림용, 저장 안 함)

    def to_json(self) -> dict:
        d = {"last_t": self.last_t, "cash": self.cash, "cash2": self.cash2, "journal_day": self.journal_day,
             "pos": asdict(self.pos) if self.pos else None, "pending": self.pending}
        return d

    @classmethod
    def from_json(cls, d: dict) -> "State":
        s = cls(last_t=d["last_t"], cash=d["cash"], pending=d.get("pending"),
                cash2=d.get("cash2", d["cash"]), journal_day=d.get("journal_day", ""))
        if d.get("pos"):
            s.pos = Position(**d["pos"])
        return s


def _day(t: int) -> int:
    return t // DAY_MS


def replay(bars: list[Bar], st: State, forming: Bar | None = None,
           rates: list[tuple[int, float]] | None = None) -> list[dict]:
    """st.last_t 다음 끝난 봉부터 차례로 판정. 끝난 매매 목록을 돌려주고 st 를 고친다.
    forming(지금 만들어지는 봉)의 시가는 매수가로만 쓴다. rates = 펀딩 기록(없으면 펀딩 0)."""
    rates = rates or []
    closes = [b.c for b in bars]
    f, s = sma(closes, FAST), sma(closes, SLOW)
    trades: list[dict] = []
    idx = {b.t: i for i, b in enumerate(bars)}

    def open_pos(i_bar_t: int, price: float, sig_i: int):
        st.pos = Position(entry_t=i_bar_t, entry=price, stop=price * (1 - STOP_PCT),
                          signal_t=bars[sig_i].t, fast=f[sig_i], slow=s[sig_i], low=price, high=price)
        st.pending = None
        st.events.append({"type": "buy", "t": i_bar_t, "price": price, "stop": st.pos.stop,
                          "signal_t": bars[sig_i].t, "fast": f[sig_i], "slow": s[sig_i]})

    def close_pos(t: int, price: float, reason: str):
        p = st.pos
        gross = price / p.entry - 1
        fund = funding_sum(rates, p.entry_t, t)
        net, net2 = nets(p.entry, price, fund)
        st.cash *= 1 + net
        st.cash2 *= 1 + net2
        tr = {"signal_t": p.signal_t, "entry_t": p.entry_t, "entry": p.entry, "exit_t": t, "exit": price,
              "reason": reason, "ret": gross, "fund": fund, "net": net, "net2": net2, "cash": st.cash,
              "cash2": st.cash2, "fast": p.fast, "slow": p.slow, "stop": p.stop,
              "low": min(p.low, price), "high": max(p.high, price)}
        trades.append(tr)
        st.events.append({"type": "sell", **tr})
        st.pos = None

    for i, b in enumerate(bars):
        if b.t <= st.last_t:
            continue
        # 기다리던 매수: 이 봉 시가에 산다
        if st.pending is not None and st.pos is None:
            sig_i = idx.get(st.pending["signal_t"])
            open_pos(b.t, b.o, sig_i)
        if st.pos is not None:
            p = st.pos
            if b.t == p.entry_t:                 # 매수한 봉: 손절만
                if b.l <= p.stop:
                    close_pos(b.t, p.stop, "손절 −3%")
                    st.last_t = b.t
                    continue
            else:
                if b.l <= p.stop:
                    close_pos(b.t, min(b.o, p.stop), "손절 −3%")
                    st.last_t = b.t
                    continue
                if _day(b.t) > _day(p.entry_t):
                    close_pos(b.t, b.o, "다음 날 09:00")
                    st.last_t = b.t
                    continue
            p.low = min(p.low or b.l, b.l)       # 끝까지 들고 있던 봉의 저가·고가 (손절선 접근 복기용)
            p.high = max(p.high, b.h)
            st.last_t = b.t
            continue
        # 보유 없음: 신호 판정
        if i >= 1 and f[i] is not None and s[i] is not None and f[i - 1] is not None and s[i - 1] is not None:
            if f[i] > s[i] and f[i - 1] <= s[i - 1] and b.c > f[i]:
                st.pending = {"signal_t": b.t}
                st.events.append({"type": "signal", "t": b.t, "close": b.c, "fast": f[i], "slow": s[i]})
        st.last_t = b.t

    # 신호 봉이 마지막 끝난 봉이면 지금 만들어지는 봉 시가로 바로 산다
    if st.pending is not None and st.pos is None and forming is not None and forming.t > st.last_t:
        sig_i = idx.get(st.pending["signal_t"])
        open_pos(forming.t, forming.o, sig_i)
        # 매수 봉은 아직 안 끝났으므로 last_t 는 그대로 — 다음 실행 때 이 봉이 끝나면 손절만 본다
    return trades
