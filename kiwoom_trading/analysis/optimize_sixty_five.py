"""65기법 매수가 / 매도 기준 그리드 서치 (포착 기준은 고정).

    python -m kiwoom_trading.analysis.optimize_sixty_five
    python -m kiwoom_trading.analysis.optimize_sixty_five --cost 0.003 --min-trades 40

평가
- 신호당 평균 순수익 = (체결된 거래 수익 합 - 거래비용) / 전체 신호 수   (미체결 신호는 0)
- 신호를 날짜 중앙값 기준 앞/뒤 절반으로 나눠 두 구간 모두에서의 성과를 함께 본다 (과최적화 점검).

체결/청산 가정 (sixty_five_exit 와 동일)
- 지정가: 신호 다음 거래일부터 valid 거래일 동안 저가 ≤ 지정가면 체결, 갭하락이면 시가 체결
- 분할 매수는 같은 금액, 같은 날 여러 주문은 높은 가격부터 체결
- 장중 손절: 체결일 포함, 저가 ≤ 손절가면 손절 (손절가가 다음 지정가보다 위면 남은 주문 취소)
- 종가 손절: 종가 ≤ 손절가면 그날 종가에 청산
- 익절: 체결 다음 날부터 고가 ≥ 목표가 (갭상승은 시가), 같은 날 손절과 겹치면 손절 우선
- 최대 보유: 첫 체결일로부터 N거래일째 종가
"""
import argparse
import itertools
import os
import statistics as st
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators.sixty_five_strategy import SixtyFiveConfig, SixtyFiveSignal
from kiwoom_trading.analysis.sixty_five_report import scan_all
from kiwoom_trading.common.daily_store import DailyStore


Rows = list[dict[str, Any]]


@dataclass(frozen=True)
class SignalCtx:
    signal: SixtyFiveSignal
    rows: Rows
    idx: int            # 신호일 인덱스
    first: dict         # 첫 장대양봉 row
    second: dict        # 두 번째 장대양봉 row (없으면 첫 번째)
    last: dict          # 마지막 장대양봉 row (= 신호일)


def _mid(row: dict) -> float:
    return (row["open"] + row["close"]) / 2


# 매수가 후보: ctx -> 지정가 목록 (None = 익일 시가 시장가)
ENTRIES: dict[str, Callable[[SignalCtx], list[Optional[float]]]] = {
    "익일 시가": lambda c: [None],
    "신호종가-3%": lambda c: [c.last["close"] * 0.97],
    "신호종가-5%": lambda c: [c.last["close"] * 0.95],
    "신호종가-8%": lambda c: [c.last["close"] * 0.92],
    "신호종가-10%": lambda c: [c.last["close"] * 0.90],
    "신호종가-15%": lambda c: [c.last["close"] * 0.85],
    "마지막봉 시가": lambda c: [c.last["open"]],
    "마지막봉 몸통중간": lambda c: [_mid(c.last)],
    "2번째봉 몸통중간": lambda c: [_mid(c.second)],
    "첫봉 종가": lambda c: [c.first["close"]],
    "첫봉 몸통중간": lambda c: [_mid(c.first)],
    "분할: 2번째봉 중간+첫봉 종가": lambda c: [_mid(c.second), c.first["close"]],
    "분할: 신호종가 -5%/-10%": lambda c: [c.last["close"] * 0.95, c.last["close"] * 0.90],
}
VALID_DAYS = [3, 5, 10, 20]
TAKE_PROFITS = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, None]
STOP_LOSSES: list[Any] = [0.02, 0.03, 0.05, 0.07, 0.10, 0.15, "첫봉저가", None]
STOP_MODES = ["장중", "종가"]
MAX_HOLDS = [1, 3, 5, 10, 20]


def build_contexts(results) -> list[SignalCtx]:
    ctxs = []
    for signal, rows in results:
        by_date = {r["date"]: i for i, r in enumerate(rows)}
        candles = [rows[by_date[c.date]] for c in signal.candles]
        ctxs.append(SignalCtx(signal, rows, by_date[signal.signal_date], candles[0], candles[min(1, len(candles) - 1)], candles[-1]))
    return ctxs


def find_fills(ctx: SignalCtx, limits: list[Optional[float]], valid: int) -> list[tuple[int, float]]:
    """[(day_index, price)] — 날짜순, 같은 날은 높은 가격 먼저."""
    rows, fills = ctx.rows, []
    end = min(len(rows) - 1, ctx.idx + valid)
    for limit in limits:
        for i in range(ctx.idx + 1, end + 1):
            row = rows[i]
            if limit is None:
                fills.append((i, row["open"]))
                break
            if row["low"] <= limit:
                fills.append((i, min(row["open"], limit)))
                break
    return sorted(fills, key=lambda f: (f[0], -f[1]))


