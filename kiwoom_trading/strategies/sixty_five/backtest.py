"""65기법 매도 규칙 비교 백테스트 (DuckDB 일봉, 전 종목).

    python -m kiwoom_trading.strategies.sixty_five.backtest
    python -m kiwoom_trading.strategies.sixty_five.backtest --detail "손절-10/익절+20"
"""
import argparse
import os
import statistics as st
import sys
from collections import Counter

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.strategies.sixty_five.exit import DEFAULT_EXIT_RULE, ExitRule, Trade, simulate
from kiwoom_trading.strategies.sixty_five.rules import SixtyFiveConfig
from kiwoom_trading.strategies.sixty_five.report import scan_all
from kiwoom_trading.common.daily_store import DailyStore


RULES = [
    DEFAULT_EXIT_RULE,
    ExitRule("익절+5%/1차시가 손절/5거래일", take_profit=0.05, structure_stop="시가", max_hold_days=5),
    ExitRule("익절+15%/1차시가 손절/10거래일", take_profit=0.15, structure_stop="시가", max_hold_days=10),
    ExitRule("익절+20%/1차시가 손절/10거래일", take_profit=0.20, structure_stop="시가", max_hold_days=10),
    ExitRule("익절+25%/1차저가 손절/5거래일", take_profit=0.25, structure_stop="저가", max_hold_days=5),
    ExitRule("익절+5%/손절-2%/5거래일", take_profit=0.05, stop_loss=-0.02, max_hold_days=5),
    ExitRule("익절+5%/손절-10%/5거래일", take_profit=0.05, stop_loss=-0.10, max_hold_days=5),
    ExitRule("5거래일 종가 매도", max_hold_days=5),
]


def summarize(name: str, trades: list[Trade], total_signals: int) -> str:
    closed = [t for t in trades if not t.is_open]
    rets = [t.ret for t in closed]
    wins = [r for r in rets if r > 0]
    losses = [-r for r in rets if r <= 0]
    pf = sum(wins) / sum(losses) if losses and sum(losses) > 0 else float("inf")
    expect = st.mean(rets) if rets else 0
    return (
        f"| {name} | {len(closed)} | {len(wins) / len(rets):.0%} | {expect:+.1%} | {st.median(rets):+.1%} | "
        f"{st.mean(wins) if wins else 0:+.1%} | {-st.mean(losses) if losses else 0:+.1%} | {pf:.2f} | "
        f"{st.mean(t.holding_days for t in closed):.0f}일 |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="65기법 매도 규칙 비교 백테스트")
    parser.add_argument("--detail", default="", help="거래 내역을 출력할 규칙 이름")
    args = parser.parse_args()

    store = DailyStore()
    db_path = store.db_path
    store.close()
    conn = duckdb.connect(db_path, read_only=True)
    try:
        results, info = scan_all(conn, SixtyFiveConfig())
    finally:
        conn.close()

    print(f"신호 {len(results)}건 | 체결된 신호만 거래로 집계 (보유 중인 거래는 제외)\n")
    print("| 규칙 | 거래 | 승률 | 평균 | 중앙값 | 평균 이익 | 평균 손실 | 손익비(PF) | 평균 보유 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for rule in RULES:
        trades = [t for s, rows in results if (t := simulate(s, rows, rule))]
        print(summarize(rule.name, trades, len(results)))
        if rule.name == args.detail:
            detail = trades
    if args.detail:
        print(f"\n[{args.detail}] 청산 사유: {dict(Counter(t.reason for t in detail))}")
        for t in sorted(detail, key=lambda t: t.signal_date, reverse=True)[:30]:
            name = (info.get(t.stock_code) or ("",))[0]
            print(f"  {t.signal_date} {name} 매수 {t.entry_date} {t.entry_price:,.0f} → "
                  f"{t.exit_date} {t.exit_price:,.0f} {t.ret:+.1%} [{t.reason}]")


if __name__ == "__main__":
    main()
