"""🪃 급락 반등 — 불장단타왕 '이번에 미장 국장 87% 승률로 발라먹은 방법'(2026-11-06 영상) 규칙 (2026-11-12 사용자 '1번', 모의만).

영상 요지: 잘 가던 종목이 짧은 시간에 크게 빠져 1분봉 VWMA100 아래로 내려왔을 때, 투매(평소 바닥보다 큰 거래대금)가 나오고
다음 봉이 그 저가를 안 깨면 반 사고, VWMA100 을 되찾거나 반등 고점 돌파가 확인되면 나머지 반을 산다.
아래 숫자(−4%·30봉, 바닥 기준 25%, ±0.3%, 3봉, 30% 익절, −0.5% 손절)는 영상 설명을 사용자와 정한 값 — 검증 전 가정.

선별 (매분, 09:10 시장 판정 뒤·강한 하락장 날 아님, 새 매수 09:10~14:30):
  ① 지금 주식(ETF·ETN·우선주·스팩 뺌) 중 장중 누적 대금 30위 안, 시총(상장주식수 × 지금 가격) 2,000억↑, 상장 20거래일 넘음
  ② 전날 외인·기관 둘 다 순매도면 뺌 (investor_daily)
  ③ 프로그램 순매수(program_intraday, 10분 스냅샷) 최근 두 번이 줄지 않음 (마지막 ≥ 그 앞) — 스냅샷이 두 번 안 되면 통과
  ④ 테마 형성: 그 종목이 속한 네이버 테마 중 하나에서 지금 대금 100위 안 종목이 2개↑ (그 종목 포함)
  ⑤ 🌀 무너지는 국면은 paper._skip_reason 이 뺌
급락 조건 (정규장 1분봉, 다 끝난 봉만): 오늘 최근 30봉 최고가 대비 그 봉 저가 −4%↑ (저가 ≤ 30봉 고가 / 1.04) 이고 종가 < 1분봉 VWMA100
  (VWMA100 = Σ종가×거래량 / Σ거래량, 최근 100봉 — 전 거래일 정규장 봉부터 이어서). 급락이 시작된 봉 = 그 30봉 고가 봉.
바닥 거래대금 기준 (종목별, 스캐너 시작 때 한 번 — 전날 대금 상위 200, data/minute_history.duckdb 지난 20거래일, 09:00~09:09·15:20↑ 봉 뺌):
  앞뒤 10봉(모두 21봉) 중 가장 낮은 저가인 봉 & 다음 30봉 안에 그 저가 +2%↑ 반등 → 그 봉 대금(종가 × 거래량) 들의 25% 분위수. 5개 안 되면 A 신호 없음.
신호 (급락 조건이 난 봉부터, 봉이 끝난 뒤 첫 확인에 시장가 = 다음 봉 시가 부근):
  A: 대금 > 바닥 기준인 봉이 나오고 다음 봉 저가가 그 봉 저가를 안 깨면 → 1/2 매수
  C: 종가가 VWMA100 위로 올라선 봉 뒤 3봉 연속 종가 ≥ VWMA100 → 보유 없으면 전부, 1/2 보유면 나머지 1/2
  D: 급락 저점 뒤 반등 고점이 VWMA100 에 막힘 (고가가 VWMA100 ±0.3% 안 & 종가 < VWMA100) → (반등 고점 + 급락 저점)/2 까지 되밀리면 1/2 매수(D1),
     그 뒤 종가가 반등 고점을 넘으면 나머지 1/2 (D2)
  급락 저점은 첫 매수 전까지 새 저가로 계속 바뀌고(그러면 D 의 반등 고점도 다시 찾음), 첫 매수 뒤엔 고정.
  첫 매수 전 종가가 급락 시작 고점을 넘거나 90봉이 지나면 그 급락은 끝난 것으로 보고 새 급락을 기다림. 한 종목 하루 한 번(모의 거래 하나),
  산 뒤 손절선에 닿으면 그날 그 종목 신호는 더 내지 않음.
매도 (paper 모드 'CRASH'): 급락 저점 × (1 − 0.5%) 닿으면 손절 · 급락 시작 전 20봉 최고가(첫 매물대)에 닿으면 30% 익절(1주면 전부)
  · 남은 물량은 30% 익절 뒤 1분봉 5개 연속 VWAP 아래 마감(매수 10분 뒤 봉부터, real.vwap_break) 이면 매도 · 15:15 전부 정리 (밤 넘기지 않음).
  익절선이 매수가 +0.5% 안이면 급락 시작 고점으로, 그것도 안 되면 익절 없이 VWAP 규칙을 처음부터 씀.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, Optional

import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.strategies.kell_squeeze.live import is_etf, regime_gate

KIND = "급락 반등"
DROP, DROP_BARS = 0.04, 30          # 최근 30봉 고가 대비 −4%↑
VWMA_N = 100                        # 1분봉 VWMA100
LOW_HALF = 10                       # 바닥 봉: 앞뒤 10봉(21봉) 중 가장 낮은 저가
REB_BARS, REB_PCT = 30, 0.02        # 바닥 봉: 다음 30봉 안 +2%↑ 반등
BASE_Q, BASE_MIN, BASE_DAYS = 0.25, 5, 20   # 바닥 봉 대금 25% 분위수, 5개↑, 지난 20거래일
BASE_FROM, BASE_TO = time(9, 10), time(15, 20)   # 바닥 기준에서 09:00~09:09·15:20↑ 봉 뺌
SWING_BARS = 20                     # 30% 익절선: 급락 시작 전 20봉 최고가
CAP_BAND = 0.003                    # D: 반등 고가가 VWMA100 ±0.3% 안
C_HOLD = 3                          # C: VWMA100 위 마감 뒤 3봉 연속 아래로 안 내려감
STOP_GAP = 0.005                    # 손절: 급락 저점 × (1 − 0.5%)
TP_FRAC = 0.3                       # 첫 매물대에서 30% 익절
TP_MIN_GAP = 0.005                  # 익절선이 매수가 +0.5% 안이면 급락 시작 고점으로
EPISODE_MAX = 90                    # 첫 매수 전 급락이 이어지는 최대 봉 수
FIRST_FRAC = 0.5                    # 첫 매수 = 종목당 금액의 1/2 (C 로 처음 사면 전부)
BUY_START, BUY_END = time(9, 10), time(14, 30)
EXIT_AT = time(15, 15)              # 15:15 전부 정리
OPEN, CLOSE = time(9, 0), time(15, 30)
MAX_VALUE_RANK = 30                 # 선별 ① 주식 중 장중 대금 30위 안
MIN_MCAP = 2e11                     # 선별 ① 시총 2,000억↑
THEME_TOP, THEME_MIN = 100, 2       # 선별 ④ 같은 테마 안 대금 100위 안 2종목↑ (그 종목 포함)
UNIVERSE = 200                      # 바닥 기준·전날 봉을 미리 읽는 종목: 전날 대금 상위 200
API_BUDGET = 15                     # 한 번 확인에 키움 1분봉 조회 최대 15번 (보유 종목 먼저, 나머지는 오래 안 본 순)
STALE = timedelta(minutes=3)        # 봉이 끝나고 3분 안 신호만 (재시작·조회 순번으로 늦게 본 옛 신호는 안 삼)
FIRST_LEGS, SECOND_LEGS = ("A", "C", "D1"), ("C", "D2")
HALF_TAG, FULL_TAG, ADD_TAG, TP_TAG = "🪃 1차 절반", "🪃 한 번에 전부", "🪃 추가", "익절선 "
MINUTE_DB = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
NAVER_DB = os.path.join(PROJECT_ROOT, "data", "naver_groups.duckdb")
COLS = ["ts", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------- 규칙 (순수 함수)
def regular(bars) -> pd.DataFrame:
    """1분봉(dict 목록 또는 DataFrame) → 정규장 09:00~15:29 봉만, 시간순 (ts = 봉 시작)."""
    df = pd.DataFrame(bars)
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["ts"] = pd.to_datetime(df["ts"])
    t = df["ts"].dt.time
    df = df[(t >= OPEN) & (t < CLOSE)]
    return df[COLS].sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


def vwma(close: np.ndarray, vol: np.ndarray, n: int = VWMA_N) -> np.ndarray:
    """봉마다 최근 n봉 Σ종가×거래량 / Σ거래량 (n봉 안 되면 nan, 거래량 합 0 이면 nan)."""
    pv = pd.Series(close * vol).rolling(n).sum()
    vs = pd.Series(vol).rolling(n).sum()
    return (pv / vs.where(vs > 0)).to_numpy()


def baseline_from(bars: pd.DataFrame) -> tuple[Optional[float], int]:
    """한 종목 지난 거래일들 정규장 1분봉 → (바닥 대금 기준 = 25% 분위수 | None, 바닥 봉 수). 날마다 따로 봄."""
    vals: list[float] = []
    if bars.empty:
        return None, 0
    b = bars.copy()
    b["ts"] = pd.to_datetime(b["ts"])
    for _, g in b.sort_values("ts").groupby(b["ts"].dt.date, sort=True):
        lo, hi = g["low"].to_numpy(float), g["high"].to_numpy(float)
        lmin = pd.Series(lo).rolling(2 * LOW_HALF + 1, center=True, min_periods=1).min().to_numpy()
        fut = pd.Series(hi[::-1]).rolling(REB_BARS, min_periods=1).max().to_numpy()[::-1]     # fut[i] = max(hi[i..i+29])
        fut = np.append(fut[1:], np.nan)                                                          # → max(hi[i+1..i+30])
        t = g["ts"].dt.time.to_numpy()
        ok = (lo == lmin) & (fut >= lo * (1 + REB_PCT)) & (t >= BASE_FROM) & (t < BASE_TO) & (g["volume"].to_numpy() > 0)
        vals.extend((g["close"].to_numpy(float) * g["volume"].to_numpy(float))[ok])
    if len(vals) < BASE_MIN:
        return None, len(vals)
    return float(np.quantile(vals, BASE_Q)), len(vals)


@dataclass
class Event:
    leg: str                 # 'A' | 'C' | 'D1' | 'D2'
    i: int                   # 신호 봉 번호 (full 안)
    ts: datetime             # 신호 봉이 끝난 시각 (= 봉 시작 + 1분) — 이 뒤 첫 확인에 시장가
    price: float             # 신호 봉 종가
    stop: float              # 급락 저점 × (1 − 0.5%)
    tp: Optional[float]      # 30% 익절선
    low: float               # 급락 저점
    peak: float              # 급락 시작 고점 (최근 30봉 고가)
    vwma: float
    detail: str


def _tp(swing: float, peak: float, price: float) -> Optional[float]:
    for x in (swing, peak):
        if x and x > price * (1 + TP_MIN_GAP):
            return float(x)
    return None


def scan(full: pd.DataFrame, n_prev: int, baseline: Optional[float],
         start: time = BUY_START, end: time = BUY_END) -> list[Event]:
    """full = 전 거래일 정규장 봉(n_prev 개) + 오늘 정규장 다 끝난 봉 (시간순). 오늘 봉을 처음부터 다시 따라가며 신호를 모두 돌려줌
    (매번 처음부터 다시 계산하므로 재시작해도 같은 결과). 신호 봉이 끝난 시각이 start~end 밖이면 신호를 내지 않음."""
    g = full.reset_index(drop=True)
    ts = [x.to_pydatetime() for x in pd.to_datetime(g["ts"])]
    h, l, c, v = (g[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    vw = vwma(c, v)
    val = c * v
    out: list[Event] = []
    ep: Optional[dict] = None
    entered: Optional[str] = None            # None → 아직 안 삼, 'half' → 1/2, 'full' → 전부
    one = timedelta(minutes=1)

    def fire(leg: str, i: int, detail: str) -> None:
        out.append(Event(leg, i, ts[i] + one, float(c[i]), ep["low"] * (1 - STOP_GAP), _tp(ep["swing"], ep["peak"], float(c[i])),
                         float(ep["low"]), float(ep["peak"]), float(vw[i]), detail))

    for i in range(n_prev, len(g)):
        ok = start <= (ts[i] + one).time() <= end
        if ep is not None and entered is None and (c[i] > ep["peak"] or i - ep["trig"] > EPISODE_MAX):
            ep = None                                     # 급락이 끝남 (시작 고점 회복 또는 90봉 지남) → 새 급락 기다림
        if ep is None:
            if entered is not None or np.isnan(vw[i]) or ts[i].time() > end:
                continue
            lo = max(n_prev, i - DROP_BARS + 1)
            k = lo + int(np.argmax(h[lo:i + 1]))
            if not (l[i] <= h[k] / (1 + DROP) and c[i] < vw[i]):
                continue
            s0 = max(0, k - SWING_BARS)
            ep = dict(trig=i, peak=float(h[k]), peak_i=k, swing=float(h[s0:k].max()) if k > s0 else float(h[k]),
                      low=float(l[i]), low_i=i, a=None, c=None, cn=0, reb=None, reb_i=None, mid=None, d1=False, d2=False)
        elif entered is None and l[i] < ep["low"]:
            ep["low"], ep["low_i"] = float(l[i]), i       # 새 저점 → D 의 반등 고점은 다시 찾음
            ep["reb"] = ep["reb_i"] = ep["mid"] = None
        elif entered is not None and l[i] <= ep["low"] * (1 - STOP_GAP):
            break                                         # 산 뒤 손절선 닿음 → 그날 이 종목은 끝 (하루 한 번)
        # A: 바닥 기준보다 큰 대금 봉 → 다음 봉이 그 저가를 안 깨면 1/2
        if entered is None:
            a = ep["a"]
            if a is not None and i == a + 1:
                ep["a"] = None
                if l[i] >= l[a] and ok:
                    fire("A", i, f"{ts[a]:%H:%M} 봉 대금 {val[a] / 1e8:,.1f}억 > 바닥 기준 {baseline / 1e8:,.1f}억, 다음 봉 저가 {l[i]:,.0f} ≥ {l[a]:,.0f}")
                    entered = "half"
            if entered is None and baseline and val[i] > baseline:
                ep["a"] = i
        # C: VWMA100 위 마감 뒤 3봉 연속 안 내려감 → 전부 또는 나머지 1/2
        if i > ep["trig"] and entered != "full":
            if ep["c"] is None:
                if c[i] > vw[i]:
                    ep["c"], ep["cn"] = i, 0
            elif c[i] >= vw[i]:
                ep["cn"] += 1
                if ep["cn"] >= C_HOLD:
                    j = ep["c"]
                    ep["c"] = None
                    if ok:
                        fire("C", i, f"{ts[j]:%H:%M} 봉 종가 {c[j]:,.0f} > VWMA100 {vw[j]:,.0f} 뒤 {C_HOLD}봉 연속 VWMA100 위 마감")
                        entered = "full"
            else:
                ep["c"] = None
        # D: 반등 고점이 VWMA100 에 막힘 → 중간값까지 되밀리면 1/2(D1), 반등 고점 넘으면 나머지 1/2(D2)
        if entered is None and ep["reb"] is None:
            if i > ep["low_i"] and not np.isnan(vw[i]) and abs(h[i] / vw[i] - 1) <= CAP_BAND and c[i] < vw[i]:
                ep["reb"], ep["reb_i"] = float(h[ep["low_i"] + 1:i + 1].max()), i
                ep["mid"] = (ep["reb"] + ep["low"]) / 2
        elif entered is None and ep["reb"] is not None and not ep["d1"]:
            if l[i] <= ep["mid"] and ok:
                fire("D1", i, f"반등 고점 {ep['reb']:,.0f}({ts[ep['reb_i']]:%H:%M}) VWMA100 에 막힌 뒤 중간값 {ep['mid']:,.0f} 까지 되밀림")
                ep["d1"], entered = True, "half"
        elif entered == "half" and ep["d1"] and not ep["d2"]:
            if c[i] > ep["reb"] and ok:
                fire("D2", i, f"종가 {c[i]:,.0f} > 반등 고점 {ep['reb']:,.0f}")
                ep["d2"], entered = True, "full"
    return out


def tp_of(note: str) -> Optional[float]:
    """paper_trades.note 의 '익절선 12,345' → 12345.0 (재시작해도 남도록 note 에 적어 둠)."""
    import re
    m = re.search(TP_TAG + r"([\d,]+)", note or "")
    return float(m.group(1).replace(",", "")) if m else None


def leg_of(source: str) -> str:
    """신호 source '급락 반등 A' → 'A'."""
    return (source or "").rsplit(" ", 1)[-1]


# ---------------------------------------------------------------- 자료
def load_prev_bars(codes: list[str], day: date, minute_db: str = MINUTE_DB) -> dict[str, pd.DataFrame]:
    """codes 의 day 하루 정규장 1분봉 (통합 AL) — VWMA100 을 전날부터 이어 계산."""
    if not codes:
        return {}
    conn = duckdb.connect(minute_db, read_only=True)
    try:
        df = conn.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv
                              WHERE exchange = 'AL' AND code IN ({','.join('?' * len(codes))}) AND ts >= ? AND ts < ?
                                AND CAST(ts AS TIME) >= TIME '09:00' AND CAST(ts AS TIME) < TIME '15:30' ORDER BY code, ts""",
                          [*codes, day, day + timedelta(days=1)]).df()
    finally:
        conn.close()
    return {c: g[COLS].reset_index(drop=True) for c, g in df.groupby("code", sort=False)}


