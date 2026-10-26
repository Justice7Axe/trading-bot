import os
import sys

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.strategies.testa.rules import (
    TestaStrategyConfig,
    backtest_testa_ma_strategy,
)
from kiwoom_trading.common.config import load_settings
from kiwoom_trading.common.storage import SupabaseReader


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def main() -> None:
    settings = load_settings()
    fetch_limit = int(os.getenv("ANALYSIS_FETCH_LIMIT", "5000"))

    reader = SupabaseReader(
        supabase_url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
        table_name=settings.supabase_table,
    )

    config = TestaStrategyConfig(
        ma_short=int(os.getenv("TESTA_MA_SHORT", "5")),
        ma_mid=int(os.getenv("TESTA_MA_MID", "25")),
        ma_long=int(os.getenv("TESTA_MA_LONG", "75")),
        long_slope_lookback=int(os.getenv("TESTA_SLOPE_LOOKBACK", "3")),
        short_swing_lookback=int(os.getenv("TESTA_SWING_LOOKBACK", "5")),
        resistance_lookback=int(os.getenv("TESTA_RESISTANCE_LOOKBACK", "20")),
        risk_reward_ratio=float(os.getenv("TESTA_RR_RATIO", "3.0")),
        partial_exit_ratio=float(os.getenv("TESTA_PARTIAL_EXIT_RATIO", "0.5")),
    )

    print("=== 테스타 이평(5/25/75) 백테스트 ===")
    print(f"- 조회 테이블: {settings.supabase_table}")
    print(f"- 종목: {', '.join(settings.stock_codes)}")
    print(f"- 조회 건수(종목별): {fetch_limit}")
    print(
        f"- 파라미터: MA({config.ma_short}/{config.ma_mid}/{config.ma_long}), "
        f"RR 1:{_fmt(config.risk_reward_ratio)}"
    )
    print("")

    for stock_code in settings.stock_codes:
        rows = reader.fetch_recent_by_stock(stock_code=stock_code, limit=fetch_limit)
        result = backtest_testa_ma_strategy(rows_desc=rows, config=config)
        trades = result["trades"]
        print(f"[{stock_code}]")
        print(f"- 사용 분봉 수: {result['bars']}")
        print(f"- 총 거래 수: {result['total_trades']}")
        print(f"- 승률: {_fmt(result['win_rate_pct'])}%")
        print(f"- 평균 R: {_fmt(result['avg_r'])}")
        print(f"- 누적 R: {_fmt(result['total_r'])}")
        print(f"- 최대 연속 손실: {result['max_loss_streak']}")

        if trades:
            latest = trades[-1]
            print(
                "- 최근 거래: "
                f"{latest['side']} {latest['entry_time']} -> {latest['exit_time']} "
                f"({latest['reason']}, {latest['pnl_r']:+.2f}R, {latest['pnl_pct']:+.2f}%)"
            )
        print("")


if __name__ == "__main__":
    main()
