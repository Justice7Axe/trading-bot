"""🏄 쿨라매기 돌파 — 크리스티안 쿨라매기 '돌파 매매' (손절봇 영상, 2026-11-15 사용자 '정할 점은 정해서 🧾 가상 장부로 먼저').
정리 문서: docs/lectures/qullamaggie_breakout.md (3·4·6절, 끝 '정한 숫자'). 스킬: .claude/skills/qullamaggie. 백테스트 안 함, 주문 없음.

대상 (스캐너 시작 때 한 번, 전 거래일까지 일봉):
  주식만 (ETF·ETN·스팩·우선주 뺌), 상장 20거래일 안 뺌 (strict_select.NEW_LISTING_DAYS).
  ① 21·63·126거래일 상승률 중 하나라도 전 종목 상위 2% 안 — 순위는 전 종목이 다 있는 daily_ohlcv 종가로 셈
     (9-14 뒤는 20:00 통합 종가지만 정규장 값은 대금 상위 일부 종목만 있어 전 종목 순위를 못 냄).
  ② 63거래일 상승률 ≥ +30% · ③ 전날 종가 > 20일선 · 쉬는 구간 — ②③과 아래는 정규장 일봉 (9-14 전 daily_ohlcv + 9-14 뒤 daily_regular,
     빈 날은 🐢 터틀 돌파와 같은 방법(TurtleContext)으로 minute_history·파일 캐시·키움 통합 1분봉으로 채움).
  쉬는 구간: 최근 10~40거래일(어제까지) 중 아래를 모두 맞는 가장 긴 구간.
     구간 폭 (최고가 ÷ 최저가 − 1) ≤ 25% · 뒤 절반 폭 < 앞 절반 폭 (좁아짐) · 뒤 절반 최저가 > 앞 절반 최저가 (저점 높아짐)
     · 최근 5거래일 종가가 모두 그날 20일선 위. 윗선 = 구간 최고가. (홀수 길이면 뒤 절반이 하루 더 김)
  ADR20 = 최근 20거래일 (고가 − 저가) ÷ 종가 평균. 10일선 = 정규장 종가 10일 단순 평균.
매수 (09:05~15:19, 하루 종목당 한 번):
  KRX 현재가 > max(윗선, 오늘 09:00~09:05 5분 고점)이 처음 된 때 한 번 판정 — 갭으로 윗선 위에서 시작해도 5분 고점을 넘으면 삼.
  5분 고점 = KRX 1분봉 09:00~09:04 봉의 고가 최고값. 현재가 = 이번 분 대금 순위 가격(없으면 KRX 시세).
  손절선 = 매수 순간 오늘 KRX 저가. 손절폭 (매수가 − 오늘 저가) ÷ 매수가 > ADR20 이면 안 삼 (그날 그 종목 끝, 로그만).
  강한 하락장 날 안 삼 — 📈 켈 수축 돌파와 같은 regime_gate (09:10 시장 판정 전에는 판정을 미룸, 판정 뒤 처음 넘은 때 삼).
  ☕ 카페 종목 제한·🌀 무너지는 국면 등 모의 공통 거르기는 안 씀 (가상 장부 — 기록이 목적).
수량: 가상 계좌 100만 원 (시작 + 끝난 매매 손익), 동시 5종목, 종목당 min(20만 원, 잔고 1% ÷ 손절폭)어치 정수 주, 1주가 안 되면 안 삼. 비용 0.25%.
매도:
  ① 장중 KRX 현재가 ≤ 손절선 → 남은 물량 전부 (산 날 포함 매일 09:00~15:30).
  ② 산 날 포함 5거래일째 09:00 시가에 절반 (1주면 팔지 않고), 남은 물량 손절선 = 산 값 (본전, 장중).
  ③ 정규장 종가가 10일선 아래로 마감한 다음 거래일 09:00 시가에 나머지 전부 (②와 같은 날이면 ③ 전부).
  목표가·보유 기간 제한 없음. 손절선은 ledger_trades.plan(stop)에 적어 두어 재시작해도 이어짐.
알림: 🟣 가상 매수·절반 매도·매도 때만 ('🏄 쿨라매기 돌파' + '포착:' 이유). 포착만 하고 안 산 것은 로그만.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time
from typing import Callable, Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.execution.ledger import COST, Ledger, Plan, price_source
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.strategies.kell_squeeze.live import is_etf, regime_gate
from kiwoom_trading.strategies.turtle.live import FILL_CACHE as TURTLE_CACHE, TurtleContext, price_jump

# ---------------------------------------------------------------- 정한 숫자 (2026-11-15)
BOOK = "쿨라매기 돌파"                 # ledger_trades.book
LABEL = "🏄 쿨라매기 돌파"
TAG = "🏄"
START_CASH = 1_000_000                 # 가상 계좌
SLOTS = 5                              # 동시 보유 종목
PER_STOCK = 200_000                    # 종목당 최대 금액
RISK = 0.01                            # 손절에 닿으면 잃는 돈 = 잔고 1%
PERIODS = (21, 63, 126)                # 1·3·6달 상승률 (거래일)
TOP_PCT = 0.02                         # 셋 중 하나라도 전 종목 상위 2%
MIN_GAIN63 = 0.30                      # 63거래일 상승률 ≥ +30%
MA_TREND = 20                          # 전날 종가 > 20일선, 최근 5일 종가 > 20일선
ABOVE_DAYS = 5
BASE_MIN, BASE_MAX = 10, 40            # 쉬는 구간 길이 (거래일)
BASE_WIDTH = 0.25                      # 구간 폭 (최고가 ÷ 최저가 − 1) ≤ 25%
ADR_DAYS = 20                          # ADR20
OPEN_HIGH_END = time(9, 5)             # 5분 고점 = 09:00~09:04 1분봉
BUY_START, BUY_END = time(9, 5), time(15, 19)
HALF_DAY = 5                           # 산 날 포함 5거래일째 09:00 절반 (영상 예시 테슬라·줌 모두 5거래일째, 2026-11-15 사용자)
EXIT_MA = 10                           # 종가 < 10일선 → 다음 거래일 09:00
SELL_START, SELL_END = time(9, 0), time(15, 30)
REPORT_AT = time(15, 40)
FETCH_BUDGET = 30                      # 한 번 확인에 정규장 빈 날을 키움 1분봉으로 채우는 수
QUOTE_BUDGET = 40                      # 한 번 확인에 대금 순위 밖 후보 시세 조회 수
MIN_ROWS = max(PERIODS[1] + 1, BASE_MAX + 1, MA_TREND + ABOVE_DAYS, ADR_DAYS)   # 정규장 일봉 최소 개수
FILL_CACHE = os.path.join(PROJECT_ROOT, "data", "qulla_regular_fill.json")


# ---------------------------------------------------------------- 규칙 (순수 함수)
def _width(highs: list[float], lows: list[float]) -> float:
    lo = min(lows)
    return max(highs) / lo - 1 if lo > 0 else float("inf")


def _ma(closes: list[float], n: int, end: int) -> Optional[float]:
    """closes[end-n+1 .. end] 평균 (end 포함). 자료가 모자라면 None."""
    if end + 1 < n or end < 0:
        return None
    return sum(closes[end - n + 1:end + 1]) / n


def find_base(bars: list[tuple]) -> Optional[dict]:
    """bars [(날짜, 시가, 고가, 저가, 종가)] 오래된 순·어제까지 → 쉬는 구간 (가장 긴 것) 또는 None."""
    if len(bars) < max(BASE_MAX, MA_TREND + ABOVE_DAYS - 1):
        return None
    c = [b[4] for b in bars]
    last = len(bars) - 1
    for k in range(last - ABOVE_DAYS + 1, last + 1):                 # 최근 5거래일 종가가 모두 20일선 위
        m = _ma(c, MA_TREND, k)
        if m is None or c[k] <= m:
            return None
    for n in range(BASE_MAX, BASE_MIN - 1, -1):
        seg = bars[-n:]
        h, l = [b[2] for b in seg], [b[3] for b in seg]
        w = _width(h, l)
        if w > BASE_WIDTH:
            continue
        half = n // 2
        w1, w2 = _width(h[:half], l[:half]), _width(h[half:], l[half:])
        lo1, lo2 = min(l[:half]), min(l[half:])
        if w2 < w1 and lo2 > lo1:
            return {"len": n, "top": max(h), "width": w, "w1": w1, "w2": w2, "lo1": lo1, "lo2": lo2,
                    "start": seg[0][0], "end": seg[-1][0]}
    return None


def features(bars: list[tuple]) -> dict:
    """정규장 일봉 → 판정 칸. ok = 대상 ②③·쉬는 구간을 모두 통과. 매도용 10일선은 ok 와 상관없이 채움."""
    c = [b[4] for b in bars]
    last = len(bars) - 1
    v = {"close": c[-1], "last": bars[-1][0], "rows": len(bars), "ma10": _ma(c, EXIT_MA, last), "ma20": _ma(c, MA_TREND, last),
         "adr": (sum((b[2] - b[3]) / b[4] for b in bars[-ADR_DAYS:]) / ADR_DAYS) if len(bars) >= ADR_DAYS else None,
         "ret63": c[-1] / c[-1 - PERIODS[1]] - 1 if len(c) > PERIODS[1] else None, "base": None, "ok": False, "why": ""}
    if len(bars) < MIN_ROWS:
        v["why"] = f"정규장 일봉 {len(bars)}개 (필요 {MIN_ROWS}개)"
    elif v["ret63"] < MIN_GAIN63:
        v["why"] = f"63일 상승률 {v['ret63']:+.0%} < +{MIN_GAIN63:.0%}"
    elif not v["ma20"] or v["close"] <= v["ma20"]:
        v["why"] = f"전날 종가 {v['close']:,.0f} ≤ 20일선 {v['ma20'] or 0:,.0f}"
    else:
        v["base"] = find_base(bars)
        v["ok"] = v["base"] is not None
        if not v["ok"]:
            v["why"] = "쉬는 구간 없음 (10~40일 폭 25%↓·좁아짐·저점 높아짐·최근 5일 20일선 위)"
    return v


def stop_width(price: float, low: float) -> float:
    return (price - low) / price if price else float("inf")


def order_qty(price: float, cash: float, width: float) -> int:
    """종목당 min(20만 원, 잔고 1% ÷ 손절폭)어치 정수 주."""
    if not price or width <= 0:
        return 0
    return int(min(PER_STOCK, cash * RISK / width) // price)


def held_days(buy_day: date, today: date, cal: list[date]) -> int:
    """산 날 포함 오늘이 몇 거래일째인지. cal = 거래일 목록 (오늘 전까지)."""
    return sum(1 for d in cal if buy_day <= d < today) + 1


# ---------------------------------------------------------------- 대상 고르기
def rank_universe(day: date, db_path: str = DEFAULT_DB_PATH) -> tuple[dict[str, dict], int, Optional[date]]:
    """day 전 거래일 기준 21·63·126거래일 상승률 순위 → ({코드: {name, ret, rank}}, 순위를 센 종목 수, 전 거래일).
    주식만(ETF·ETN·스팩·우선주 뺌), 상장 20거래일 안 뺌, 전 거래일에 거래된(거래량 > 0, 거래 정지 뺌) 종목만."""
    from kiwoom_trading.execution import strict_select
    from kiwoom_trading.strategies.hong_limitup.live import is_plain_stock
    conn = duckdb.connect(db_path, read_only=True)
    try:
        prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code = '005930' AND date < ?", [day]).fetchone()[0]
        names = dict(conn.execute("SELECT code, name FROM stocks WHERE NOT coalesce(delisted, false)").fetchall())
        rows = conn.execute(f"""
            WITH d AS (SELECT code, date, close, volume, row_number() OVER (PARTITION BY code ORDER BY date DESC) AS rn
                       FROM daily_ohlcv WHERE date < ? AND date >= ? - INTERVAL 400 DAY AND close > 0)
            SELECT code, max(date) FILTER (WHERE rn = 1 AND coalesce(volume, 0) > 0), max(close) FILTER (WHERE rn = 1),
                   {', '.join(f'max(close) FILTER (WHERE rn = {p + 1})' for p in PERIODS)}
            FROM d WHERE rn <= {max(PERIODS) + 1} GROUP BY code""", [day, day]).fetchall()
    finally:
        conn.close()
    listed = strict_select.load_context(day, db_path).listed
    pool = {}
    for code, last, c0, *past in rows:
        name = names.get(code)
        if not name or last != prev or is_etf(name) or not is_plain_stock(code, name) or code in listed:
            continue
        pool[code] = {"name": name, "ret": {p: (c0 / x - 1) if x else None for p, x in zip(PERIODS, past)}, "rank": {}}
    for p in PERIODS:
        have = sorted((v["ret"][p], c) for c, v in pool.items() if v["ret"][p] is not None)
        have.reverse()
        top = max(1, int(round(len(have) * TOP_PCT)))
        for r, (_, c) in enumerate(have[:top], 1):
            pool[c]["rank"][p] = (r, len(have))
    picked = {c: v for c, v in pool.items() if v["rank"]}
    return picked, len(pool), prev


class QullaContext(TurtleContext):
    """종목별 정규장 일봉 판정 칸 (🐢 TurtleContext 의 정규장 일봉 이어 붙이기·빈 날 채우기를 그대로 쓰고 계산만 바꿈)."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH, cache_path: Optional[str] = FILL_CACHE, **kw) -> None:
        super().__init__(day, db_path=db_path, cache_path=cache_path, sectors={}, **kw)
        if cache_path != TURTLE_CACHE and os.path.exists(TURTLE_CACHE):      # 🐢 가 받아 둔 빈 날도 씀 (읽기만)
            try:
                with open(TURTLE_CACHE, encoding="utf-8") as f:
                    for k, val in json.load(f).items():
                        self.cache.setdefault(k, val)
            except Exception:
                logging.warning("쿨라매기: 터틀 빈 날 캐시 읽기 실패 — 무시")

    def _finish(self, c: str) -> None:
        rows = self.rows.pop(c, {})
        self.missing.pop(c, None)
        bars = [(d, *v) for d, v in sorted(rows.items())]
        jump = price_jump(bars[-(MIN_ROWS + 5):])
        if jump:
            self.bad[c] = jump
            logging.info("쿨라매기: %s 오늘 뺌 — %s", c, jump)
            return
        if not bars:
            self.bad[c] = "정규장 일봉 없음"
            return
        self.info[c] = features(bars)


