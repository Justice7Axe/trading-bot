"""65기법 리포트: 전 종목 스캔 → 오늘 기준 일일 리포트(텔레그램 전송용) / 과거 신호 이력.

    python -m kiwoom_trading.analysis.sixty_five_report                     # 일일 리포트 (오늘 포착/매수 대기/보유 중)
    python -m kiwoom_trading.analysis.sixty_five_report --send              # 텔레그램 전송
    python -m kiwoom_trading.analysis.sixty_five_report --history --top 10  # 과거 신호 이력
"""
import argparse
import os
import sys
from collections import defaultdict
from typing import Any, Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators.sixty_five_entry import DEFAULT_ENTRY_VALID_DAYS, EntryPlan, plan_entries
from kiwoom_trading.analysis.indicators.sixty_five_exit import DEFAULT_EXIT_RULE, simulate, structure_stop_price
from kiwoom_trading.analysis.indicators.sector_strength import compute_sector_metrics, leading_sector_reason
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
    return apply_sector_filter(conn, results, config), info


def apply_sector_filter(conn: duckdb.DuckDBPyConnection, results: list, config: SixtyFiveConfig) -> list:
    """신호에 업종 지표를 붙이고, 주도 섹터 조건을 통과한 신호만 남긴다."""
    metrics = compute_sector_metrics(conn, [(s.stock_code, s.signal_date) for s, _ in results])
    kept = []
    for s, rows in results:
        s.sector = metrics.get((s.stock_code, s.signal_date))
        if leading_sector_reason(s.sector, config.min_sector_value_share, config.min_sector_big_ratio) is None:
            kept.append((s, rows))
    return kept


def describe_entry(plan: EntryPlan, stop_price: Optional[float]) -> list[str]:
    limit = plan.entry_price
    target = limit * (1 + DEFAULT_EXIT_RULE.take_profit)
    lines = ["매매 계획"]
    if plan.fill:
        gap = " (갭하락 시가 체결)" if plan.fill.price < limit else ""
        lines.append(f"  매수 {limit:,} (1차 장대양봉 종가) → 체결 {plan.fill.date:%m-%d} (+{plan.fill.days_after_signal}일){gap}")
    elif plan.still_open:
        lines.append(f"  매수 {limit:,} (1차 장대양봉 종가) → 대기 중 (현재가 {plan.last_close:,} 대비 {_pct(limit, plan.last_close)}, ~{plan.valid_until or f'{DEFAULT_ENTRY_VALID_DAYS}거래일'})")
    else:
        lines.append(f"  매수 {limit:,} (1차 장대양봉 종가) → 미체결 ({DEFAULT_ENTRY_VALID_DAYS}거래일 내 미도달)")
    stop_text = f"손절 {stop_price:,.0f} (1차 장대양봉 시가, {_pct(stop_price, limit)})" if stop_price else "손절 없음"
    lines.append(f"  익절 {target:,.0f} (+{DEFAULT_EXIT_RULE.take_profit:.0%}) / {stop_text} / 최대 {DEFAULT_EXIT_RULE.max_hold_days}거래일")
    if stop_price and stop_price >= limit:
        lines.append("  ※ 손절선이 매수가 이상 → 매매 제외")
    return lines


STAR_TURNOVER = 0.30  # 신호일 거래대금 / 시가총액 — 백테스트상 5거래일 성과가 좋았던 구간


def turnover_of(signal: SixtyFiveSignal, rows: list[dict[str, Any]]) -> Optional[float]:
    row = next(r for r in rows if r["date"] == signal.signal_date)
    return row["value"] / signal.market_cap if signal.market_cap and row.get("value") else None