def load_baselines(codes: list[str], days: list[date], minute_db: str = MINUTE_DB) -> dict[str, tuple[Optional[float], int]]:
    """지역 1분봉 DB 로 종목별 바닥 대금 기준 (baseline_from 과 같은 계산을 DuckDB 창 함수로 한 번에)."""
    if not codes or not days:
        return {}
    conn = duckdb.connect(minute_db, read_only=True)
    try:
        rows = conn.execute(f"""
            WITH b AS (SELECT code, ts, CAST(ts AS DATE) AS d, high, low, close, volume FROM minute_ohlcv
                       WHERE exchange = 'AL' AND code IN ({','.join('?' * len(codes))}) AND ts >= ? AND ts < ?
                         AND CAST(ts AS TIME) >= TIME '09:00' AND CAST(ts AS TIME) < TIME '15:30'),
                 w AS (SELECT *, min(low) OVER (PARTITION BY code, d ORDER BY ts ROWS BETWEEN {LOW_HALF} PRECEDING AND {LOW_HALF} FOLLOWING) AS lmin,
                              max(high) OVER (PARTITION BY code, d ORDER BY ts ROWS BETWEEN 1 FOLLOWING AND {REB_BARS} FOLLOWING) AS fut
                       FROM b)
            SELECT code, count(*) AS n, quantile_cont(close * volume, {BASE_Q}) AS q FROM w
            WHERE low = lmin AND fut >= low * {1 + REB_PCT} AND CAST(ts AS TIME) >= TIME '{BASE_FROM:%H:%M}'
              AND CAST(ts AS TIME) < TIME '{BASE_TO:%H:%M}' AND volume > 0
            GROUP BY code""", [*codes, days[0], days[-1] + timedelta(days=1)]).fetchall()
    finally:
        conn.close()
    return {c: ((float(q) if n >= BASE_MIN else None), int(n)) for c, n, q in rows}


