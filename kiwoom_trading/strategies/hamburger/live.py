"""🍔 햄버거 장중 신호 → 모의투자 (2026-10-23 사용자: 햄버거 모의매매, 종목은 엄격히 골라 확실한 종목만).

규칙은 analysis/indicators/hamburger.py 그대로 (불개미 파이널 9·10·12·13강, docs/hamburger_design.md).
엄격한 선정 = 검증에서 유일하게 모든 기간 수익이었던 H4 (설계 문서 9-2c):
- 대상: 전날 대금 상위 40 (검증 표본과 같은 범위) 중 최근 20거래일 안에 기준 캔들 날(대금 터진 +8% 장대양봉)이 있는 종목
- 햄버거 봉 종가가 전일 종가 대비 0% 초과 ~ +3% 이하일 때만 (높은 자리 햄버거는 버림)
- 장 시작 15분 뒤 고점 갱신 → 끼 안쪽이면 돌파한 전고점까지 눌릴 때 매수 (09:15~14:30)
- 익절 +2% (모의투자 '목표' 방식), 손절 = 전저점(−2~−5%), 남으면 15:19 정리
근거: 6~8월(처음 보는 기간) 앞 15건 87% +1.09% / 뒤 13건 85% +1.24%, 4.5개월 35건 승률 89% 약 +1.2%.
⚠️ 0~3% 범위는 데이터를 보고 좁힌 값이고 1년 검증 전이다 → 모의투자로 실제 체결을 쌓아 판단한다.
"""
import logging
import os
import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from typing import Optional

import duckdb

from kiwoom_trading.strategies.hamburger.rules import (BurgerParams, pick_reference_days, reference_bar,
                                                          simulate_day, with_params)
from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import RankItem

KIND = "햄버거"
TOP_N = 40                      # 전날 대금 상위 40 (H4 검증 범위)
POS_MIN, POS_MAX = 0.0, 0.03    # 햄버거 봉 종가 위치 (전일 대비)
PARAMS = with_params(BurgerParams(), tp=0.02, tp_large=0.02)
START, LAST = time(9, 15), time(14, 31)
FRESH_MIN = 3                   # 체결 봉이 이 분 안이어야 지금 사는 자리 (재시작·지연 여유)
CACHE_DB = os.path.join(PROJECT_ROOT, "data", "hamburger_minute_cache.duckdb")
DAILY_DB = os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")


def _ref_bars(client: KiwoomDailyClient, conn, code: str, day: date) -> list[dict]:
    """기준 캔들 날 통합(AL) 1분봉 — 백테스트 캐시를 같이 쓴다."""
    if not conn.execute("SELECT 1 FROM done WHERE code=? AND day=?", [code, day]).fetchone():
        bars = fetch_minute_bars(client, code, day, "AL")
        if bars:
            conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)",
                             [(code, day, b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in bars])
        conn.execute("INSERT OR REPLACE INTO done VALUES (?,?,?)", [code, day, len(bars)])
    rows = conn.execute("SELECT ts, open, high, low, close, volume FROM bars WHERE code=? AND day=? ORDER BY ts", [code, day]).fetchall()
    return [dict(zip(("ts", "open", "high", "low", "close", "volume"), r)) for r in rows]


