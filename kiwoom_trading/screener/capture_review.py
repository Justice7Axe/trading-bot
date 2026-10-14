"""장 마감 후 '오늘 포착 종목 복기표' — 포착 경로별로 포착 시점 이후 차트상 수익이 났는지.

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.capture_review               # 마지막 거래일
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.capture_review --date 20261014 --send

포착 경로 (screener.duckdb 기록):
  ⚡ 장중 포착(detections.first_ts) · 👀 조회 급등 · 🌅 프리마켓 주목(watch_adds) · 🏁 조기 주도주 · 🚀 대금 가속 · 🔥 테마 특징주(early_alerts)
  🧩 테마 형성(theme_alerts) · 🔭 전일 관심 · 😴 쉬는 주도주(장 시작부터 감시 → 09:00 시가 기준)
성과: 포착한 분의 종가에 샀다고 가정(통합 1분봉, minute_ohlcv AL — 20:00 일일 업데이트가 감시 종목 1분봉을 저장한 뒤 실행)
  종가까지 = 그날 KRX 종가 / 포착가, 최대 상승·하락 = 15:30 까지 고가·저가, 판정 = +3%·-3% 중 먼저 닿은 쪽. 비용 미반영.
2026-10-14 첫 복기: 108종목 중 +3% 먼저 31 / -3% 먼저 68, 종가까지 평균 -2.0% — 포착은 '무엇을 볼지', 진입은 별도 과제.
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, time
from typing import Optional

import duckdb
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.screener.early_watch import active_rest_leaders
from kiwoom_trading.screener.store import ScreenerStore


SOURCE_LABEL = {"조회 급등": "👀 조회 급등", "프리마켓 주목": "🌅 프리마켓 주목", "조기 주도주": "🏁 조기 주도주",
                "대금 가속": "🚀 대금 가속", "테마 특징주": "🔥 테마 특징주", "테마 형성": "🧩 테마 형성"}
REPORT_DIR = os.path.join(PROJECT_ROOT, "data", "reports")


def collect_events(store: ScreenerStore, day: date) -> list[tuple[str, str, Optional[time]]]:
    """[(code, 경로, 포착 시각 — None 이면 장 시작부터 감시)]"""
    c = store.conn
    ev: list[tuple[str, str, Optional[time]]] = []
    for code, ts in c.execute("SELECT code, coalesce(first_ts, ts) FROM detections WHERE date = ? AND mode = 'intraday'", [day]).fetchall():
        ev.append((code, "⚡ 장중 포착", ts.time()))
    for code, src, ts in c.execute("SELECT code, source, ts FROM watch_adds WHERE date = ?", [day]).fetchall():
        if src in ("조회 급등", "프리마켓 주목"):
            ev.append((code, SOURCE_LABEL[src], ts.time()))
    for code, src, ts in c.execute("SELECT code, source, ts FROM early_alerts WHERE date = ?", [day]).fetchall():
        ev.append((code, SOURCE_LABEL.get(src, src), ts.time()))
    for code, ts in c.execute("SELECT code, min(ts) FROM theme_alerts WHERE date = ? GROUP BY code", [day]).fetchall():
        ev.append((code, "🧩 테마 형성", ts.time()))
    for code in store.previous_daily_watchlist(day):
        ev.append((code, "🔭 전일 관심", None))
    for code in active_rest_leaders(store, day):
        ev.append((code, "😴 쉬는 주도주", None))
    return [e for e in ev if e[2] is None or e[2] <= time(15, 30)]


def review(day: date, store: ScreenerStore, daily_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    events = collect_events(store, day)
    d = duckdb.connect(daily_path, read_only=True)
    try:
        names = dict(d.execute("SELECT code, name FROM stocks").fetchall())
        pc = dict(d.execute("SELECT code, close FROM daily_ohlcv WHERE date = (SELECT max(date) FROM daily_ohlcv WHERE date < ?)", [day]).fetchall())
        dc = dict(d.execute("SELECT code, close FROM daily_ohlcv WHERE date = ?", [day]).fetchall())
        codes = sorted({e[0] for e in events})
        bars = d.execute(
            f"SELECT code, ts, open, high, low, close FROM minute_ohlcv WHERE exchange = 'AL' AND ts::DATE = ? AND ts::TIME < '15:30' "
            f"AND code IN ({','.join('?' * len(codes))}) ORDER BY code, ts", [day, *codes]).df() if codes else pd.DataFrame()
    finally:
        d.close()
    rows = []
    for code, path, t in events:
        g = bars[bars.code == code] if len(bars) else bars
        if g.empty or code not in pc:
            continue
        if t is None:                                         # 장 시작부터 감시 → 09:00 시가
            fut = g[g.ts.dt.time >= time(9, 0)]
            if fut.empty:
                continue
            entry, at = fut.open.iloc[0], "09:00"
        else:
            cap = g[g.ts.dt.time <= t]
            if cap.empty:
                continue
            entry, at = cap.close.iloc[-1], t.strftime("%H:%M")
            fut = g[g.ts.dt.time > t]
        if fut.empty or not entry:
            continue
        up = fut.index[fut.high >= entry * 1.03]
        dn = fut.index[fut.low <= entry * 0.97]
        verdict = "✅" if len(up) and (not len(dn) or up[0] < dn[0]) else ("❌" if len(dn) else "➖")
        rows.append(dict(종목=names.get(code, code), 코드=code, 경로=path, 포착=at, 포착가=int(entry),
                         포착시_등락=entry / pc[code] - 1, 종가까지=dc.get(code, fut.close.iloc[-1]) / entry - 1,
                         최대상승=fut.high.max() / entry - 1, 최대상승시각=fut.loc[fut.high.idxmax(), "ts"].strftime("%H:%M"),
                         최대하락=fut.low.min() / entry - 1, 판정=verdict, 당일등락=dc.get(code, 0) / pc[code] - 1))
    return pd.DataFrame(rows)


def summarize(day: date, df: pd.DataFrame) -> str:
    if df.empty:
        return f"📋 포착 복기 ({day}) — 포착 기록 또는 1분봉 없음"
    lines = [f"📋 포착 복기 ({day}) — 포착한 분의 종가에 샀다면 (비용 미반영)", "경로 | 종목 | 종가까지 | 최대↑/↓ | +3%먼저/−3%먼저"]
    for path, g in df.groupby("경로"):
        lines.append(f"{path} | {len(g)} | {g.종가까지.mean():+.1%} | {g.최대상승.mean():+.1%}/{g.최대하락.mean():+.1%} | "
                     f"{(g.판정 == '✅').mean():.0%}/{(g.판정 == '❌').mean():.0%}")
    by_stock = df.sort_values("포착").groupby("종목").first().reset_index()
    lines.append(f"종목별 {len(by_stock)}개(가장 이른 포착): ✅ {(by_stock.판정 == '✅').sum()} / ❌ {(by_stock.판정 == '❌').sum()} / "
                 f"➖ {(by_stock.판정 == '➖').sum()}, 종가까지 평균 {by_stock.종가까지.mean():+.1%}")
    best = by_stock.sort_values("종가까지", ascending=False).head(5)
    worst = by_stock.sort_values("종가까지").head(5)
    lines.append("잘 맞음: " + ", ".join(f"{r.종목}({r.포착} {r.종가까지:+.1%})" for r in best.itertuples()))
    lines.append("빗나감: " + ", ".join(f"{r.종목}({r.포착} {r.종가까지:+.1%})" for r in worst.itertuples()))
    lines.append("(포착 = 볼 종목. 7일 검증: 포착 후 즉시·VWAP 눌림·50% 되돌림·🎯 진입 모두 장중 -1~-2%, 다음날까지 보유 -1~-3%)")
    return "\n".join(lines)


def build_capture_review(day: Optional[date] = None, save: bool = True) -> str:
    store = ScreenerStore()
    try:
        if day is None:
            d = duckdb.connect(DEFAULT_DB_PATH, read_only=True)
            try:
                day = d.execute("SELECT max(date) FROM daily_ohlcv").fetchone()[0]
            finally:
                d.close()
        df = review(day, store)
    finally:
        store.close()
    if save and not df.empty:
        os.makedirs(REPORT_DIR, exist_ok=True)
        df.sort_values(["경로", "포착"]).to_csv(os.path.join(REPORT_DIR, f"capture_review_{day:%Y%m%d}.csv"), index=False, encoding="utf-8-sig")
        df.sort_values("포착").groupby("종목").first().reset_index().sort_values("포착").to_csv(
            os.path.join(REPORT_DIR, f"capture_review_{day:%Y%m%d}_by_stock.csv"), index=False, encoding="utf-8-sig")
    return summarize(day, df)


def main() -> None:
    parser = argparse.ArgumentParser(description="오늘 포착 종목 복기표")
    parser.add_argument("--date", help="YYYYMMDD (기본: 마지막 거래일)")
    parser.add_argument("--send", action="store_true", help="텔레그램 전송")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    day = datetime.strptime(args.date, "%Y%m%d").date() if args.date else None
    text = build_capture_review(day)
    print(text)
    if args.send:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message(text)


if __name__ == "__main__":
    main()
