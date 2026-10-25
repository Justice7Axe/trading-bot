"""강창권 백테스트용 1분봉 추가 수집 (키움 ka10080, 통합 AL) → data/kang_minute.duckdb.

minute_history.duckdb 는 날짜별 '그날·전날 대금 상위 200' 만 있어, 갭 상승·급등 종목 중 그날 대금이
작았던 종목(대개 실패한 종목)이 빠진다. 그대로 쓰면 결과가 부푼다 → 빠진 (종목, 날짜)만 따로 받는다.
그날과 함께 전날·전전날 봉도 받는다 (최대 2페이지) — 1분봉 240·480선 계산용.
기존 DB 는 건드리지 않는다 (다른 검증 결과가 바뀌지 않게).

대상 (우선순위 순, 각 그룹 안은 오래된 날부터 — 키움은 약 1년치만 줘서 오래된 날부터 사라짐):
  1. 시초가 갭 ≥ +10%  (8장 시초가 매매)
  2. 전날 +15% 이상 오른 종목의 다음 날  (15장 CK480 '전일 15%↑', 8장 상한가 다음 날)
  3. 장중 고가 ≥ +15% 인 날  (15장 CK480 '당일 15%↑')

    python .claude/skills/kang/scripts/kang_fetch.py [--groups 1,2,3] [--dry-run]
"""
import argparse
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime

import duckdb

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from kiwoom_trading.common.daily_store import DailyStore  # noqa: E402
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client  # noqa: E402
from kiwoom_trading.ingestion.collectors.minute_collector import EXCHANGE_SUFFIX, _to_int  # noqa: E402

OUT_DB = os.path.join(ROOT, "data", "kang_minute.duckdb")
SINCE = "2025-10-16"
GROUPS = {
    1: "open / pc - 1 >= 0.10",
    2: "pc / ppc - 1 >= 0.15",
    3: "high / pc - 1 >= 0.15",
}


def fetch_days(client, code: str, day, keep: set) -> list[dict]:
    """base_dt=day 부터 과거로 최대 2페이지(900봉씩). keep(그날·전날·전전날) 날짜의 봉만 남긴다.
    1분봉 240·480선을 이어서 계산하려면 전날·전전날 정규장 봉이 필요하다 (KRX 전용 종목은 1페이지에 약 2.4일치)."""
    body = {"stk_cd": code + EXCHANGE_SUFFIX["AL"], "tic_scope": "1", "upd_stkpc_tp": "1", "base_dt": day.strftime("%Y%m%d")}
    bars, cont, key = [], "N", ""
    oldest = min(keep).strftime("%Y%m%d")
    for _ in range(2):
        payload, cont, key = client._post("/api/dostk/chart", "ka10080", body, cont, key)
        items = payload.get("stk_min_pole_chart_qry") or []
        for it in items:
            tm = str(it.get("cntr_tm") or "")
            ts = datetime.strptime(tm, "%Y%m%d%H%M%S") if tm else None
            if ts and ts.date() in keep:
                bars.append({"code": code, "exchange": "AL", "ts": ts, "open": _to_int(it.get("open_pric")),
                             "high": _to_int(it.get("high_pric")), "low": _to_int(it.get("low_pric")),
                             "close": _to_int(it.get("cur_prc")), "volume": _to_int(it.get("trde_qty")) or 0})
        if not items or str(items[-1].get("cntr_tm", "")) < oldest or cont != "Y" or not key:
            break
    return bars


def _copy(name: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), "kangf_" + name)
    shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


def targets(groups: list[int]) -> list[tuple]:
    d = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
    d.execute(f"ATTACH '{_copy('minute_history.duckdb')}' AS m (READ_ONLY)")
    out, seen = [], set()
    for g in groups:
        rows = d.execute(f"""
            WITH x AS (SELECT code, date, open, high, close, lag(close) OVER w pc, lag(close, 2) OVER w ppc
                       FROM daily_ohlcv WINDOW w AS (PARTITION BY code ORDER BY date))
            SELECT x.date, x.code FROM x LEFT JOIN m.minute_backfill_done b ON b.code = x.code AND b.date = x.date
            WHERE x.date >= ? AND b.code IS NULL AND pc > 0 AND ppc > 0 AND {GROUPS[g]}
            ORDER BY x.date, x.code""", [SINCE]).fetchall()
        for r in rows:
            if r not in seen:
                seen.add(r); out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", default="1,2,3")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    todo = targets([int(x) for x in a.groups.split(",")])
    store = DailyStore(OUT_DB)
    store.conn.execute("CREATE TABLE IF NOT EXISTS minute_backfill_done (code VARCHAR, date DATE, bars INTEGER, "
                       "done_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY (code, date))")
    done = {(r[1], r[0]) for r in store.conn.execute("SELECT code, date FROM minute_backfill_done").fetchall()}
    rest = [(d, c) for d, c in todo if (d, c) not in done]
    logging.info("대상 %s건, 완료 %s, 남음 %s", len(todo), len(done), len(rest))
    if a.dry_run:
        return
    cal = [r[0] for r in duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True).execute(
        "SELECT DISTINCT date FROM daily_ohlcv WHERE code = '005930' ORDER BY 1").fetchall()]
    client = build_client()
    t0 = time.monotonic()
    try:
        for i, (day, code) in enumerate(rest, 1):
            try:
                k = cal.index(day)
                bars = fetch_days(client, code, day, set(cal[max(0, k - 2):k + 1]))
            except Exception as exc:  # 토큰 만료·네트워크 — 다음 실행에서 다시 받음
                logging.warning("실패 %s %s: %s", day, code, exc)
                continue
            store.upsert_minutes(bars)
            store.conn.execute("INSERT OR REPLACE INTO minute_backfill_done (code, date, bars) VALUES (?, ?, ?)",
                               [code, day, sum(1 for b in bars if b["ts"].date() == day)])
            if i % 200 == 0 or i == len(rest):
                rate = i / max(1e-9, time.monotonic() - t0)
                logging.info("[%s/%s] %s %s 봉 %s개 (%.2f건/초, 남은 %.1f시간)", i, len(rest), day, code, len(bars), rate, (len(rest) - i) / rate / 3600)
    finally:
        store.close()


if __name__ == "__main__":
    main()
