"""종목별 시간대 프로그램 매매 (키움 ka90008) — 하루치 체결 단위 이력을 매일 밤 저장 → data/program_tick.duckdb
(2026-11-01 사용자 '시장 흐름과 상관없이 대금·수급이 몰리는 것을 일찍 확인해 상승 종목을 조기 발견하는 기법').

+ 체결강도 시간별(ka10046, 날짜 칸 없음 = 마지막 거래일, 약 1분 간격) → strength_tick (2026-11-01 추가).
ka90008 은 date 를 넣어도 **마지막 거래일** 하루치만 준다 (19:59 → 08:30 거꾸로, 프로그램 체결이 바뀔 때마다 한 줄, 지니언스 10-30 1,973줄).
장중 10분 스냅샷(program_intraday, 전 종목)보다 훨씬 촘촘해서, 장 마감 뒤 하루 한 번 받아 두면 분 단위 수급 이력이 쌓인다.
대상: 그날 대금 상위 TOP(주식, 우선주 제외) ∪ 전날 대금 상위 PREV — 그날 오른 종목과 '전날 정보로 고를 수 있는 종목' 둘 다.
금액 단위: 백만 원 (응답 그대로, '--268' 같은 이중 부호는 음수로).

    python -m kiwoom_trading.ingestion.collectors.program_tick              # 마지막 거래일
    python -m kiwoom_trading.ingestion.collectors.program_tick --top 5 --prev 0   # 시험
예약: 평일 20:20 (EllieTrading_ProgramTick). 받은 (날짜, 종목)은 program_tick_done 에 기록해 다시 돌려도 건너뜀.
"""
import argparse
import logging
import os
import sys
import time
from datetime import date, datetime

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client

DB = os.path.join(PROJECT_ROOT, "data", "program_tick.duckdb")
DAILY_DB = os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")


def _num(v) -> int:
    s = str(v or "0").replace(",", "").strip()
    neg = s.startswith("-")
    s = s.lstrip("+-")
    try:
        x = int(float(s or 0))
    except ValueError:
        return 0
    return -x if neg else x


def targets(day: date, top: int, prev: int) -> list[str]:
    conn = duckdb.connect(DAILY_DB, read_only=True)
    try:
        pday = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [day]).fetchone()[0]
        q = """SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value > 0
               AND right(d.code, 1) NOT IN ('5','7','9','K') ORDER BY d.value DESC LIMIT ?"""
        a = [c for (c,) in conn.execute(q, [day, top]).fetchall()]
        b = [c for (c,) in conn.execute(q, [pday, prev]).fetchall()] if prev else []
    finally:
        conn.close()
    seen, out = set(), []
    for c in a + b:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def fetch(client, code: str, day: date, max_pages: int = 200) -> list[tuple]:
    rows, cont, key = [], "N", ""
    for _ in range(max_pages):
        payload, cont, key = client._post("/api/dostk/mrkcond", "ka90008",
                                          {"amt_qty_tp": "1", "stk_cd": code, "date": day.strftime("%Y%m%d")}, cont, key)
        for r in payload.get("stk_tm_prm_trde_trnsn") or []:
            tm = str(r.get("tm") or "")
            if len(tm) != 6:
                continue
            rows.append((day, code, f"{tm[:2]}:{tm[2:4]}:{tm[4:]}", abs(_num(r.get("cur_prc"))), _num(r.get("trde_qty")),
                         _num(r.get("prm_buy_amt")), _num(r.get("prm_sell_amt")), _num(r.get("prm_netprps_amt")),
                         _num(r.get("prm_netprps_qty")), str(r.get("stex_tp") or "")))
        if cont != "Y" or not key:
            break
    return rows


