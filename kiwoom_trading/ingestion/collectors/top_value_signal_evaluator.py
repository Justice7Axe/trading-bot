from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TopValueSignalConfig:
    ma_short: int = 5
    ma_mid: int = 25
    ma_long: int = 75
    long_slope_lookback: int = 3


def _minute_key(row: dict[str, Any]) -> str:
    snapshot_minute = str(row.get("snapshot_minute") or "").strip()
    if snapshot_minute:
        return snapshot_minute

    raw_values = row.get("raw_values")
    if isinstance(raw_values, dict):
        nested_snapshot = str(raw_values.get("snapshot_minute") or "").strip()
        if nested_snapshot:
            return nested_snapshot

    collected_at = str(row.get("collected_at") or "")
    if not collected_at:
        return ""
    normalized = collected_at.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    return dt.strftime("%Y%m%d%H%M")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return None


def _sma(series: list[float], end_idx: int, period: int) -> float | None:
    start = end_idx - period + 1
    if start < 0:
        return None
    window = series[start : end_idx + 1]
    return sum(window) / period


def _build_bars(rows_desc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_asc = list(reversed(rows_desc))
    bars: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows_asc:
        key = _minute_key(row)
        if key == "" or key in seen:
            continue
        seen.add(key)

        close = _to_float(row.get("current_price"))
        if close is None:
            continue

        bars.append(
            {
                "minute_key": key,
                "collected_at": str(row.get("collected_at") or ""),
                "stock_code": str(row.get("stock_code") or ""),
                "close": close,
            }
        )
    return bars


def latest_top_value_entry_signal(
    rows_desc: list[dict[str, Any]],
    config: TopValueSignalConfig | None = None,
) -> dict[str, Any]:
    cfg = config or TopValueSignalConfig()
    bars = _build_bars(rows_desc)
    min_bars = cfg.ma_long + cfg.long_slope_lookback + 2
    if len(bars) < min_bars:
        return {
            "signal_side": None,
            "reason": "not_enough_bars",
            "close": None,
            "ma5": None,
            "ma25": None,
            "ma75": None,
            "ma75_prev": None,
        }

    closes = [b["close"] for b in bars]
    i = len(bars) - 1

    ma5 = _sma(closes, i, cfg.ma_short)
    ma25 = _sma(closes, i, cfg.ma_mid)
    ma75 = _sma(closes, i, cfg.ma_long)
    ma75_prev = _sma(closes, i - cfg.long_slope_lookback, cfg.ma_long)
    ma5_prev = _sma(closes, i - 1, cfg.ma_short)
    prev_close = closes[i - 1]
    close = closes[i]

    if ma5 is None or ma25 is None or ma75 is None or ma75_prev is None or ma5_prev is None:
        return {
            "signal_side": None,
            "reason": "ma_unavailable",
            "close": close,
            "ma5": ma5,
            "ma25": ma25,
            "ma75": ma75,
            "ma75_prev": ma75_prev,
        }

    bullish = (ma5 > ma25 > ma75) and (ma75 > ma75_prev)
    bearish = (ma5 < ma25 < ma75) and (ma75 < ma75_prev)
    long_entry_signal = bullish and (prev_close <= ma5_prev) and (close > ma5)
    short_entry_signal = bearish and (prev_close >= ma5_prev) and (close < ma5)

    side: str | None = None
    reason = "no_signal"
    if long_entry_signal:
        side = "long"
        reason = "ma_alignment_reclaim_5"
    elif short_entry_signal:
        side = "short"
        reason = "ma_alignment_break_5"

    return {
        "signal_side": side,
        "reason": reason,
        "close": close,
        "ma5": ma5,
        "ma25": ma25,
        "ma75": ma75,
        "ma75_prev": ma75_prev,
        "latest_collected_at": bars[i]["collected_at"],
        "latest_minute_key": bars[i]["minute_key"],
    }
