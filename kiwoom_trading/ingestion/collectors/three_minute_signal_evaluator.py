"""
3분봉 기준 신호 평가:
- 중심선(20이평/VWAP) 돌파
- RSI 30 탈출 후 50까지 회복
- 거래량 동반
- 돌파 후 눌림에서 중심선/이평선 지지
"""
from datetime import datetime
from typing import Any


def _minute_key(row: dict[str, Any]) -> str:
    snapshot_minute = str(row.get("snapshot_minute") or "").strip()
    if snapshot_minute and len(snapshot_minute) >= 12:
        return snapshot_minute
    collected_at = str(row.get("collected_at") or "")
    if not collected_at:
        return ""
    normalized = collected_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y%m%d%H%M")
    except Exception:
        return ""


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _snapshot_to_3m_key(snapshot_minute: str) -> str:
    """1분 스냅샷 키(YYYYMMDDHHMM)를 3분 봉 키로 변환. 예: 202603160931 -> 202603160930"""
    if not snapshot_minute or len(snapshot_minute) < 12:
        return ""
    try:
        hh = int(snapshot_minute[8:10])
        mm = int(snapshot_minute[10:12])
        total_mins = hh * 60 + mm
        bucket_mins = (total_mins // 3) * 3
        return snapshot_minute[:8] + f"{bucket_mins // 60:02d}{bucket_mins % 60:02d}"
    except (ValueError, IndexError):
        return ""


def _build_3m_bars(rows_desc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """1분 스냅샷 목록(최신이 앞)을 3분봉 리스트(과거→최신 순)로 집계."""
    rows_asc = list(reversed(rows_desc))
    by_3m: dict[str, list[dict[str, Any]]] = {}
    for row in rows_asc:
        key_1m = _minute_key(row)
        if key_1m == "":
            continue
        key_3m = _snapshot_to_3m_key(key_1m)
        if key_3m == "":
            continue
        if key_3m not in by_3m:
            by_3m[key_3m] = []
        by_3m[key_3m].append(row)

    bars: list[dict[str, Any]] = []
    for key_3m in sorted(by_3m.keys()):
        group = by_3m[key_3m]
        if not group:
            continue
        prices = [_to_float(r.get("current_price")) for r in group]
        prices = [p for p in prices if p is not None]
        if not prices:
            continue
        cum_values = [_to_int(r.get("cum_trade_value")) for r in group]
        cum_values = [v for v in cum_values if v is not None]
        open_p = prices[0]
        close_p = prices[-1]
        high_p = max(prices)
        low_p = min(prices)
        value_delta = (cum_values[-1] - cum_values[0]) if len(cum_values) >= 2 else (cum_values[0] if cum_values else 0)
        if value_delta is None:
            value_delta = 0
        bars.append({
            "minute_key": key_3m,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "value_delta": max(0, value_delta),
        })
    return bars


def _sma(series: list[float], end_idx: int, period: int) -> float | None:
    start = end_idx - period + 1
    if start < 0:
        return None
    window = series[start : end_idx + 1]
    return sum(window) / period


def _rsi(closes: list[float], end_idx: int, period: int = 14) -> float | None:
    start = end_idx - period
    if start < 0:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(start + 1, end_idx + 1):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains += delta
        else:
            losses += -delta
    if period == 0:
        return None
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def evaluate_3m_signal(rows_desc: list[dict[str, Any]]) -> dict[str, Any]:
    """
    조건:
    1) 중심선(20이평) 돌파
    2) RSI 30 탈출 후 50까지 회복
    3) 거래량 동반 (value_delta > 평균)
    4) 돌파 후 눌림에서 중심선 지지
    """
    bars = _build_3m_bars(rows_desc)
    min_bars = 25  # MA20 + RSI 14 + 여유
    if len(bars) < min_bars:
        return {
            "signal_side": None,
            "reason": "not_enough_3m_bars",
            "bars_count": len(bars),
        }

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    value_deltas = [b["value_delta"] for b in bars]

    n = len(bars) - 1
    ma20 = _sma(closes, n, 20)
    if ma20 is None:
        return {"signal_side": None, "reason": "ma20_unavailable", "bars_count": len(bars)}

    rsi_now = _rsi(closes, n, 14)
    avg_value = sum(value_deltas[-20:]) / 20.0 if len(value_deltas) >= 20 else (sum(value_deltas) / len(value_deltas) if value_deltas else 0)

    # 1) 돌파 구간 찾기: close > MA20 이전에 close <= MA20 이었던 시점
    breakout_idx: int | None = None
    for i in range(1, n + 1):
        ma20_i = _sma(closes, i, 20)
        ma20_prev = _sma(closes, i - 1, 20)
        if ma20_i is None or ma20_prev is None:
            continue
        if closes[i] > ma20_i and closes[i - 1] <= ma20_prev:
            breakout_idx = i
            break

    if breakout_idx is None:
        return {
            "signal_side": None,
            "reason": "no_center_breakout",
            "close": closes[n],
            "ma20": ma20,
            "rsi": rsi_now,
            "bars_count": len(bars),
        }

    # 2) RSI 30 탈출 후 50 회복: 과거 구간에서 RSI<=30 이었고, 현재 RSI는 30 초과 ~ 55 이하(50 회복 중)
    rsi_was_below_30 = False
    for i in range(14, n + 1):
        r = _rsi(closes, i, 14)
        if r is not None and r <= 30:
            rsi_was_below_30 = True
            break
    rsi_recovered = (
        rsi_was_below_30
        and rsi_now is not None
        and 30 < rsi_now <= 55
    )
    if not rsi_recovered:
        return {
            "signal_side": None,
            "reason": "rsi_not_recovered",
            "close": closes[n],
            "ma20": ma20,
            "rsi": rsi_now,
            "bars_count": len(bars),
        }

    # 3) 거래량 동반: 돌파 봉 또는 최근 봉에서 value_delta > 평균
    volume_ok = False
    for i in range(max(0, breakout_idx - 2), min(n + 1, breakout_idx + 4)):
        if i < len(value_deltas) and value_deltas[i] >= avg_value * 0.8:
            volume_ok = True
            break
    if n < len(value_deltas) and value_deltas[n] >= avg_value * 0.8:
        volume_ok = True
    if not volume_ok and avg_value <= 0:
        volume_ok = True
    if not volume_ok:
        return {
            "signal_side": None,
            "reason": "volume_not_confirmed",
            "close": closes[n],
            "ma20": ma20,
            "rsi": rsi_now,
            "bars_count": len(bars),
        }

    # 4) 돌파 후 눌림에서 중심선 지지: breakout 이후 어떤 봉에서 low <= MA20 근처였다가 close > MA20 (지지)
    support_ok = False
    ma20_list = [_sma(closes, i, 20) for i in range(len(bars))]
    for i in range(breakout_idx + 1, n + 1):
        ma20_i = ma20_list[i] if i < len(ma20_list) else _sma(closes, i, 20)
        if ma20_i is None:
            continue
        # 눌림: 저가가 중심선 근처 (1% 이내)
        if lows[i] <= ma20_i * 1.01 and closes[i] >= ma20_i * 0.99:
            support_ok = True
            break
    # 현재가가 중심선 위에 있으면 지지 유지로 간주
    if closes[n] >= ma20 * 0.99:
        support_ok = True
    if not support_ok:
        return {
            "signal_side": None,
            "reason": "no_support_after_breakout",
            "close": closes[n],
            "ma20": ma20,
            "rsi": rsi_now,
            "bars_count": len(bars),
        }

    return {
        "signal_side": "long",
        "reason": "3m_center_rsi_support",
        "close": closes[n],
        "ma20": ma20,
        "rsi": rsi_now,
        "bars_count": len(bars),
        "latest_minute_key": bars[n]["minute_key"],
        "breakout_idx": breakout_idx,
    }
