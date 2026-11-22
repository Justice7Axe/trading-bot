"""🍔 햄버거 기법(불개미 매매) × 영웅문 조건검색식(햄버거1·햄버거2·불개미검증) 백테스트 (2026-11-22 사용자 요청).

사용자 의도 (11-22 정정): **조건식 = 1차 종목 거르기(범위)**, **매수 자리 = 햄버거 기법**. 조건식에 걸린 순간 바로 사는 것이 아님.

버전 (모두 같은 기간·같은 비용 0.25%, 매도 A·B 두 가지를 함께 셈):
  0   기준선 = 지금 햄버거 모의 규칙 H4 그대로 (strategies/hamburger/live.py 와 같은 함수·숫자)
        대상 = 전날 대금 상위 40 중 최근 20거래일 안 기준 캔들 날이 있는 종목, 햄버거 봉 위치 0~+3%,
        전고점 지정가 눌림 매수(60분 안·14:30 전), 익절 +2% / 손절 전저점(−2~−5%) / 남으면 15:19.
  1~3 기준선 매매 중 그 시각까지 그날 조건식에 걸린 종목만 (가: 그날 매수 전 한 번이라도, 나: 매수 직전 10분 안)
  4   종목 범위 = '전날 대금 상위 40' 대신 '그날 그 시각까지 조건식에 걸린 종목' (조건식마다 따로).
        매수는 H4 규칙 그대로, 단 돌파(고점 갱신)·체결은 조건에 처음 걸린 봉 뒤에만 인정.
        4a 기준 캔들 날이 있는 종목만 / 4b 기준 캔들 날이 없으면 '오늘 조건 포착 전 가장 큰 1분봉(조정 대금)'을 기준봉으로 씀.
  5   4번 범위에서 위키(docs/wiki/bulgaemi/README.md 1-3·1-5절)의 다른 사는 자리를 하나씩:
        5A 햄버거 압도 돌파 · 5B 시간 매물 소화 돌파 · 5C 큰 봉 뒤 쌍바닥 · 그리고 1-5절 피하는 자리 거르기를 넣은 판.
        수치 정의는 아래 DEF (강의·위키에 숫자가 없는 것은 정의값으로 정함 — 보고서에 적음).

매도:
  A (햄버거 규칙) = 익절 +2% / 손절 전저점 / 둘 다 아니면 15:19 봉 종가 (H4 그대로)
  B (backtest-rules 기본형) = 익절 +2% / 같은 손절 / 둘 다 아니면 정규장 끝(15:30 봉)까지 지켜보고 다음 날 09:00 시가
  → 두 매도의 차이는 '15:19 정리'냐 '다음 날 09:00'냐 뿐임.

조건식 판정은 PR #237 이 만든 data/condition_filter/hits.duckdb (kiwoom_trading/backtest/condition_filter.py) 를 그대로 씀.

자료 함정 처리 (.claude/skills/backtest-rules):
  - 1분봉 = minute_history (통합 AL, 원가격). 1분봉이 있는 종목 = 그날∪전날 대금 상위 약 550종목.
    빠진 종목의 그날 대금은 거의 다 120억 아래(하루 최대값 중앙 40억·99% 118억) → 조건식(1분 10억↑·누적 4,000억↑)에 걸릴 종목은
    사실상 다 들어 있어, '조건에 걸린 종목'을 범위로 써도 그날 대금 순위로 고르는 미래 정보가 거의 없음 (보고서에 숫자 적음).
  - 전일 종가: 기준선은 live.py 와 똑같이 일봉 daily_ohlcv 종가 (09-14 부터는 20:00 애프터 종가).
    4·5번은 condition_filter 의 pclose (전 거래일 1분봉 정규장 종가) — 1분봉 원가격과 같은 기준.
  - 종가 매도 없음, 같은 봉이면 손절 먼저, 지정가 체결 봉에선 익절 안 봄, 시가 매수 봉에선 손절만 봄.
  - 시장 분위기 U/N+/N-/D = backtest/playbook/regime.py 규칙. 10-23 까지는 보존본 regime_feat.pkl, 그 뒤는 build_regime 함수로 새로 계산.

실행:  .venv/Scripts/python.exe -m kiwoom_trading.backtest.hamburger_condition_bt            (캐시 있으면 재사용)
       .venv/Scripts/python.exe -m kiwoom_trading.backtest.hamburger_condition_bt --rebuild  (매매 목록 다시 계산)
출력:  data/hamburger_condition_bt/{results.md, trades.csv, trades.pkl, regime_feat_full.pkl}, data/reports/hamburger_condition_bt_YYYYMMDD.html
"""
import argparse
import csv
import os
import pickle
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

import duckdb
import numpy as np

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.common.krx import tick_size, upper_limit
from kiwoom_trading.strategies.hamburger import live as HB
from kiwoom_trading.strategies.hamburger.rules import (BurgerParams, _upper_wick, adj_value, bar_value, pick_reference_days,
                                                          reference_bar, simulate_day)

