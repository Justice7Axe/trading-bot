"""조기 발굴 검증 (⑤).

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.validate_early --daily
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.validate_early --minute            # 약 40분 (1분봉 1,600건 조회)
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.validate_early --minute --sample 200

--daily : '쉬어 가는 주도주'(D일) 의 D+1 일봉 성과 vs 비교군 (대금 50위 이내 전체 / +3%↑ / 10일 +20%↑),
          조건 민감도(이웃 값), 앞/뒤 1년 분할
--minute: 쉬는 날 이후 D+1~D+5 (이탈 해제 규칙 적용) 1분봉에 매수 신호(지지 반등/돌파 후 눌림)를 돌려 신호당 순수익 비교
          (쉬는 주도주 전부 vs '+3%↑'·'전체' 무작위 표본). 진입 = 신호 봉 종가, 손절 = 신호 손절가(봉 저가로 판정),
          청산 = 15:20 종가 또는 익절 +3% / +5% 변형. 비용 0.25%.
          1분봉은 minute_ohlcv(통합 AL, 없으면 KRX) 에 저장해 재실행 시 재사용. 키움 1분봉은 약 1년치만 제공.
"""
import argparse
import logging
import os
import random
import sys
from dataclasses import asdict
from datetime import date, time

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, DailyStore
from kiwoom_trading.screener.early_watch import REST_HOLD_DAYS, REST_MAX_DROP, RestLeaderConfig
from kiwoom_trading.screener.intraday_signals import Signal, detect_signals


COST = 0.0025
EXIT_TIME = time(15, 20)

FEATURES_SQL = """
CREATE OR REPLACE TEMP TABLE f AS
WITH r AS (
    SELECT o.code, o.date, o.high, o.close, o.value, rank() OVER (PARTITION BY o.date ORDER BY o.value DESC) AS vrank
    FROM daily_ohlcv o JOIN stocks s USING (code) WHERE NOT s.delisted
), d AS (
    SELECT o.code, o.date, o.close, o.value, o.vrank,
           lag(o.close) OVER w AS pc, lag(o.close, 10) OVER w AS c10,
           max(o.value) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS maxv5,
           max(o.high) OVER (w ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS hi10,
           lead(o.date) OVER w AS n_date, lead(o.high) OVER w AS n_high, lead(o.close) OVER w AS n_close,
           max(o.high) OVER (w ROWS BETWEEN 1 FOLLOWING AND 3 FOLLOWING) AS n3_high
    FROM r o
    WINDOW w AS (PARTITION BY o.code ORDER BY o.date)
)
SELECT *, close / pc - 1 AS chg, close / c10 - 1 AS ret10, value / maxv5 AS vratio, close / hi10 AS near,
       n_high / close - 1 AS up, n_close / close - 1 AS nret, n3_high / close - 1 AS up3
FROM d WHERE pc > 0 AND c10 > 0 AND n_close IS NOT NULL
"""


def pool_where(cfg: RestLeaderConfig) -> str:
    return (f"ret10 >= {cfg.min_run_10d} AND maxv5 >= {cfg.min_peak_value_5d} AND abs(chg) <= {cfg.max_abs_change}"
            f" AND vratio >= {cfg.min_value_vs_peak} AND near >= {cfg.min_close_vs_high10} AND vrank <= {cfg.max_value_rank}")


def daily_report(conn: duckdb.DuckDBPyConnection) -> None:
    def row(where: str, label: str) -> None:
        n, days, up, p5, p10, ret, win, p3 = conn.execute(f"""
            SELECT count(*), count(DISTINCT date), avg(up), avg((up >= 0.05)::INT), avg((up >= 0.10)::INT),
                   avg(nret), avg((nret > 0)::INT), avg((up3 >= 0.10)::INT) FROM f WHERE {where}""").fetchone()
        if not n:
            print(f"{label:40s} 해당 없음")
            return
        print(f"{label:40s} {n:6,d}건 하루 {n / days:4.1f} | 다음날 고가 {up:+.2%} 고가+5% {p5:4.0%} +10% {p10:4.0%}"
              f" | 종가 {ret:+.2%} 승률 {win:4.0%} | 3일 내 +10% {p3:4.0%}")

    base = RestLeaderConfig()
    print("== 비교군 ==")
    row("vrank <= 50", "대금 50위 이내 전체")
    row("vrank <= 50 AND chg >= 0.03", "대금 50위 & +3%↑")
    row("vrank <= 50 AND ret10 >= 0.2", "대금 50위 & 10일 +20%↑")
    print("== 쉬어 가는 주도주 (기본값) ==")
    row(pool_where(base), "기본값")
    print("== 민감도 ==")
    for key, values in {
        "min_run_10d": [0.15, 0.3], "min_peak_value_5d": [50e9, 200e9], "max_abs_change": [0.02, 0.05],
        "min_value_vs_peak": [0.3, 0.7], "min_close_vs_high10": [0.85, 0.95], "max_value_rank": [30, 100],
    }.items():
        for v in values:
            cfg = RestLeaderConfig(**{**asdict(base), key: v})
            row(pool_where(cfg), f"{key}={v:g}")
    print("== 앞/뒤 분할 ==")
    mid = conn.execute("SELECT min(date) + CAST((max(date) - min(date)) / 2 AS INTEGER) FROM f").fetchone()[0]
    row(pool_where(base) + f" AND date < DATE '{mid}'", f"{mid} 이전")
    row(pool_where(base) + f" AND date >= DATE '{mid}'", f"{mid} 이후")


