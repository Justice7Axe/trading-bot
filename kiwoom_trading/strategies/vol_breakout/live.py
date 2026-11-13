"""📏 변동성 돌파 — 래리 윌리엄스 '0.5 단타 공식' 쇼츠(돈이 만든 세계, 2026-11-12) 규칙 (2026-11-13 사용자 '1B 2A 3B 4A', 모의만).
정리 문서: docs/lectures/larry_williams_volatility_breakout_shorts.md. 백테스트 안 함 — 숫자는 영상 규칙과 사용자 선택 그대로.

기준선 = 오늘 09:00 정규장 시가 + (어제 정규장 고가 − 어제 정규장 저가) × 0.5
  어제 고가·저가는 data/daily_regular.duckdb (9-14 뒤 daily_ohlcv 는 08:00~20:00 통합 값이라 쓰지 않음).
  daily_regular 는 1분봉이 있는 종목(날짜별 대금 상위 약 500)만 있음 → 전 거래일이 통째로 없으면 data/minute_history.duckdb 통합(AL) 1분봉으로,
  종목이 없으면 그 종목만 키움 1분봉(통합 AL, 전 거래일 하루치)을 한 번 받아 09:00~15:30 봉의 고가·저가로 만듦 (daily_regular 와 같은 범위).
  오늘 시가는 키움 KRX 시세(ka10001)의 시가 — 종목마다 하루 한 번만 조회 (거래량 0 이면 시가가 아직 없어 다음 확인 때 다시).
종목 범위 (1B, 📈 켈 수축과 같은 KellSelector, 테마 조건만 뺌): 지금 대금 100억↑ & 주식(ETF·ETN·우선주·스팩 뺌) 중 대금 100위 안,
  전날 외인·기관 둘 다 순매도면 뺌, 상장 20거래일 안 뺌 · 🌀 무너지는 국면은 paper 가 뺌.
매수 (2A, 09:00~15:19, 모든 날 4A): 현재가(분마다 받는 KRX 대금 순위의 현재가)가 기준선 이상이 되는 첫 확인 → 모의 매수 신호. 종목당 하루 한 번.
  신호가 = 기준선 → paper 의 추격 제한(신호가 +1% 넘으면 안 삼)이 '기준선보다 1% 넘게 위면 안 삼'이 됨.
  처음 보는 종목(대금 100위에 늦게 들어옴 등)은 첫 조회 때 이미 지나간 돌파를 사지 않음:
    오늘 고가가 기준선 이상인데 지금가가 기준선 아래 → '이미 닿았다 내려옴', 지금가가 기준선 +1% 넘음 → '늦게 봄(이미 넘어감)' 으로 그날 끝.
  기준선이 오늘 상한가 이상이거나 어제 폭이 0 이하면 안 삼.
매도 (paper '다음날' 방식 + 📏 전용 손절): 현재가가 오늘 시가 아래로 내려오면 바로 매도 (3B, t.stop = 오늘 시가) · 익절 없음
  · 15:19 정리 없이 들고 넘어가 다음 날 09:00 시가에 전량 매도.
금액·보유 한도: 다른 신규 모의(📈 켈·🕯 하이킨아시·🪃 급락 반등)와 같은 종목당 100만 원·보유 10종목 한도 (Nada 금액 축소·R7 그대로).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.strategies.kell_squeeze.live import MAX_VALUE_RANK, KellSelector

KIND = "변동성 돌파"
LABEL = "📏 변동성 돌파"
K = 0.5                                      # 어제 폭 × 0.5
BUY_START, BUY_END = time(9, 0), time(15, 19)   # 15:19 부터는 paper 가 안 삼
CHASE = 0.01                                 # 처음 볼 때 기준선 +1% 넘게 이미 올라가 있으면 늦게 본 것 (paper MAX_CHASE 와 같은 값)
QUOTE_BUDGET = 30                            # 한 번 확인에 새로 시가를 조회하는 종목 수 (나머지는 다음 확인 때)
REG_OPEN, REG_CLOSE = time(9, 0), time(15, 30)   # 어제 정규장 봉 범위 (daily_regular 와 같음)
MIN_BARS = 30                                # 1분봉으로 만들 때 정규장 봉이 30개 안 되면 안 씀 (daily_regular 와 같음)
LOG_EVERY = 10                               # 신호가 없으면 10분마다 한 줄 요약
REGULAR_DB = os.path.join(PROJECT_ROOT, "data", "daily_regular.duckdb")
MINUTE_DB = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")


# ---------------------------------------------------------------- 규칙 (순수 함수)
def baseline(open_: float, high: float, low: float, k: float = K) -> float:
    """기준선 = 오늘 시가 + (어제 고가 − 어제 저가) × k."""
    return float(open_) + (float(high) - float(low)) * k


def first_look(price: float, day_high: float, line: float) -> Optional[str]:
    """처음 조회한 종목: 이미 지나간 돌파면 이유, 아니면 None (None 이고 price ≥ line 이면 지금 신호)."""
    if price < line <= day_high:
        return "이미 닿았다 내려옴"
    if price > line * (1 + CHASE):
        return "늦게 봄(이미 넘어감)"
    return None


def plan_text(line: float, open_: float, rng: float) -> str:
    """매수 알림·R1 계획에 쓰는 매도 규칙 설명."""
    return (f"{LABEL} — 기준선 {line:,.0f}원(오늘 시가 {open_:,.0f} + 어제 폭 {rng:,.0f} × {K:g}) · "
            f"손절: 지금가가 오늘 시가 {open_:,.0f}원 아래로 내려오면 바로 매도 · 익절 없음 · 15:19 정리 없이 다음 날 09:00 시가에 전량 매도")


# ---------------------------------------------------------------- 자료
def prev_trading_day(day: date, db_path: str = DEFAULT_DB_PATH) -> Optional[date]:
    conn = duckdb.connect(db_path, read_only=True)
    try:
        return conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code = '005930' AND date < ?", [day]).fetchone()[0]
    finally:
        conn.close()


def load_prev_range(prev: date, regular_db: str = REGULAR_DB, minute_db: str = MINUTE_DB) -> tuple[dict[str, tuple[float, float]], str]:
    """전 거래일 정규장 {코드: (고가, 저가)} 와 출처. daily_regular 에 그날이 없으면 통합 1분봉 09:00~15:29 로 만듦."""
    try:
        conn = duckdb.connect(regular_db, read_only=True)
        try:
            rows = conn.execute("SELECT code, high, low FROM daily_regular WHERE date = ? AND high IS NOT NULL AND low IS NOT NULL", [prev]).fetchall()
        finally:
            conn.close()
        if rows:
            return {c: (float(h), float(lo)) for c, h, lo in rows}, "daily_regular"
        logging.warning("변동성 돌파: daily_regular 에 %s 가 없음 — 1분봉으로 어제 고가·저가를 만듦", prev)
    except Exception:
        logging.exception("변동성 돌파: daily_regular 읽기 실패 — 1분봉으로 어제 고가·저가를 만듦")
    conn = duckdb.connect(minute_db, read_only=True)
    try:
        rows = conn.execute("""SELECT code, max(high), min(low) FROM minute_ohlcv
                               WHERE exchange = 'AL' AND ts >= ? AND ts < ? AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '15:30'
                               GROUP BY code""", [prev, prev + timedelta(days=1)]).fetchall()
    finally:
        conn.close()
    return {c: (float(h), float(lo)) for c, h, lo in rows if h is not None and lo is not None}, "minute_history"


class VbContext:
    """스캐너 시작 때 한 번: 전 거래일 정규장 고가·저가 (전 종목)."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH, regular_db: str = REGULAR_DB, minute_db: str = MINUTE_DB) -> None:
        self.day = day
        self.prev = prev_trading_day(day, db_path)
        self.ranges, self.src = load_prev_range(self.prev, regular_db, minute_db) if self.prev else ({}, "없음")
        logging.info("변동성 돌파 준비: 어제(%s) 정규장 고가·저가 %s종목 (%s)", self.prev, len(self.ranges), self.src)

    def prev_range(self, code: str) -> Optional[tuple[float, float]]:
        return self.ranges.get(code)

    def fetch_range(self, client, code: str) -> Optional[tuple[float, float]]:
        """daily_regular 에 없는 종목: 키움 통합 1분봉 전 거래일 하루치 → 09:00~15:30 고가·저가 (받으면 ranges 에 넣어 다시 안 받음)."""
        if self.prev is None or client is None:
            return None
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        bars = [b for b in fetch_minute_bars(client, code, self.prev, "AL") if REG_OPEN <= b["ts"].time() <= REG_CLOSE and b["high"] and b["low"]]
        if len(bars) < MIN_BARS:
            return None
        self.ranges[code] = (float(max(b["high"] for b in bars)), float(min(b["low"] for b in bars)))
        return self.ranges[code]


