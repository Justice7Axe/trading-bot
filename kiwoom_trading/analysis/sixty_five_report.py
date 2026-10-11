"""65기법 리포트: 전 종목 스캔 → 가장 최근 신호 N종목 요약 (텔레그램 전송용 텍스트).

    python -m kiwoom_trading.analysis.sixty_five_report            # 콘솔 출력
    python -m kiwoom_trading.analysis.sixty_five_report --send     # 텔레그램 전송
    python -m kiwoom_trading.analysis.sixty_five_report --top 10
"""
import argparse
import os
import sys
from collections import defaultdict
from typing import Any, Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators.sixty_five_strategy import SixtyFiveConfig, SixtyFiveSignal, scan_sixty_five
from kiwoom_trading.common.daily_store import DailyStore


def _cap(value: Optional[int]) -> str:
    if value is None:
        return "시총 미상"
    if value >= 1_000_000_000_000:
        return f"시총 {value / 1_000_000_000_000:,.1f}조"
    return f"시총 {value / 100_000_000:,.0f}억"


def _pct(a: float, b: float) -> str:
    return f"{a / b - 1:+.1%}"


def _ma(rows: list[dict[str, Any]], n: int) -> Optional[float]:
    if len(rows) < n:
        return None
    return sum(r["close"] for r in rows[-n:]) / n


def load_all(conn: duckdb.DuckDBPyConnection) -> dict[str, list[dict[str, Any]]]:
    cursor = conn.execute(
        "SELECT code, date, open, high, low, close, value, market_cap FROM daily_ohlcv ORDER BY code, date"
    )
    columns = [d[0] for d in cursor.description]
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cursor.fetchall():
        item = dict(zip(columns, row))
        by_code[item.pop("code")].append(item)
    return by_code


def scan_all(conn: duckdb.DuckDBPyConnection, config: SixtyFiveConfig) -> tuple[list[tuple[SixtyFiveSignal, list[dict[str, Any]]]], dict]:
    info = {code: (name, shares) for code, name, shares in conn.execute("SELECT code, name, listed_shares FROM stocks").fetchall()}
    results = []
    for code, rows in load_all(conn).items():
        signals, _ = scan_sixty_five(code, rows, config, (info.get(code) or (None, None))[1])
        results.extend((s, rows) for s in signals)
    return results, info


def describe_signal(signal: SixtyFiveSignal, rows: list[dict[str, Any]], name: Optional[str], signal_count: int, latest_date) -> str:
    idx = next(i for i, r in enumerate(rows) if r["date"] == signal.signal_date)
    sig_close = rows[idx]["close"]
    after = rows[idx + 1:]
    last = rows[-1]
    is_new = signal.signal_date == latest_date

    lines = [
        f"{'🆕 ' if is_new else ''}{name or ''} ({signal.stock_code})",
        f"신호일 {signal.signal_date} | 합계 {signal.rise_sum:.1%} ≥ 기준 {signal.target_sum:.0%} | {_cap(signal.market_cap)}",
    ]
    for c in signal.candles:
        lines.append(f"  · {c.date:%m-%d} 고가 {c.high:,} (+{c.rise:.1%}) 대금 {c.trade_value / 1e8:,.0f}억")

    if after:
        hi = max(after, key=lambda r: r["high"])
        lo = min(after, key=lambda r: r["low"])
        horizons = [f"+{n}일 {_pct(after[n - 1]['close'], sig_close)}" for n in (1, 5, 20) if len(after) >= n]
        lines.append(f"신호 후: {' / '.join(horizons)}")
        lines.append(f"  최고 {_pct(hi['high'], sig_close)} ({hi['date']:%m-%d}), 최저 {_pct(lo['low'], sig_close)} ({lo['date']:%m-%d})")
    else:
        lines.append("신호 후: 오늘 발생한 신호")

    peak = max(r["high"] for r in rows[idx:])
    ma5, ma20 = _ma(rows, 5), _ma(rows, 20)
    trend = []
    if ma5:
        trend.append(f"MA5 {'위' if last['close'] >= ma5 else '아래'}")
    if ma20:
        trend.append(f"MA20 {'위' if last['close'] >= ma20 else '아래'}")
    lines.append(
        f"현재 {last['date']:%m-%d} {last['close']:,} (신호 대비 {_pct(last['close'], sig_close)}, "
        f"고점 대비 {_pct(last['close'], peak)}) {', '.join(trend)}"
    )
    if signal_count > 1:
        lines.append(f"최근 2년 신호 {signal_count}회")
    return "\n".join(lines)


def build_report(top_n: int = 5, config: Optional[SixtyFiveConfig] = None) -> str:
    config = config or SixtyFiveConfig()
    store = DailyStore()  # 경로/환경변수 해석만 재사용
    db_path = store.db_path
    store.close()

    conn = duckdb.connect(db_path, read_only=True)
    try:
        latest_date = conn.execute("SELECT max(date) FROM daily_ohlcv").fetchone()[0]
        stock_count = conn.execute("SELECT count(DISTINCT code) FROM daily_ohlcv").fetchone()[0]
        results, info = scan_all(conn, config)
    finally:
        conn.close()

    counts: dict[str, int] = defaultdict(int)
    for s, _ in results:
        counts[s.stock_code] += 1
    latest_by_code: dict[str, tuple] = {}
    for s, rows in sorted(results, key=lambda x: x[0].signal_date, reverse=True):
        latest_by_code.setdefault(s.stock_code, (s, rows))
    top = list(latest_by_code.values())[:top_n]
    new_today = sum(1 for s, _ in latest_by_code.values() if s.signal_date == latest_date)

    header = [
        f"📈 65기법 리포트 ({latest_date})",
        f"스캔 {stock_count:,}종목 | 전체 신호 {len(results)}건 / {len(latest_by_code)}종목 | 오늘 신규 {new_today}종목",
        f"조건: {config.window}캔들 내 고가 기준 +{config.min_candle_rise:.0%} 장대양봉(대금 ≥{config.min_trade_value / 1e8:,.0f}억) 합계 "
        f"≥{config.target_sum:.0%} (시총 {config.large_cap_threshold / 1e12:g}조↑ ≥{config.large_cap_target_sum:.0%})",
        f"── 최근 신호 {len(top)}종목 ──",
    ]
    if not top:
        return "\n".join(header + ["해당 종목 없음"])
    body = [
        describe_signal(s, rows, (info.get(s.stock_code) or (None, None))[0], counts[s.stock_code], latest_date)
        for s, rows in top
    ]
    return "\n".join(header) + "\n\n" + "\n\n".join(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="65기법 최근 신호 리포트")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--send", action="store_true", help="텔레그램으로 전송")
    args = parser.parse_args()

    report = build_report(args.top)
    print(report)
    if args.send:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message(report)


if __name__ == "__main__":
    main()
