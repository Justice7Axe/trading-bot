from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TestaStrategyConfig:
    ma_short: int = 5
    ma_mid: int = 25
    ma_long: int = 75
    long_slope_lookback: int = 3
    short_swing_lookback: int = 5
    resistance_lookback: int = 20
    risk_reward_ratio: float = 3.0
    partial_exit_ratio: float = 0.5


@dataclass
class Trade:
    stock_code: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    pnl_r: float
    pnl_pct: float
    partial_exit_used: bool
    reason: str


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
    # rows_desc는 최신순이므로 시간순으로 뒤집어 처리합니다.
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
        open_price = _to_float(row.get("open_price")) or close
        high_price = _to_float(row.get("high_price")) or close
        low_price = _to_float(row.get("low_price")) or close

        bars.append(
            {
                "minute_key": key,
                "collected_at": str(row.get("collected_at") or ""),
                "stock_code": str(row.get("stock_code") or ""),
                "open": open_price,
                "high": max(high_price, close, open_price),
                "low": min(low_price, close, open_price),
                "close": close,
            }
        )
    return bars


def backtest_testa_ma_strategy(
    rows_desc: list[dict[str, Any]],
    config: TestaStrategyConfig | None = None,
) -> dict[str, Any]:
    cfg = config or TestaStrategyConfig()
    bars = _build_bars(rows_desc)
    if len(bars) < cfg.ma_long + cfg.long_slope_lookback + 5:
        return {
            "bars": len(bars),
            "trades": [],
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "avg_r": 0.0,
            "total_r": 0.0,
            "max_loss_streak": 0,
        }

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    trades: list[Trade] = []
    position: dict[str, Any] | None = None
    loss_streak = 0
    max_loss_streak = 0

    start_idx = max(cfg.ma_long + cfg.long_slope_lookback, cfg.resistance_lookback + 1)
    for i in range(start_idx, len(bars)):
        bar = bars[i]
        close = closes[i]
        high = highs[i]
        low = lows[i]

        ma5 = _sma(closes, i, cfg.ma_short)
        ma25 = _sma(closes, i, cfg.ma_mid)
        ma75 = _sma(closes, i, cfg.ma_long)
        ma75_prev = _sma(closes, i - cfg.long_slope_lookback, cfg.ma_long)
        ma5_prev = _sma(closes, i - 1, cfg.ma_short)
        prev_close = closes[i - 1]

        if ma5 is None or ma25 is None or ma75 is None or ma75_prev is None or ma5_prev is None:
            continue

        if position is not None:
            side = position["side"]
            stop = position["stop"]
            partial_target = position["partial_target"]
            final_target = position["final_target"]
            entry = position["entry"]
            risk = position["risk"]
            partial_done = position["partial_done"]
            realized_r = position["realized_r"]
            realized_return = position["realized_return"]
            partial_used = position["partial_used"]

            if side == "long":
                if low <= stop:
                    exit_price = stop
                    remain_ratio = 0.5 if partial_done else 1.0
                    pnl_r = realized_r + ((exit_price - entry) / risk) * remain_ratio
                    pnl_pct = realized_return + ((exit_price - entry) / entry) * 100 * remain_ratio
                    trades.append(
                        Trade(
                            stock_code=bar["stock_code"],
                            side="long",
                            entry_time=position["entry_time"],
                            exit_time=bar["collected_at"],
                            entry_price=entry,
                            exit_price=exit_price,
                            stop_price=stop,
                            target_price=final_target,
                            pnl_r=pnl_r,
                            pnl_pct=pnl_pct,
                            partial_exit_used=partial_used,
                            reason="stop_loss",
                        )
                    )
                    position = None
                else:
                    if (not partial_done) and high >= partial_target:
                        partial_exit_price = partial_target
                        realized_r += ((partial_exit_price - entry) / risk) * cfg.partial_exit_ratio
                        realized_return += ((partial_exit_price - entry) / entry) * 100 * cfg.partial_exit_ratio
                        partial_done = True
                        position["partial_done"] = True
                        position["realized_r"] = realized_r
                        position["realized_return"] = realized_return
                    if high >= final_target:
                        exit_price = final_target
                        remain_ratio = 0.5 if partial_done else 1.0
                        pnl_r = realized_r + ((exit_price - entry) / risk) * remain_ratio
                        pnl_pct = realized_return + ((exit_price - entry) / entry) * 100 * remain_ratio
                        trades.append(
                            Trade(
                                stock_code=bar["stock_code"],
                                side="long",
                                entry_time=position["entry_time"],
                                exit_time=bar["collected_at"],
                                entry_price=entry,
                                exit_price=exit_price,
                                stop_price=stop,
                                target_price=final_target,
                                pnl_r=pnl_r,
                                pnl_pct=pnl_pct,
                                partial_exit_used=partial_used,
                                reason="take_profit",
                            )
                        )
                        position = None

            else:
                if high >= stop:
                    exit_price = stop
                    remain_ratio = 0.5 if partial_done else 1.0
                    pnl_r = realized_r + ((entry - exit_price) / risk) * remain_ratio
                    pnl_pct = realized_return + ((entry - exit_price) / entry) * 100 * remain_ratio
                    trades.append(
                        Trade(
                            stock_code=bar["stock_code"],
                            side="short",
                            entry_time=position["entry_time"],
                            exit_time=bar["collected_at"],
                            entry_price=entry,
                            exit_price=exit_price,
                            stop_price=stop,
                            target_price=final_target,
                            pnl_r=pnl_r,
                            pnl_pct=pnl_pct,
                            partial_exit_used=partial_used,
                            reason="stop_loss",
                        )
                    )
                    position = None
                else:
                    if (not partial_done) and low <= partial_target:
                        partial_exit_price = partial_target
                        realized_r += ((entry - partial_exit_price) / risk) * cfg.partial_exit_ratio
                        realized_return += ((entry - partial_exit_price) / entry) * 100 * cfg.partial_exit_ratio
                        partial_done = True
                        position["partial_done"] = True
                        position["realized_r"] = realized_r
                        position["realized_return"] = realized_return
                    if low <= final_target:
                        exit_price = final_target
                        remain_ratio = 0.5 if partial_done else 1.0
                        pnl_r = realized_r + ((entry - exit_price) / risk) * remain_ratio
                        pnl_pct = realized_return + ((entry - exit_price) / entry) * 100 * remain_ratio
                        trades.append(
                            Trade(
                                stock_code=bar["stock_code"],
                                side="short",
                                entry_time=position["entry_time"],
                                exit_time=bar["collected_at"],
                                entry_price=entry,
                                exit_price=exit_price,
                                stop_price=stop,
                                target_price=final_target,
                                pnl_r=pnl_r,
                                pnl_pct=pnl_pct,
                                partial_exit_used=partial_used,
                                reason="take_profit",
                            )
                        )
                        position = None

            if position is None and trades:
                if trades[-1].pnl_r < 0:
                    loss_streak += 1
                    max_loss_streak = max(max_loss_streak, loss_streak)
                else:
                    loss_streak = 0
            continue

        bullish = (ma5 > ma25 > ma75) and (ma75 > ma75_prev)
        bearish = (ma5 < ma25 < ma75) and (ma75 < ma75_prev)
        long_entry_signal = bullish and (prev_close <= ma5_prev) and (close > ma5)
        short_entry_signal = bearish and (prev_close >= ma5_prev) and (close < ma5)

        if long_entry_signal:
            swing_start = max(0, i - cfg.short_swing_lookback)
            resistance_start = max(0, i - cfg.resistance_lookback)
            stop = min(lows[swing_start:i])
            if stop >= close:
                continue

            risk = close - stop
            final_target = close + (risk * cfg.risk_reward_ratio)
            prior_resistance = max(highs[resistance_start:i])
            one_r_target = close + risk
            if close < prior_resistance < final_target:
                partial_target = prior_resistance
                partial_used = True
            else:
                partial_target = one_r_target
                partial_used = False

            position = {
                "side": "long",
                "entry_time": bar["collected_at"],
                "entry": close,
                "stop": stop,
                "risk": risk,
                "partial_target": partial_target,
                "final_target": final_target,
                "partial_done": False,
                "realized_r": 0.0,
                "realized_return": 0.0,
                "partial_used": partial_used,
            }
            continue

        if short_entry_signal:
            swing_start = max(0, i - cfg.short_swing_lookback)
            support_start = max(0, i - cfg.resistance_lookback)
            stop = max(highs[swing_start:i])
            if stop <= close:
                continue

            risk = stop - close
            final_target = close - (risk * cfg.risk_reward_ratio)
            prior_support = min(lows[support_start:i])
            one_r_target = close - risk
            if final_target < prior_support < close:
                partial_target = prior_support
                partial_used = True
            else:
                partial_target = one_r_target
                partial_used = False

            position = {
                "side": "short",
                "entry_time": bar["collected_at"],
                "entry": close,
                "stop": stop,
                "risk": risk,
                "partial_target": partial_target,
                "final_target": final_target,
                "partial_done": False,
                "realized_r": 0.0,
                "realized_return": 0.0,
                "partial_used": partial_used,
            }

    total_trades = len(trades)
    if total_trades == 0:
        return {
            "bars": len(bars),
            "trades": [],
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "avg_r": 0.0,
            "total_r": 0.0,
            "max_loss_streak": max_loss_streak,
        }

    wins = sum(1 for t in trades if t.pnl_r > 0)
    total_r = sum(t.pnl_r for t in trades)
    avg_r = total_r / total_trades

    return {
        "bars": len(bars),
        "trades": [t.__dict__ for t in trades],
        "total_trades": total_trades,
        "win_rate_pct": (wins / total_trades) * 100,
        "avg_r": avg_r,
        "total_r": total_r,
        "max_loss_streak": max_loss_streak,
    }
