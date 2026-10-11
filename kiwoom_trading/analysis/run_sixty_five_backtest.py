"""65기법 매도 규칙 비교 백테스트 (DuckDB 일봉, 전 종목).

    python -m kiwoom_trading.analysis.run_sixty_five_backtest
    python -m kiwoom_trading.analysis.run_sixty_five_backtest --detail "손절-10/익절+20"
"""
import argparse
import os
import statistics as st
import sys
from collections import Counter

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators.sixty_five_exit import ExitRule, Trade, simulate
from kiwoom_trading.analysis.indicators.sixty_five_strategy import SixtyFiveConfig
from kiwoom_trading.analysis.sixty_five_report import scan_all
from kiwoom_trading.common.daily_store import DailyStore


RULES = [
    ExitRule("20일 보유", max_hold_days=20),
    ExitRule("60일 보유", max_hold_days=60),
    ExitRule("손절-10/익절+15", stop_loss=-0.10, take_profit=0.15),
    ExitRule("손절-10/익절+20", stop_loss=-0.10, take_profit=0.20),
    ExitRule("손절-7/익절+20", stop_loss=-0.07, take_profit=0.20),
    ExitRule("손절-15/익절+30", stop_loss=-0.15, take_profit=0.30),
    ExitRule("첫봉저가손절/익절+20", structure_stop=True, take_profit=0.20),
    ExitRule("손절-10/추적-15", stop_loss=-0.10, trailing_stop=0.15),
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
            print(f"  {t.signal_date} {name} 진입 {t.entry_date} ({t.fills}회 체결) 평단 {t.avg_cost:,.0f} → "
                  f"{t.exit_date} {t.exit_price:,.0f} {t.ret:+.1%} [{t.reason}]")


if __name__ == "__main__":
    main()
