"""조기 주도주(09:15 전 관문) × 장중 외국인·기관 잠정치 — 매일 누적 검증.

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.gate_flow            # 저장된 모든 날 평가 + 누적 요약
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.gate_flow --date 20261014

관문 통과: 스캐너가 매분 저장한 KRX 거래대금 순위 스냅샷(rank_snapshots value_krx)에서
           09:15 전에 누적 대금 500억 & +3% 를 처음 넘은 시각 (ETF 등 stocks 에 없는 종목 제외)
수급: investor_intraday (장중 잠정치, 외국인 첫 갱신 09:20 무렵 / 기관 09:50 무렵, 장 시작부터 누적)
      - 외국인(첫 값), 기관(첫 값), 외국인+기관(10:00 시점 최신 값)
정답: 그날 일봉 거래대금 30위 이내 & +5%↑ (주도주)
과거 장중 잠정치는 API 로 받을 수 없어 2026-10-14 부터 쌓인 날만 평가된다. 표본이 20일은 넘어야 판단 가능.
참고(장 마감 확정치, 상한): 09:20 관문 + 당일 외국인+기관 순매수 → 정밀도 38% → 51% (25일)
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, time
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.screener.store import ScreenerStore


GATE_VALUE = 50_000_000_000
GATE_CHANGE = 0.03
GATE_DEADLINE = time(9, 15)
FLOW_AT = time(10, 0)
MIN_DAYS = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS gate_flow_eval (
    date         DATE,
    code         VARCHAR,
    name         VARCHAR,
    gate_ts      TIMESTAMP,
    gate_price   BIGINT,
    foreign_1st  BIGINT,     -- 외국인 첫 잠정치 (원)
    foreign_ts   TIMESTAMP,
    inst_1st     BIGINT,     -- 기관 첫 잠정치
    inst_ts      TIMESTAMP,
    fi_1000      BIGINT,     -- 10:00 시점 최신 외국인 + 기관
    leader       BOOLEAN,    -- 대금 30위 & +5%
    value_rank   INTEGER,
    day_ret      DOUBLE,
    ret_after    DOUBLE,     -- 관문 통과 가격 → 종가
    PRIMARY KEY (date, code)
);
"""


def evaluate(store: ScreenerStore, day: date, daily_path: str = DEFAULT_DB_PATH) -> int:
    conn = store.conn
    conn.execute(SCHEMA)
    d = duckdb.connect(daily_path, read_only=True)
    try:
        listed = {r[0] for r in d.execute("SELECT code FROM stocks").fetchall()}
        daily = {c: (vr, ret, close) for c, vr, ret, close in d.execute("""
            WITH r AS (SELECT code, date, close, value, lag(close) OVER (PARTITION BY code ORDER BY date) pc FROM daily_ohlcv)
            SELECT code, rank() OVER (ORDER BY value DESC), close / pc - 1, close FROM r WHERE date = ?""", [day]).fetchall()}
    finally:
        d.close()
    if not daily:
        logging.info("%s 일봉 없음 → 평가 보류", day)
        return 0
    gates = conn.execute("""
        SELECT code, any_value(name), min(ts), arg_min(price, ts) FROM rank_snapshots
        WHERE date = ? AND source = 'value_krx' AND trade_value >= ? AND change_rate >= ? AND date_trunc('minute', ts)::TIME <= ?
        GROUP BY code""", [day, GATE_VALUE, GATE_CHANGE, GATE_DEADLINE]).fetchall()

    def first(investor: str, code: str):
        return conn.execute("""SELECT net_amount, ts FROM investor_intraday WHERE date = ? AND investor = ?
                               AND ts = (SELECT min(ts) FROM investor_intraday WHERE date = ? AND investor = ?) AND code = ?""",
                            [day, investor, day, investor, code]).fetchone() or (0, None)

    def latest_sum(code: str) -> Optional[int]:
        total, seen = 0, False
        for inv in ("foreign", "institution"):
            row = conn.execute("""SELECT net_amount FROM investor_intraday WHERE date = ? AND investor = ? AND code = ?
                                  AND ts = (SELECT max(ts) FROM investor_intraday WHERE date = ? AND investor = ? AND ts::TIME <= ?)""",
                               [day, inv, code, day, inv, FLOW_AT]).fetchone()
            has_snapshot = conn.execute("SELECT count(*) FROM investor_intraday WHERE date = ? AND investor = ? AND ts::TIME <= ?",
                                        [day, inv, FLOW_AT]).fetchone()[0]
            if has_snapshot:
                seen = True
                total += row[0] if row else 0
        return total if seen else None

    conn.execute("DELETE FROM gate_flow_eval WHERE date = ?", [day])
    n = 0
    for code, name, ts, price in gates:
        if code not in listed or code not in daily:
            continue
        vr, ret, close = daily[code]
        f_amt, f_ts = first("foreign", code)
        i_amt, i_ts = first("institution", code)
        conn.execute("INSERT INTO gate_flow_eval VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            day, code, name, ts, price, f_amt, f_ts, i_amt, i_ts, latest_sum(code),
            bool(vr <= 30 and ret is not None and ret >= 0.05), vr, ret, close / price - 1 if price else None])
        n += 1
    logging.info("관문×수급 평가 %s: %s종목", day, n)
    return n


