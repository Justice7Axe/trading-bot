"""📈 켈 수축 돌파 — 영상 'Kell 수축 돌파' 규칙 (2026-11-12 사용자 확정, 모의만). 일봉·30분봉 두 가지.

매수 (봉 종가 기준, 신호 봉 = 지금 막 끝난 봉):
  ① 정배열: EMA10 > EMA20 > EMA50 (종가 지수이동평균)
  ② 수축: 직전 10봉 폭 (최고가−최저가)/종가 < 그 앞 10봉 폭, 직전 10봉 평균 거래량 < 그 앞 10봉 평균 (두 구간 모두 신호 봉 뺌)
  ③ 장대양봉: 종가 > 시가, 몸통 ≥ 직전 20봉 평균 몸통 × 1.5
  ④ 거래량 급증: 거래량 > 직전 20봉 평균 + 2 × 표준편차
  ⑤ 돌파: 종가 > 직전 20봉 최고가 (돌파선 hiN — 매수 때 손절선으로 저장)
  하락(정배열 아님) 뒤 정배열이 시작되고 처음 나온 신호는 건너뜀 (기록만), 두 번째부터 삼.
  정배열이 이어지는 동안 판 뒤 다시 나온 신호는 바로 삼. 자료 첫머리부터 계속 정배열이면 시작을 몰라 첫 신호는 건너뜀(보수적으로).
매도 (봉 종가 기준만): 종가 < hiN → 손절, 종가 < EMA20 → 정리.
공통 선별 (사용자 원칙): ① 지금 대금 100억↑ & 주식 중 대금 100위 안 (ETF·ETN·우선주·스팩 뺌) ② 전날 외인·기관 둘 다 순매도면 뺌
  ③ 같은 네이버 테마 안 지금 +4%↑ 종목 2개↑ ④ 09:10 시장 판정 뒤, 강한 하락장 날 안 삼 ⑤ 🌀 무너지는 국면은 paper 가 뺌
  ⑥ 상장 20거래일 안 종목 뺌 (paper 엄격 선정도 한 번 더 막음).
일봉 (KIND_D): 15:15~15:19 한 번 — 전 거래일까지 일봉(9-14 뒤 가격은 daily_regular 정규장 값) + 오늘 KRX 시세(시가·고가·저가·현재가·거래량)를
  오늘 봉으로 붙여 판정 → 모의 매수. 매도는 다음 거래일부터 09:00: 전날 정규장 종가 < hiN 또는 < 일봉 EMA20 (paper 모드 'KELL_D').
30분봉 (KIND_M): 정규장 1분봉(통합 AL)으로 30분봉(09:00·09:30 … 15:00, 마지막 봉 15:00~15:30 동시호가 포함, 봉 이름 = 시작 시각).
  지난 10거래일은 data/minute_history.duckdb, 없는 날과 오늘은 키움 1분봉 조회. 봉이 끝난 뒤 첫 확인(1분 여유)마다 판정 → 모의 매수,
  들고 있는 종목은 같은 때 종가 < hiN 또는 < 30분봉 EMA20 이면 매도 (paper 모드 'KELL_M', 15:19 정리 없이 밤을 넘김).
숫자(10/10 수축, 20봉, 몸통 1.5배, 평균+2σ)는 영상 설명을 사용자와 정한 값 — 검증 전 가정.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, Optional

import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.screener.intraday_signals import Signal

KIND_D = "켈 수축 일봉"
KIND_M = "켈 수축 30분"
SQ = 10                  # 수축: 직전 10봉 vs 그 앞 10봉
N = 20                   # 몸통·거래량 평균, 돌파선(직전 20봉 최고가)
BODY_MULT = 1.5          # 장대양봉: 몸통 ≥ 직전 20봉 평균 몸통 × 1.5
VOL_SIGMA = 2.0          # 거래량 > 직전 20봉 평균 + 2σ
EMA_FAST, EMA_MID, EMA_SLOW = 10, 20, 50
WARMUP = EMA_SLOW        # EMA50 이 자리 잡기 전 봉은 판정하지 않음 (51번째 봉부터)
MIN_BARS = 60            # 판정에 필요한 최소 봉 수
MIN_VALUE = 1e10         # 선별 ① 지금 거래대금 100억↑
MAX_VALUE_RANK = 100     # 선별 ① 주식 중 대금 100위 안
THEME_UP, THEME_MIN = 0.04, 2   # 선별 ③ 같은 테마 안 +4%↑ 2종목↑
MAX_CANDS = 30           # 한 번 판정에 보는 후보 수 (API 부담)
D_START, D_END = time(15, 15), time(15, 19)   # 일봉: 15:15~15:19 한 번
M_OPEN, M_LAST = time(9, 0), 12               # 30분봉: 09:00 부터 13봉(0~12), 12번 = 15:00~15:30
BAR_DELAY = timedelta(minutes=1)              # 봉이 끝나고 1분 뒤 판정 (마지막 1분봉이 들어오도록)
HIST_DAYS = 10           # 30분봉 지난 거래일 (10일 × 13봉 = 130봉)
API_HIST_BUDGET = 20     # 30분봉: 지역 DB 에 없는 지난날 1분봉을 한 번 판정에 최대 20번까지만 조회
REGULAR_DB = os.path.join(PROJECT_ROOT, "data", "daily_regular.duckdb")
MINUTE_DB = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
NAVER_DB = os.path.join(PROJECT_ROOT, "data", "naver_groups.duckdb")
ETF_WORDS = ("KODEX", "TIGER", "KBSTAR", "RISE ", "ACE ", "SOL ", "HANARO", "KOSEF", "ARIRANG", "PLUS ", "ETN", "KIWOOM", "TIMEFOLIO",
             "1Q ", "WON ", "KoAct", "TIME ", "인버스", "레버리지")


# ---------------------------------------------------------------- 규칙 (순수 함수)
def ema(x: pd.Series, n: int) -> pd.Series:
    return x.astype(float).ewm(span=n, adjust=False).mean()


def features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars(open·high·low·close·volume, 오래된 순) → 봉마다 조건 칸. 수축·평균은 모두 신호 봉을 뺀 직전 구간."""
    g = bars.reset_index(drop=True).copy()
    o, h, l, c, v = (g[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    g["e10"], g["e20"], g["e50"] = ema(c, EMA_FAST), ema(c, EMA_MID), ema(c, EMA_SLOW)
    g["aligned"] = (g["e10"] > g["e20"]) & (g["e20"] > g["e50"])
    width = (h.rolling(SQ).max() - l.rolling(SQ).min()) / c       # j-9..j 구간 폭 ÷ 그 구간 끝 종가
    g["w_last"], g["w_prev"] = width.shift(1), width.shift(1 + SQ)
    vol10 = v.rolling(SQ).mean()
    g["v_last"], g["v_prev"] = vol10.shift(1), vol10.shift(1 + SQ)
    g["squeeze"] = (g["w_last"] < g["w_prev"]) & (g["v_last"] < g["v_prev"])
    body = c - o
    g["body_avg"] = body.abs().rolling(N).mean().shift(1)
    g["big"] = (body > 0) & (body >= g["body_avg"] * BODY_MULT)
    g["vol_avg"] = v.rolling(N).mean().shift(1)
    g["vol_sd"] = v.rolling(N).std(ddof=0).shift(1)
    g["spike"] = v > g["vol_avg"] + VOL_SIGMA * g["vol_sd"]
    g["hiN"] = h.rolling(N).max().shift(1)
    g["brk"] = c > g["hiN"]
    g["qualify"] = g["aligned"] & g["squeeze"] & g["big"] & g["spike"] & g["brk"]
    return g


def statuses(g: pd.DataFrame) -> list[Optional[str]]:
    """봉마다 None / 'skip'(하락 뒤 첫 신호) / 'buy'. 정배열 아닌 봉이 나오면 다음 정배열 구간의 첫 신호는 건너뜀."""
    out: list[Optional[str]] = [None] * len(g)
    seen = 0                     # 이번 정배열 구간에서 나온 신호 수 (구간 시작 모르면 0 부터 = 첫 신호 건너뜀)
    for i in range(WARMUP, len(g)):
        if not bool(g.at[i, "aligned"]):
            seen = 0
            continue
        if bool(g.at[i, "qualify"]):
            out[i] = "skip" if seen == 0 else "buy"
            seen += 1
    return out


def evaluate_last(bars: pd.DataFrame) -> tuple[Optional[str], Optional[dict]]:
    """마지막 봉의 판정 ('buy'·'skip'·None)과 숫자. 봉이 MIN_BARS 보다 적으면 (None, None)."""
    if len(bars) < MIN_BARS:
        return None, None
    g = features(bars)
    st = statuses(g)[-1]
    r = g.iloc[-1]
    info = {k: float(r[k]) for k in ("close", "open", "e10", "e20", "e50", "hiN", "w_last", "w_prev", "v_last", "v_prev", "body_avg", "vol_avg", "vol_sd", "volume")}
    info["body_mult"] = (info["close"] - info["open"]) / info["body_avg"] if info["body_avg"] else float("nan")
    info["vol_mult"] = info["volume"] / info["vol_avg"] if info["vol_avg"] else float("nan")
    return st, info


def exit_reason(close: float, hi_n: Optional[float], ema20: float, unit: str) -> Optional[str]:
    """봉 종가로 매도 사유: 돌파선 아래 → 손절 먼저, 그다음 EMA20 아래 → 정리."""
    if hi_n and close < hi_n:
        return f"켈 손절 — {unit} 종가 {close:,.0f} < 돌파선 {hi_n:,.0f}"
    if close < ema20:
        return f"켈 정리 — {unit} 종가 {close:,.0f} < EMA20 {ema20:,.0f}"
    return None


def reason_text(info: dict, unit: str, when: str) -> str:
    body = f"{info['body_mult']:.1f}배" if np.isfinite(info["body_mult"]) else "— (앞 20봉 몸통 0)"
    return (f"📈 켈 수축 돌파({unit}) — EMA10 {info['e10']:,.0f} > EMA20 {info['e20']:,.0f} > EMA50 {info['e50']:,.0f} 정배열, "
            f"직전 10봉 폭 {info['w_last']:.1%} < 그 앞 10봉 {info['w_prev']:.1%}·평균 거래량 줄어든 뒤 "
            f"장대양봉(몸통 20봉 평균의 {body})·거래량 20봉 평균의 {info['vol_mult']:.1f}배로 "
            f"20봉 고가 {info['hiN']:,.0f} 돌파 ({when} 종가 {info['close']:,.0f}) · 종가가 {info['hiN']:,.0f} 아래면 손절, EMA20 아래면 정리")


def to_30m(bars: pd.DataFrame) -> pd.DataFrame:
    """1분봉(ts·open·high·low·close·volume) → 정규장 30분봉 (봉 이름 = 시작 시각, 15:30 동시호가는 15:00 봉에)."""
    if bars.empty:
        return pd.DataFrame(columns=["start", "open", "high", "low", "close", "volume"])
    b = bars.copy()
    b["ts"] = pd.to_datetime(b["ts"])
    m = (b["ts"].dt.hour * 60 + b["ts"].dt.minute) - (M_OPEN.hour * 60 + M_OPEN.minute)
    b = b[(m >= 0) & (m <= 390)].copy()
    b["k"] = np.minimum(m[b.index] // 30, M_LAST)
    b["d"] = b["ts"].dt.normalize()
    b = b.sort_values("ts")
    agg = b.groupby(["d", "k"], sort=True).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                               close=("close", "last"), volume=("volume", "sum")).reset_index()
    agg["start"] = agg["d"] + pd.to_timedelta(M_OPEN.hour * 60 + M_OPEN.minute + agg["k"] * 30, unit="m")
    return agg[["start", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def bar_index(now: datetime) -> Optional[int]:
    """지금 끝난(1분 여유) 마지막 30분봉 번호 0~12, 09:31 전이면 None."""
    base = datetime.combine(now.date(), M_OPEN)
    mins = (now.replace(tzinfo=None) - base - BAR_DELAY).total_seconds() / 60
    if mins < 30:
        return None
    return min(int(mins // 30) - 1, M_LAST)


def is_etf(name: str) -> bool:
    return any(w in (name or "") for w in ETF_WORDS)


def regime_gate(regime, now: datetime) -> Optional[str]:
    """선별 ④: 09:10 시장 판정 뒤, 강한 하락장 날 아님. 막히면 이유."""
    if regime is None:
        return None
    from kiwoom_trading.screener.market_regime import CHECKS, WINDOW_MIN
    if regime.strong_down:
        return "강한 하락장 날"
    first = CHECKS[0]
    decided = first in regime.done or regime.strong_up or now.time() >= time(first.hour, first.minute + WINDOW_MIN)   # 재시작하면 done 이 비어 있어 09:15 뒤는 판정 끝난 것으로 봄
    return None if decided else "09:10 시장 판정 전"


# ---------------------------------------------------------------- 선별 (두 매매 공통)
class KellSelector:
    """스캐너 시작 때 한 번: 주식 목록·전날 수급·네이버 테마·신규 상장. pick() 은 매 판정 때 지금 대금 순위로 고름."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH) -> None:
        self.day = day
        conn = duckdb.connect(db_path, read_only=True)
        try:
            self.names = dict(conn.execute("SELECT code, name FROM stocks WHERE NOT coalesce(delisted, false)").fetchall())
            fday = conn.execute("SELECT max(date) FROM investor_daily WHERE date < ?", [day]).fetchone()[0]
            self.flow = {c: (f, i) for c, f, i in conn.execute("SELECT code, foreign_, institution FROM investor_daily WHERE date = ?", [fday]).fetchall()}
        finally:
            conn.close()
        from kiwoom_trading.execution import strict_select
        self.listed = strict_select.load_context(day, db_path).listed     # 상장 20거래일 안
        try:
            from kiwoom_trading.common.leader import load_themes
            self.themes = load_themes(NAVER_DB)
        except Exception:
            logging.exception("켈: 네이버 테마 읽기 실패 — 테마 형성 조건을 못 봐 오늘은 안 삼")
            self.themes = {}
        logging.info("켈 선별 준비: 주식 %s종목, 전날 수급 %s종목 (%s), 테마 소속 %s종목, 신규 상장 %s종목 뺌",
                     len(self.names), len(self.flow), fday, len(self.themes), len(self.listed))

    def pick(self, value_top: list, limit: int = MAX_CANDS) -> list:
        """value_top(RankItem) → 선별 ①②③⑥ 통과 종목 (대금 순, 최대 limit)."""
        stocks = [x for x in sorted(value_top, key=lambda x: -(x.trade_value or 0))
                  if x.code in self.names and not is_etf(x.name) and _plain(x.code, x.name)]
        up = {x.code for x in value_top if (x.change_rate or 0) >= THEME_UP}
        count: dict[str, int] = {}
        for c in up:
            for th in self.themes.get(c, ()):
                count[th] = count.get(th, 0) + 1
        out = []
        for rank, x in enumerate(stocks[:MAX_VALUE_RANK], 1):
            if (x.trade_value or 0) < MIN_VALUE:
                break                                            # 대금 순이라 뒤는 모두 100억 미만
            f, i = self.flow.get(x.code, (None, None))
            if f is not None and i is not None and f < 0 and i < 0:
                continue
            if not any(count.get(th, 0) >= THEME_MIN for th in self.themes.get(x.code, ())):
                continue
            if x.code in self.listed:
                continue
            out.append(x)
            if len(out) >= limit:
                break
        return out

    def hot_theme(self, code: str, value_top: list) -> str:
        up = {x.code for x in value_top if (x.change_rate or 0) >= THEME_UP}
        best = max(((th, sum(1 for c in up if th in self.themes.get(c, ()))) for th in self.themes.get(code, ())), key=lambda t: t[1], default=("", 0))
        return f"{best[0]} {best[1]}종목 +4%↑" if best[0] else ""


def _plain(code: str, name: str) -> bool:
    from kiwoom_trading.strategies.hong_limitup.live import is_plain_stock
    return is_plain_stock(code, name)


# ---------------------------------------------------------------- 일봉
def load_daily(codes: Iterable[str], day: date, db_path: str = DEFAULT_DB_PATH, days: int = 400) -> dict[str, pd.DataFrame]:
    """codes 의 day 전까지 일봉 (오래된 순). 9-14 뒤 가격(시가·고가·저가·종가)은 daily_regular 정규장 값으로 덮어씀.
    거래량은 daily_ohlcv 그대로 (KRX 만 — 오늘 KRX 시세 거래량과 같은 기준, daily_regular 거래량은 NXT 포함이라 섞지 않음)."""
    codes = list(dict.fromkeys(codes))
    if not codes:
        return {}
    conn = duckdb.connect(db_path, read_only=True)
    try:
        df = conn.execute(f"""SELECT code, date, open, high, low, close, volume FROM daily_ohlcv
                              WHERE code IN ({','.join('?' * len(codes))}) AND date < ? AND date >= ? - INTERVAL {int(days)} DAY""",
                          [*codes, day, day]).df()
    finally:
        conn.close()
    try:
        rc = duckdb.connect(REGULAR_DB, read_only=True)
        try:
            reg = rc.execute(f"SELECT code, date, open, high, low, close FROM daily_regular WHERE code IN ({','.join('?' * len(codes))}) AND date < ?",
                             [*codes, day]).df()
        finally:
            rc.close()
        if len(reg):
            df = df.merge(reg, on=["code", "date"], how="left", suffixes=("", "_r"))
            for c in ("open", "high", "low", "close"):
                df[c] = df[f"{c}_r"].fillna(df[c])
            df = df.drop(columns=[f"{c}_r" for c in ("open", "high", "low", "close")])
    except Exception:
        logging.exception("켈: daily_regular 읽기 실패 — daily_ohlcv 값만 씀")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values(["code", "date"])
    return {c: g.reset_index(drop=True) for c, g in df.groupby("code", sort=False)}


class KellDailyContext:
    """일봉 판정 자료 (필요한 종목만 그때 읽음) + 스캐너 시작 때 보유 종목 매도 판정."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH) -> None:
        self.day, self.db_path = day, db_path

    def history(self, codes: Iterable[str]) -> dict[str, pd.DataFrame]:
        return load_daily(codes, self.day, self.db_path)

    def exits(self, held: dict[str, tuple[str, Optional[float]]]) -> dict[str, str]:
        """held = {거래 id: (코드, hiN)} → {거래 id: 매도 사유} — 전 거래일 정규장 종가 < hiN 또는 < 일봉 EMA20."""
        out: dict[str, str] = {}
        hist = self.history(c for c, _ in held.values())
        for tid, (code, hi_n) in held.items():
            g = hist.get(code)
            if g is None or len(g) < EMA_MID:
                logging.warning("켈 일봉 매도 판정 자료 부족 %s", code)
                continue
            close, e20 = float(g["close"].iloc[-1]), float(ema(g["close"], EMA_MID).iloc[-1])
            why = exit_reason(close, hi_n, e20, f"{g['date'].iloc[-1]:%m-%d} 일봉")
            if why:
                out[tid] = why + " — 시초 매도"
        return out


class KellDailyWatcher:
    """15:15~15:19 한 번: 선별 통과 종목(최대 30)의 일봉 + 오늘 KRX 시세 봉으로 판정 → 모의 매수 신호."""

    def __init__(self, ctx: KellDailyContext, selector: KellSelector, market, done: set, regime=None) -> None:
        self.ctx, self.sel, self.market, self.regime = ctx, selector, market, regime
        self.done = set(done)
        self.fired = False

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if self.fired or not (D_START <= now.time() <= D_END):
            return []
        self.fired = True
        gate = regime_gate(self.regime, now)
        if gate:
            logging.info("켈 수축 일봉: %s — 오늘 안 삼", gate)
            return []
        picks = [x for x in self.sel.pick(value_top) if x.code not in self.done]
        hist = self.ctx.history(x.code for x in picks)
        out, skipped, short = [], [], []
        naive = now.replace(tzinfo=None, second=0, microsecond=0)
        for x in picks:
            g = hist.get(x.code)
            if g is None or len(g) < MIN_BARS - 1:
                short.append(x.name)
                continue
            try:
                q = self.market.quote(x.code, integrated=False)
            except Exception:
                logging.warning("켈 일봉 시세 조회 실패 %s", x.code)
                continue
            if not q or not q.price:
                continue
            bars = pd.concat([g, pd.DataFrame([{"code": x.code, "date": self.ctx.day, "open": q.open, "high": q.high, "low": q.low,
                                                "close": q.price, "volume": q.volume}])], ignore_index=True)
            st, info = evaluate_last(bars)
            if st == "skip":
                skipped.append(f"{x.name} (돌파선 {info['hiN']:,.0f})")
            if st != "buy":
                continue
            self.done.add(x.code)
            theme = self.sel.hot_theme(x.code, value_top)
            out.append((x.code, x.name, "켈 수축", Signal(ts=naive, kind=KIND_D, price=float(q.price), level=info["hiN"], stop=info["hiN"],
                                                       reason=reason_text(info, "일봉", f"{now:%H:%M} 오늘")
                                                       + f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억" + (f" · 테마 {theme}" if theme else "")
                                                       + " — 다음 거래일부터 09:00 판정")))
        logging.info("켈 수축 일봉 %s: 후보 %s종목 → 신호 %s %s · 하락 뒤 첫 신호라 건너뜀 %s · 일봉 부족 %s", f"{now:%H:%M}", len(picks), len(out),
                     ", ".join(n for _, n, _, _ in out), ", ".join(skipped) or "없음", ", ".join(short) or "없음")
        return out


# ---------------------------------------------------------------- 30분봉
def trading_days_before(day: date, n: int, db_path: str = DEFAULT_DB_PATH) -> list[date]:
    conn = duckdb.connect(db_path, read_only=True)
    try:
        rows = conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code = '005930' AND date < ? ORDER BY date DESC LIMIT ?", [day, n]).fetchall()
    finally:
        conn.close()
    return sorted(r[0] for r in rows)


def load_local_30m(codes: list[str], days: list[date], minute_db: str = MINUTE_DB) -> dict[str, pd.DataFrame]:
    """지역 1분봉 DB(통합 AL) → 종목별 정규장 30분봉 (지난 거래일들)."""
    if not codes or not days:
        return {}
    conn = duckdb.connect(minute_db, read_only=True)
    try:
        df = conn.execute(f"""
            SELECT code, CAST(ts AS DATE) AS d, LEAST(CAST(floor((hour(ts) * 60 + minute(ts) - 540) / 30) AS INT), {M_LAST}) AS k,
                   arg_min(open, ts) AS open, max(high) AS high, min(low) AS low, arg_max(close, ts) AS close, sum(volume) AS volume
            FROM minute_ohlcv WHERE exchange = 'AL' AND code IN ({','.join('?' * len(codes))}) AND ts >= ? AND ts < ?
              AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '15:30'
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", [*codes, days[0], days[-1] + timedelta(days=1)]).df()
    finally:
        conn.close()
    out = {}
    for c, g in df.groupby("code", sort=False):
        g = g[pd.to_datetime(g["d"]).isin(pd.to_datetime(pd.Series(days)))].copy()
        g["start"] = pd.to_datetime(g["d"]) + pd.to_timedelta(540 + g["k"] * 30, unit="m")
        out[c] = g[["start", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return out


class KellMinuteWatcher:
    """30분봉이 끝날 때마다: 보유 종목 매도 판정(exits) → 선별 통과 종목(최대 30) 매수 판정.
    held() = [(거래 id, 코드, hiN)] — paper 가 KELL_M 매도에 exits[거래 id] 를 씀."""

    def __init__(self, client, day: date, selector: KellSelector, regime=None, held: Optional[Callable[[], list]] = None,
                 done: Iterable = (), db_path: str = DEFAULT_DB_PATH, minute_db: str = MINUTE_DB) -> None:
        self.client, self.day, self.sel, self.regime = client, day, selector, regime
        self.held = held or (lambda: [])
        self.done = set(done)                      # (코드, 봉 끝 시각) — 같은 봉 신호 한 번
        self.minute_db = minute_db
        self.days = trading_days_before(day, HIST_DAYS, db_path)
        self.hist: dict[str, pd.DataFrame] = {}    # 코드 → 지난 거래일 30분봉 (하루 한 번 채움)
        self.retry: set[str] = set()               # 지난날을 다 못 채운 종목
        self.today: dict[str, tuple[int, pd.DataFrame]] = {}   # 코드 → (봉 번호, 오늘 30분봉) — 같은 봉엔 다시 조회 안 함
        self.exits: dict[str, str] = {}
        self.last_k: Optional[int] = None
        self.morning_done = False

    # ---------------- 자료
    def _fetch(self, code: str, day: date) -> pd.DataFrame:
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        return to_30m(pd.DataFrame(fetch_minute_bars(self.client, code, day, "AL")))

    def _ensure_hist(self, codes: list[str]) -> None:
        new = [c for c in codes if c not in self.hist or c in self.retry]
        if not new:
            return
        try:
            local = load_local_30m([c for c in new if c not in self.hist], self.days, self.minute_db)
        except Exception:
            logging.exception("켈 30분봉: 지역 1분봉 DB 읽기 실패 — 키움 조회로 채움")
            local = {}
        budget = API_HIST_BUDGET
        for c in new:
            g = self.hist[c] if c in self.hist else local.get(c, pd.DataFrame(columns=["start", "open", "high", "low", "close", "volume"]))
            have = set(pd.to_datetime(g["start"]).dt.date) if len(g) else set()
            missing = [d for d in self.days if d not in have][-5:]          # 최근 5일까지만 메움
            parts, done = [g], 0
            for d in missing:
                if budget <= 0:
                    break
                budget -= 1
                done += 1
                try:
                    parts.append(self._fetch(c, d))
                except Exception:
                    logging.warning("켈 30분봉 지난 1분봉 조회 실패 %s %s", c, d)
            g = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else g
            if len(g):
                g = g.sort_values("start").drop_duplicates("start").reset_index(drop=True)
            self.hist[c] = g
            if done < len(missing):
                self.retry.add(c)                   # 조회 예산이 떨어져 못 채운 날은 다음 판정 때 다시
            else:
                self.retry.discard(c)

    def _series(self, code: str, k: Optional[int]) -> pd.DataFrame:
        """지난 거래일 + 오늘 0~k 번 봉 (k None 이면 지난날만)."""
        base = self.hist.get(code, pd.DataFrame(columns=["start", "open", "high", "low", "close", "volume"]))
        if k is None:
            return base
        cached = self.today.get(code)
        if cached is None or cached[0] != k:
            t = self._fetch(code, self.day)
            t = t[t["start"] < datetime.combine(self.day, M_OPEN) + timedelta(minutes=30 * (k + 1))]
            self.today[code] = (k, t)
        today = self.today[code][1]
        return pd.concat([p for p in (base, today) if len(p)], ignore_index=True) if len(today) else base

    # ---------------- 판정
    def _refresh_exits(self, k: Optional[int], label: str) -> None:
        held = self.held()
        self._ensure_hist([c for _, c, _ in held])
        exits: dict[str, str] = {}
        for tid, code, hi_n in held:
            try:
                s = self._series(code, k)
            except Exception:
                logging.warning("켈 30분봉 매도 판정 조회 실패 %s", code)
                continue
            if len(s) < EMA_MID:
                continue
            why = exit_reason(float(s["close"].iloc[-1]), hi_n, float(ema(s["close"], EMA_MID).iloc[-1]),
                              f"{pd.Timestamp(s['start'].iloc[-1]):%m-%d %H:%M} 30분봉")
            if why:
                exits[tid] = why
        self.exits = exits
        if held:
            logging.info("켈 수축 30분 매도 판정 %s: 보유 %s건 → 매도 %s", label, len(held), ", ".join(exits.values()) or "없음")

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if now.date() != self.day:
            return []
        k = bar_index(now)
        if k is None:
            if not self.morning_done and now.time() >= M_OPEN:
                self.morning_done = True          # 전날 마지막 봉으로 들고 넘어온 종목 매도 판정 (재시작해도 09:00 에 팔도록)
                try:
                    self._refresh_exits(None, "전날 마지막 봉")
                except Exception:
                    logging.exception("켈 수축 30분 아침 매도 판정 실패")
            return []
        if k == self.last_k:
            return []
        self.last_k = k
        self.morning_done = True
        end = datetime.combine(self.day, M_OPEN) + timedelta(minutes=30 * (k + 1))
        try:
            self._refresh_exits(k, f"{end:%H:%M}")
        except Exception:
            logging.exception("켈 수축 30분 매도 판정 실패")
        gate = regime_gate(self.regime, now)
        if gate:
            logging.info("켈 수축 30분 %s: %s — 안 삼", f"{end:%H:%M}", gate)
            return []
        picks = [x for x in self.sel.pick(value_top) if (x.code, end) not in self.done]
        self._ensure_hist([x.code for x in picks])
        out, skipped, short = [], [], []
        for x in picks:
            try:
                s = self._series(x.code, k)
            except Exception:
                logging.warning("켈 30분봉 오늘 1분봉 조회 실패 %s", x.code)
                continue
            if not len(s) or pd.Timestamp(s["start"].iloc[-1]) != end - timedelta(minutes=30):
                continue                              # 오늘 이 봉이 아직 없음 (거래 정지 등)
            st, info = evaluate_last(s)
            if st is None and info is None:
                short.append(x.name)
                continue
            if st == "skip":
                skipped.append(f"{x.name} (돌파선 {info['hiN']:,.0f})")
            if st != "buy":
                continue
            self.done.add((x.code, end))
            theme = self.sel.hot_theme(x.code, value_top)
            out.append((x.code, x.name, "켈 수축", Signal(ts=end, kind=KIND_M, price=info["close"], level=info["hiN"], stop=info["hiN"],
                                                       reason=reason_text(info, "30분봉", f"{end - timedelta(minutes=30):%H:%M}~{end:%H:%M} 봉")
                                                       + f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억" + (f" · 테마 {theme}" if theme else "")
                                                       + " — 30분봉 끝날 때마다 판정, 15:19 정리 없이 들고 감")))
        logging.info("켈 수축 30분 %s 봉: 후보 %s종목 → 신호 %s %s · 하락 뒤 첫 신호라 건너뜀 %s · 봉 부족 %s", f"{end:%H:%M}", len(picks), len(out),
                     ", ".join(n for _, n, _, _ in out), ", ".join(skipped) or "없음", ", ".join(short) or "없음")
        return out
