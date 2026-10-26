"""65기법: 장대양봉 캔들 구조 기준 매수가 / 익절 / 손절가 그리드 서치 (포착 기준 고정).

    python -m kiwoom_trading.strategies.sixty_five.optimize_candles

- 매수가: 1·2·3차 장대양봉의 시가 / 몸통 중간 / 종가 (지정가, 신호 다음 거래일부터 DEFAULT_ENTRY_VALID_DAYS 거래일 유효)
- 손절가: 1·2·3차 장대양봉의 시가 / 몸통 중간 / 종가 중 매수 위치보다 아래인 것
- 손절 판정: 장중(저가 ≤ 손절가) / 종가(종가 ≤ 손절가)
- 익절: 매수가 대비 +N% (체결 다음 날부터), 최대 보유 N거래일째 종가 청산
체결/청산 세부 가정은 optimize_sixty_five.simulate 와 동일.
"""
import argparse
import itertools
import os
import statistics as st
import sys
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.strategies.sixty_five.entry import DEFAULT_ENTRY_VALID_DAYS
from kiwoom_trading.strategies.sixty_five.rules import SixtyFiveConfig
from kiwoom_trading.strategies.sixty_five.optimize import SignalCtx, build_contexts, find_fills
from kiwoom_trading.strategies.sixty_five.report import scan_all
from kiwoom_trading.common.daily_store import DailyStore


