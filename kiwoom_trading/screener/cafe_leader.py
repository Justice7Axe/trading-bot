"""☕ [카페] 테마 대장 체크리스트 + 1천만 원 가상 장부 (주문 없음).
(2026-10-27 사용자: 불개미 카페 '수학은직관력' 10-26 로보티즈·루닛 일지의 관점을 우리 규칙에 넣고, 포착되게 보완)

카페 관점 → 우리 체크 (매분 09:00~10:30, 대상 = 전날 대금 200위 + 지금 KRX 대금 상위 200 — 실시간이라 지금 순위는 미래 정보 아님.
  백테스트는 1분봉 자료 쏠림 때문에 전날 200위 안만 시험했다. 10-26 루닛은 전날 대금 59억이라 그 밖이었음):
  ① 장 초반 테마 형성·대장 : 네이버 테마 중 지금 +4%↑ 종목 2개↑, 그중 오늘 누적 대금 1위이고 +5%↑
  ② 최근 기관 수급        : 전날까지 3거래일 중 기관 순매수 + 2일↑ (일봉 투자자 확정치) — 표시만 (1년: 넣으면 오히려 나빠짐)
  ③ NXT 프리장 햄버거      : 08:00~08:59 통합 1분봉 누적 대금 ≥ 50억 → 9시 15분 기다림 해제 (아니면 09:15 부터)
  ④ 일봉 자리             : 직전 15거래일 고가÷저가 −1 ≤ 30% 박스 + 그 시각 가격 > 15일 고가 (루닛 '3주 박스 전고점 돌파')
  ⑤ 오늘 수급(잠정)       : 그 시각까지 외국인·기관 가집계, 프로그램 순매수 — 표시만 (과거 자료 없어 검증 불가)
  ⑥ 매수 자리             : 1분봉 당일 고점 돌파 + 햄버거(봉 대금 ≥ 10억·직전 5봉 평균 2배) → 돌파한 고점에 지정가, 10분 안 눌림 체결
가상 장부는 ①③④⑥ 이 모두 맞을 때만 산다 (텔레그램 체크리스트는 ①③⑥ 이 맞을 때) (1년 run_cafe_leader_backtest: 91건 건당 +0.82%, 앞 +1.21%/뒤 +0.37%,
  최고 5일 빼도 +, 단 조건 16개 중 고른 값이라 우연일 수 있음 → 이 장부로 확인). ①③⑥ 만 맞으면 체크리스트 알림만.
매도: 절반 +2.5%, 나머지 상한가 닿으면 상한가 / −2% 손절 즉시 / 아니면 다음 날 09:00. 하루 3종목, 종목당 잔고 ÷ 3. 비용 0.25%.
"""
import logging
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

import duckdb

from kiwoom_trading.analysis.indicators.hong import upper_limit
from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

