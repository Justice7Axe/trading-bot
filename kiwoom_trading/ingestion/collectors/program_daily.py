"""종목별 일별 프로그램 매매 (키움 ka90013) 과거 백필 → data/program_daily.duckdb
(2026-11-01 사용자 '과거 수급 데이터는 백필 못하나?' → '진행해줘'). 장중 시간대별은 과거 조회가 안 되지만 일별은 된다.

대상: 2024-10-11 이후 하루 대금 500위(주식, 우선주 제외) 안에 20일 이상 든 종목. 한 쪽 20거래일, 연속 조회로 SINCE 까지.
금액 단위: 백만 원 (응답 그대로, '--61437' 이중 부호 = 음수).
    python -m kiwoom_trading.ingestion.collectors.program_daily            # 백필 (받은 종목 건너뜀)
    python -m kiwoom_trading.ingestion.collectors.program_daily --codes 005930,000660
"""
import argparse
import logging
import os
import sys
import time
from datetime import date

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.ingestion.collectors.program_tick import _num

DB = os.path.join(PROJECT_ROOT, "data", "program_daily.duckdb")
DAILY_DB = os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")
SINCE = date(2024, 10, 11)


def targets(top: int = 500, min_days: int = 20) -> list[str]:
    c = duckdb.connect(DAILY_DB, read_only=True)
    try:
        return [x for (x,) in c.execute("""SELECT code FROM (SELECT code, row_number() OVER (PARTITION BY date ORDER BY value DESC) rk
                    FROM daily_ohlcv JOIN stocks USING(code) WHERE value > 0 AND right(code, 1) NOT IN ('5','7','9','K'))
                    WHERE rk <= ? GROUP BY code HAVING count(*) >= ? ORDER BY count(*) DESC""", [top, min_days]).fetchall()]
    finally:
        c.close()


def fetch(client, code: str, end: str) -> list[tuple]:
    out, cont, key = [], "N", ""
    for _ in range(120):
        p, cont, key = client._post("/api/dostk/mrkcond", "ka90013", {"amt_qty_tp": "1", "stk_cd": code, "date": end}, cont, key)
        rows = p.get("stk_daly_prm_trde_trnsn") or []
        stop = False
        for r in rows:
            dt = str(r.get("dt") or "")
            if len(dt) != 8: continue
            d = date(int(dt[:4]), int(dt[4:6]), int(dt[6:]))
            if d < SINCE: stop = True; continue
            out.append((code, d, abs(_num(r.get("cur_prc"))), _num(r.get("trde_qty")), _num(r.get("prm_buy_amt")),
                        _num(r.get("prm_sell_amt")), _num(r.get("prm_netprps_amt")), _num(r.get("prm_netprps_qty"))))
        if stop or cont != "Y" or not key or not rows:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default=None)
    ap.add_argument("--end", default=None, help="YYYYMMDD (기본: daily_ohlcv 마지막 날)")
    ap.add_argument("--since", default=None, help="YYYYMMDD (기본 20241011) — 더 오래된 기간 백필 (2026-11-01)")
    a = ap.parse_args()
    global SINCE
    if a.since:
        SINCE = date(int(a.since[:4]), int(a.since[4:6]), int(a.since[6:]))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(PROJECT_ROOT, "data", "logs", "program_daily.log"), encoding="utf-8")])
    if a.end:
        end = a.end
    else:
        c = duckdb.connect(DAILY_DB, read_only=True)
        end = c.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930'").fetchone()[0].strftime("%Y%m%d")
        c.close()
    codes = a.codes.split(",") if a.codes else targets()
    conn = duckdb.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS program_daily (code VARCHAR, date DATE, price BIGINT, volume BIGINT,
                    buy_amt BIGINT, sell_amt BIGINT, net_amt BIGINT, net_qty BIGINT, PRIMARY KEY (code, date))""")
    conn.execute("CREATE TABLE IF NOT EXISTS program_daily_done (code VARCHAR PRIMARY KEY, until VARCHAR, rows INTEGER, done_at TIMESTAMP DEFAULT current_timestamp)")
    done = {c for (c,) in conn.execute("SELECT code FROM program_daily_done WHERE until = ?", [end]).fetchall()}
    todo = [c for c in codes if c not in done]
    logging.info("일별 프로그램 백필 ~%s: 대상 %s, 이미 %s, 남음 %s", end, len(codes), len(done), len(todo))
    client = build_client(); t0 = time.time()
    for i, code in enumerate(todo, 1):
        try:
            rows = fetch(client, code, end)
        except Exception:
            logging.exception("ka90013 실패 %s", code); continue
        if rows:
            conn.executemany("INSERT OR REPLACE INTO program_daily VALUES (?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO program_daily_done (code, until, rows) VALUES (?,?,?)", [code, end, len(rows)])
        if i % 100 == 0:
            logging.info("  %s/%s (%.0f분)", i, len(todo), (time.time() - t0) / 60)
    logging.info("완료 %s종목, %.0f분", len(todo), (time.time() - t0) / 60)
    conn.close()


if __name__ == "__main__":
    main()
