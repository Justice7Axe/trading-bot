"""모의투자 매매 타점 차트 — 그날 매매마다 1분봉 위에 신호·매수·매도 지점과 손절선을 그린 HTML.

1분봉은 20:00 일일 업데이트가 저장한 감시 종목 1분봉(daily_ohlcv.duckdb minute_ohlcv)을 쓴다.
통합(AL) 시세가 있으면 그것을, 없으면 KRX 를 쓴다. 차트는 lightweight-charts(jsdelivr) 로 그린다.

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.paper_chart [YYYYMMDD]   # 기본 오늘 → data/reports/paper_chart_YYYYMMDD.html
"""
import argparse
import calendar
import json
import os
from datetime import date, datetime, time

import duckdb

from kiwoom_trading.common.config import KST
from kiwoom_trading.screener.early_watch import usual_value
from kiwoom_trading.screener.history import load_history
from kiwoom_trading.screener.paper_trader import COST, load_trades, net_pnl
from kiwoom_trading.screener.store import PROJECT_ROOT, ScreenerStore

DAILY_DB = os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")
TEMPLATE = os.path.join(os.path.dirname(__file__), "paper_chart_template.html")


def _epoch(ts: datetime) -> int:
    """KST 시각을 그대로 UTC 초로 → 차트 축에 KST 시각이 그대로 보인다."""
    return calendar.timegm(ts.timetuple())


def _value_at(store: ScreenerStore, con, code: str, buy_ts: datetime, virtual: bool, avg_value_20) -> dict:
    """매수 시점 거래대금 지표.

    - 순위·누적 대금: KRX 누적 거래대금 순위 스냅샷(value_krx, 200위까지) 중 매수 직전 것. 200위 밖이면 KRX 1분봉으로 누적 대금만 계산.
    - 가속도: 매수 직전 완성된 1분봉 5개 대금(가격×거래량) — 실주문은 KRX, 가상(애프터장)은 통합(AL) 1분봉.
      · 평소 대비: 20일 평균 대금 × 같은 시간대 비중 (대금 가속 조건과 같은 기준, 정규장만)
      · 직전 5분 대비: 그 앞 5분 대금과 비교
    """
    minute = buy_ts.replace(second=0, microsecond=0)
    snap = store.conn.execute(
        "SELECT rank, trade_value, ts FROM rank_snapshots WHERE source = 'value_krx' AND code = ? AND date = ? "
        "AND ts <= ? AND ts >= ? - INTERVAL 3 MINUTE ORDER BY ts DESC LIMIT 1", [code, buy_ts.date(), buy_ts, buy_ts]).fetchone()
    krx_cum = con.execute("SELECT sum(close * volume) FROM minute_ohlcv WHERE code = ? AND exchange = 'KRX' AND ts::date = ? AND ts < ?",
                          [code, buy_ts.date(), minute]).fetchone()[0]
    ex = "AL" if virtual else "KRX"
    bars = con.execute("SELECT close * volume FROM minute_ohlcv WHERE code = ? AND exchange = ? AND ts::date = ? AND ts < ? "
                       "ORDER BY ts DESC LIMIT 10", [code, ex, buy_ts.date(), minute]).fetchall()
    vals = [float(b[0] or 0) for b in bars]
    v5, prev5 = sum(vals[:5]), sum(vals[5:10])
    usual = usual_value(avg_value_20, minute.time(), 5) if avg_value_20 and time(9, 5) <= minute.time() <= time(15, 30) else 0
    al_cum = None
    if virtual:
        al_cum = con.execute("SELECT sum(close * volume) FROM minute_ohlcv WHERE code = ? AND exchange = 'AL' AND ts::date = ? AND ts < ?",
                             [code, buy_ts.date(), minute]).fetchone()[0]
    return {
        "rank": snap[0] if snap else None,
        "cum": float(snap[1]) if snap else (float(krx_cum) if krx_cum else None),
        "al_cum": float(al_cum) if al_cum else None,
        "v5": v5 if vals else None, "basis": ex,
        "x_usual": v5 / usual if usual else None,
        "x_prev": v5 / prev5 if prev5 else None,
    }


def build_data(day: date) -> dict:
    store = ScreenerStore()
    con = duckdb.connect(DAILY_DB, read_only=True)
    candles: dict[str, list] = {}
    flows: dict[str, dict] = {}
    try:
        trades = [t for t in load_trades(store, "date = ?", [day]) if t.buy_price and t.buy_ts]
        asset = store.conn.execute("SELECT asset_start, asset_end FROM paper_days WHERE date = ?", [day]).fetchone()
        hist = load_history(con, day)
        for t in trades:
            h = hist.get(t.code)
            flows[t.id] = _value_at(store, con, t.code, t.buy_ts, bool(t.virtual), h.avg_value_20 if h else None)
        for code in sorted({t.code for t in trades}):
            for ex in ("AL", "KRX"):
                rows = con.execute("SELECT ts, open, high, low, close, volume FROM minute_ohlcv "
                                   "WHERE code = ? AND exchange = ? AND ts::date = ? ORDER BY ts", [code, ex, day]).fetchall()
                if rows:
                    candles[code] = [[_epoch(r[0]), *r[1:]] for r in rows]
                    break
    finally:
        con.close()
        store.close()
    out = []
    for t in trades:
        pnl = net_pnl(t)
        out.append({
            "code": t.code, "name": t.name, "kind": t.kind, "mode": t.mode, "virtual": bool(t.virtual),
            "source": t.source, "qty": t.qty,
            "signal": [_epoch(t.signal_ts), t.signal_price] if t.signal_ts and t.signal_price else None,
            "buy": [_epoch(t.buy_ts), t.buy_price],
            "sell": [_epoch(t.sell_ts), t.sell_price] if t.sell_ts and t.sell_price else None,
            "stop": t.stop, "reason": t.sell_reason or "", "status": t.status,
            "ret": (t.sell_price / t.buy_price - 1 - COST) if t.sell_price else None,
            "pnl": pnl, "flow": flows.get(t.id),
        })
    return {"date": day.isoformat(), "asset": list(asset) if asset else None, "trades": out, "candles": candles}


def main() -> None:
    parser = argparse.ArgumentParser(description="모의투자 매매 타점 차트 HTML")
    parser.add_argument("day", nargs="?", default="", help="YYYYMMDD (기본 오늘)")
    parser.add_argument("--out", default="", help="저장 경로 (기본 data/reports/paper_chart_YYYYMMDD.html)")
    args = parser.parse_args()
    day = datetime.strptime(args.day, "%Y%m%d").date() if args.day else datetime.now(KST).date()
    data = build_data(day)
    with open(TEMPLATE, encoding="utf-8") as f:
        page = f.read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    out = args.out or os.path.join(PROJECT_ROOT, "data", "reports", f"paper_chart_{day:%Y%m%d}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"{out} — 매매 {len(data['trades'])}건, 1분봉 {len(data['candles'])}종목")


if __name__ == "__main__":
    main()