TAG = "☕ [카페]"
START_CASH = 10_000_000
SLOTS = 3
UP_MIN, LEAD_MIN = 0.04, 0.05
PRE_VALUE = 5e9
BAR_VALUE, BAR_MULT = 1e9, 2.0
BOX_DAYS, BOX_WIDTH = 15, 0.30
PULL_BARS = 10
HALF_TP, STOP, COST = 0.025, 0.02, 0.0025
START, LAST_BUY = time(9, 0), time(10, 30)
OPEN, CLOSE, REPORT_AT = time(9, 0), time(15, 30), time(15, 40)
MAX_LEADERS = 8               # 한 번에 1분봉을 받는 대장 수 (호출 간격 0.25초)
NAVER_DB = os.path.join(PROJECT_ROOT, "data", "naver_groups.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cafe_checks (     -- ☕ 테마 대장 돌파 체크리스트 (알림·검증용)
    date DATE, ts TIMESTAMP, code VARCHAR, name VARCHAR, theme VARCHAR, n_up INTEGER, chg DOUBLE,
    inst3 INTEGER, pre_value DOUBLE, box BOOLEAN, level DOUBLE, foreign_ DOUBLE, inst DOUBLE, program DOUBLE, decision VARCHAR
);
CREATE TABLE IF NOT EXISTS cafe_trades (
    id VARCHAR PRIMARY KEY, date DATE, code VARCHAR, name VARCHAR, buy_ts TIMESTAMP, buy_price DOUBLE, qty INTEGER,
    limit_price DOUBLE, half_ts TIMESTAMP, half_qty INTEGER, sell_ts TIMESTAMP, sell_price DOUBLE, reason VARCHAR, pnl DOUBLE, status VARCHAR
);
CREATE TABLE IF NOT EXISTS cafe_days (date DATE PRIMARY KEY, reported BOOLEAN, note VARCHAR);
"""


@dataclass
class CafeStock:
    code: str
    name: str
    hi15: Optional[float]
    lo15: Optional[float]
    inst3: Optional[int]        # 최근 3일 중 기관 순매수 + 날 수


@dataclass
class CafeContext:
    day: Optional[date]
    stocks: dict = field(default_factory=dict)      # code → CafeStock (일봉 있는 전 종목)
    top200: set = field(default_factory=set)        # 전날 대금 200위 안
    themes: dict = field(default_factory=dict)      # code → {테마 이름}


def load_cafe_context(conn, today: date, naver_db: str = NAVER_DB) -> CafeContext:
    day = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [today]).fetchone()[0]
    if day is None:
        return CafeContext(None)
    rows = conn.execute(f"""
        WITH days AS (SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date <= ? ORDER BY date DESC LIMIT {BOX_DAYS}),
             box AS (SELECT code, max(high) AS hi, min(low) AS lo, count(*) AS n FROM daily_ohlcv
                     WHERE date IN (SELECT date FROM days) GROUP BY code),
             d3 AS (SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date <= ? ORDER BY date DESC LIMIT 3),
             inv AS (SELECT code, count(*) FILTER (WHERE institution > 0) AS pos, count(*) AS n FROM investor_daily
                     WHERE date IN (SELECT date FROM d3) GROUP BY code)
        SELECT s.code, s.name, b.hi, b.lo, b.n, i.pos, i.n FROM stocks s JOIN box b USING (code) LEFT JOIN inv i USING (code)""",
                        [day, day]).fetchall()
    stocks = {c: CafeStock(c, nm, hi if n == BOX_DAYS else None, lo if n == BOX_DAYS else None, pos if ni == 3 else None)
              for c, nm, hi, lo, n, pos, ni in rows}
    top200 = {c for (c,) in conn.execute("SELECT code FROM daily_ohlcv WHERE date = ? AND value IS NOT NULL ORDER BY value DESC LIMIT 200",
                                         [day]).fetchall()}
    themes = defaultdict(set)
    try:
        copy = os.path.join(tempfile.gettempdir(), f"cafe_{os.getpid()}_naver_groups.duckdb")
        shutil.copy(naver_db, copy)
        ng = duckdb.connect(copy, read_only=True)
        try:
            for name, c in ng.execute("SELECT name, code FROM naver_groups WHERE kind='테마' AND date=(SELECT max(date) FROM naver_groups)").fetchall():
                themes[c].add(name)
        finally:
            ng.close()
    except Exception:
        logging.exception("카페: 네이버 테마 목록을 못 읽음 (테마 대장 판단 불가)")
    return CafeContext(day, stocks, top200, dict(themes))


def _val(b: dict) -> float:
    return b["volume"] * (b["high"] + b["low"] + b["close"]) / 3


class CafeLeaderWatcher:
    def __init__(self, store, market, client, today: date, ctx: CafeContext,
                 notify: Optional[Callable[[str], object]] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.client = client
        self.today = today
        self.ctx = ctx
        self.notify = notify or (lambda text: None)
        self.conn.execute(SCHEMA)
        row = self.conn.execute("SELECT reported FROM cafe_days WHERE date = ?", [today]).fetchone()
        self.reported = bool(row and row[0])
        self.checked: set[str] = {c for (c,) in self.conn.execute("SELECT DISTINCT code FROM cafe_checks WHERE date = ?", [today]).fetchall()}
        self.pending: dict[str, dict] = {}      # code → 눌림 지정가 대기 {level, until, info}
        self.limits: dict[str, int] = {}

    # ------------------------------------------------------------ 상태
    def cash(self) -> float:
        return START_CASH + (self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM cafe_trades WHERE status = 'closed'").fetchone()[0] or 0)

    def open_trades(self):
        return self.conn.execute("""SELECT id, date, code, name, buy_price, qty, limit_price, half_qty FROM cafe_trades
                                    WHERE status = 'open' ORDER BY buy_ts""").fetchall()

    def _flow(self, code: str, now: datetime):
        ts = now.replace(tzinfo=None)
        q = """SELECT net_amount FROM investor_intraday WHERE date = ? AND code = ? AND investor = ? AND ts <= ? ORDER BY ts DESC LIMIT 1"""
        fo = self.conn.execute(q, [self.today, code, "foreign", ts]).fetchone()
        ins = self.conn.execute(q, [self.today, code, "institution", ts]).fetchone()
        pg = self.conn.execute("""SELECT net_amount FROM program_intraday WHERE date = ? AND code = ? AND ts <= ?
                                  ORDER BY ts DESC LIMIT 1""", [self.today, code, ts]).fetchone()
        return (fo[0] if fo else None), (ins[0] if ins else None), (pg[0] if pg else None)

    # ------------------------------------------------------------ 매분
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        if OPEN <= tm < CLOSE:
            self._manage(now, value_top)
        if START <= tm <= (datetime.combine(self.today, LAST_BUY) + timedelta(minutes=PULL_BARS)).time() and self.ctx.stocks:
            self._scan(now, value_top)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            self.conn.execute("INSERT OR REPLACE INTO cafe_days VALUES (?, ?, ?)", [self.today, True, self._note()])
            self.notify(self.summary())

    def leaders(self, value_top) -> dict[str, tuple[str, int, float]]:
        """지금 테마 대장 → {code: (테마, +4%↑ 종목 수, 등락률)} (지금 대금 상위 200 안 종목으로 판단)."""
        rows = [r for r in value_top if r.code in self.ctx.stocks and r.change_rate is not None and r.trade_value]
        by_theme = defaultdict(list)
        for r in rows:
            if r.change_rate >= UP_MIN:
                for th in self.ctx.themes.get(r.code, ()):
                    by_theme[th].append(r)
        out = {}
        for th, mem in by_theme.items():
            if len(mem) < 2:
                continue
            top = max(mem, key=lambda r: r.trade_value)
            if top.change_rate >= LEAD_MIN and (top.code not in out or len(mem) > out[top.code][1]):
                out[top.code] = (th, len(mem), top.change_rate)
        return out

    def _scan(self, now: datetime, value_top) -> None:
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        lead = self.leaders(value_top) if now.time() <= LAST_BUY else {}
        codes = [c for c in lead if c not in self.checked][:MAX_LEADERS] + [c for c in self.pending]
        for code in dict.fromkeys(codes):
            try:
                bars = [b for b in fetch_minute_bars(self.client, code, self.today, "AL") if b["ts"] < minute]
            except Exception as exc:
                logging.warning("카페: %s 1분봉 조회 실패: %s", code, exc)
                continue
            if code in self.pending:
                self._try_fill(now, code, bars)
            elif code in lead:
                self._check_breakout(now, code, bars, lead[code])

    def _check_breakout(self, now: datetime, code: str, bars: list[dict], lead) -> None:
        pre = [b for b in bars if b["ts"].time() < time(9, 0)]
        reg = [b for b in bars if time(9, 0) <= b["ts"].time() <= time(15, 30)]
        if len(reg) < 4:
            return
        pre_value = sum(_val(b) for b in pre)
        start = time(9, 0) if pre_value >= PRE_VALUE else time(9, 15)
        x = reg[-1]
        hi = max(b["high"] for b in reg[:-1])
        prev5 = [_val(b) for b in reg[-6:-1]]
        bv = _val(x)
        if not (x["ts"].time() >= start and x["close"] > hi and x["close"] > x["open"]
                and bv >= BAR_VALUE and bv >= BAR_MULT * (sum(prev5) / len(prev5))):
            return
        st = self.ctx.stocks[code]
        box = bool(st.hi15 and st.lo15 and st.hi15 / st.lo15 - 1 <= BOX_WIDTH and x["close"] > st.hi15)
        fo, ins, pg = self._flow(code, now)
        all_ok = box and len(self.conn.execute("SELECT 1 FROM cafe_trades WHERE date = ?", [self.today]).fetchall()) < SLOTS
        decision = f"눌림 지정가 {hi:,.0f} 대기 (10분)" if all_ok else ("④ 일봉 박스 아님 → 알림만" if not box else f"오늘 {SLOTS}종목 다 참")
        self.checked.add(code)
        th, n_up, chg = lead
        th = th if code in self.ctx.top200 else f"{th} (전날 대금 200위 밖)"
        self.conn.execute("INSERT INTO cafe_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          [self.today, now.replace(tzinfo=None), code, st.name, th, n_up, chg, st.inst3, pre_value, box, hi,
                           fo, ins, pg, decision])
        if all_ok:
            self.pending[code] = dict(level=hi, until=x["ts"] + timedelta(minutes=PULL_BARS), name=st.name)
        logging.info("카페 체크 %s %s → %s (프리장 %.0f억)", st.name, x["ts"], decision, pre_value / 1e8)
        if pre_value < PRE_VALUE and not all_ok:     # 텔레그램은 ①③⑥(카페 핵심)이 맞을 때만, 나머지는 cafe_checks 에 기록만
            return
        ok = lambda b: "✅" if b else "❌"
        fmt = lambda v: "-" if v is None else f"{v / 1e8:+,.0f}억"
        hi15 = f"{st.hi15:,.0f}" if st.hi15 else "-"
        width = f"{st.hi15 / st.lo15 - 1:.0%}" if st.hi15 and st.lo15 else "-"
        self.notify(
            f"{TAG} 테마 대장 돌파 체크 {st.name}({code}) {x['ts']:%H:%M} {x['close']:,}원 ({chg:+.1%})\n"
            f"  ① 테마 대장 ✅ '{th}' (+4%↑ {n_up}종목 중 대금 1위)\n"
            f"  ② 최근 기관 {ok((st.inst3 or 0) >= 2)} 3일 중 {st.inst3 if st.inst3 is not None else '?'}일 순매수 (참고)\n"
            f"  ③ 프리장 햄버거 {ok(pre_value >= PRE_VALUE)} 08시 대금 {pre_value / 1e8:,.0f}억 → {'09:00 부터' if pre_value >= PRE_VALUE else '09:15 부터'}\n"
            f"  ④ 일봉 박스 돌파 {ok(box)} 15일 고가 {hi15} (폭 {width})\n"
            f"  ⑤ 오늘 수급(잠정): 외국인 {fmt(fo)} · 기관 {fmt(ins)} · 프로그램 {fmt(pg)} (참고)\n"
            f"  ⑥ 1분봉 고점 {hi:,.0f} 돌파 + 햄버거 {bv / 1e8:,.0f}억 ✅\n"
            f"  → {decision} (가상 장부, 주문 없음 · 1년 ①③④⑥ 91건 건당 +0.82%)")

    def _try_fill(self, now: datetime, code: str, bars: list[dict]) -> None:
        p = self.pending[code]
        after = [b for b in bars if b["ts"] > p["until"] - timedelta(minutes=PULL_BARS) and b["ts"] <= p["until"]]
        for b in after:
            if b["low"] <= p["level"]:
                self.pending.pop(code)
                self._buy(now, code, p["name"], min(b["open"], p["level"]), b["ts"])
                return
        if bars and bars[-1]["ts"] >= p["until"]:
            self.pending.pop(code)
            self.conn.execute("UPDATE cafe_checks SET decision = decision || ' → 10분 안 안 눌려 못 삼' WHERE date = ? AND code = ?", [self.today, code])
            self.notify(f"{TAG} {p['name']} 돌파 고점 {p['level']:,.0f} 까지 10분 안에 안 눌려 못 삼 (가상)")

    def _buy(self, now, code, name, price, ts) -> None:
        cash = self.cash()
        qty = int(cash / SLOTS // price)
        if qty < 1:
            return
        try:
            q = self.market.quote(code, integrated=False)
            lim = upper_limit(float(q.base_price)) if q and q.base_price else price * 1.3
        except Exception:
            lim = price * 1.3
        self.conn.execute("""INSERT OR REPLACE INTO cafe_trades (id, date, code, name, buy_ts, buy_price, qty, limit_price, half_qty, status)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'open')""",
                          [f"{now:%Y%m%d}-{code}", self.today, code, name, ts, price, qty, lim])
        self.notify(f"{TAG} 눌림 가상 매수 {name}({code}) {qty}주 × {price:,.0f}원 ({ts:%H:%M})\n"
                    f"  매도: 절반 +2.5% {price * (1 + HALF_TP):,.0f} · 손절 −2% {price * (1 - STOP):,.0f} · 상한가 {lim:,.0f} 전부 · 아니면 다음 날 09:00 (잔고 {cash:,.0f}원)")

    def _manage(self, now: datetime, value_top) -> None:
        px = {r.code: r.price for r in value_top if r.price}
        for tid, d, code, name, buy, qty, lim, half_qty in self.open_trades():
            price = px.get(code)
            if price is None or d < self.today:
                try:
                    q = self.market.quote(code, integrated=False)
                    price = q.price if q and q.price else None
                except Exception:
                    logging.warning("카페: %s 시세 조회 실패", code)
            if not price:
                continue
            price = float(price)
            half_qty = half_qty or 0
            if d < self.today:
                self._close(now, tid, name, code, buy, qty, half_qty, price, "다음 날 09:00 매도")
            elif price <= buy * (1 - STOP):
                self._close(now, tid, name, code, buy, qty, half_qty, price, "손절 −2%")
            elif price >= lim:
                self._close(now, tid, name, code, buy, qty, half_qty, lim, "상한가 전부 매도")
            elif not half_qty and price >= buy * (1 + HALF_TP) and qty >= 2:
                h = qty // 2
                self.conn.execute("UPDATE cafe_trades SET half_ts = ?, half_qty = ? WHERE id = ?", [now.replace(tzinfo=None), h, tid])
                self.notify(f"{TAG} {name} +2.5% → 절반 {h}주 매도 {price:,.0f}원 (가상)")

    def _close(self, now, tid, name, code, buy, qty, half_qty, price, reason) -> None:
        rest = qty - half_qty
        pnl = half_qty * buy * HALF_TP + rest * (price - buy) - qty * buy * COST
        self.conn.execute("UPDATE cafe_trades SET sell_ts = ?, sell_price = ?, reason = ?, pnl = ?, status = 'closed' WHERE id = ?",
                          [now.replace(tzinfo=None), price, reason, pnl, tid])
        cash = self.cash()
        self.notify(f"{TAG} 매도 {name}({code}) {rest}주 × {price:,.0f}원 — {reason}, 합계 {pnl / (qty * buy):+.2%} ({pnl:+,.0f}원)"
                    f" → 잔고 {cash:,.0f}원 (시작 대비 {cash / START_CASH - 1:+.1%}, 가상 기록)")

    def _note(self) -> str:
        rows = self.conn.execute("SELECT name, decision FROM cafe_checks WHERE date = ? ORDER BY ts", [self.today]).fetchall()
        return "; ".join(f"{n} {d}" for n, d in rows) if rows else "테마 대장 돌파 없음"

    def summary(self) -> str:
        cash = self.cash()
        n, w = self.conn.execute("SELECT count(*), count(*) FILTER (WHERE pnl > 0) FROM cafe_trades WHERE status = 'closed'").fetchone()
        held = self.open_trades()
        hold = ", ".join(f"{h[3]} {h[5] - (h[7] or 0)}주" for h in held) if held else "없음"
        return (f"{TAG} 1천만 가상 장부 {self.today:%m-%d} 마감: 잔고 {cash:,.0f}원 (시작 대비 {cash / START_CASH - 1:+.1%}), "
                f"끝난 매매 {n}건 중 수익 {w}건, 보유 {hold}\n  오늘 체크: {self._note()}")