class HamburgerWatcher:
    """장 시작 전 대상 종목·기준봉을 정해 두고, 장중 매분 통합 1분봉으로 햄버거 매매를 처음부터 다시 따라간다 (인과적)."""

    def __init__(self, client: KiwoomDailyClient, today: date, seen: Optional[set[tuple[str, datetime]]] = None) -> None:
        self.client = client
        self.today = today
        self.seen: set[tuple[str, datetime]] = set(seen or ())
        self.done: set[str] = {c for c, _ in self.seen}
        self.cache: dict = {}                  # run_once 가 넣어 주는 공유 캐시 (KRX 봉용, 여기서는 안 씀)
        self.cases: dict[str, dict] = {}
        self._prepare()

    def _prepare(self) -> None:
        copy = os.path.join(tempfile.gettempdir(), f"hbw_{os.getpid()}_daily_ohlcv.duckdb")   # 20:00 일봉 업데이트와 잠금이 겹치지 않게 복사본
        shutil.copy(DAILY_DB, copy)
        daily = duckdb.connect(copy, read_only=True)
        try:
            prev_day = daily.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [self.today]).fetchone()[0]
            top = daily.execute("SELECT d.code, s.name FROM daily_ohlcv d JOIN stocks s USING (code) WHERE d.date = ? "
                                "AND d.value IS NOT NULL ORDER BY d.value DESC LIMIT ?", [prev_day, TOP_N]).fetchall()
            rows_by = {}
            for code, _ in top:
                rows_by[code] = [dict(zip(("date", "open", "high", "low", "close", "value", "market_cap"), r)) for r in daily.execute(
                    "SELECT date, open, high, low, close, value, market_cap FROM daily_ohlcv WHERE code=? AND date >= ? AND date < ? ORDER BY date",
                    [code, self.today - timedelta(days=90), self.today]).fetchall()]
        finally:
            daily.close()
        cache = duckdb.connect(CACHE_DB)
        cache.execute("""CREATE TABLE IF NOT EXISTS bars (code VARCHAR, day DATE, ts TIMESTAMP, open BIGINT, high BIGINT,
                         low BIGINT, close BIGINT, volume BIGINT, PRIMARY KEY (code, ts));
                         CREATE TABLE IF NOT EXISTS done (code VARCHAR, day DATE, n INTEGER, PRIMARY KEY (code, day));""")
        try:
            for code, name in top:
                rows = rows_by[code]
                cands, today_env = pick_reference_days(rows, self.today, PARAMS)
                refs = []
                for c in cands[:PARAMS.max_refs]:
                    try:
                        rb = reference_bar(_ref_bars(self.client, cache, code, c["date"]), c["prev_close"], PARAMS)
                    except Exception as exc:
                        logging.warning("햄버거 기준봉 1분봉 실패 %s %s: %s", code, c["date"], exc)
                        continue
                    if rb:
                        refs.append((c, rb))
                if not refs:
                    continue
                c, rb = max(refs, key=lambda x: x[1]["value"])
                mult = PARAMS.env_mult if (today_env and not c["env_burst"]) else 1.0
                self.cases[code] = {"name": name, "prev_close": rows[-1]["close"], "ref": rb, "ref_date": c["date"],
                                    "kki": c["high_pct"], "mult": mult,
                                    "large": bool(rows[-1].get("market_cap") and rows[-1]["market_cap"] >= PARAMS.large_cap)}
        finally:
            cache.close()
        logging.info("햄버거 대상 %s종목 (전날 %s 대금 상위 %s 중 기준 캔들 날 있음): %s", len(self.cases), prev_day, TOP_N,
                     ", ".join(f"{v['name']}(기준 {v['ref_date']:%m-%d} {v['ref']['value'] / 1e8:,.0f}억×{v['mult']})"
                               for v in self.cases.values()))

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        if not (START <= now.time() <= LAST):
            return []
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for code, c in self.cases.items():
            if code in self.done:
                continue
            try:
                bars = [b for b in fetch_minute_bars(self.client, code, self.today, "AL") if b["ts"] < minute]
            except Exception as exc:
                logging.warning("햄버거 1분봉 조회 실패 %s: %s", code, exc)
                continue
            r = simulate_day(bars, c["prev_close"], c["ref"]["value"], c["kki"], c["mult"], PARAMS, c["large"])
            burger = r.get("burger")
            if burger and not (POS_MIN < burger["pct"] <= POS_MAX):
                self.done.add(code)
                logging.info("햄버거 %s: %s 햄버거 위치 %+.1f%% — 0~+3%% 밖이라 버림", c["name"], f"{burger['ts']:%H:%M}", burger["pct"] * 100)
                continue
            if r["status"] in ("no_fill", "kki_over"):     # 첫 햄버거 뒤 눌림 미체결·끼 초과 → 그날은 끝
                self.done.add(code)
            if r["status"] != "traded":
                continue
            self.done.add(code)
            e = r["entry"]
            if minute - e["ts"] > timedelta(minutes=FRESH_MIN) or (code, e["ts"]) in self.seen:
                logging.info("햄버거 %s: 체결 자리 %s 가 지나서 사지 않음", c["name"], f"{e['ts']:%H:%M}")
                continue
            self.seen.add((code, e["ts"]))
            reason = (f"기준 {c['ref_date']:%m-%d} {c['ref']['ts']:%H:%M} {c['ref']['value'] / 1e8:,.0f}억 × {c['mult']} → "
                      f"햄버거 {burger['ts']:%H:%M} ({burger['strength']:.1f}배, 위치 {burger['pct']:+.1%}) · "
                      f"전고점 {r['breakout']['limit']:,.0f} 돌파 뒤 눌림 — 익절 +2%, 손절 {e['stop']:,.0f}, 남으면 15:19")
            out.append((code, c["name"], KIND, Signal(e["ts"], KIND, float(e["price"]), float(r["breakout"]["limit"]), float(e["stop"]), reason)))
        return out
