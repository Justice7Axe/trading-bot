"""🪜 이평선 재정배열 코인 선물 모의 — 판정 엔진 시험 (네트워크 없음)."""
import random

from kiwoom_trading.strategies.crypto_align import core

T0 = 1_780_000_000_000 // core.DAY_MS * core.DAY_MS   # 어떤 날 00:00 UTC


def _bars(closes, lows=None, opens=None):
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else (closes[i - 1] if i else c)
        lo = lows[i] if lows else min(o, c) - 0.01
        out.append(core.Bar(T0 + i * core.BAR_MS, o, max(o, c) + 0.01, lo, c, 1.0))
    return out


def _cross_series():
    # 130봉 내림 → 오름: 60선이 120선을 위로 넘는 봉이 생김
    return [100 - i * 0.1 for i in range(130)] + [87 + i * 0.4 for i in range(120)]


def test_signal_buys_next_open_and_sells_next_day():
    bars = _bars(_cross_series() + [140.0] * 200)
    st = core.State()
    trades = core.replay(bars, st)
    assert trades, "신호가 있어야 함"
    t = trades[0]
    i_sig = next(i for i, b in enumerate(bars) if b.t == t["signal_t"])
    assert t["entry_t"] == bars[i_sig + 1].t and t["entry"] == bars[i_sig + 1].o
    assert t["reason"] == "다음 날 09:00"
    assert t["exit_t"] // core.DAY_MS == t["entry_t"] // core.DAY_MS + 1
    assert t["exit_t"] % core.DAY_MS == 0        # 다음 날 첫 봉


def test_stop_on_entry_bar():
    closes = _cross_series()
    bars = _bars(closes + [140.0] * 50)
    st = core.State()
    first = core.replay(bars, st)[0]
    i_e = next(i for i, b in enumerate(bars) if b.t == first["entry_t"])
    lows = [b.l for b in bars]
    lows[i_e] = bars[i_e].o * 0.96               # 매수한 봉에서 −4% 까지 빠짐
    bars2 = _bars(closes + [140.0] * 50, lows=lows)
    t = core.replay(bars2, core.State())[0]
    assert t["reason"] == "손절 −3%" and t["exit_t"] == bars2[i_e].t
    assert abs(t["exit"] / t["entry"] - 0.97) < 1e-9


def test_incremental_equals_full_replay():
    random.seed(7)
    c, closes = 100.0, []
    for _ in range(3000):
        c *= 1 + random.gauss(0, 0.006)
        closes.append(c)
    bars = _bars(closes)
    full = core.replay(bars, core.State())
    st = core.State()
    inc = []
    for k in range(200, len(bars) + 1, 7):      # 몇 봉씩 끊어 받는 실시간과 같은지
        forming = bars[k] if k < len(bars) else None
        inc += core.replay(bars[:k], st, forming)
    assert [(t["entry_t"], t["exit_t"], round(t["net"], 12)) for t in inc] == \
           [(t["entry_t"], t["exit_t"], round(t["net"], 12)) for t in full]
    assert len(full) > 5


def test_state_roundtrip():
    st = core.State(last_t=5, cash=1234.5, pos=core.Position(1, 2.0, 1.94, 0, 1.0, 0.9), pending=None)
    st2 = core.State.from_json(st.to_json())
    assert st2.pos == st.pos and st2.cash == st.cash and st2.last_t == 5


if __name__ == "__main__":   # pytest 없이: python -m tests.test_crypto_align
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("통과", name)