DATA = os.environ.get("TRADING_DATA") or (os.path.join(PROJECT_ROOT, "data") if os.path.exists(os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb"))
                                          else "D:/Ellie/trading/data")   # 워크트리에서 돌려도 메인 폴더 자료를 읽음
OUT = os.path.join(DATA, "hamburger_condition_bt")
COST = 0.0025
H4: BurgerParams = HB.PARAMS                    # tp 0.02, 전저점 손절, 15:19
POS_MIN, POS_MAX = HB.POS_MIN, HB.POS_MAX       # 햄버거 봉 위치 0~+3%
TOP_HB = HB.TOP_N                               # 40
FIRST_DAY = date(2025, 11, 12)                  # 기준 캔들 날을 찾을 20거래일이 쌓인 첫날 (옛 1년 검증 burger_year.py 와 같음)
LIVE_FROM = time(9, 12)                         # live 는 09:15 부터 보고, 체결 봉이 3분 안이어야 삼
CONDS = [("h1", "햄버거1"), ("h2", "햄버거2"), ("bg", "불개미검증")]
MIN_N = 15
ARTIFACT = 0.15                                 # 일봉 전일 종가와 1분봉 전일 정규장 종가가 15% 넘게 다르면 분할·병합 등 가격 기준 차이 → 뺌

# 5번 사는 자리·피하는 자리 정의값 (강의·위키에 숫자가 없는 것은 여기서 정함)
DEF = dict(
    a_from=time(9, 15),       # 5A: 9시 15분 규칙 뒤의 당일 고점 돌파만 (강의 타점 규칙과 같음)
    chase=0.01,               # 추격 금지: 돌파 봉 다음 봉 시가가 돌파한 고점 +1% 넘으면 안 삼 (live '+1% 추격 금지'와 같음)
    b_base_min=120,           # 5B: 고점 아래에서 다진 시간 ≥ 120분 (재영솔루텍 약 3시간, 사용자 지시 '2시간↑')
    b_band=0.07,              # 5B: 다지는 동안 저가가 그 고점 −7% 안 (재영솔루텍 1,620~1,720 ≈ 6%)
    c_drop=0.02,              # 5C: 큰 봉 고가에서 −2%↑ 밀려야 '밀림'
    c_tol=0.01,               # 5C: 두 번째 저점이 첫 저점 ±1% 안 (퓨처켐 09:50·10:05 둘 다 약 22,900)
    c_gap=5,                  # 5C: 두 저점 사이 ≥ 5분
    c_bounce=0.01,            # 5C: 두 저점 사이 반등 ≥ +1%
    c_window=120,             # 5C: 큰 봉 뒤 120분 안
    wick=0.5,                 # 피하는 자리: 윗꼬리 ≥ 봉 길이 50% (햄버거 기준봉의 윗꼬리 제외 기준과 같음)
    late=time(13, 0),         # 피하는 자리: 13:00 뒤 + 끼 다 쓴 긴 시간 돌파 (롯데케미칼 14:04)
    kki_fallback_days=20,     # 4b: 기준 캔들 날이 없을 때 끼 = 최근 20거래일 최고 고가 등락률
)


# ------------------------------------------------------------------ 자료 열기
def ro(path: str) -> duckdb.DuckDBPyConnection:
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.IOException:
        dst = os.path.join(tempfile.gettempdir(), "hcb_" + os.path.basename(path))
        shutil.copy(path, dst)
        return duckdb.connect(dst, read_only=True)


class Src:
    def __init__(self) -> None:
        self.m = ro(os.path.join(DATA, "minute_history.duckdb"))
        self.dm = ro(os.path.join(DATA, "daily_ohlcv.duckdb"))
        self.hc = ro(os.path.join(DATA, "condition_filter", "hits.duckdb"))
        try:
            self.hbc = ro(os.path.join(DATA, os.path.basename(HB.CACHE_DB)))          # 기준 캔들 날 1분봉이 minute_history 에 없을 때 (live 캐시)
        except Exception:
            self.hbc = None
        self.all_days = [d for (d,) in self.dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
        self.mdays = [d for (d,) in self.hc.execute("SELECT DISTINCT d FROM cover WHERE src='mh' ORDER BY 1").fetchall()]
        self.names = dict(self.dm.execute("SELECT code, name FROM stocks").fetchall())
        self.pclose = {(c, d): pc for c, d, pc in self.hc.execute("SELECT code, d, pc FROM pclose WHERE pc > 0").fetchall()}
        self.cover = {(c, d) for c, d in self.hc.execute("SELECT code, d FROM cover WHERE src='mh'").fetchall()}
        self._daily: dict[str, list[dict]] = {}
        self._bars: dict[tuple[str, date], list[dict]] = {}

    def prev_day(self, d: date) -> date:
        return max(x for x in self.all_days if x < d)

    def next_mday(self, d: date) -> Optional[date]:
        i = self.mdays.index(d)
        return self.mdays[i + 1] if i + 1 < len(self.mdays) else None

    def top(self, d: date, n: int) -> list[str]:
        """live.py 와 같은 쿼리: 일봉 대금 상위 n (stocks 에 있는 종목)."""
        return [c for (c,) in self.dm.execute(
            "SELECT d.code FROM daily_ohlcv d JOIN stocks s USING (code) WHERE d.date = ? AND d.value IS NOT NULL "
            "ORDER BY d.value DESC LIMIT ?", [d, n]).fetchall()]

    def daily(self, code: str) -> list[dict]:
        if code not in self._daily:
            self._daily[code] = [dict(zip(("date", "open", "high", "low", "close", "value", "market_cap"), r)) for r in self.dm.execute(
                "SELECT date, open, high, low, close, value, market_cap FROM daily_ohlcv WHERE code=? AND date >= DATE '2025-06-01' ORDER BY date",
                [code]).fetchall()]
        return self._daily[code]

    def load_day(self, codes: set[str], d: date) -> dict[str, list[dict]]:
        out = defaultdict(list)
        if not codes:
            return out
        ph = ",".join("?" * len(codes))
        for r in self.m.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv
                                    WHERE ts >= ? AND ts <= ? AND code IN ({ph}) ORDER BY code, ts""",
                                [datetime.combine(d, time(8, 0)), datetime.combine(d, time(15, 30)), *sorted(codes)]).fetchall():
            out[r[0]].append(dict(ts=r[1], open=r[2], high=r[3], low=r[4], close=r[5], volume=r[6]))
        return out

    def opens_0900(self, codes: set[str], d: Optional[date]) -> dict[str, float]:
        if not codes or d is None:
            return {}
        ph = ",".join("?" * len(codes))
        return dict(self.m.execute(f"SELECT code, open FROM minute_ohlcv WHERE ts = ? AND code IN ({ph})",
                                   [datetime.combine(d, time(9, 0)), *sorted(codes)]).fetchall())

    def ref_bars(self, code: str, d: date) -> list[dict]:
        key = (code, d)
        if key not in self._bars:
            rows = self.m.execute("SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code=? AND ts >= ? AND ts < ? ORDER BY ts",
                                  [code, datetime.combine(d, time(0)), datetime.combine(d + timedelta(days=1), time(0))]).fetchall()
            if not rows and self.hbc is not None:
                rows = self.hbc.execute("SELECT ts, open, high, low, close, volume FROM bars WHERE code=? AND day=? ORDER BY ts", [code, d]).fetchall()
            self._bars[key] = [dict(zip(("ts", "open", "high", "low", "close", "volume"), r)) for r in rows]
        return self._bars[key]


# ------------------------------------------------------------------ 시장 분위기
def regime_feat(src: Src, rebuild: bool) -> dict:
    path = os.path.join(OUT, "regime_feat_full.pkl")
    if os.path.exists(path) and not rebuild:
        return pickle.load(open(path, "rb"))
    from kiwoom_trading.backtest.playbook import build_regime as br
    br.LAST_DAY, br.DONE_BY = date(2100, 1, 1), datetime(2100, 1, 1)
    M0, B1 = br.build_m0_b1(src.m, src.dm, set())
    ctx, snap = br.index_parts(ro(os.path.join(DATA, "index.duckdb")))
    new = br.build_feat(M0, B1, ctx, snap)
    old = pickle.load(open(os.path.join(DATA, "backtest", "playbook", "regime_feat.pkl"), "rb"))
    feat = dict(new)
    feat.update(old)                                   # 10-23 까지는 보존본 (매매표 백테스트와 같은 판정)
    pickle.dump(feat, open(path, "wb"))
    both = set(old) & set(new)
    same = sum(br.cls_of(old[d]) == br.cls_of(new[d]) for d in both)
    print(f"시장 분위기: 보존본 {len(old)}일 + 새로 {len(set(new) - set(old))}일, 겹치는 날 판정 같음 {same}/{len(both)}", flush=True)
    return feat


def cls(feat: dict, d: date) -> Optional[str]:
    x = feat.get(d)
    if not x:
        return None
    if x["K1z"] <= -1 or x["M0"] <= -0.015:
        return "D"
    if x["K1z"] >= 1 or x["M0"] >= 0.02:
        return "U"
    return "N+" if x["dd52"] > -0.10 else "N-"


# ------------------------------------------------------------------ 햄버거 기준봉
def hb_case(src: Src, code: str, d: date) -> Optional[dict]:
    """live.HamburgerWatcher._prepare 와 같은 방식으로 기준봉·끼·배수를 정함."""
    rows = [r for r in src.daily(code) if d - timedelta(days=90) <= r["date"] < d]
    if not rows:
        return None
    cands, today_env = pick_reference_days(rows, d, H4)
    refs = []
    for c in cands[:H4.max_refs]:
        rb = reference_bar(src.ref_bars(code, c["date"]), c["prev_close"], H4)
        if rb:
            refs.append((c, rb))
    if not refs:
        return None
    c, rb = max(refs, key=lambda x: x[1]["value"])
    mult = H4.env_mult if (today_env and not c["env_burst"]) else 1.0
    return {"prev_close": rows[-1]["close"], "ref_value": rb["value"], "ref_date": c["date"], "kki": c["high_pct"], "mult": mult}


def kki_recent(src: Src, code: str, d: date) -> float:
    rows = [r for r in src.daily(code) if r["date"] < d][-(DEF["kki_fallback_days"] + 1):]
    xs = [rows[i]["high"] / rows[i - 1]["close"] - 1 for i in range(1, len(rows)) if rows[i - 1]["close"]]
    return max(xs) if xs else 0.0


# ------------------------------------------------------------------ 햄버거 하루 시뮬 (rules.simulate_day 를 그대로 옮기고 '조건 포착 뒤' 옵션만 더함)
def sim(bars: list[dict], prev_close: float, ref_value: float, kki: float, mult: float, p: BurgerParams,
        brk_after: Optional[datetime] = None, burger_from: Optional[datetime] = None) -> dict[str, Any]:
    """brk_after: 이 봉부터의 고점 갱신만 돌파로 인정 (조건 포착 봉 마감 때 둘 다 알게 되고, 체결은 다음 봉부터라 미래 정보 아님). burger_from: 이 봉부터만 햄버거로 셈 (4b).
    둘 다 None 이면 rules.simulate_day 와 같은 결과 (build 에서 기준선마다 확인)."""
    bars = [b for b in bars if b["ts"].time() <= p.exit_at]
    thr = ref_value * mult
    out: dict[str, Any] = {"thr": thr, "status": "no_burger"}
    if not bars or not prev_close or thr <= 0:
        return out
    start = next((b["ts"] for b in bars if b["ts"].time() < time(9, 0) and bar_value(b) >= ref_value * p.nxt_switch), None)
    nxt_start = start is not None
    if start is None:
        start = next((b["ts"] for b in bars if b["ts"].time() >= time(9, 0)), bars[0]["ts"])
    gate = start if (nxt_start and p.nxt_skip_15) else start + timedelta(minutes=p.wait_min)
    burger = run_high = breakout = entry = None
    recent: list[float] = []
    for i, b in enumerate(bars):
        t = b["ts"]
        v = adj_value(b)
        if burger_from is not None and t < burger_from:
            recent = []
        else:
            recent = (recent + [v])[-3:]
            if burger is None and b["close"] > b["open"] and (v >= thr or (len(recent) == 3 and min(recent) >= thr * 0.5 and sum(recent) >= thr * 1.5)):
                burger = {"ts": t, "value": v, "strength": v / thr, "pct": b["close"] / prev_close - 1, "i": i}
                out["burger"] = burger
        if entry is None:
            if breakout is None:
                prev_high = run_high
                if not (nxt_start and t.time() == time(9, 0)):
                    run_high = b["high"] if run_high is None else max(run_high, b["high"])
                if (burger and prev_high is not None and t >= gate and b["high"] > prev_high and t.time() <= p.last_entry
                        and (brk_after is None or t >= brk_after)):
                    allow = kki + (p.kki_over if burger["strength"] >= 2 else 0)
                    if prev_high / prev_close - 1 > allow:
                        out["status"] = "kki_over"
                        continue
                    base_low = min(x["low"] for x in bars[max(0, i - p.stop_lookback):i + 1])
                    breakout = {"ts": t, "limit": prev_high, "base_low": base_low}
                    out["breakout"] = breakout
                continue
            if (t - breakout["ts"]).total_seconds() > p.entry_window_min * 60 or t.time() > p.last_entry:
                out["status"] = "no_fill"
                return out
            if t > breakout["ts"] and b["low"] <= breakout["limit"]:
                px = min(breakout["limit"], b["open"])
                stop = min(px * (1 - p.stop_min), max(px * (1 - p.stop_max), breakout["base_low"] * 0.995))
                entry = {"ts": t, "price": px, "stop": stop, "tp": px * (1 + p.tp)}
                out.update(status="traded", entry=entry)
                if b["low"] <= stop:
                    return _close(out, t, stop, "손절")
            continue
        if b["low"] <= entry["stop"]:
            return _close(out, t, min(entry["stop"], b["open"]), "손절")
        if b["high"] >= entry["tp"]:
            return _close(out, t, max(entry["tp"], b["open"]), "익절")
    if entry is not None:
        return _close(out, bars[-1]["ts"], bars[-1]["close"], "장 마감")
    if breakout is None and burger is not None and out["status"] == "no_burger":
        out["status"] = "no_breakout"
    return out


def _close(out: dict, ts: datetime, price: float, reason: str) -> dict:
    out["exit"] = {"ts": ts, "price": price, "reason": reason}
    out["ret"] = price / out["entry"]["price"] - 1 - COST
    return out


# ------------------------------------------------------------------ 매도 (A: 15:19 / B: 다음 날 09:00)
def walk_exit(bars: list[dict], j: int, px: float, stop: float, tp: float, until: time, limit_fill: bool) -> Optional[tuple]:
    """bars[j] = 매수 봉. 지정가 체결 봉·시가 매수 봉 모두 그 봉에선 손절만 봄 (순서를 모름 → 보수적). 끝까지 안 닿으면 None."""
    for k in range(j, len(bars)):
        b = bars[k]
        if b["ts"].time() > until:
            break
        if b["low"] <= stop:
            return b["ts"], (stop if k == j else min(stop, b["open"])), "손절"
        if k > j and b["high"] >= tp:
            return b["ts"], max(tp, b["open"]), "익절"
    return None


def exits(bars: list[dict], j: int, px: float, stop: float, nopen: Optional[float], nd: Optional[date]) -> tuple[tuple, Optional[tuple]]:
    tp = px * (1 + H4.tp)
    a = walk_exit(bars, j, px, stop, tp, H4.exit_at, True)
    if a is None:
        last = [b for b in bars[j:] if b["ts"].time() <= H4.exit_at][-1]
        a = (last["ts"], last["close"], "15:19")
    b = walk_exit(bars, j, px, stop, tp, time(15, 30), True)
    if b is None:
        b = (datetime.combine(nd, time(9, 0)), nopen, "다음 날 09:00") if (nopen and nd) else None
    return a, b


def slip_ret(entry: float, exit_: float, n: int = 2) -> float:
    return (exit_ - n * tick_size(exit_)) / (entry + n * tick_size(entry)) - 1 - COST


def clamp_stop(px: float, low: float) -> float:
    return min(px * (1 - H4.stop_min), max(px * (1 - H4.stop_max), low * 0.995))


# ------------------------------------------------------------------ 5번 사는 자리
def spot_a(bars: list[dict], after: datetime, thr: float, kki: float, prev_close: float) -> Optional[dict]:
    """5A 햄버거 압도 돌파: 조정 대금 ≥ 기준(×배수) 인 양봉이 09:15 뒤 당일 고점을 종가로 뚫는 봉 → 다음 봉 시가 매수."""
    run_high = None
    for i, b in enumerate(bars):
        t = b["ts"]
        if t.time() < time(9, 0):
            continue
        ph = run_high
        run_high = b["high"] if run_high is None else max(run_high, b["high"])
        if ph is None or t < after or t.time() < DEF["a_from"] or t.time() >= H4.last_entry:
            continue
        v = adj_value(b)
        if b["close"] > b["open"] and v >= thr and b["close"] > ph:
            if ph / prev_close - 1 > kki + (H4.kki_over if v >= 2 * thr else 0):
                return None                        # 끼 넘음 → 그날 끝 (H4 와 같음)
            base_low = min(x["low"] for x in bars[max(0, i - H4.stop_lookback):i + 1])
            return {"i": i, "level": ph, "base_low": base_low, "kind": "A"}
    return None


def spot_b(bars: list[dict], after: datetime) -> Optional[dict]:
    """5B 시간 매물 소화 돌파: 당일 고점 H 뒤 ≥120분 동안 고가 ≤ H·저가 ≥ H×0.93 으로 다진 뒤 종가로 H 돌파 → 다음 봉 시가."""
    reg = [(i, b) for i, b in enumerate(bars) if b["ts"].time() >= time(9, 0)]
    hi, hi_t, lo_since = None, None, None
    for i, b in reg:
        t = b["ts"]
        if hi is not None and b["close"] > hi:
            held = (t - hi_t).total_seconds() / 60
            if (held >= DEF["b_base_min"] and lo_since >= hi * (1 - DEF["b_band"]) and t >= after
                    and time(9, 15) <= t.time() < H4.last_entry):
                base_low = min(x["low"] for x in bars[max(0, i - H4.stop_lookback):i + 1])
                return {"i": i, "level": hi, "base_low": base_low, "kind": "B", "held": held, "hi_t": hi_t}
        if hi is None or b["high"] > hi:
            hi, hi_t, lo_since = b["high"], t, b["low"]
        else:
            lo_since = min(lo_since, b["low"])
    return None


def spot_c(bars: list[dict], burger_i: int, after: datetime) -> Optional[dict]:
    """5C 큰 봉 뒤 쌍바닥: 햄버거 봉 고가에서 −2%↑ 밀린 첫 저점 L1, +1%↑ 반등, 5분↑ 뒤 L1 ±1% 두 번째 저점,
    그 뒤 양봉이 저점 +0.5% 위로 마감 → 다음 봉 시가. 햄버거 봉 뒤 120분 안, 새 저점(L1 −1% 아래)이 나오면 L1 을 다시 잡음."""
    bh = bars[burger_i]["high"]
    t0 = bars[burger_i]["ts"]
    l1 = l1_i = None
    bounced = False
    l2_i = None
    for k in range(burger_i + 1, len(bars)):
        b = bars[k]
        if (b["ts"] - t0).total_seconds() > DEF["c_window"] * 60 or b["ts"].time() >= H4.last_entry:
            return None
        if l1 is None or b["low"] < l1 * (1 - DEF["c_tol"]):
            l1, l1_i, bounced, l2_i = b["low"], k, False, None
            continue
        if l2_i is None:
            if b["low"] < l1:
                l1, l1_i = b["low"], k
                continue
            if b["high"] >= l1 * (1 + DEF["c_bounce"]):
                bounced = True
            if bounced and k - l1_i >= DEF["c_gap"] and b["low"] <= l1 * (1 + DEF["c_tol"]):
                l2_i = k
        if l2_i is not None and l1 <= bh * (1 - DEF["c_drop"]):
            low2 = min(x["low"] for x in bars[l2_i:k + 1])
            if b["close"] > b["open"] and b["close"] > low2 * 1.005 and b["ts"] >= after:
                return {"i": k, "level": None, "base_low": min(l1, low2), "kind": "C"}
        if l2_i is not None and k - l2_i > 5:
            l2_i, bounced = None, False
    return None


def avoid_flags(bars: list[dict], burger_i: Optional[int], until_i: int, has_ref: bool) -> dict:
    """1-5절 피하는 자리 (매수 봉 전까지 본 것만).
    first_wick: 급등 첫날(기준 캔들 날 없음)인데 그날 대금 가장 큰 봉이 윗꼬리 ≥ 50%
    burger_wick: 햄버거 봉 바로 다음 1~2봉 안에 윗꼬리 ≥ 50% 음봉"""
    seen = [b for b in bars[:until_i] if b["ts"].time() >= time(8, 0)]
    first_wick = False
    if not has_ref and seen:
        big = max(seen, key=bar_value)
        first_wick = _upper_wick(big) >= DEF["wick"]
    burger_wick = False
    if burger_i is not None:
        for b in bars[burger_i + 1:min(burger_i + 3, until_i)]:
            if b["close"] < b["open"] and _upper_wick(b) >= DEF["wick"]:
                burger_wick = True
    return {"first_wick": first_wick, "burger_wick": burger_wick}


# ------------------------------------------------------------------ 매매 목록 만들기
def build(src: Src, feat: dict, limit_days: int = 0) -> dict:
    hits_by = defaultdict(lambda: defaultdict(list))      # (code, d) → cond → [ts...]
    for code, d, ts, h1, h2, bg in src.hc.execute("SELECT code, d, ts, h1, h2, bg FROM hits ORDER BY ts").fetchall():
        for k, f in (("h1", h1), ("h2", h2), ("bg", bg)):
            if f:
                hits_by[(code, d)][k].append(ts)
    by_day = defaultdict(list)
    for (code, d) in hits_by:
        by_day[d].append(code)
    T, notes = [], defaultdict(int)
    days = [d for d in src.mdays if d >= FIRST_DAY]
    if limit_days:
        days = days[:limit_days]

    def rec(ver, code, d, rg, bars, j, px, stop, nopen, nd, extra=None, limit_fill=True):
        a, b = exits(bars, j, px, stop, nopen.get(code), nd)
        r = dict(ver=ver, code=code, d=d, regime=rg, entry_ts=bars[j]["ts"], px=px, stop=stop,
                 a_ts=a[0], a_px=a[1], a_reason=a[2], a_ret=a[1] / px - 1 - COST, a_slip=slip_ret(px, a[1]),
                 b_ts=b[0] if b else None, b_px=b[1] if b else None, b_reason=b[2] if b else None,
                 b_ret=(b[1] / px - 1 - COST) if b else None, b_slip=slip_ret(px, b[1]) if b else None)
        if not b:
            notes["다음 날 09:00 시가 없음 (매도 B 에서만 빠짐)"] += 1
        r.update(extra or {})
        T.append(r)
        return r

    for n_day, d in enumerate(days):
        prev = src.prev_day(d)
        top40 = src.top(prev, TOP_HB)
        nd = src.next_mday(d)
        firsts = {}                                     # code → {cond: 첫 봉 ts}
        for code in by_day.get(d, []):
            if (code, d) not in src.cover:
                continue
            hk = hits_by[(code, d)]
            f = {k: hk[k][0] for k, _ in CONDS if hk.get(k)}
            if f:
                firsts[code] = f
        need = set(top40) | set(firsts)
        bars = src.load_day(need, d)
        nopen = src.opens_0900(need, nd)
        rg = cls(feat, d)
        cases = {}

        def case_of(code):
            if code not in cases:
                cases[code] = hb_case(src, code, d)
            return cases[code]

        # 0) 기준선 H4
        for code in top40:
            bs = bars.get(code)
            if not bs:
                notes["기준선: 그날 1분봉 없음"] += 1
                continue
            case = case_of(code)
            if not case:
                continue
            pcm = src.pclose.get((code, d))
            if pcm and abs(case["prev_close"] / pcm - 1) > ARTIFACT:
                notes["기준선: 일봉·1분봉 가격 기준 다름(분할 등) 뺌"] += 1
                continue
            r = sim(bs, case["prev_close"], case["ref_value"], case["kki"], case["mult"], H4)
            r0 = simulate_day(bs, case["prev_close"], case["ref_value"], case["kki"], case["mult"], H4)
            if r.get("ret") != r0.get("ret") or r.get("status") != r0.get("status"):
                notes["경고: sim 과 rules.simulate_day 결과 다름"] += 1
            burger = r.get("burger")
            if r.get("status") != "traded" or not (POS_MIN < burger["pct"] <= POS_MAX):
                continue
            e = r["entry"]
            if e["ts"].time() < LIVE_FROM:
                notes["기준선: 09:12 전 체결(live 는 못 삼) 뺌"] += 1
                continue
            j = next(i for i, b in enumerate(bs) if b["ts"] == e["ts"])
            hk = hits_by.get((code, d), {})
            flags = {}
            for k, _ in CONDS:
                ts_list = hk.get(k, [])
                flags[k + "_ga"] = any(t < e["ts"] for t in ts_list)
                flags[k + "_na"] = any(e["ts"] - timedelta(minutes=10) <= t < e["ts"] for t in ts_list)
            x = rec("base", code, d, rg, bs, j, e["price"], e["stop"], nopen, nd,
                    dict(pos=burger["pct"], mismatch=bool(pcm and abs(case["prev_close"] / pcm - 1) > 0.03), **flags))
            if abs(x["a_ret"] - r["ret"]) > 1e-9:
                notes["경고: 매도 A 가 simulate_day 와 다름"] += 1

        # 4·5) 조건식에 걸린 종목 = 범위
        for code, f in firsts.items():
            bs = bars.get(code)
            pcm = src.pclose.get((code, d))
            drows = [r for r in src.daily(code) if r["date"] < d]
            if not bs or not pcm or not drows or not drows[-1]["close"]:
                notes["4·5: 봉·전일 종가 없음"] += 1
                continue
            pc = drows[-1]["close"]                      # live 와 같은 전일 종가 (일봉)
            if abs(pc / pcm - 1) > ARTIFACT:
                notes["4·5: 일봉·1분봉 가격 기준 다름(분할 등) 뺌"] += 1
                continue
            case = case_of(code)
            lim = upper_limit(pcm)
            for k, hts in f.items():
                def ok_px(px):
                    return px < lim - tick_size(lim)
                # 4a / 4b
                if case:
                    r = sim(bs, pc, case["ref_value"], case["kki"], case["mult"], H4, brk_after=hts)
                    variant, kki, thr = "4a", case["kki"], case["ref_value"] * case["mult"]
                else:
                    before = [adj_value(b) for b in bs if b["ts"] < hts]
                    if not before:
                        continue
                    kki = kki_recent(src, code, d)
                    thr = max(before)
                    r = sim(bs, pc, thr, kki, 1.0, H4, brk_after=hts, burger_from=hts)
                    variant = "4b"
                burger = r.get("burger")
                if r.get("status") == "traded" and POS_MIN < burger["pct"] <= POS_MAX and r["entry"]["ts"].time() >= LIVE_FROM:
                    e = r["entry"]
                    j = next(i for i, b in enumerate(bs) if b["ts"] == e["ts"])
                    av = avoid_flags(bs, burger["i"], j, bool(case))
                    rec(f"{variant}_{k}", code, d, rg, bs, j, e["price"], e["stop"], nopen, nd,
                        dict(cond=k, hit_ts=hts, pos=burger["pct"], has_ref=bool(case), **av))
                # 5A·5C: 기준 캔들 날이 있는 종목 (진짜 햄버거 기준) / 5B: 조건 걸린 종목 전부
                cands = []
                if case:
                    sa = spot_a(bs, hts, case["ref_value"] * case["mult"], case["kki"], pc)
                    if sa:
                        cands.append(sa)
                    rb = sim(bs, pc, case["ref_value"], case["kki"], case["mult"], H4)
                    if rb.get("burger"):
                        sc = spot_c(bs, rb["burger"]["i"], hts)
                        if sc:
                            sc["burger_i"] = rb["burger"]["i"]
                            cands.append(sc)
                sb = spot_b(bs, hts)
                if sb:
                    cands.append(sb)
                for s in cands:
                    j = s["i"] + 1
                    if j >= len(bs) or bs[j]["ts"].time() > H4.last_entry:
                        continue
                    px = bs[j]["open"]
                    if not ok_px(px):
                        notes[f"5{s['kind']}: 상한가(또는 한 칸 아래)라 못 삼"] += 1
                        continue
                    chase = s["level"] is not None and px > s["level"] * (1 + DEF["chase"])
                    stop = clamp_stop(px, s["base_low"])
                    bi = s.get("burger_i")
                    if s["kind"] == "A":
                        bi = s["i"]
                    av = avoid_flags(bs, bi, j, bool(case))
                    late_kki = bool(s["kind"] == "B" and case and bs[s["i"]]["ts"].time() >= DEF["late"]
                                    and s["level"] / pc - 1 >= case["kki"])
                    rec(f"5{s['kind']}_{k}", code, d, rg, bs, j, px, stop, nopen, nd,
                        dict(cond=k, hit_ts=hts, has_ref=bool(case), chase=chase, late_kki=late_kki, **av))
        if n_day % 20 == 0:
            print(f"  {d} 누적 {len(T)}건", flush=True)
    return dict(T=T, notes=dict(notes), days=days)


# ------------------------------------------------------------------ 집계
def stats(tr: list[tuple[date, float]], split: date) -> dict:
    if not tr:
        return dict(n=0)
    v = np.array([x for _, x in tr])
    w, l = v[v > 0], v[v <= 0]
    a = [x for d, x in tr if d < split]
    b = [x for d, x in tr if d >= split]
    bd = defaultdict(float)
    for d, x in tr:
        bd[d] += x
    best5 = sum(sorted(bd.values(), reverse=True)[:5])
    eq = np.cumsum([x for _, x in sorted(tr, key=lambda t: t[0])])
    mdd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    top10 = float(np.sort(v)[::-1][:10].sum())
    s = dict(n=len(v), win=float((v > 0).mean()), sum=float(v.sum()), mean=float(v.mean()),
             payoff=float(w.mean() / -l.mean()) if len(w) and len(l) and l.mean() < 0 else float("nan"),
             pf=float(w.sum() / -l.sum()) if len(l) and l.sum() < 0 else float("inf"), mdd=mdd,
             na=len(a), a=float(np.mean(a)) if a else float("nan"), nb=len(b), b=float(np.mean(b)) if b else float("nan"),
             ex5=float(v.sum() - best5), ex10=float(v.sum() - top10))
    s["star"] = bool(len(v) >= MIN_N and a and b and s["a"] > 0 and s["b"] > 0 and s["ex5"] > 0)
    return s


def pct(x, d=2):
    return "-" if x is None or x != x else f"{x * 100:+.{d}f}%"


def pp(x):
    return "-" if x is None or x != x else f"{x * 100:+.1f}"


def num(x):
    return "-" if x is None or x != x else ("∞" if x == float("inf") else f"{x:.2f}")


HEAD = ["버전", "건수", "승률", "합계(%p)", "건당", "손익비", "PF", "최대 낙폭(%p)", "앞 반 건당(건)", "뒤 반 건당(건)", "최고 5일 빼면(%p)",
        "최고 10건 빼면(%p)", "★"]


def row(name: str, s: dict) -> list[str]:
    if not s.get("n"):
        return [name, "0"] + ["-"] * (len(HEAD) - 2)
    star = "★" if s["star"] else ("(건수 부족)" if s["n"] < MIN_N else "")
    return [name, str(s["n"]), f"{s['win']:.0%}", pp(s["sum"]), pct(s["mean"]), num(s["payoff"]), num(s["pf"]), pp(-s["mdd"]),
            f"{pct(s['a'])} ({s['na']})", f"{pct(s['b'])} ({s['nb']})", pp(s["ex5"]), pp(s["ex10"]), star]


def md_table(head, rows) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows])


# ------------------------------------------------------------------ 계좌 시뮬 (strict_select.choose.real_sim 과 같은 방식)
def tick_up(p: float) -> float:
    t = tick_size(p)
    return float(int(-(-p // t)) * t)


def account(trs: list[dict], days: list[date], split: date, seed: float, per: float) -> dict:
    """현금 안에서 종목당 per 원(1주가 per 보다 비싸면 1주), 정수 주, 지정가 = 가격 +1% 호가 올림으로 증거금,
    같은 날 같은 종목 한 번, 장중 매도는 그 시각 뒤 신호부터 현금, 다음 날 매도는 그날 아침 현금. 손익 = 수량 × 가격 × 수익률. 복리 아님."""
    byd = defaultdict(list)
    for t in trs:
        byd[t["d"]].append(t)
    cash = float(seed)
    hold = []                                  # (돌아오는 날, 시각 or None, 돌려받을 돈, 손익)
    curve, dp, n, skip = [], [], 0, 0
    for d in days:
        keep, day_p = [], 0.0
        for h in hold:
            if h[0] < d or (h[0] == d and h[1] is None):
                cash += h[2]
                day_p += h[3]
            else:
                keep.append(h)
        hold = keep
        got = set()
        for t in sorted(byd.get(d, []), key=lambda t: t["entry_ts"]):
            keep = []
            for h in hold:
                if h[0] == d and h[1] is not None and h[1] <= t["entry_ts"]:
                    cash += h[2]
                    day_p += h[3]
                else:
                    keep.append(h)
            hold = keep
            if t["code"] in got:
                continue
            lim = tick_up(t["px"] * 1.01)
            q = min(max(1, int(per // lim)), int(cash // lim))
            if q < 1:
                skip += 1
                continue
            cash -= q * lim
            p = q * t["px"] * t["r"]
            got.add(t["code"])
            n += 1
            hold.append((t["xd"], None, q * lim + p, p) if t["next_day"] else (d, t["xt"], q * lim + p, p))
        curve.append((d, cash + sum(h[2] - h[3] for h in hold)))
        dp.append(day_p)
    for h in hold:
        cash += h[2]
    curve[-1] = (curve[-1][0], cash)
    v = np.array([x for _, x in curve])
    pk = np.maximum.accumulate(np.r_[seed, v])[1:]
    half = [x for dd, x in curve if dd < split][-1]
    return dict(final=cash, mdd=float(((pk - v) / pk).max()), front=half / seed - 1, back=cash / half - 1, n=n, skip=skip,
                ex5=cash - seed - sum(sorted(dp, reverse=True)[:5]))


# ------------------------------------------------------------------ 버전 정의
def as_trade(t: dict, mode: str) -> Optional[dict]:
    if mode == "a":
        return dict(d=t["d"], code=t["code"], entry_ts=t["entry_ts"], px=t["px"], r=t["a_ret"], slip=t["a_slip"], xt=t["a_ts"],
                    next_day=False, xd=None, regime=t["regime"])
    if t["b_ret"] is None:
        return None
    nd = t["b_reason"] == "다음 날 09:00"
    return dict(d=t["d"], code=t["code"], entry_ts=t["entry_ts"], px=t["px"], r=t["b_ret"], slip=t["b_slip"],
                xt=None if nd else t["b_ts"], next_day=nd, xd=t["b_ts"].date() if nd else None, regime=t["regime"])


def dedup(xs: list[dict]) -> list[dict]:
    """같은 날 같은 종목은 먼저 산 한 번만 (4b 와 5번 합칠 때)."""
    seen, out = set(), []
    for t in sorted(xs, key=lambda t: t["entry_ts"]):
        if (t["code"], t["d"]) not in seen:
            seen.add((t["code"], t["d"]))
            out.append(t)
    return out


def versions(R: dict) -> list[tuple[str, list[dict]]]:
    T = R["T"]
    base = [t for t in T if t["ver"] == "base"]
    V = [("0. 기준선 H4 (전날 대금 40위, 지금 모의 규칙)", base)]
    for i, (k, nm) in enumerate(CONDS, 1):
        V.append((f"{i}. 기준선 ∩ {nm} (가) 그날 매수 전 한 번이라도", [t for t in base if t[k + "_ga"]]))
        V.append((f"{i}. 기준선 ∩ {nm} (나) 매수 직전 10분 안", [t for t in base if t[k + "_na"]]))
    for k, nm in CONDS:
        a4 = [t for t in T if t["ver"] == f"4a_{k}"]
        b4 = [t for t in T if t["ver"] == f"4b_{k}"]
        V.append((f"4a. {nm} 걸린 종목 → H4 (기준 캔들 날 있는 종목)", a4))
        V.append((f"4b. {nm} 걸린 종목 → H4 (4a + 기준일 없으면 오늘 포착 전 최대 봉)", a4 + b4))
        V.append((f"4b'. 그중 기준일 없는 종목만", b4))
    for k, nm in CONDS:
        a4 = [t for t in T if t["ver"] == f"4a_{k}"]
        b4 = [t for t in T if t["ver"] == f"4b_{k}"]
        s5 = {s: [t for t in T if t["ver"] == f"5{s}_{k}"] for s in "ABC"}
        V.append((f"5A. {nm} 범위 · 햄버거 압도 돌파", s5["A"]))
        V.append((f"5B. {nm} 범위 · 시간 매물 소화 돌파", s5["B"]))
        V.append((f"5C. {nm} 범위 · 큰 봉 뒤 쌍바닥", s5["C"]))
        V.append((f"5D. {nm} 4b + 피하는 자리 거르기 (첫날 윗꼬리·햄버거 직후 윗꼬리 음봉)",
                  [t for t in a4 + b4 if not t["first_wick"] and not t["burger_wick"]]))
        V.append((f"5E. {nm} 5A + 피하는 자리 거르기 (+추격 금지 +1%)",
                  [t for t in s5["A"] if not t["chase"] and not t["burger_wick"]]))
        V.append((f"5F. {nm} 5B + 피하는 자리 거르기 (+추격 금지·오후 끼 다 쓴 돌파)",
                  [t for t in s5["B"] if not t["chase"] and not t["late_kki"] and not t["first_wick"]]))
        V.append((f"5G. {nm} 4b·5A·5B·5C 합침 (종목·날당 첫 매수 한 번, 거르기 넣음)",
                  dedup([t for t in a4 + b4 if not t["first_wick"] and not t["burger_wick"]]
                        + [t for t in s5["A"] if not t["chase"] and not t["burger_wick"]]
                        + [t for t in s5["B"] if not t["chase"] and not t["late_kki"] and not t["first_wick"]] + s5["C"])))
    return V


def report(R: dict) -> str:
    days = R["days"]
    split = days[len(days) // 2]
    V = versions(R)
    VA = [(nm, [x for x in (as_trade(t, "a") for t in xs) if x]) for nm, xs in V]
    VB = [(nm, [x for x in (as_trade(t, "b") for t in xs) if x]) for nm, xs in V]
    L = [f"# 햄버거 × 조건검색식 백테스트 결과 (자동 생성 {date.today()})", "",
         f"- 기간 {days[0]} ~ {days[-1]} ({len(days)}거래일), 앞/뒤 나눔 {split}, 비용 0.25%, 합계 %p = 건당 100만 원이면 만 원",
         "- 기록: " + ", ".join(f"{k} {v}" for k, v in sorted(R["notes"].items())),
         "- 정의값: " + ", ".join(f"{k}={v}" for k, v in DEF.items()), ""]
    for title, VV in (("매도 A (햄버거 규칙: +2% / 전저점 / 15:19)", VA), ("매도 B (+2% / 전저점 / 다음 날 09:00)", VB)):
        L.append(f"## {title} — 모든 날")
        L.append(md_table(HEAD, [row(nm, stats([(t["d"], t["r"]) for t in xs], split)) for nm, xs in VV]))
        L.append(f"\n## {title} — 지금 모의 규칙대로 강한 하락장(D)·약세장 보통 날(N-) 은 안 삼 (U·N+ 날만)")
        L.append(md_table(HEAD, [row(nm, stats([(t["d"], t["r"]) for t in xs if t["regime"] in ("U", "N+")], split)) for nm, xs in VV]))
        L.append("")
    L.append("## 시장 분위기별 건수 · 건당 (매도 A) — U 강한 상승 / N+ 보통·상승 추세 / N- 보통·약세장 / D 강한 하락")
    rows = []
    for nm, xs in VA:
        cells = [nm]
        for rg in ("U", "N+", "N-", "D", None):
            ys = [t["r"] for t in xs if t["regime"] == rg]
            cells.append(f"{len(ys)}건 {pct(np.mean(ys)) if ys else '-'}")
        rows.append(cells)
    L.append(md_table(["버전", "U", "N+", "N-", "D", "판정 없음"], rows))
    L.append("\n## 월별 합계 (%p, 매도 A)")
    months = sorted({f"{d:%y-%m}" for d in days})
    rows = []
    for nm, xs in VA:
        m = defaultdict(float)
        for t in xs:
            m[f"{t['d']:%y-%m}"] += t["r"]
        rows.append([nm] + [pp(m[k]) if k in m else "" for k in months])
    L.append(md_table(["버전"] + months, rows))
    L.append("\n## 호가 2칸 미끄러짐 (사고팔 때 각각 2칸 불리, 매도 A)")
    L.append(md_table(HEAD, [row(nm, stats([(t["d"], t["slip"]) for t in xs], split)) for nm, xs in VA]))
    for title, VV in (("매도 A", VA), ("매도 B", VB)):
        L.append(f"\n## 계좌 시뮬 ({title}) — 10만 원: 종목당 3만 · 100만 원: 종목당 10만, 정수 주, 현금 안에서, 복리 아님")
        rows = []
        for nm, xs in VV:
            a = account(xs, days, split, 100_000, 30_000)
            b = account(xs, days, split, 1_000_000, 100_000)
            rows.append([nm, f"{a['final']:,.0f}", f"{a['final'] / 1e5 - 1:+.1%}", f"{a['mdd']:.1%}", f"{a['front']:+.1%} / {a['back']:+.1%}",
                         f"{a['n']} (못 삼 {a['skip']})", f"{b['final']:,.0f}", f"{b['final'] / 1e6 - 1:+.1%}", f"{b['mdd']:.1%}",
                         f"{b['front']:+.1%} / {b['back']:+.1%}", f"{b['n']} (못 삼 {b['skip']})"])
        L.append(md_table(["버전", "10만 끝", "수익률", "낙폭", "앞/뒤", "산 건수", "100만 끝", "수익률", "낙폭", "앞/뒤", "산 건수"], rows))
    T = R["T"]
    L.append("\n## 매도 이유 (매도 A / 매도 B)")
    rows = []
    for nm, xs in V:
        if not xs:
            continue
        ra = ", ".join(f"{r} {sum(t['a_reason'] == r for t in xs)}" for r in ("익절", "손절", "15:19"))
        rb = ", ".join(f"{r} {sum(t['b_reason'] == r for t in xs)}" for r in ("익절", "손절", "다음 날 09:00"))
        rows.append([nm, ra, rb])
    L.append(md_table(["버전", "매도 A", "매도 B"], rows))
    base = [t for t in T if t["ver"] == "base"]
    L.append(f"\n- 기준선 {len(base)}건 중 전일 종가(일봉)와 1분봉 전일 정규장 종가가 3% 넘게 다른 건 {sum(t['mismatch'] for t in base)}건")
    L.append("\n## 옛 1년 검증(2026-10-23, burger_year.py) 구간과 기준선 비교 (매도 A)")
    per = [("25-11~26-02", date(2025, 11, 1), date(2026, 2, 28)), ("26-03~05", date(2026, 3, 1), date(2026, 5, 31)),
           ("26-06~08", date(2026, 6, 1), date(2026, 8, 31)), ("26-09~10-22", date(2026, 9, 1), date(2026, 10, 22)),
           ("10-23~11-20 (모의 기간)", date(2026, 10, 23), date(2026, 11, 20))]
    rows = []
    for nm, a, b in per:
        ys = [t["a_ret"] for t in base if a <= t["d"] <= b]
        rows.append([nm, str(len(ys)), pct(np.mean(ys)) if ys else "-", f"{np.mean(np.array(ys) > 0):.0%}" if ys else "-"])
    L.append(md_table(["구간", "건수", "건당", "승률"], rows))
    L.append("\n## 기준선 매매 목록")
    rows = [[f"{t['d']}", f"{_NAMES.get(t['code'], t['code'])}({t['code']})", t["regime"] or "-", f"{t['entry_ts']:%H:%M}",
             f"{t['pos'] * 100:+.1f}%", t["a_reason"], pct(t["a_ret"]), pct(t["b_ret"]),
             "".join(nm[0] if t[k + "_ga"] else "·" for k, nm in CONDS)] for t in base]
    L.append(md_table(["날짜", "종목", "분위기", "매수", "햄버거 위치", "매도 A", "손익 A", "손익 B", "걸림(햄1·햄2·불)"], rows))
    return "\n".join(L)


_NAMES: dict = {}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--regime", action="store_true", help="시장 분위기 특징값도 다시 계산")
    ap.add_argument("--days", type=int, default=0, help="시험용: 앞에서 N 거래일만")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    src = Src()
    _NAMES.update(src.names)
    feat = regime_feat(src, a.regime)
    pk = os.path.join(OUT, "trades.pkl")
    if os.path.exists(pk) and not a.rebuild:
        R = pickle.load(open(pk, "rb"))
    else:
        R = build(src, feat, a.days)
        if not a.days:
            pickle.dump(R, open(pk, "wb"))
    md = report(R)
    with open(os.path.join(OUT, "results.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(OUT, "trades.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        keys = sorted({k for t in R["T"] for k in t})
        w.writerow(keys + ["name"])
        for t in R["T"]:
            w.writerow([t.get(k) for k in keys] + [_NAMES.get(t["code"], "")])
    from kiwoom_trading.backtest.condition_filter import md_to_html
    os.makedirs(os.path.join(DATA, "reports"), exist_ok=True)
    hp = os.path.join(DATA, "reports", f"hamburger_condition_bt_{date.today():%Y%m%d}.html")
    with open(hp, "w", encoding="utf-8") as f:
        f.write(md_to_html(md, "햄버거 × 조건검색식 백테스트"))
    print(f"결과 {os.path.join(OUT, 'results.md')}\nHTML {hp}")


if __name__ == "__main__":
    main()
