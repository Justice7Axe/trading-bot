"""햄버거 규칙 백테스트 (indicators/hamburger.py).

    python -m kiwoom_trading.analysis.run_hamburger_backtest --lecture                          # 강의 예시로 기준봉 고르기 점검
    python -m kiwoom_trading.analysis.run_hamburger_backtest --sample --since 2026-09-01 --top 40  # 규칙 선정용 표본 (전날 대금 상위 N)
    python -m kiwoom_trading.analysis.run_hamburger_backtest --week 2026-10-12                      # 그 주 스캐너 감시·매수 후보

1분봉(통합 AL)은 키움 ka10080 으로 받아 data/hamburger_minute_cache.duckdb 에 캐시한다
(1년 백필 data/minute_history.duckdb 는 다른 작업이 쓰는 중이라 잠겨 있을 수 있다).
일봉·스크리너 DB 는 잠금을 피하려고 복사본을 읽는다.
"""
import argparse
import itertools
import json
import logging
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators.hamburger import (VARIANTS, BurgerParams, pick_reference_days, reference_bar,
                                                          simulate_day, with_params)
from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

CACHE_DB = os.path.join(PROJECT_ROOT, "data", "hamburger_minute_cache.duckdb")


def _copy(path: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), "hb_" + os.path.basename(path))
    shutil.copy(path, dst)
    return dst