# ---------------------------------------------------------------- 감시
class VbWatcher:
    """매분: 선별 통과 종목의 기준선(종목마다 하루 한 번 시가 조회로 확정)과 대금 순위의 현재가를 비교 → 첫 돌파면 모의 매수 신호.
    1분봉은 받지 않음 — 현재가는 스캐너가 매분 받는 KRX 대금 순위 값을 그대로 씀 (추가 조회 = 종목당 하루 한 번 시세)."""

    def __init__(self, market, selector: KellSelector, ctx: VbContext, done: Iterable = (), budget: int = QUOTE_BUDGET) -> None:
        self.market, self.sel, self.ctx = market, selector, ctx
        self.day = ctx.day
        self.done: set[str] = set(done)                 # 오늘 신호를 낸(또는 늦게 봐 끝난) 종목 — 하루 한 번
        self.lines: dict[str, dict] = {}                # 코드 → {open, upper, rng, line} (기준선 확정)
        self.bad: dict[str, str] = {}                   # 코드 → 기준선을 못 쓰는 이유 (어제 값 없음·폭 0·상한가 이상)
        self.late: dict[str, str] = {}                  # 코드 → 처음 볼 때 이미 지나간 돌파
        self.budget = budget
        self.fetched = 0                                # daily_regular 에 없어 키움 1분봉으로 어제 폭을 만든 종목 수

    def _fix_line(self, x) -> Optional[str]:
        """시가 조회로 기준선 확정. 돌려주는 값: None(확정됨) | 'wait'(시가 아직 없음·조회 실패) | 못 쓰는 이유."""
        rng = self.ctx.prev_range(x.code)
        if rng is None:
            try:
                rng = self.ctx.fetch_range(getattr(self.market, "client", None), x.code)
            except Exception:
                logging.warning("변동성 돌파 어제 1분봉 조회 실패 %s", x.code)
                return "wait"
            self.fetched += 1
            if rng is None:
                return "어제 정규장 값 없음"
        hi, lo = rng
        if hi - lo <= 0:
            return "어제 폭 0"
        try:
            q = self.market.quote(x.code, integrated=False)
        except Exception:
            logging.warning("변동성 돌파 시세 조회 실패 %s", x.code)
            return "wait"
        if not q or not q.open or not q.volume:
            return "wait"
        line = baseline(q.open, hi, lo)
        if q.upper and line >= q.upper:
            return f"기준선 {line:,.0f} ≥ 상한가 {q.upper:,}"
        self.lines[x.code] = {"open": float(q.open), "upper": q.upper, "rng": hi - lo, "line": line, "high": float(q.high), "price": float(q.price)}
        return None

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if now.date() != self.day or not (BUY_START <= now.time() < BUY_END):
            return []
        picks = [x for x in self.sel.pick(value_top, limit=MAX_VALUE_RANK, theme=False) if x.code not in self.done]
        naive = now.replace(tzinfo=None, second=0, microsecond=0)
        budget, out, new_lines = self.budget, [], 0
        for x in picks:
            if x.code in self.bad:
                continue
            fresh = x.code not in self.lines
            if fresh:
                if budget <= 0:
                    continue
                budget -= 1
                why = self._fix_line(x)
                if why == "wait":
                    continue
                if why:
                    self.bad[x.code] = why
                    continue
                new_lines += 1
            v = self.lines[x.code]
            line = v["line"]
            if fresh:
                price, high = v["price"], max(v["high"], float(x.price or 0))
                late = first_look(price, high, line)
                if late:
                    self.late[x.code] = late
                    self.done.add(x.code)
                    continue
            else:
                price = float(x.price or 0)
            if not price or price < line:
                continue
            self.done.add(x.code)
            reason = (f"{LABEL} — 지금가 {price:,.0f}원이 기준선 {line:,.0f}원(오늘 시가 {v['open']:,.0f} + 어제 정규장 폭 {v['rng']:,.0f} × {K:g}) 에 닿음 "
                      f"(어제 {self.ctx.prev:%m-%d} 정규장 고가−저가, 시가 대비 +{line / v['open'] - 1:.1%}) · 손절 = 오늘 시가 {v['open']:,.0f} 아래 · 익절 없음 · 다음 날 09:00 시가 매도"
                      + f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억" + (f" · 상한가 {v['upper']:,}" if v.get("upper") else ""))
            out.append((x.code, x.name, LABEL, Signal(ts=naive, kind=KIND, price=line, level=line, stop=v["open"], reason=reason)))
        if out or now.minute % LOG_EVERY == 0:
            bad: dict[str, int] = {}
            for why in self.bad.values():
                key = "상한가 이상" if why.startswith("기준선") else why
                bad[key] = bad.get(key, 0) + 1
            late: dict[str, int] = {}
            for why in self.late.values():
                late[why] = late.get(why, 0) + 1
            logging.info("변동성 돌파 %s: 대상 %s종목 · 기준선 계산 %s(이번에 %s, 시세 조회 %s번, 어제 폭 1분봉으로 만든 종목 누적 %s) · 신호 %s %s · 못 씀 %s · 늦게 봄 %s",
                         f"{now:%H:%M}", len(picks), len(self.lines), new_lines, self.budget - budget, self.fetched, len(out),
                         ", ".join(f"{n} {s.level:,.0f}" for _, n, _, s in out),
                         ", ".join(f"{k} {n}" for k, n in bad.items()) or "없음", ", ".join(f"{k} {n}" for k, n in late.items()) or "없음")
        return out