# ---------------------------------------------------------------- 가상 장부
class QullaBook:
    """🏄 쿨라매기 돌파 가상 장부. run_intraday 의 books 목록에서 tick(now, value_top) 로 돈다."""

    def __init__(self, store, market, today: date, ctx: QullaContext, ranks: dict[str, dict], n_ranked: int, client=None, regime=None,
                 notify: Optional[Callable[[str], object]] = None, db_path: str = DEFAULT_DB_PATH, fetch_budget: int = FETCH_BUDGET) -> None:
        self.conn = store.conn
        self.market, self.client, self.regime = market, client, regime
        self.today = today
        self.ctx, self.ranks, self.n_ranked = ctx, ranks, n_ranked
        self.notify = notify or (lambda text: None)
        self.ledger = Ledger(self.conn, BOOK, TAG, today, START_CASH, SLOTS)      # 알림은 이 장부가 직접 (🟣 형식)
        self.fetch_budget = fetch_budget
        conn = duckdb.connect(db_path, read_only=True)
        try:
            self.cal = [d for (d,) in conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code = '005930' AND date < ? ORDER BY 1",
                                                   [today]).fetchall()]
        finally:
            conn.close()
        self.cal_ext = self.cal + [today]   # 재현 때 다음 날로 넘어가도 산 날을 셀 수 있게
        self.hi5: dict[str, float] = {}     # 오늘 5분 고점
        self.done: set[str] = set()         # 오늘 판정 끝 (샀든 안 샀든)
        self.morning: set[str] = set()      # 오늘 아침(②③) 판정 끝난 거래 id
        self.gate_logged: Optional[str] = None
        self.full_logged = False
        self.reported = False
        self.summary_sink = None
        self.sig_count = 0

    # ------------------------------------------------------------ 상태
    def cash(self) -> float:
        return self.ledger.cash()

    def open_trades(self) -> list[dict]:
        return self.ledger.open_trades()

    def candidates(self) -> list[str]:
        return [c for c in self.ranks if (self.ctx.info.get(c) or {}).get("ok")]

    def _days(self, buy_day: date) -> int:
        return held_days(buy_day, self.today, self.cal_ext)

    # ------------------------------------------------------------ 1분마다
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        held = [t["code"] for t in self.open_trades()]
        todo = [c for c in list(held) + list(self.ranks) if c not in self.ctx.info and c not in self.ctx.bad]
        if todo:
            try:
                self.ctx.prepare(todo, self.fetch_budget, self.client)
                if not [c for c in todo if c not in self.ctx.info and c not in self.ctx.bad]:
                    self.log_candidates()
            except Exception:
                logging.exception("쿨라매기: 정규장 일봉 계산 실패")
        px = price_source(self.market, value_top)
        if SELL_START <= tm < SELL_END:
            self._sell(now, px)
        if BUY_START <= tm <= BUY_END:
            self._buy(now, value_top, px)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            if self.open_trades() or self.ledger.bought_today():
                (self.summary_sink.append if self.summary_sink is not None else self.notify)(self.summary())

    def log_candidates(self) -> None:
        ok = self.candidates()
        logging.info("%s 대상 %s종목 (상승률 상위 %s종목 중): %s", LABEL, len(ok), len(self.ranks),
                     ", ".join(f"{self.ranks[c]['name']} 윗선 {self.ctx.info[c]['base']['top']:,.0f}" for c in ok) or "없음")

    # ------------------------------------------------------------ 매도
    def _open_price(self, code: str, px) -> Optional[float]:
        try:
            q = self.market.quote(code, integrated=False)
        except Exception:
            q = None
        if q is not None and getattr(q, "open", 0):
            return float(q.open)
        return px(code, False)

    def _sell(self, now: datetime, px) -> None:
        for t in self.open_trades():
            plan = Plan.loads(t["plan"])
            if t["date"] < self.today and t["id"] not in self.morning:
                if not self._morning(now, t, plan, px):
                    continue                          # 아직 판정 못 함 (10일선 자료 없음) → 손절 감시도 아침 판정 뒤
                t = next((x for x in self.open_trades() if x["id"] == t["id"]), None)
                if t is None:
                    continue
                plan = Plan.loads(t["plan"])
            p = px(t["code"], False)
            if p and plan.stop and p <= plan.stop:
                self._close(now, t, p, ("본전 손절" if plan.stop >= t["buy_price"] else "손절") + f" — 현재가 {p:,.0f} ≤ 손절선 {plan.stop:,.0f}")

    def _morning(self, now: datetime, t: dict, plan: Plan, px) -> bool:
        """다음 거래일 09:00 판정 (③ 10일선 → ② 5거래일째 절반). 판정했으면 True."""
        v = self.ctx.info.get(t["code"])
        if v is None or v.get("ma10") is None:
            if t["code"] in self.ctx.bad:
                logging.warning("쿨라매기: %s 10일선 못 구함 (%s) — 손절선만 봄", t["name"], self.ctx.bad[t["code"]])
                self.morning.add(t["id"])
                return True
            return False
        o = self._open_price(t["code"], px)
        if not o:
            return False
        self.morning.add(t["id"])
        if v["close"] < v["ma10"]:
            self._close(now, t, o, f"10일선 아래 마감 ({v['last']:%m-%d} 정규장 종가 {v['close']:,.0f} < 10일선 {v['ma10']:,.0f}) → 다음 거래일 09:00 시가")
            return True
        n = self._days(t["date"])
        if n >= HALF_DAY and not (t["part_qty"] or 0) and not (plan.stop and plan.stop >= t["buy_price"]):
            qty, buy = t["qty"], t["buy_price"]
            h = qty // 2
            plan.stop = float(buy)
            if h >= 1:
                self.conn.execute("UPDATE ledger_trades SET part_ts = ?, part_qty = ?, part_price = ?, plan = ? WHERE id = ?",
                                  [now.replace(tzinfo=None), h, float(o), plan.dumps(), t["id"]])
                self.notify(f"🟣 가상 절반 매도 {t['name']}({t['code']}) {h}주 × {o:,.0f}원 ({o / buy - 1 - COST:+.2%}, 비용 포함) "
                            f"({LABEL} 가상 장부, 주문 없음)\n  [{LABEL}] 산 날 포함 {n}거래일째 09:00 시가 절반 · 남은 {qty - h}주 손절선 → 산 값 {buy:,.0f}원(본전) · "
                            f"정규장 종가 10일선 아래 마감이면 다음 거래일 09:00 나머지")
                logging.info("%s 절반 매도 %s %s주 × %s", LABEL, t["name"], h, o)
            else:
                self.conn.execute("UPDATE ledger_trades SET plan = ? WHERE id = ?", [plan.dumps(), t["id"]])
                logging.info("%s %s 1주라 절반 매도 없이 손절선만 본전 %s", LABEL, t["name"], buy)
        return True

    def _close(self, now: datetime, t: dict, price: float, reason: str) -> None:
        self.ledger._close(now, t, price, reason)
        self.done.add(t["code"])            # 판 날은 같은 종목 다시 안 삼
        pnl = self.conn.execute("SELECT pnl FROM ledger_trades WHERE id = ?", [t["id"]]).fetchone()[0] or 0
        part, qty, buy = t["part_qty"] or 0, t["qty"], t["buy_price"]
        cash = self.cash()
        self.notify(f"🟣 가상 매도 {t['name']}({t['code']}) {qty - part}주 × {price:,.0f}원 — {reason}"
                    + (f" (절반 {part}주는 {t['part_price']:,.0f}원)" if part else "")
                    + f"\n  [{LABEL}] 합계 {pnl / (qty * buy):+.2%} ({pnl:+,.0f}원, 비용 포함) → 잔고 {cash:,.0f}원 (시작 대비 {cash / START_CASH - 1:+.1%}, 주문 없음)")

    # ------------------------------------------------------------ 매수
    def _five_min_high(self, code: str) -> Optional[float]:
        if code in self.hi5:
            return self.hi5[code]
        bars = []
        try:
            bars = [b for b in fetch_minute_bars(self.client, code, self.today, "KRX")
                    if time(9, 0) <= b["ts"].time() < OPEN_HIGH_END and b.get("high")]
        except Exception:
            logging.warning("쿨라매기: %s 1분봉 조회 실패 — 다음 확인 때 다시", code)
            return None
        if not bars:
            return None
        self.hi5[code] = float(max(b["high"] for b in bars))
        return self.hi5[code]

    def _buy(self, now: datetime, value_top, px) -> None:
        gate = regime_gate(self.regime, now)
        if gate:
            if gate != self.gate_logged:
                logging.info("%s: %s — 안 삼", LABEL, gate)
                self.gate_logged = gate
            return
        held = {t["code"] for t in self.open_trades()}
        in_rank = {r.code for r in value_top if getattr(r, "price", None)}
        budget = QUOTE_BUDGET
        for c in self.candidates():
            if c in self.done or c in held or self.ledger.bought_today(c):
                continue
            v, rk = self.ctx.info[c], self.ranks[c]
            hi5 = self._five_min_high(c)
            if hi5 is None:
                continue
            trigger = max(v["base"]["top"], hi5)
            if c not in in_rank:
                if budget <= 0:
                    continue
                budget -= 1
            p = px(c, False)
            if not p or p <= trigger:
                continue
            try:
                q = self.market.quote(c, integrated=False)
            except Exception:
                logging.warning("쿨라매기: %s 시세 조회 실패", c)
                continue
            if not q or not q.price or not q.low:
                continue
            price, low = float(q.price), float(q.low)
            if price <= trigger:
                continue
            self.done.add(c)
            self.sig_count += 1
            w = stop_width(price, low)
            why = self._reason(c, v, rk, hi5, price, low, w)
            if w > v["adr"]:
                logging.info("%s 포착만 (안 삼) %s: 손절폭 %.2f%% > ADR20 %.2f%% — %s", LABEL, rk["name"], w * 100, v["adr"] * 100, why)
                continue
            if len(self.open_trades()) >= SLOTS:
                logging.info("%s 포착만 (안 삼) %s: 동시 %s종목 다 참 — %s", LABEL, rk["name"], SLOTS, why)
                continue
            cash = self.cash()
            qty = order_qty(price, cash, w)
            if qty < 1:
                logging.info("%s 포착만 (안 삼) %s: 1주도 못 삼 (가격 %s, 잔고 %s) — %s", LABEL, rk["name"], price, cash, why)
                continue
            tid = self.ledger.buy(now, c, rk["name"], price, Plan(stop=low, next_day=False), note=why, qty=qty, quiet=True)
            if not tid:
                logging.info("%s 포착만 (안 삼) %s: 장부가 안 받음 (오늘 %s건) — %s", LABEL, rk["name"], self.ledger.n_today(), why)
                continue
            held.add(c)
            self.notify(f"🟣 가상 매수 {rk['name']}({c}) {qty}주 × {price:,.0f}원 = {qty * price / 1e4:,.0f}만 원 ({LABEL} 가상 장부, 주문 없이 기록만)\n"
                        f"  [{LABEL} {now:%H:%M}] 손절 {low:,.0f}원 ({low / price - 1:+.1%}, 오늘 저가) · 산 날 포함 {HALF_DAY}거래일째 09:00 시가 절반 → "
                        f"남은 물량 손절 = 산 값 · 정규장 종가가 {EXIT_MA}일선 아래로 마감하면 다음 거래일 09:00 나머지 · 목표가·보유 기간 없음 "
                        f"(잔고 {cash:,.0f}원)\n  포착: {why}")

    def _reason(self, c: str, v: dict, rk: dict, hi5: float, price: float, low: float, w: float) -> str:
        names = {21: "1달", 63: "3달", 126: "6달"}
        ranks = " · ".join(f"{names[p]}({p}일) {rk['ret'][p]:+.0%} {r}위/{n}" for p, (r, n) in sorted(rk["rank"].items()))
        b = v["base"]
        return (f"상승률 상위 {TOP_PCT:.0%} — {ranks} · 정규장 63일 {v['ret63']:+.0%} · 쉬는 구간 {b['len']}거래일 ({b['start']:%m-%d}~{b['end']:%m-%d}, "
                f"폭 {b['width']:.1%}, 뒤 절반 {b['w2']:.1%} < 앞 절반 {b['w1']:.1%}, 저점 {b['lo1']:,.0f} → {b['lo2']:,.0f}) · 윗선 {b['top']:,.0f} · "
                f"5분 고점 {hi5:,.0f} → 현재가 {price:,.0f} 돌파 · 손절폭 {w:.1%} (오늘 저가 {low:,.0f}) ≤ ADR20 {v['adr']:.1%}")

    # ------------------------------------------------------------ 요약
    def summary(self) -> str:
        return f"{LABEL} 가상 장부 {self.today:%m-%d} (오늘 돌파 판정 {self.sig_count}건)\n" + self.ledger.summary_line()