def summary(store: ScreenerStore) -> str:
    conn = store.conn
    conn.execute(SCHEMA)
    days = conn.execute("SELECT count(DISTINCT date) FROM gate_flow_eval").fetchone()[0]
    if not days:
        return "🏁 관문×수급 누적 검증: 아직 평가된 날 없음"

    def row(where: str, label: str) -> str:
        n, hits, avg_ret = conn.execute(f"SELECT count(*), sum(leader::INT), avg(ret_after) FROM gate_flow_eval WHERE {where}").fetchone()
        if not n:
            return f"  {label}: 0종목"
        return f"  {label}: {n}종목, 주도주 {hits or 0} → 정밀도 {(hits or 0) / n:.0%}, 통과가→종가 {avg_ret:+.1%}"

    lines = [f"🏁 관문(09:15 전 500억&+3%) × 장중 수급 누적 검증 — {days}일" + (" (표본 부족, 20일↑ 필요)" if days < MIN_DAYS else "")]
    lines.append(row("true", "관문만"))
    lines.append(row("foreign_1st > 0", "+ 외국인 첫 잠정치 순매수(09:20 무렵)"))
    lines.append(row("inst_1st > 0", "+ 기관 첫 잠정치 순매수(09:50 무렵)"))
    lines.append(row("fi_1000 > 0", "+ 10:00 외국인+기관 순매수"))
    lines.append(row("fi_1000 <= 0", "  (10:00 외국인+기관 순매도/없음)"))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="조기 주도주 관문 × 장중 수급 누적 검증")
    parser.add_argument("--date", help="YYYYMMDD (없으면 저장된 모든 날)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = ScreenerStore()
    try:
        if args.date:
            days = [datetime.strptime(args.date, "%Y%m%d").date()]
        else:
            days = [r[0] for r in store.conn.execute("SELECT DISTINCT date FROM investor_intraday ORDER BY 1").fetchall()]
        for day in days:
            evaluate(store, day)
        print(summary(store))
        for r in store.conn.execute("""SELECT date, name, gate_ts::TIME, foreign_1st/1e8, inst_1st/1e8, fi_1000/1e8, leader, value_rank, day_ret
                                       FROM gate_flow_eval ORDER BY date, gate_ts""").fetchall():
            print(f"  {r[0]} {r[1]} {r[2]:%H:%M} 외국인 {r[3]:+,.0f}억 기관 {r[4]:+,.0f}억 10시 합 {(r[5] or 0):+,.0f}억 → "
                  f"{'주도주' if r[6] else '아님'} (대금 {r[7]}위, {r[8]:+.1%})")
    finally:
        store.close()


if __name__ == "__main__":
    main()
