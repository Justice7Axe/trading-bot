from datetime import datetime
from typing import Any


def _minute_key(row: dict[str, Any]) -> str:
    raw_values = row.get("raw_values")
    if isinstance(raw_values, dict):
        snapshot_minute = raw_values.get("snapshot_minute")
        if isinstance(snapshot_minute, str) and snapshot_minute.strip():
            return snapshot_minute.strip()

    collected_at = str(row.get("collected_at") or "")
    if not collected_at:
        return ""
    normalized = collected_at.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    return dt.strftime("%Y%m%d%H%M")


def dedupe_per_minute(rows_desc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows_desc:
        key = _minute_key(row)
        if key == "" or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _safe_price(row: dict[str, Any]) -> float | None:
    value = row.get("current_price")
    if value is None:
        return None
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return None


def _safe_volume(row: dict[str, Any]) -> float | None:
    value = row.get("trade_volume")
    if value is None:
        return None
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return None


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[:period]) / period


def _stddev(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[:period]
    mean = sum(window) / period
    variance = sum((v - mean) ** 2 for v in window) / period
    return variance ** 0.5


def _rsi(values_desc: list[float], period: int = 14) -> float | None:
    if len(values_desc) < period + 1:
        return None
    values = list(reversed(values_desc[: period + 1]))
    gains = 0.0
    losses = 0.0
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        if delta > 0:
            gains += delta
        else:
            losses += -delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def summarize_stock(rows_desc: list[dict[str, Any]]) -> dict[str, Any]:
    minute_rows = dedupe_per_minute(rows_desc)
    prices = [p for p in (_safe_price(row) for row in minute_rows) if p is not None]
    volumes = [v for v in (_safe_volume(row) for row in minute_rows) if v is not None]
    latest = prices[0] if prices else None

    def pct_change(idx: int) -> float | None:
        if latest is None or len(prices) <= idx or prices[idx] == 0:
            return None
        return (latest - prices[idx]) / prices[idx] * 100

    sma_20 = _sma(prices, 20)
    std_20 = _stddev(prices, 20)
    bb_upper = (sma_20 + 2 * std_20) if (sma_20 is not None and std_20 is not None) else None
    bb_lower = (sma_20 - 2 * std_20) if (sma_20 is not None and std_20 is not None) else None
    rsi_14 = _rsi(prices, 14)
    avg_volume_20 = _sma(volumes, 20)
    latest_volume = volumes[0] if volumes else None
    volume_spike = bool(
        latest_volume is not None
        and avg_volume_20 is not None
        and avg_volume_20 > 0
        and latest_volume >= avg_volume_20 * 2
    )

    return {
        "minute_points": len(minute_rows),
        "latest_price": latest,
        "change_1m_pct": pct_change(1),
        "change_5m_pct": pct_change(5),
        "change_20m_pct": pct_change(20),
        "sma_5": _sma(prices, 5),
        "sma_20": sma_20,
        "rsi_14": rsi_14,
        "bb_upper_20_2": bb_upper,
        "bb_lower_20_2": bb_lower,
        "latest_volume": latest_volume,
        "avg_volume_20": avg_volume_20,
        "volume_spike_2x": volume_spike,
        "latest_collected_at": minute_rows[0]["collected_at"] if minute_rows else None,
        "latest_minute_key": _minute_key(minute_rows[0]) if minute_rows else None,
    }


def latest_strategy_signals(
    rows_desc: list[dict[str, Any]],
    rsi_buy_threshold: float = 30.0,
    rsi_sell_threshold: float = 70.0,
) -> dict[str, bool | float | None]:
    minute_rows = dedupe_per_minute(rows_desc)
    prices = [p for p in (_safe_price(row) for row in minute_rows) if p is not None]
    rsi_14 = _rsi(prices, 14)

    sma_5_now = _sma(prices, 5)
    sma_20_now = _sma(prices, 20)
    sma_5_prev = _sma(prices[1:], 5) if len(prices) > 5 else None
    sma_20_prev = _sma(prices[1:], 20) if len(prices) > 20 else None

    golden_cross = bool(
        sma_5_now is not None
        and sma_20_now is not None
        and sma_5_prev is not None
        and sma_20_prev is not None
        and sma_5_now > sma_20_now
        and sma_5_prev <= sma_20_prev
    )
    dead_cross = bool(
        sma_5_now is not None
        and sma_20_now is not None
        and sma_5_prev is not None
        and sma_20_prev is not None
        and sma_5_now < sma_20_now
        and sma_5_prev >= sma_20_prev
    )

    strategy_buy = bool(golden_cross and rsi_14 is not None and rsi_14 <= rsi_buy_threshold)
    strategy_sell = bool(dead_cross and rsi_14 is not None and rsi_14 >= rsi_sell_threshold)

    return {
        "golden_cross": golden_cross,
        "dead_cross": dead_cross,
        "strategy_buy": strategy_buy,
        "strategy_sell": strategy_sell,
        "strategy_rsi": rsi_14,
    }