def describe_signal(signal: SixtyFiveSignal, rows: list[dict[str, Any]], name: Optional[str], signal_count: int, latest_date) -> str:
    idx = next(i for i, r in enumerate(rows) if r["date"] == signal.signal_date)
    sig_close = rows[idx]["close"]
    after = rows[idx + 1:]
    last = rows[-1]
    is_new = signal.signal_date == latest_date
    turnover = turnover_of(signal, rows)
    star = turnover is not None and turnover >= STAR_TURNOVER

    lines = [
        f"{'🆕 ' if is_new else ''}{'⭐ ' if star else ''}{name or ''} ({signal.stock_code})",
        f"신호일 {signal.signal_date} | 합계 {signal.rise_sum:.1%} ≥ 기준 {signal.target_sum:.0%} | {_cap(signal.market_cap)}"
        + (f" | 회전율 {turnover:.0%}" if turnover is not None else ""),
        (f"업종 {signal.sector.sector}: 거래대금 비중 {signal.sector.value_share:.1%} / 장대양봉 비율 {signal.sector.big_ratio:.0%}"
         if signal.sector else "업종 정보 없음"),
    ]
    for c in signal.candles:
        lines.append(f"  · {c.date:%m-%d} 고가 {c.high:,} (+{c.rise:.1%}) 대금 {c.trade_value / 1e8:,.0f}억")
    lines += describe_entry(plan_entries(signal, rows), structure_stop_price(signal, rows, DEFAULT_EXIT_RULE))
    trade = simulate(signal, rows, DEFAULT_EXIT_RULE)
    if trade and trade.is_open:
        lines.append(f"  매도: 보유 {trade.holding_days}/{DEFAULT_EXIT_RULE.max_hold_days}일째, 현재 {trade.ret:+.1%}")
    elif trade:
        verdict = "✅ 수익" if trade.ret > 0 else "❌ 손실"
        how = {"익절": "익절", "손절": "손절"}.get(trade.reason, "종가")
        lines.append(
            f"  매도: {trade.exit_date:%m-%d} {how} {trade.exit_price:,.0f} (매수 후 {trade.holding_days}거래일) "
            f"→ {trade.ret:+.1%} {verdict}"
        )

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


def _conditions_text(config: SixtyFiveConfig) -> list[str]:
    return [
        f"조건: {config.window}캔들 내 고가 기준 +{config.min_candle_rise:.0%} 장대양봉(대금 ≥{config.min_trade_value / 1e8:,.0f}억) 합계 "
        f"≥{config.target_sum:.0%} (시총 {config.large_cap_threshold / 1e12:g}조↑: +{config.large_cap_min_candle_rise:.0%} "
        f"{config.large_cap_min_candles}개 이상, 합계 ≥{config.large_cap_target_sum:.0%})"
        + (f" | {config.lookback_bars}봉전 종가 대비 고가 ≥{config.min_rise_from_lookback:.0%}" if config.min_rise_from_lookback is not None else "")
        + (f" | 시총 ≥{config.min_market_cap / 1e8:,.0f}억" if config.min_market_cap else "")
        + (f" | 급등 {config.max_rally_days}거래일 이내" if config.max_rally_days else "")
        + (f" | 주도 업종(거래대금 비중 ≥{config.min_sector_value_share:.0%}, 장대양봉 비율 ≥{config.min_sector_big_ratio:.0%})"
           if config.min_sector_value_share is not None or config.min_sector_big_ratio is not None else ""),
        f"매매: 1차 장대양봉 종가 지정가(신호 다음 거래일부터 {DEFAULT_ENTRY_VALID_DAYS}거래일) → +{DEFAULT_EXIT_RULE.take_profit:.0%} 익절 / "
        f"1차 장대양봉 {DEFAULT_EXIT_RULE.structure_stop} 이탈 손절 / 최대 {DEFAULT_EXIT_RULE.max_hold_days}거래일",
        f"⭐ = 신호일 회전율(거래대금÷시총) {STAR_TURNOVER:.0%} 이상",
    ]


def _load(config: SixtyFiveConfig):
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
    return latest_date, stock_count, results, info


def _star(signal: SixtyFiveSignal, rows: list[dict[str, Any]]) -> str:
    turnover = turnover_of(signal, rows)
    return "⭐" if turnover is not None and turnover >= STAR_TURNOVER else ""


