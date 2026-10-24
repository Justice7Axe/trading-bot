"""지수 일봉·1분봉 저장 → data/index.duckdb (2026-10-25 사용자 '20:00 업데이트에 지수 저장 넣어줘').

    python -m kiwoom_trading.ingestion.collectors.index_collector            # 마지막 저장 뒤부터 오늘까지
    python -m kiwoom_trading.ingestion.collectors.index_collector --dry-run  # 받을 것만 보고 저장 안 함

- 코스피(001) · 코스닥(101) · 코스피200(201). 키움 ka20006 업종일봉, ka20005 업종분봉(1분). 값은 지수 × 100 정수로 온다.
- idx_daily(code, date, open, high, low, close, value) / idx_min(code, ts, open, high, low, close), 같은 키는 덮어쓴다.
- 1분봉은 키움이 약 1년치만 주므로 매일 이어 받아야 한다. 마지막 저장 시각보다 오래된 페이지가 나오면 멈춘다
  (PC 가 며칠 꺼져 있었어도 밀린 날을 채운다). 표에 처음이면 1년 전까지.
- 장중 시장 판정(market_regime)은 이 파일을 보지 않고 API 로 직접 조회한다. 이 파일은 분석·검증용.
"""
import argparse
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT

INDEX_DB = os.path.join(PROJECT_ROOT, "data", "index.duckdb")
CODES = {"001": "코스피", "101": "코스닥", "201": "코스피200"}
FIRST_DAILY = date(2021, 11, 1)
MAX_PAGES = 60


def _num(x) -> float:
    return abs(float(str(x).replace(",", "") or 0)) / 100


def _open(path: str) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS idx_daily(code VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, value DOUBLE, PRIMARY KEY(code, date))")
    db.execute("CREATE TABLE IF NOT EXISTS idx_min(code VARCHAR, ts TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, PRIMARY KEY(code, ts))")
    return db


def _pages(client, api_id: str, body: dict, key: str, stop):
    """연속조회로 페이지를 넘기며 rows 를 돌려준다. stop(rows) 가 참이면 그 페이지까지."""
    cont, nxt = "N", ""
    for _ in range(MAX_PAGES):
        payload, cont, nxt = client._post("/api/dostk/chart", api_id, body, cont, nxt)
        rows = payload.get(key) or []
        yield rows
        if not rows or stop(rows) or cont != "Y" or not nxt:
            return


def update_index(client, today: Optional[date] = None, path: str = INDEX_DB, dry_run: bool = False) -> dict[str, tuple[int, int]]:
    """코드별 (일봉 수, 1분봉 수) 저장."""
    today = today or date.today()
    db = _open(path) if not dry_run else None
    out = {}
    try:
        for code, name in CODES.items():
            last_d = db.execute("SELECT max(date) FROM idx_daily WHERE code = ?", [code]).fetchone()[0] if db else None
            last_t = db.execute("SELECT max(ts) FROM idx_min WHERE code = ?", [code]).fetchone()[0] if db else None
            since_d = (last_d - timedelta(days=3)) if last_d else FIRST_DAILY
            since_t = (last_t - timedelta(days=1)) if last_t else datetime.combine(today - timedelta(days=366), datetime.min.time())

            daily = []
            for rows in _pages(client, "ka20006", {"inds_cd": code, "base_dt": f"{today:%Y%m%d}"}, "inds_dt_pole_qry",
                               lambda rs: rs[-1]["dt"] < f"{since_d:%Y%m%d}"):
                daily += [[code, datetime.strptime(r["dt"], "%Y%m%d").date(), _num(r["open_pric"]), _num(r["high_pric"]),
                           _num(r["low_pric"]), _num(r["cur_prc"]), float(str(r.get("trde_prica") or 0).replace(",", "") or 0)]
                          for r in rows if r.get("dt", "") >= f"{since_d:%Y%m%d}"]
            mins = []
            for rows in _pages(client, "ka20005", {"inds_cd": code, "tic_scope": "1", "base_dt": f"{today:%Y%m%d}"}, "inds_min_pole_qry",
                               lambda rs: rs[-1]["cntr_tm"] < f"{since_t:%Y%m%d%H%M%S}"):
                mins += [[code, datetime.strptime(r["cntr_tm"], "%Y%m%d%H%M%S"), _num(r["open_pric"]), _num(r["high_pric"]),
                          _num(r["low_pric"]), _num(r["cur_prc"])]
                         for r in rows if r.get("cntr_tm", "") >= f"{since_t:%Y%m%d%H%M%S}"]
            if db:
                if daily:
                    db.executemany("INSERT OR REPLACE INTO idx_daily VALUES (?, ?, ?, ?, ?, ?, ?)", daily)
                if mins:
                    db.executemany("INSERT OR REPLACE INTO idx_min VALUES (?, ?, ?, ?, ?, ?)", mins)
            out[code] = (len(daily), len(mins))
            logging.info("지수 %s(%s): 일봉 %s개(%s~), 1분봉 %s개(%s~)%s", name, code, len(daily), since_d, len(mins),
                         f"{since_t:%Y-%m-%d %H:%M}", " [저장 안 함]" if dry_run else "")
    finally:
        if db:
            db.close()
    return out


def main(argv: Optional[list[str]] = None) -> int:
    from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    update_index(build_client(), dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