def simulate(bars: list[dict], s: Signal, take_profit: float | None) -> float:
    idx = next(i for i, b in enumerate(bars) if b["ts"] == s.ts)
    for b in bars[idx + 1:]:
        if b["low"] <= s.stop:
            return s.stop / s.price - 1 - COST
        if take_profit and b["high"] >= s.price * (1 + take_profit):
            return take_profit - COST
        if b["ts"].time() >= EXIT_TIME:
            return b["close"] / s.price - 1 - COST
    return bars[-1]["close"] / s.price - 1 - COST


def load_bars(store: DailyStore, client, code: str, day: date) -> list[dict]:
    from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

    for exchange in ("AL", "KRX"):
        rows = store.conn.execute(
            "SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code = ? AND exchange = ? AND ts::DATE = ? ORDER BY ts",
            [code, exchange, day],
        ).fetchall()
        if not rows and client is not None:
            try:
                fetched = fetch_minute_bars(client, code, day, exchange)
            except Exception as exc:
                logging.warning("1분봉 조회 실패 %s %s %s: %s", code, day, exchange, exc)
                fetched = []
            store.upsert_minutes(fetched)
            rows = [(b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in fetched]
        if rows:
            return [dict(ts=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
    return []


def minute_report(conn: duckdb.DuckDBPyConnection, sample: int, since: date) -> None:
    from kiwoom_trading.ingestion.collectors.daily_backfill import build_client

    random.seed(7)
    # 쉬는 주도주: 쉬는 날 이후 1~REST_HOLD_DAYS 거래일 (라이브와 같은 이탈 해제 규칙). 같은 종목·일은 1번만
    conn.execute("CREATE OR REPLACE TEMP TABLE dd AS SELECT code, date, close, row_number() OVER (PARTITION BY code ORDER BY date) rn FROM daily_ohlcv")
    rest_days = conn.execute(f"""
        WITH e AS (SELECT f.code, f.close c0, dd.rn FROM f JOIN dd USING (code, date) WHERE {pool_where(RestLeaderConfig())})
        SELECT DISTINCT e.code, t.date FROM e
        JOIN dd t ON t.code = e.code AND t.rn BETWEEN e.rn + 1 AND e.rn + ?
        JOIN dd p ON p.code = e.code AND p.rn = t.rn - 1
        WHERE p.close >= e.c0 * (1 - ?) AND t.date >= ? ORDER BY t.date""", [REST_HOLD_DAYS, REST_MAX_DROP, since]).fetchall()
    groups = {
        f"쉬는 주도주 D+1~{REST_HOLD_DAYS}": rest_days,
        "쉬는 주도주 D+1": conn.execute(f"SELECT code, n_date FROM f WHERE {pool_where(RestLeaderConfig())} AND n_date >= ?", [since]).fetchall(),
        "+3%↑ 표본": conn.execute("SELECT code, n_date FROM f WHERE vrank <= 50 AND chg >= 0.03 AND n_date >= ?", [since]).fetchall(),
        "전체 표본": conn.execute("SELECT code, n_date FROM f WHERE vrank <= 50 AND n_date >= ?", [since]).fetchall(),
    }
    for g in ("+3%↑ 표본", "전체 표본"):
        groups[g] = random.sample(groups[g], min(sample, len(groups[g])))
    conn.close()

    client = build_client()
    store = DailyStore()
    try:
        for g, items in groups.items():
            results: dict[str, list[tuple[float, float, float]]] = {}
            for k, (code, day) in enumerate(items, 1):
                bars = load_bars(store, client, code, day)
                for s in detect_signals(bars):
                    if s.ts.time() < EXIT_TIME:
                        results.setdefault(s.kind, []).append(tuple(simulate(bars, s, tp) for tp in (None, 0.03, 0.05)))
                if k % 100 == 0:
                    logging.info("%s %s/%s", g, k, len(items))
            print(f"== {g}: {len(items)}종목·일 ==")
            for kind, rs in sorted(results.items()) + [("전체", [r for v in results.values() for r in v])]:
                if not rs:
                    continue
                cells = []
                for j, label in enumerate(("15:20 청산", "익절 +3%", "익절 +5%")):
                    avg = sum(r[j] for r in rs) / len(rs)
                    win = sum(r[j] > 0 for r in rs) / len(rs)
                    cells.append(f"{label} {avg:+.2%} 승률 {win:.0%}")
                print(f"  {kind:8s} 신호 {len(rs):4d}건 | " + " | ".join(cells))
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="조기 발굴(쉬어 가는 주도주 + 1분봉 매수 신호) 검증")
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--minute", action="store_true")
    parser.add_argument("--sample", type=int, default=500, help="비교군 무작위 표본 수 (기본 500)")
    parser.add_argument("--since", default="2025-10-20", help="1분봉 검증 시작일 (키움 1분봉 약 1년치)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = duckdb.connect(DEFAULT_DB_PATH, read_only=True)
    conn.execute(FEATURES_SQL)
    if args.daily or not args.minute:
        daily_report(conn)
    if args.minute:
        minute_report(conn, args.sample, date.fromisoformat(args.since))
    else:
        conn.close()


if __name__ == "__main__":
    main()