class Bars:
    """통합(AL) 1분봉 캐시."""

    def __init__(self) -> None:
        self.conn = duckdb.connect(CACHE_DB)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS bars (code VARCHAR, day DATE, ts TIMESTAMP, open BIGINT, high BIGINT,
                             low BIGINT, close BIGINT, volume BIGINT, PRIMARY KEY (code, ts));
                             CREATE TABLE IF NOT EXISTS done (code VARCHAR, day DATE, n INTEGER, PRIMARY KEY (code, day));""")
        self.client = None
        self.fetched = 0

    def get(self, code: str, day: date) -> list[dict]:
        if not self.conn.execute("SELECT 1 FROM done WHERE code=? AND day=?", [code, day]).fetchone():
            if self.client is None:
                self.client = build_client()
            try:
                bars = fetch_minute_bars(self.client, code, day, "AL")
            except Exception as exc:
                logging.warning("1분봉 실패 %s %s: %s", code, day, exc)
                return []
            self.fetched += 1
            if bars:
                self.conn.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)",
                                      [(code, day, b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in bars])
            self.conn.execute("INSERT OR REPLACE INTO done VALUES (?,?,?)", [code, day, len(bars)])
            if self.fetched % 50 == 0:
                logging.info("1분봉 %s건 받음", self.fetched)
        rows = self.conn.execute("SELECT ts, open, high, low, close, volume FROM bars WHERE code=? AND day=? ORDER BY ts",
                                 [code, day]).fetchall()
        return [{"ts": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows]


class Daily:
    def __init__(self) -> None:
        self.conn = duckdb.connect(_copy(os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")), read_only=True)
        self._cache: dict[str, list[dict]] = {}
        self.names = dict(self.conn.execute("SELECT code, name FROM stocks").fetchall())

    def rows(self, code: str) -> list[dict]:
        if code not in self._cache:
            self._cache[code] = [dict(zip(("date", "open", "high", "low", "close", "value", "market_cap"), r)) for r in self.conn.execute(
                "SELECT date, open, high, low, close, value, market_cap FROM daily_ohlcv WHERE code=? AND date >= DATE '2025-06-01' ORDER BY date",
                [code]).fetchall()]
        return self._cache[code]

    def trading_days(self, since: date, until: date) -> list[date]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date BETWEEN ? AND ? ORDER BY date", [since, until]).fetchall()]

    def top_value(self, day: date, n: int) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT d.code FROM daily_ohlcv d JOIN stocks s USING (code) WHERE d.date = ? AND d.value IS NOT NULL "
            "ORDER BY d.value DESC LIMIT ?", [day, n]).fetchall()]


def prepare(daily: Daily, bars: Bars, cases: list[tuple[str, date]]) -> list[dict]:
    """(code, D) 마다 매매일 봉·기준 후보·후보별 기준봉을 미리 계산 (변형 전체에서 재사용)."""
    out = []
    p0 = BurgerParams()
    for code, d in cases:
        rows = daily.rows(code)
        prev = [r for r in rows if r["date"] < d]
        if len(prev) < 25:
            continue
        # 기준일 후보는 burst_k 와 무관하게 같다 → 정렬만 변형별로 다시 한다
        cands, _ = pick_reference_days(rows, d, p0)
        if not cands:
            continue
        refs = {}
        for c in cands[:4]:
            rb = reference_bar(bars.get(code, c["date"]), c["prev_close"], p0)
            if rb:
                refs[c["date"]] = rb
        if not refs:
            continue
        day_bars = bars.get(code, d)
        if not day_bars:
            continue
        today = next((r for r in rows if r["date"] == d), None)
        out.append({"code": code, "date": d, "rows": rows, "bars": day_bars, "refs": refs,
                    "prev_close": prev[-1]["close"], "large": bool(prev[-1].get("market_cap") and prev[-1]["market_cap"] >= 10e12),
                    "day_ret": (today["close"] / prev[-1]["close"] - 1) if today else None})
    return out


def run_case(case: dict, p: BurgerParams) -> dict:
    cands, today_env = pick_reference_days(case["rows"], case["date"], p)
    cands = [c for c in cands if c["date"] in case["refs"]][:p.max_refs]
    if not cands:
        return {"status": "no_ref"}
    best = max(cands, key=lambda c: case["refs"][c["date"]]["value"])
    ref = case["refs"][best["date"]]
    mult = p.env_mult if (today_env and not best["env_burst"]) else 1.0
    r = simulate_day(case["bars"], case["prev_close"], ref["value"], best["high_pct"], mult, p, case["large"])
    r.update(ref_date=best["date"], ref_ts=ref["ts"], ref_value=ref["value"], kki=best["high_pct"], mult=mult)
    return r


def summarize(results: list[tuple[dict, dict]], split: Optional[date] = None) -> dict:
    trades = [(c, r) for c, r in results if r.get("status") == "traded"]
    rets = [r["ret"] for _, r in trades]
    s = {"cases": len(results), "burgers": sum(1 for _, r in results if r.get("burger")), "n": len(rets),
         "win": sum(1 for x in rets if x > 0) / len(rets) if rets else 0, "avg": sum(rets) / len(rets) if rets else 0,
         "sum": sum(rets)}
    if split:
        for name, sel in (("앞", lambda c: c["date"] < split), ("뒤", lambda c: c["date"] >= split)):
            xs = [r["ret"] for c, r in trades if sel(c)]
            s[name] = (len(xs), sum(xs) / len(xs) if xs else 0)
    return s


def grid() -> list[tuple[str, BurgerParams]]:
    keys = list(VARIANTS)
    out = []
    for combo in itertools.product(*(VARIANTS[k] for k in keys)):
        kw = dict(zip(keys, combo))
        label = (f"15분{'생략' if kw['nxt_skip_15'] else '적용'} 전환{'1/3' if kw['nxt_switch'] < 0.4 else '1/2'} "
                 f"터짐{kw['burst_k']:g}배 보정{kw['env_mult']:g}")
        out.append((label, with_params(BurgerParams(), **kw)))
    return out


def week_cases(daily: Daily, monday: date) -> list[tuple[str, date]]:
    sc = duckdb.connect(_copy(os.path.join(PROJECT_ROOT, "data", "screener.duckdb")), read_only=True)
    cases = set()
    for d in daily.trading_days(monday, monday + timedelta(days=4)):
        codes = {r[0] for r in sc.execute("SELECT DISTINCT code FROM buy_signals WHERE date = ?", [d]).fetchall()}
        codes |= {r[0] for r in sc.execute("SELECT DISTINCT code FROM detections WHERE date = ? AND mode = 'intraday'", [d]).fetchall()}
        codes |= {r[0] for r in sc.execute("SELECT DISTINCT code FROM watch_adds WHERE date = ?", [d]).fetchall()}
        prev = sc.execute("SELECT max(date) FROM detections WHERE mode='daily' AND date < ?", [d]).fetchone()[0]
        if prev:
            codes |= {r[0] for r in sc.execute("SELECT code FROM detections WHERE mode='daily' AND date = ?", [prev]).fetchall()}
        cases |= {(c, d) for c in codes}
    return sorted(cases, key=lambda x: (x[1], x[0]))


LECTURE_REFS = [  # (종목, 코드, 기준일, 강의가 고른 기준봉 시각, 금액(억)) — docs/hamburger_lectures.md 4·7장
    ("대한전선", "001440", "2026-04-08", "12:19", 47), ("대한전선", "001440", "2026-04-01", "13:06", 35),
    ("이수스페셜티케미컬", "457190", "2026-04-15", "09:34", 29), ("롯데에너지머티리얼즈", "020150", "2026-04-10", "09:36", 24),
    ("두산에너빌리티", "034020", "2026-04-08", "12:04", 223), ("제주반도체", "080220", "2026-04-24", "09:25", 300),
    ("이수페타시스", "007660", "2026-04-08", "15:01", 56), ("OCI홀딩스", "010060", "2026-04-21", "12:20", 150),
    ("태성", "323280", "2026-04-22", "09:03", 78), ("로보티즈", "108490", "2026-04-24", "12:32", 63),
    ("비나텍", "126340", "2026-04-14", "09:36", 20), ("퀄리타스반도체", "432720", "2026-04-30", "10:18", 39),
    ("SKC", "011790", "2026-04-16", "10:04", 61), ("DB하이텍", "000990", "2026-04-24", "08:13", 101),
    ("보성파워텍", "006910", "2026-05-04", "09:44", 106), ("두산퓨얼셀", "336260", "2026-04-22", "10:17", 40),
]


def lecture_check(daily: Daily, bars: Bars) -> None:
    p = BurgerParams()
    ok = 0
    for name, code, d, t, amt in LECTURE_REFS:
        d = date.fromisoformat(d)
        rows = daily.rows(code)
        prev = [r for r in rows if r["date"] < d]
        rb = reference_bar(bars.get(code, d), prev[-1]["close"], p)
        got = f"{rb['ts']:%H:%M} {rb['value'] / 1e8:.0f}억(원 {rb['raw'] / 1e8:.0f})" if rb else "없음"
        hit = rb and (rb["ts"].strftime("%H:%M") == t or abs(rb["value"] / 1e8 - amt) <= amt * 0.25)
        ok += bool(hit)
        print(f"{'✅' if hit else '❌'} {name} {d} 강의 {t} {amt}억 → 코드 {got}")
    print(f"기준봉 일치 {ok}/{len(LECTURE_REFS)} (같은 시각 또는 금액 ±25%)")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lecture", action="store_true")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--until", default="2026-10-15")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--week", default="")
    ap.add_argument("--params", default="", help="JSON, 예: '{\"nxt_skip_15\": true}'")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    daily, bars = Daily(), Bars()
    if a.lecture:
        lecture_check(daily, bars)
    if a.sample:
        days = daily.trading_days(date.fromisoformat(a.since), date.fromisoformat(a.until))
        all_days = daily.trading_days(date.fromisoformat(a.since) - timedelta(days=10), date.fromisoformat(a.until))
        cases = []
        for d in days:
            prev = [x for x in all_days if x < d][-1]
            cases += [(c, d) for c in daily.top_value(prev, a.top)]
        prepared = prepare(daily, bars, cases)
        split = days[len(days) // 2]
        print(f"\n표본 {len(cases)}건 → 기준일 있는 {len(prepared)}건, 1분봉 새로 받음 {bars.fetched}건, 앞/뒤 나눔 {split}")
        rows = []
        for label, p in grid():
            res = [(c, run_case(c, p)) for c in prepared]
            s = summarize(res, split)
            rows.append((label, s))
            print(f"{label:28} 햄버거 {s['burgers']:3} 매매 {s['n']:3} 승률 {s['win']:4.0%} 평균 {s['avg']:+6.2%} 합 {s['sum']:+6.1%} "
                  f"| 앞 {s['앞'][0]:3} {s['앞'][1]:+6.2%} 뒤 {s['뒤'][0]:3} {s['뒤'][1]:+6.2%}")
        if a.out:
            json.dump([{"label": l, **{k: v for k, v in s.items()}} for l, s in rows], open(a.out, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1, default=str)
    if a.week:
        p = with_params(BurgerParams(), **json.loads(a.params)) if a.params else BurgerParams()
        cases = week_cases(daily, date.fromisoformat(a.week))
        prepared = prepare(daily, bars, cases)
        print(f"\n주간 후보 {len(cases)}건 → 기준일 있는 {len(prepared)}건")
        res = [(c, run_case(c, p)) for c in prepared]
        stat = defaultdict(int)
        for c, r in res:
            stat[r["status"]] += 1
            if r.get("status") == "traded":
                e, x = r["entry"], r["exit"]
                print(f"  {c['date']} {daily.names.get(c['code'], c['code'])}({c['code']}) 기준 {r['ref_date']:%m-%d} {r['ref_ts']:%H:%M} "
                      f"{r['ref_value'] / 1e8:.0f}억×{r['mult']:g} 끼 {r['kki']:.0%} | 햄버거 {r['burger']['ts']:%H:%M} "
                      f"{r['burger']['value'] / 1e8:.0f}억 | 매수 {e['ts']:%H:%M} {e['price']:,.0f} → {x['reason']} {x['ts']:%H:%M} "
                      f"{x['price']:,.0f} = {r['ret']:+.2%}")
        s = summarize(res)
        print(f"상태: {dict(stat)}")
        print(f"매매 {s['n']}건 · 승률 {s['win']:.0%} · 평균 {s['avg']:+.2%} · 합 {s['sum']:+.1%}")


if __name__ == "__main__":
    main()