def simulate(ctx: SignalCtx, fills: list[tuple[int, float]], tp, sl, mode: str, hold: int) -> Optional[tuple[float, int, bool]]:
    """(수익률, 보유일, 데이터 끝까지 보유중 여부)"""
    if not fills:
        return None
    rows = ctx.rows
    entry_i = fills[0][0]
    prices: list[float] = []
    structure = ctx.first["low"]

    def level() -> Optional[float]:
        if sl is None:
            return None
        if sl == "첫봉저가":
            return structure
        return sum(prices) / len(prices) * (1 - sl)

    k = 0
    for i in range(entry_i, len(rows)):
        row = rows[i]
        filled_today = False
        while k < len(fills) and fills[k][0] == i:
            lv = level() if prices else None
            if mode == "장중" and lv is not None and lv > fills[k][1] and row["low"] <= lv:
                return min(row["open"], lv) / (sum(prices) / len(prices)) - 1, i - entry_i, False
            prices.append(fills[k][1])
            k += 1
            filled_today = True
        avg = sum(prices) / len(prices)
        lv = level()
        if lv is not None:
            if mode == "장중" and row["low"] <= lv:
                exit_price = lv if filled_today else min(row["open"], lv)
                return exit_price / avg - 1, i - entry_i, False
            if mode == "종가" and row["close"] <= lv:
                return row["close"] / avg - 1, i - entry_i, False
        if not filled_today and tp is not None and row["high"] >= avg * (1 + tp):
            return max(row["open"], avg * (1 + tp)) / avg - 1, i - entry_i, False
        if i - entry_i >= hold:
            return row["close"] / avg - 1, i - entry_i, False
    return rows[-1]["close"] / (sum(prices) / len(prices)) - 1, len(rows) - 1 - entry_i, True


def main() -> None:
    parser = argparse.ArgumentParser(description="65기법 매수/매도 기준 그리드 서치")
    parser.add_argument("--cost", type=float, default=0.0025, help="왕복 거래비용 (기본 0.0025 = 0.25%%)")
    parser.add_argument("--min-trades", type=int, default=40)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    store = DailyStore()
    db_path = store.db_path
    store.close()
    conn = duckdb.connect(db_path, read_only=True)
    try:
        results, _ = scan_all(conn, SixtyFiveConfig())
    finally:
        conn.close()
    ctxs = build_contexts(results)
    split = sorted(c.signal.signal_date for c in ctxs)[len(ctxs) // 2]
    halves = [[c.signal.signal_date < split for c in ctxs], [c.signal.signal_date >= split for c in ctxs]]
    print(f"신호 {len(ctxs)}건 | 앞 구간 < {split} ≤ 뒤 구간 | 거래비용 {args.cost:.2%}")

    rows_out = []
    for entry_name, valid in itertools.product(ENTRIES, VALID_DAYS):
        if entry_name == "익일 시가" and valid != VALID_DAYS[0]:
            continue  # 시장가는 유효기간 무관
        fills_all = [find_fills(c, ENTRIES[entry_name](c), valid) for c in ctxs]
        for tp, sl, mode, hold in itertools.product(TAKE_PROFITS, STOP_LOSSES, STOP_MODES, MAX_HOLDS):
            if sl is None and mode == "종가":
                continue
            per_signal = []
            trades = []
            for c, fills in zip(ctxs, fills_all):
                r = simulate(c, fills, tp, sl, mode, hold)
                if r is None or r[2]:
                    per_signal.append(0.0)
                    continue
                net = r[0] - args.cost
                per_signal.append(net)
                trades.append((net, r[1]))
            if len(trades) < args.min_trades:
                continue
            rets = [t[0] for t in trades]
            wins, losses = [x for x in rets if x > 0], [-x for x in rets if x <= 0]
            half_means = [st.mean([v for v, m in zip(per_signal, h) if m]) for h in halves]
            rows_out.append({
                "entry": entry_name, "valid": valid, "tp": tp, "sl": sl, "mode": mode, "hold": hold,
                "per_signal": st.mean(per_signal), "first": half_means[0], "second": half_means[1],
                "trades": len(trades), "win": len(wins) / len(rets), "avg": st.mean(rets),
                "pf": sum(wins) / sum(losses) if sum(losses) > 0 else float("inf"),
                "days": st.mean(t[1] for t in trades),
            })

    def fmt(r: dict) -> str:
        tp = f"+{r['tp']:.0%}" if r["tp"] is not None else "없음"
        sl = r["sl"] if isinstance(r["sl"], str) or r["sl"] is None else f"-{r['sl']:.0%}"
        sl = "없음" if sl is None else sl
        valid = "-" if r["entry"] == "익일 시가" else f"{r['valid']}일"
        return (f"| {r['entry']} | {valid} | {tp} | {sl} ({r['mode']}) | {r['hold']}일 | {r['trades']} | {r['win']:.0%} | "
                f"{r['avg']:+.2%} | {r['pf']:.2f} | {r['days']:.1f}일 | **{r['per_signal']:+.2%}** | {r['first']:+.2%} / {r['second']:+.2%} |")

    header = "| 매수가 | 유효 | 익절 | 손절 | 최대보유 | 거래 | 승률 | 거래당 | PF | 보유 | 신호당 | 앞/뒤 구간 |\n|---|---|---|---|---|---|---|---|---|---|---|---|"
    print(f"\n조합 {len(rows_out):,}개 평가\n")
    robust = sorted([r for r in rows_out if r["first"] > 0 and r["second"] > 0], key=lambda r: min(r["first"], r["second"]), reverse=True)
    print(f"## 앞/뒤 두 구간 모두 플러스: {len(robust)}개 — 약한 구간 기준 상위 {args.top}\n{header}")
    for r in robust[: args.top]:
        print(fmt(r))
    print(f"\n## 전체 기간 신호당 수익 상위 {args.top}\n{header}")
    for r in sorted(rows_out, key=lambda r: r["per_signal"], reverse=True)[: args.top]:
        print(fmt(r))
    print(f"\n## 매수가별 최고 조합\n{header}")
    best_by_entry = {}
    for r in rows_out:
        if r["entry"] not in best_by_entry or min(r["first"], r["second"]) > min(best_by_entry[r["entry"]]["first"], best_by_entry[r["entry"]]["second"]):
            best_by_entry[r["entry"]] = r
    for r in sorted(best_by_entry.values(), key=lambda r: min(r["first"], r["second"]), reverse=True):
        print(fmt(r))


if __name__ == "__main__":
    main()