POINTS = ["시가", "중간", "종가"]          # 캔들 내 위치 (아래 → 위)
CANDLES = [0, 1, 2]                        # 1차 / 2차 / 3차 장대양봉
TAKE_PROFITS = [0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
STOP_MODES = ["장중", "종가"]
MAX_HOLDS = [5, 10]
VALID_DAYS = DEFAULT_ENTRY_VALID_DAYS


def label(candle: int, point: str) -> str:
    return f"{candle + 1}차 {point}"


def price_at(ctx: SignalCtx, candle: int, point: str) -> Optional[float]:
    rows, by_date = ctx.rows, {r["date"]: i for i, r in enumerate(ctx.rows)}
    if candle >= len(ctx.signal.candles):
        return None
    row = rows[by_date[ctx.signal.candles[candle].date]]
    return {"시가": row["open"], "종가": row["close"], "중간": (row["open"] + row["close"]) / 2}[point]


def simulate_level(ctx: SignalCtx, fill: tuple[int, float], stop: float, mode: str, tp: float, hold: int):
    """단일 체결, 고정 손절가. (수익률, 보유일, 보유중) 또는 None(손절가 ≥ 체결가)."""
    entry_i, price = fill
    if stop >= price:
        return None
    rows = ctx.rows
    for i in range(entry_i, len(rows)):
        row = rows[i]
        if mode == "장중" and row["low"] <= stop:
            exit_price = stop if i == entry_i else min(row["open"], stop)
            return exit_price / price - 1, i - entry_i, False
        if mode == "종가" and row["close"] <= stop:
            return row["close"] / price - 1, i - entry_i, False
        if i > entry_i and row["high"] >= price * (1 + tp):
            return max(row["open"], price * (1 + tp)) / price - 1, i - entry_i, False
        if i - entry_i >= hold:
            return row["close"] / price - 1, i - entry_i, False
    return rows[-1]["close"] / price - 1, len(rows) - 1 - entry_i, True


def main() -> None:
    parser = argparse.ArgumentParser(description="65기법 캔들 구조 기준 매수/손절/익절 그리드 서치")
    parser.add_argument("--cost", type=float, default=0.0025)
    parser.add_argument("--min-trades", type=int, default=30)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    store = DailyStore()
    db_path = store.db_path
    store.close()
    conn = duckdb.connect(db_path, read_only=True)
    try:
        ctxs = build_contexts(scan_all(conn, SixtyFiveConfig())[0])
    finally:
        conn.close()
    split = sorted(c.signal.signal_date for c in ctxs)[len(ctxs) // 2]
    print(f"신호 {len(ctxs)}건 (장대양봉 3개 이상 {sum(len(c.signal.candles) >= 3 for c in ctxs)}건) | 앞/뒤 경계 {split} | 비용 {args.cost:.2%}")

    results = []
    spots = list(itertools.product(CANDLES, POINTS))
    for entry in spots:
        entry_prices = [price_at(c, *entry) for c in ctxs]
        fills = [find_fills(c, [p], VALID_DAYS) if p is not None else [] for c, p in zip(ctxs, entry_prices)]
        for stop_spot in spots:
            # 손절은 매수 위치보다 아래: 이전 캔들은 모든 위치, 같은 캔들은 더 아래 위치만
            same_candle_below = stop_spot[0] == entry[0] and POINTS.index(stop_spot[1]) < POINTS.index(entry[1])
            if not (stop_spot[0] < entry[0] or same_candle_below):
                continue
            stops = [price_at(c, *stop_spot) for c in ctxs]
            for tp, mode, hold in itertools.product(TAKE_PROFITS, STOP_MODES, MAX_HOLDS):
                per_signal, trades, skipped = [], [], 0
                halves = ([], [])
                for c, f, s in zip(ctxs, fills, stops):
                    r = simulate_level(c, f[0], s, mode, tp, hold) if (f and s is not None) else None
                    if f and s is not None and r is None:
                        skipped += 1
                    v = 0.0 if (r is None or r[2]) else r[0] - args.cost
                    per_signal.append(v)
                    halves[c.signal.signal_date >= split].append(v)
                    if r and not r[2]:
                        trades.append((v, r[1]))
                if len(trades) < args.min_trades:
                    continue
                rets = [t[0] for t in trades]
                wins, losses = [x for x in rets if x > 0], [-x for x in rets if x <= 0]
                results.append({
                    "entry": label(*entry), "stop": label(*stop_spot), "tp": tp, "mode": mode, "hold": hold,
                    "trades": len(trades), "skipped": skipped, "win": len(wins) / len(rets), "avg": st.mean(rets),
                    "avg_loss": -st.mean(losses) if losses else 0.0, "worst": min(rets),
                    "pf": sum(wins) / sum(losses) if sum(losses) > 0 else float("inf"),
                    "per_signal": st.mean(per_signal), "first": st.mean(halves[0]), "second": st.mean(halves[1]),
                })

    def fmt(r: dict) -> str:
        return (f"| {r['entry']} | +{r['tp']:.0%} | {r['stop']} ({r['mode']}) | {r['hold']}일 | {r['trades']} | {r['win']:.0%} | "
                f"{r['avg']:+.2%} | {r['avg_loss']:+.1%} | {r['worst']:+.1%} | {r['pf']:.2f} | **{r['per_signal']:+.2%}** | "
                f"{r['first']:+.2%} / {r['second']:+.2%} |")

    header = ("| 매수 | 익절 | 손절 | 보유 | 거래 | 승률 | 거래당 | 평균손실 | 최악 | PF | 신호당 | 앞/뒤 |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|---|")
    robust = [r for r in results if r["first"] > 0 and r["second"] > 0]
    print(f"\n조합 {len(results):,}개 평가, 앞/뒤 모두 플러스 {len(robust)}개")

    print(f"\n## 1. 매수 위치별 최고 조합 (앞/뒤 중 약한 구간 기준)\n{header}")
    best = {}
    for r in results:
        key = r["entry"]
        if key not in best or min(r["first"], r["second"]) > min(best[key]["first"], best[key]["second"]):
            best[key] = r
    for r in sorted(best.values(), key=lambda r: min(r["first"], r["second"]), reverse=True):
        print(fmt(r))

    print(f"\n## 2. 앞/뒤 모두 플러스 상위 {args.top} (약한 구간 기준)\n{header}")
    for r in sorted(robust, key=lambda r: min(r["first"], r["second"]), reverse=True)[: args.top]:
        print(fmt(r))

    print("\n## 3. 익절 % 별 성과 (앞/뒤 모두 플러스 조합 수, 최고 신호당)")
    for tp in TAKE_PROFITS:
        rs = [r for r in robust if r["tp"] == tp]
        top = max(rs, key=lambda r: r["per_signal"]) if rs else None
        print(f"  +{tp:.0%}: {len(rs)}개" + (f", 최고 {top['per_signal']:+.2%} ({top['entry']} / {top['stop']} {top['mode']})" if top else ""))

    print("\n## 4. 손절 위치별 성과 (앞/뒤 모두 플러스 조합 수, 최고 신호당)")
    for spot in spots:
        for mode in STOP_MODES:
            rs = [r for r in robust if r["stop"] == label(*spot) and r["mode"] == mode]
            if rs:
                top = max(rs, key=lambda r: r["per_signal"])
                print(f"  {label(*spot)} ({mode}): {len(rs)}개, 최고 {top['per_signal']:+.2%} (매수 {top['entry']}, +{top['tp']:.0%}, 평균손실 {top['avg_loss']:+.1%})")


if __name__ == "__main__":
    main()