class CrashContext:
    """스캐너 시작 때 한 번: 주식 목록·상장주식수·전날 수급·신규 상장·네이버 테마 + 전날 대금 상위 200 의 바닥 기준·전날 1분봉."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH, minute_db: str = MINUTE_DB, naver_db: str = NAVER_DB) -> None:
        self.day, self.minute_db = day, minute_db
        conn = duckdb.connect(db_path, read_only=True)
        try:
            rows = conn.execute("SELECT code, name, listed_shares FROM stocks WHERE NOT coalesce(delisted, false)").fetchall()
            fday = conn.execute("SELECT max(date) FROM investor_daily WHERE date < ?", [day]).fetchone()[0]
            self.flow = {c: (f, i) for c, f, i in conn.execute("SELECT code, foreign_, institution FROM investor_daily WHERE date = ?", [fday]).fetchall()}
            self.days = [d for (d,) in conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code = '005930' AND date < ? ORDER BY date DESC LIMIT ?",
                                                     [day, BASE_DAYS]).fetchall()][::-1]
            prev = self.days[-1] if self.days else None
            top = [c for (c,) in conn.execute("""SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL
                                                 ORDER BY d.value DESC LIMIT ?""", [prev, UNIVERSE * 2]).fetchall()] if prev else []
        finally:
            conn.close()
        self.names = {c: n for c, n, _ in rows}
        self.shares = {c: int(s or 0) for c, _, s in rows}
        self.prev_day = self.days[-1] if self.days else None
        from kiwoom_trading.execution import strict_select
        self.listed = strict_select.load_context(day, db_path).listed     # 상장 20거래일 안
        try:
            from kiwoom_trading.common.leader import load_themes
            self.themes = load_themes(naver_db)
        except Exception:
            logging.exception("급락 반등: 네이버 테마 읽기 실패 — 테마 형성 조건을 못 봐 오늘은 안 삼")
            self.themes = {}
        self.universe = [c for c in top if _plain(c, self.names.get(c, "")) and not is_etf(self.names.get(c, ""))][:UNIVERSE]
        self.baseline: dict[str, tuple[Optional[float], int]] = {}
        self.prev_bars: dict[str, pd.DataFrame] = {}
        try:
            self.baseline = load_baselines(self.universe, self.days, minute_db)
            self.prev_bars = load_prev_bars(self.universe, self.prev_day, minute_db) if self.prev_day else {}
        except Exception:
            logging.exception("급락 반등: 지역 1분봉 DB 읽기 실패 — 바닥 기준 없이(A 신호 없음) 전날 봉은 키움 조회로")
        ok = sum(1 for b, _ in self.baseline.values() if b)
        logging.info("급락 반등 준비: 전날(%s) 대금 상위 %s종목 중 바닥 기준 있음 %s · 전날 1분봉 %s종목 · 수급 %s종목(%s) · 테마 소속 %s · 신규 상장 %s 뺌",
                     self.prev_day, len(self.universe), ok, len(self.prev_bars), len(self.flow), fday, len(self.themes), len(self.listed))

    def base(self, code: str) -> Optional[float]:
        return (self.baseline.get(code) or (None, 0))[0]

    def select(self, value_top: list, program: dict[str, list]) -> tuple[list, dict[str, int]]:
        """value_top(RankItem) → 선별 ①~④ 통과 종목 (대금 순)과 탈락 이유별 수."""
        stocks = [x for x in sorted(value_top, key=lambda x: -(x.trade_value or 0))
                  if x.code in self.names and not is_etf(x.name) and _plain(x.code, x.name)]
        top100 = {x.code for x in stocks[:THEME_TOP]}
        count: dict[str, int] = {}
        for c in top100:
            for th in self.themes.get(c, ()):
                count[th] = count.get(th, 0) + 1
        out, drop = [], {}
        for x in stocks[:MAX_VALUE_RANK]:
            why = None
            if (self.shares.get(x.code, 0) * (x.price or 0)) < MIN_MCAP:
                why = "시총 2천억 미만"
            elif x.code in self.listed:
                why = "신규 상장"
            else:
                f, i = self.flow.get(x.code, (None, None))
                p = program.get(x.code) or []
                if f is not None and i is not None and f < 0 and i < 0:
                    why = "전날 외인·기관 둘 다 순매도"
                elif len(p) >= 2 and p[0] < p[1]:
                    why = "프로그램 순매수 줄어듦"
                elif not any(count.get(th, 0) >= THEME_MIN for th in self.themes.get(x.code, ())):
                    why = "테마 형성 없음"
            if why:
                drop[why] = drop.get(why, 0) + 1
            else:
                out.append(x)
        return out, drop

    def theme_text(self, code: str, value_top: list) -> str:
        top = {x.code for x in sorted(value_top, key=lambda x: -(x.trade_value or 0))[:THEME_TOP]}
        best = max(((th, sum(1 for c in top if th in self.themes.get(c, ()))) for th in self.themes.get(code, ())), key=lambda t: t[1], default=("", 0))
        return f"{best[0]} 대금 100위 안 {best[1]}종목" if best[0] else ""


def _plain(code: str, name: str) -> bool:
    from kiwoom_trading.strategies.hong_limitup.live import is_plain_stock
    return is_plain_stock(code, name)


def load_program(conn, day: date, codes: list[str]) -> dict[str, list]:
    """program_intraday 최근 두 스냅샷의 순매수 [마지막, 그 앞] (장중 스캐너 DB 연결로)."""
    if conn is None or not codes:
        return {}
    rows = conn.execute(f"""SELECT code, net_amount FROM (
                                SELECT code, net_amount, ts, row_number() OVER (PARTITION BY code ORDER BY ts DESC) AS rn
                                FROM program_intraday WHERE date = ? AND code IN ({','.join('?' * len(codes))}))
                            WHERE rn <= 2 ORDER BY code, rn""", [day, *codes]).fetchall()
    out: dict[str, list] = {}
    for c, net in rows:
        out.setdefault(c, []).append(net or 0)
    return out


# ---------------------------------------------------------------- 감시
class CrashWatcher:
    """매분: 보유 중인 🪃 종목(나머지 1/2 판정) + 선별 통과 종목의 오늘 통합(AL) 1분봉 → scan → 방금 끝난 봉의 신호만 모의 매수 신호로.
    held() = {코드: 'half' | 'full' | 'closed'} — 오늘 🪃 로 산 종목 (paper 가 넣어 줌)."""

    def __init__(self, client, ctx: CrashContext, store=None, regime=None, held: Optional[Callable[[], dict]] = None,
                 done: Iterable = (), budget: int = API_BUDGET) -> None:
        self.client, self.ctx, self.store, self.regime = client, ctx, store, regime
        self.held = held or (lambda: {})
        self.done = set(done)                      # (코드, 신호 시각) — 같은 신호 한 번
        self.cache: dict = {}                      # run_once 가 매분 넣어 주는 공유 캐시 — 키 (코드, 'AL')
        self.seen: dict[str, datetime] = {}        # 코드 → 마지막으로 오늘 1분봉을 받은 때 (조회 순번)
        self.budget = budget
        self.day = ctx.day

    def _fetch(self, code: str, day: date) -> pd.DataFrame:
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        return regular(fetch_minute_bars(self.client, code, day, "AL"))

    def _today(self, code: str) -> Optional[pd.DataFrame]:
        key = (code, "AL")
        if key not in self.cache:
            self.cache[key] = self._fetch(code, self.day)
        return self.cache[key]

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if now.date() != self.day or not (BUY_START <= now.time() <= (datetime.combine(self.day, BUY_END) + timedelta(minutes=1)).time()):
            return []
        gate = regime_gate(self.regime, now)
        if gate:
            return []
        held = self.held()
        half = [c for c, s in held.items() if s == "half"]
        try:
            program = load_program(getattr(self.store, "conn", None), self.day, [x.code for x in value_top])
        except Exception:
            logging.exception("급락 반등: 프로그램 매매 읽기 실패 — 프로그램 조건 없이 봄")
            program = {}
        picks, drop = self.ctx.select(value_top, program)
        picks = [x for x in picks if x.code not in held]
        names = {x.code: x.name for x in value_top}
        order = half + sorted((x.code for x in picks), key=lambda c: self.seen.get(c, datetime.min))   # 보유 먼저, 나머지는 오래 안 본 순
        naive = now.replace(tzinfo=None, second=0, microsecond=0)
        budget, out, looked = self.budget, [], 0
        for code in order:
            cached = (code, "AL") in self.cache
            if not cached and budget <= 0:
                continue
            try:
                if not cached:
                    budget -= 1
                today = self._today(code)
                prev = self.ctx.prev_bars.get(code)
                if prev is None and self.ctx.prev_day and budget > 0:
                    budget -= 1
                    prev = self.ctx.prev_bars[code] = self._fetch(code, self.ctx.prev_day)
            except Exception:
                logging.warning("급락 반등 1분봉 조회 실패 %s", code)
                continue
            self.seen[code] = naive
            looked += 1
            today = today[today["ts"] + timedelta(minutes=1) <= naive]           # 다 끝난 봉만
            if today.empty:
                continue
            prev = prev if prev is not None else pd.DataFrame(columns=COLS)
            full = pd.concat([p for p in (prev, today) if len(p)], ignore_index=True)
            base = self.ctx.base(code)
            evs = scan(full, len(prev), base)
            legs = SECOND_LEGS if code in half else FIRST_LEGS
            for e in evs:
                if e.leg not in legs or e.ts < naive - STALE or (code, e.ts) in self.done:
                    continue
                self.done.add((code, e.ts))
                name = names.get(code) or self.ctx.names.get(code, code)
                x = next((r for r in value_top if r.code == code), None)
                theme = self.ctx.theme_text(code, value_top)
                size = {"A": "1/2 매수", "D1": "1/2 매수", "D2": "나머지 1/2", "C": "나머지 1/2" if code in half else "전부 매수"}[e.leg]
                tp = f"{e.tp:,.0f} 에서 30% 익절" if e.tp else "익절선 없음(VWAP 규칙만)"
                reason = (f"🪃 급락 반등 {e.leg} — 최근 30봉 고가 {e.peak:,.0f} → 저점 {e.low:,.0f}({e.low / e.peak - 1:+.1%}), 1분봉 VWMA100 {e.vwma:,.0f} 아래 급락 뒤 "
                          f"{e.detail} → {size} · 손절 {e.stop:,.0f}(저점 −0.5%) · {tp} · 남은 물량 VWAP 5봉 이탈·15:15 정리"
                          + (f" · 바닥 기준 {base / 1e8:,.1f}억" if base else " · 바닥 기준 없음")
                          + (f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억" if x else "") + (f" · 테마 {theme}" if theme else ""))
                out.append((code, name, f"{KIND} {e.leg}", Signal(ts=e.ts, kind=KIND, price=e.price, level=e.tp or 0.0, stop=e.stop, reason=reason)))
        if out or now.minute % 10 == 0:
            logging.info("급락 반등 %s: 선별 통과 %s종목(탈락 %s) · 보유 1/2 %s · 1분봉 본 종목 %s(조회 %s번) → 신호 %s %s", f"{now:%H:%M}", len(picks),
                         ", ".join(f"{k} {n}" for k, n in drop.items()) or "없음", len(half), looked, self.budget - budget, len(out),
                         ", ".join(f"{n} {s.ts:%H:%M}" for _, n, _, s in out))
        return out