def build_report(config: Optional[SixtyFiveConfig] = None) -> str:
    """일일 리포트: 오늘 포착 / 매수 대기 중 / 보유 중 / 오늘 청산."""
    config = config or SixtyFiveConfig()
    latest_date, stock_count, results, info = _load(config)

    def name_of(code: str) -> str:
        return (info.get(code) or (None, None))[0] or code

    today, pending, holding, closed_today = [], [], [], []
    for s, rows in results:
        if s.signal_date == latest_date:
            today.append((s, rows))
            continue
        plan = plan_entries(s, rows)
        stop = structure_stop_price(s, rows, DEFAULT_EXIT_RULE)
        if plan.still_open and (stop is None or stop < plan.entry_price):
            pending.append((s, rows, plan, stop))
            continue
        trade = simulate(s, rows, DEFAULT_EXIT_RULE)
        if trade and trade.is_open:
            holding.append((s, rows, trade, stop))
        elif trade and trade.exit_date == latest_date:
            closed_today.append((s, rows, trade))

    lines = [f"📈 65기법 일일 리포트 ({latest_date})", f"스캔 {stock_count:,}종목", *_conditions_text(config)]

    lines.append(f"\n🆕 오늘 포착 {len(today)}종목")
    if not today:
        lines.append("  오늘 포착 종목 없음")
    for s, rows in sorted(today, key=lambda x: x[0].stock_code):
        lines.append(describe_signal(s, rows, name_of(s.stock_code), 1, latest_date))

    lines.append(f"\n⏳ 매수 대기 중 {len(pending)}종목 (지정가 유지)")
    if not pending:
        lines.append("  없음")
    for s, rows, plan, stop in sorted(pending, key=lambda x: x[0].signal_date, reverse=True):
        signal_idx = next(i for i, r in enumerate(rows) if r["date"] == s.signal_date)
        left = DEFAULT_ENTRY_VALID_DAYS - (len(rows) - 1 - signal_idx)
        stop_text = f"손절 {stop:,.0f}({_pct(stop, plan.entry_price)})" if stop else "손절 없음"
        lines.append(
            f"  {_star(s, rows)}{name_of(s.stock_code)}({s.stock_code}) 신호 {s.signal_date:%m-%d} | 매수 {plan.entry_price:,} "
            f"(현재 {plan.last_close:,} 대비 {_pct(plan.entry_price, plan.last_close)}) | "
            f"익절 {plan.entry_price * (1 + DEFAULT_EXIT_RULE.take_profit):,.0f} | {stop_text} | 남은 {left}거래일"
        )

    lines.append(f"\n📌 보유 중 {len(holding)}종목")
    if not holding:
        lines.append("  없음")
    for s, rows, trade, stop in holding:
        lines.append(
            f"  {_star(s, rows)}{name_of(s.stock_code)}({s.stock_code}) 매수 {trade.entry_date:%m-%d} {trade.entry_price:,.0f} → "
            f"현재 {trade.exit_price:,.0f} ({trade.ret:+.1%}) | 익절 {trade.entry_price * (1 + DEFAULT_EXIT_RULE.take_profit):,.0f} "
            f"| 손절 {stop:,.0f} | 보유 {trade.holding_days}/{DEFAULT_EXIT_RULE.max_hold_days}일"
        )

    if closed_today:
        lines.append(f"\n✅ 오늘 청산 {len(closed_today)}종목")
        for s, rows, trade in closed_today:
            how = {"익절": "익절", "손절": "손절"}.get(trade.reason, "5일 종가")
            lines.append(f"  {name_of(s.stock_code)}({s.stock_code}) {how} {trade.exit_price:,.0f} → {trade.ret:+.1%}")
    return "\n".join(lines)


def build_history_report(top_n: int = 5, config: Optional[SixtyFiveConfig] = None) -> str:
    """과거 이력 확인용: 가장 최근 신호 N종목 상세 + 과거 성과."""
    config = config or SixtyFiveConfig()
    latest_date, stock_count, results, info = _load(config)
    counts: dict[str, int] = defaultdict(int)
    for s, _ in results:
        counts[s.stock_code] += 1
    latest_by_code: dict[str, tuple] = {}
    for s, rows in sorted(results, key=lambda x: x[0].signal_date, reverse=True):
        latest_by_code.setdefault(s.stock_code, (s, rows))
    top = list(latest_by_code.values())[:top_n]
    closed = [t for s, rows in results if (t := simulate(s, rows, DEFAULT_EXIT_RULE)) and not t.is_open]
    win_rate = sum(t.ret > 0 for t in closed) / len(closed) if closed else 0
    avg_ret = sum(t.ret for t in closed) / len(closed) if closed else 0
    header = [
        f"📈 65기법 신호 이력 ({latest_date})",
        f"스캔 {stock_count:,}종목 | 전체 신호 {len(results)}건 / {len(latest_by_code)}종목",
        *_conditions_text(config),
        f"과거 성과: {len(closed)}건 승률 {win_rate:.0%}, 평균 {avg_ret:+.1%} (거래비용 미반영)",
        f"── 최근 신호 {len(top)}종목 ──",
    ]
    body = [
        describe_signal(s, rows, (info.get(s.stock_code) or (None, None))[0], counts[s.stock_code], latest_date)
        for s, rows in top
    ]
    return "\n".join(header) + "\n\n" + ("\n\n".join(body) if body else "해당 종목 없음")


def main() -> None:
    parser = argparse.ArgumentParser(description="65기법 리포트 (기본: 오늘 기준 일일 리포트)")
    parser.add_argument("--history", action="store_true", help="과거 신호 이력 리포트")
    parser.add_argument("--top", type=int, default=5, help="--history 에서 보여줄 종목 수")
    parser.add_argument("--send", action="store_true", help="텔레그램으로 전송")
    args = parser.parse_args()

    report = build_history_report(args.top) if args.history else build_report()
    print(report)
    if args.send:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message(report)


if __name__ == "__main__":
    main()