def fetch_strength(client, code: str, day: date, max_pages: int = 40) -> list[tuple]:
    """ka10046 체결강도 시간별 (마지막 거래일, 약 1분 간격 08:30~19:59). 2026-11-01 추가 — 사려는 쪽이 얼마나 서두르는지."""
    rows, cont, key = [], "N", ""
    for _ in range(max_pages):
        payload, cont, key = client._post("/api/dostk/mrkcond", "ka10046", {"stk_cd": code}, cont, key)
        for r in payload.get("cntr_str_tm") or []:
            tm = str(r.get("cntr_tm") or "")
            if len(tm) != 6:
                continue
            f = lambda k: float(str(r.get(k) or "0").replace(",", "").lstrip("+") or 0)
            rows.append((day, code, f"{tm[:2]}:{tm[2:4]}:{tm[4:]}", abs(_num(r.get("cur_prc"))), _num(r.get("acc_trde_qty")),
                         _num(r.get("acc_trde_prica")), f("cntr_str"), f("cntr_str_5min"), f("cntr_str_20min"), f("cntr_str_60min")))
        if cont != "Y" or not key:
            break
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=400)
    ap.add_argument("--prev", type=int, default=300)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (기본: daily_ohlcv 마지막 날 = 마지막 거래일)")
    a = ap.parse_args()
    os.makedirs(os.path.join(PROJECT_ROOT, "data", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(PROJECT_ROOT, "data", "logs", "program_tick.log"), encoding="utf-8")])
    if a.date:
        day = date.fromisoformat(a.date)
    else:
        c = duckdb.connect(DAILY_DB, read_only=True)
        day = c.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930'").fetchone()[0]
        c.close()
    codes = targets(day, a.top, a.prev)
    conn = duckdb.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS program_tick (date DATE, code VARCHAR, tm VARCHAR, price BIGINT, volume BIGINT,
                    buy_amt BIGINT, sell_amt BIGINT, net_amt BIGINT, net_qty BIGINT, exchange VARCHAR)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS strength_tick (date DATE, code VARCHAR, tm VARCHAR, price BIGINT, acc_qty BIGINT,
                    acc_amt BIGINT, strength DOUBLE, s5 DOUBLE, s20 DOUBLE, s60 DOUBLE)""")
    conn.execute("CREATE TABLE IF NOT EXISTS strength_tick_done (date DATE, code VARCHAR, rows INTEGER, PRIMARY KEY (date, code))")
    conn.execute("CREATE TABLE IF NOT EXISTS program_tick_done (date DATE, code VARCHAR, rows INTEGER, done_at TIMESTAMP DEFAULT current_timestamp, PRIMARY KEY (date, code))")
    done = {c for (c,) in conn.execute("SELECT code FROM program_tick_done WHERE date = ?", [day]).fetchall()}
    todo = [c for c in codes if c not in done]
    logging.info("프로그램 체결 이력 %s: 대상 %s종목, 이미 받음 %s, 남음 %s", day, len(codes), len(done), len(todo))
    client = build_client()
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        try:
            rows = fetch(client, code, day)
        except Exception:
            logging.exception("ka90008 실패 %s", code); continue
        if rows:
            conn.executemany("INSERT INTO program_tick VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO program_tick_done (date, code, rows) VALUES (?,?,?)", [day, code, len(rows)])
        if i % 50 == 0:
            logging.info("  %s/%s (%.0f초)", i, len(todo), time.time() - t0)
    logging.info("프로그램 완료 %s종목, %.0f초", len(todo), time.time() - t0)
    sdone = {c for (c,) in conn.execute("SELECT code FROM strength_tick_done WHERE date = ?", [day]).fetchall()}
    stodo = [c for c in codes if c not in sdone]
    logging.info("체결강도 %s: 남음 %s", day, len(stodo)); t1 = time.time()
    for i, code in enumerate(stodo, 1):
        try:
            rows = fetch_strength(client, code, day)
        except Exception:
            logging.exception("ka10046 실패 %s", code); continue
        if rows:
            conn.executemany("INSERT INTO strength_tick VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO strength_tick_done VALUES (?,?,?)", [day, code, len(rows)])
        if i % 100 == 0:
            logging.info("  체결강도 %s/%s (%.0f초)", i, len(stodo), time.time() - t1)
    logging.info("체결강도 완료 %s종목, %.0f초", len(stodo), time.time() - t1)
    conn.close()


if __name__ == "__main__":
    main()
