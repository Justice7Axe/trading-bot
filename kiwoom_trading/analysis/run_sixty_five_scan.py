"""65기법 스캔 실행 (DuckDB 일봉 데이터 대상).

    python -m kiwoom_trading.analysis.run_sixty_five_scan                     # DB 전 종목
    python -m kiwoom_trading.analysis.run_sixty_five_scan --codes 009150
    python -m kiwoom_trading.analysis.run_sixty_five_scan --codes 009150 --window 5 --base open
"""
import argparse
import os
import sys

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators.sixty_five_strategy import SixtyFiveConfig, scan_sixty_five
from kiwoom_trading.common.daily_store import DailyStore


def _eok(value: int) -> str:
    return f"{value / 100_000_000:,.0f}억"


def _cap(value) -> str:
    if value is None:
        return "시총 미상"
    return f"시총 {value / 1_000_000_000_000:,.1f}조" if value >= 1_000_000_000_000 else f"시총 {_eok(value)}"


def load_rows(conn: duckdb.DuckDBPyConnection, code: str) -> list[dict]:
    cursor = conn.execute(
        "SELECT date, open, high, low, close, value, market_cap FROM daily_ohlcv WHERE code = ? ORDER BY date", [code]
    )
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(description="65기법 종목 발굴 스캔")
    parser.add_argument("--codes", default="", help="쉼표 구분 종목코드 (비우면 DB 전 종목)")
    parser.add_argument("--window", type=int, default=6, help="캔들 창 크기 (기본 6)")
    parser.add_argument("--min-rise", type=float, default=0.15, help="장대양봉 기준 상승률 (기본 0.15)")
    parser.add_argument("--target", type=float, default=0.65, help="장대양봉 상승률 합계 기준 (기본 0.65)")
    parser.add_argument("--large-cap-jo", type=float, default=10.0, help="대형주 기준을 적용할 시가총액(조, 기본 10)")
    parser.add_argument("--large-cap-rise", type=float, default=0.13, help="대형주 장대양봉 기준 (기본 0.13)")
    parser.add_argument("--large-cap-count", type=int, default=3, help="대형주 최소 장대양봉 개수 (기본 3)")
    parser.add_argument("--large-cap-target", type=float, default=0.50, help="대형주 합계 기준 (기본 0.50)")
    parser.add_argument("--max-rally-days", type=int, default=0, help="1차 장대양봉~신호일 최대 거래일 수 (기본 0=끔)")
    parser.add_argument("--min-cap-eok", type=int, default=5000, help="신호일 최소 시가총액(억, 기본 5000, 0이면 끔)")
    parser.add_argument("--min-5d-rise", type=float, default=0.33, help="5봉전 종가 대비 신호일 고가 최소 등락률 (기본 0.33, 음수면 끔)")
    parser.add_argument("--min-value-eok", type=int, default=1000, help="장대양봉 최소 거래대금(억, 기본 1000)")
    parser.add_argument("--base", choices=("prev_close", "open"), default="prev_close", help="상승률 기준: 전일종가 / 당일시가")
    parser.add_argument("--top", type=int, default=5, help="조건 미달 시 보여줄 상위 창 개수")
    args = parser.parse_args()

    config = SixtyFiveConfig(
        window=args.window,
        min_candle_rise=args.min_rise,
        target_sum=args.target,
        min_trade_value=args.min_value_eok * 100_000_000,
        rise_base=args.base,
        large_cap_threshold=int(args.large_cap_jo * 1_000_000_000_000),
        large_cap_min_candle_rise=args.large_cap_rise,
        large_cap_min_candles=args.large_cap_count,
        large_cap_target_sum=args.large_cap_target,
        min_rise_from_lookback=args.min_5d_rise if args.min_5d_rise >= 0 else None,
        min_market_cap=args.min_cap_eok * 100_000_000,
        max_rally_days=args.max_rally_days or None,
    )

    store = DailyStore()  # 경로/환경변수 해석만 재사용
    db_path = store.db_path
    store.close()
    conn = duckdb.connect(db_path, read_only=True)
    try:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()] or [
            row[0] for row in conn.execute("SELECT DISTINCT code FROM daily_ohlcv ORDER BY code").fetchall()
        ]
        stock_info = {code: (name, shares) for code, name, shares in conn.execute("SELECT code, name, listed_shares FROM stocks").fetchall()}

        print(
            f"=== 65기법 스캔: {len(codes)}종목 | 창 {config.window}캔들, 장대양봉 ≥{config.min_candle_rise:.0%} "
            f"(고가/{'전일종가' if config.rise_base == 'prev_close' else '시가'}), 합계 ≥{config.target_sum:.0%} "
            f"(시총 {config.large_cap_threshold / 1e12:g}조 이상: +{config.large_cap_min_candle_rise:.0%} 장대양봉 "
            f"{config.large_cap_min_candles}개 이상, 합계 ≥{config.large_cap_target_sum:.0%}), "
            f"거래대금 ≥{_eok(config.min_trade_value)} ==="
        )
        total_signals = 0
        for code in codes:
            rows = load_rows(conn, code)
            if not rows:
                print(f"\n[{code}] 데이터 없음")
                continue
            name, listed_shares = stock_info.get(code, (None, None))
            signals, scores = scan_sixty_five(code, rows, config, listed_shares)
            total_signals += len(signals)
            label = f"{code} {name or ''}".strip()
            if listed_shares is None and not any(r.get("market_cap") for r in rows):
                label += " (상장주식수 없음 → 65% 기준만 적용)"
            print(f"\n[{label}] {rows[0]['date']} ~ {rows[-1]['date']} ({len(rows)}일) → 신호 {len(signals)}건")

            for s in signals:
                print(
                    f"  ★ 신호일 {s.signal_date} (창 {s.window_start}~) 합계 {s.rise_sum:.1%} ≥ 기준 {s.target_sum:.0%} "
                    f"| 종가 {s.signal_close:,}, {_cap(s.market_cap)}"
                )
                for c in s.candles:
                    print(f"     - {c.date} 고가 {c.high:,} (+{c.rise:.1%}) 거래대금 {_eok(c.trade_value)}")

            for w in scores:
                if w.rejected:
                    print(f"  ✕ {w.end_date} 합계 {w.rise_sum:.1%} 통과했지만 필터 탈락: {w.rejected} ({_cap(w.market_cap)})")

            if not signals:
                # 같은 장대양봉 조합은 창이 달라도 하나로 묶는다 (가장 이른 창 기준)
                unique: dict[tuple, object] = {}
                for w in scores:
                    unique.setdefault(w.candle_dates or (w.end_date,), w)
                best = sorted(unique.values(), key=lambda w: w.rise_sum, reverse=True)[: args.top]
                if not best:
                    print(f"  기준({config.min_candle_rise:.0%}) 이상 캔들 없음")
                for w in best:
                    note = f", 거래대금 미달로 제외 {w.excluded_by_value}개" if w.excluded_by_value else ""
                    dates = ", ".join(d.strftime("%m-%d") for d in w.candle_dates) or "-"
                    print(f"  · 합계 {w.rise_sum:.1%} (기준 {w.target_sum:.0%}, {_cap(w.market_cap)}) | 장대양봉 {w.candle_count}개 [{dates}]{note}")
        print(f"\n총 신호 {total_signals}건")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
