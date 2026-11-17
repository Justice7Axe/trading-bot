"""☕ [카페] 테마 대장 체크리스트 + 1천만 원 가상 장부 (주문 없음).
(2026-10-27 사용자: 불개미 카페 '수학은직관력' 10-26 로보티즈·루닛 일지의 관점을 우리 규칙에 넣고, 포착되게 보완)

카페 관점 → 우리 체크 (매분 09:00~10:30, 대상 = 전날 대금 200위 + 지금 KRX 대금 상위 200 — 실시간이라 지금 순위는 미래 정보 아님.
  백테스트는 1분봉 자료 쏠림 때문에 전날 200위 안만 시험했다. 10-26 루닛은 전날 대금 59억이라 그 밖이었음):
  ① 장 초반 테마 형성·대장 : 네이버 테마 중 지금 +4%↑ 종목 2개↑, 그중 오늘 누적 대금 1위이고 +5%↑
  ② 최근 기관 수급        : 전날까지 3거래일 중 기관 순매수 + 2일↑ (일봉 투자자 확정치) — 표시만 (1년: 넣으면 오히려 나빠짐)
  ③ NXT 프리장 햄버거      : 08:00~08:59 통합 1분봉 누적 대금 ≥ 50억 → 9시 15분 기다림 해제 (아니면 09:15 부터)
  ④ 일봉 자리             : 직전 10거래일 고가÷저가 −1 ≤ 30% 박스 + 그 시각 가격 > 10일 고가 (처음 15일 → 2026-10-27 사용자 '10일·30%':
                           1년 140건 +0.81%, 앞 +0.84/뒤 +0.77 — 15일 91건 +0.82%, 5일·30% +0.33%)
  ⑤ 오늘 수급(잠정)       : 그 시각까지 외국인·기관 가집계, 프로그램 순매수 — 표시만 (과거 자료 없어 검증 불가)
  ⑥ 매수 자리             : 1분봉 당일 고점 돌파 + 햄버거(봉 대금 ≥ 10억·직전 5봉 평균 2배) → 돌파한 고점에 지정가, 10분 안 눌림 체결
2026-10-30 사용자 '15일 박스 아님 조건도 빼줘' → ④ 는 표시만, 가상 장부·모의·실전은 ①③⑥ 이면 산다
  (1년 눌림 지정가 ①+③ 601건 건당 +0.24%, 앞 +0.38/뒤 +0.12, 최고 5일 빼면 −31만, 낙폭 53만 — ④ 넣은 140건 +0.81% 보다 건당·낙폭 나쁨, 합계는 큼).
옛 규칙: 가상 장부는 ①③④⑥ 이 모두 맞을 때만 산다 (텔레그램 체크리스트는 ①③⑥ 이 맞을 때) (1년 run_cafe_leader_backtest: 91건 건당 +0.82%, 앞 +1.21%/뒤 +0.37%,
  최고 5일 빼도 +, 단 조건 16개 중 고른 값이라 우연일 수 있음 → 이 장부로 확인). ①③⑥ 만 맞으면 체크리스트 알림만.
매도: 절반 +2.5%, 나머지 상한가 닿으면 상한가 / −2% 손절 즉시 / 아니면 다음 날 09:00. 하루 3종목, 종목당 잔고 ÷ 3. 비용 0.25%.

👑 테마 1등 포착 (2026-11-18 사용자 '대장주는 포착이 반드시 되도록'): 11-17 카페 특징테마 대장(인디에프·세미파이브·현대백화점)이
  하나도 안 잡힌 원인 = ① 이 '지금 KRX 대금 상위 200' 안에서만, '테마 안 대금 1위'로 대장을 골라서 (인디에프는 상한가 잠긴 뒤 09:43 에야
  192위, 현대백화점은 13:39 에야 200위 안). 그래서 매분 09:00~15:20 대금 상위 200 + 등락률 상위 200(ka10027 통합, 대금 10억↑)을 합쳐
  네이버 테마 안 +4%↑ 2종목↑ 중 **등락률 1등**(+29.5%↑ 끼리는 대금 순, +5%↑, 신규 상장 20거래일 안 제외)을 '테마 1등'으로 기록한다
  (표 cafe_leader_hits, 로그, 15:42 ☕ 마감 요약). 매수 규칙(①③⑥)은 그대로 — 등락률 1등으로 ①을 바꾼 1년 시험(①+③ 눌림 655건 −0.01%)이
  지금 규칙(대금 1위 601건 +0.24%)보다 나빠 매수에는 쓰지 않음. 그래서 알림도 따로 없음(텔레그램 원칙: 매매 대상 아닌 포착은 알림 금지).
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

from kiwoom_trading.common.krx import upper_limit
from kiwoom_trading.common.leader import theme_leaders
from kiwoom_trading.execution.ledger import Ledger, Plan, price_source
from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

TAG = "☕ [카페]"
KIND = "카페 테마 대장"     # 모의·실전 신호 종류 (2026-10-27 사용자 "모의·실전 모두") — 가상 장부가 살 때 함께 넘긴다
START_CASH = 10_000_000
SLOTS = 3
BOOK = "카페 대장"            # 공용 가상 장부(execution/ledger.py) 이름
UP_MIN, LEAD_MIN = 0.04, 0.05
PRE_VALUE = 5e9
BAR_VALUE, BAR_MULT = 1e9, 2.0
BOX_DAYS, BOX_WIDTH = 10, 0.30
PULL_BARS = 10
HALF_TP, STOP, COST = 0.025, 0.02, 0.0025
# 추격 금지 (2026-11-18, 11-17 가온칩스 +21% 자리 매수 → 손절): 돌파 고점(눌림 지정가)이 어제 대비 +15% 넘으면 안 삼.
# 1년(exit_study.py): ①③⑥ 601건 +0.20%(최고 5일 빼면 −54만) → 546건 +0.32% ★(앞 +0.53/뒤 +0.13, 최고 5일 빼도 +5만),
# 계좌 100만 100.3만 → 106.7만·낙폭 15→12%, 10만 104,612 → 105,422. 손절 −3·−4%·절반 뒤 본전 손절은 못 통과.
CHASE_MAX = 0.15
START, LAST_BUY = time(9, 0), time(10, 30)
OPEN, CLOSE, REPORT_AT = time(9, 0), time(15, 30), time(15, 40)
MAX_LEADERS = 8               # 한 번에 1분봉을 받는 대장 수 (호출 간격 0.25초)
NAVER_DB = os.path.join(PROJECT_ROOT, "data", "naver_groups.duckdb")
# 👑 테마 1등 포착 (기록만, 2026-11-18)
TOP_START, TOP_END = time(9, 0), time(15, 20)
RISER_VALUE = "100"           # ka10027 거래대금 조건 '100' = 10억↑ (인디에프 11-17 09:05 누적 12억)
LIMIT_TIE = 0.295             # 이 위(상한가 근처)끼리는 등락률 같다고 보고 대금 순
NEW_LISTING_DAYS = 20         # strict_select 와 같은 기준 (상장일 = 1거래일째)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cafe_checks (     -- ☕ 테마 대장 돌파 체크리스트 (알림·검증용)
    date DATE, ts TIMESTAMP, code VARCHAR, name VARCHAR, theme VARCHAR, n_up INTEGER, chg DOUBLE,
    inst3 INTEGER, pre_value DOUBLE, box BOOLEAN, level DOUBLE, foreign_ DOUBLE, inst DOUBLE, program DOUBLE, decision VARCHAR
);
CREATE TABLE IF NOT EXISTS cafe_leader_hits (   -- 👑 테마 1등(등락률) 처음 된 순간 — 종목당 하루 한 줄 (기록만)
    date DATE, ts TIMESTAMP, code VARCHAR, name VARCHAR, theme VARCHAR, n_up INTEGER, chg DOUBLE, value DOUBLE,
    prev_top200 BOOLEAN, value_leader BOOLEAN, note VARCHAR
);
"""


def top_by_chg(rows, themes: dict, up_min: float = UP_MIN, lead_min: float = LEAD_MIN) -> dict[str, tuple[str, int, float]]:
    """rows = [(code, 등락률, 누적 대금)] → 테마 등락률 1등 {code: (테마, +4%↑ 종목 수, 등락률)}.
    카페 특징테마의 1등 = 그날 등락률 순 (research/cafe_leaders/parse.py) — 상한가 근처(+29.5%↑) 끼리는 대금 큰 쪽."""
    keyed = [(c, (min(ch, LIMIT_TIE) if ch >= LIMIT_TIE else ch), v, ch) for c, ch, v in rows if ch is not None and v]
    by_theme = defaultdict(list)
    for c, k, v, ch in keyed:
        if ch >= up_min:
            for th in themes.get(c, ()):
                by_theme[th].append((k, v, c, ch))
    out = {}
    for th, mem in by_theme.items():
        if len(mem) < 2:
            continue
        _, _, code, ch = max(mem)
        if ch >= lead_min and (code not in out or len(mem) > out[code][1]):
            out[code] = (th, len(mem), ch)
    return out


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
    new_listed: set = field(default_factory=set)    # 신규 상장 20거래일 안 (테마 1등·대장에서 뺌)


def _new_listed(conn, today: date) -> set:
    try:
        rows = conn.execute("""
            SELECT s.code, (SELECT count(*) FROM daily_ohlcv d WHERE d.code = '005930' AND d.date >= s.list_date AND d.date < ?)
            FROM stocks s WHERE s.list_date > ? - INTERVAL 60 DAY""", [today, today]).fetchall()
        return {c for c, n in rows if int(n) + 1 <= NEW_LISTING_DAYS}
    except Exception:
        logging.exception("카페: 신규 상장 목록을 못 읽음")
        return set()


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
    return CafeContext(day, stocks, top200, dict(themes), _new_listed(conn, today))


def _val(b: dict) -> float:
    return b["volume"] * (b["high"] + b["low"] + b["close"]) / 3


class CafeLeaderWatcher:
    def __init__(self, store, market, client, today: date, ctx: CafeContext,
                 notify: Optional[Callable[[str], object]] = None,
                 on_trade: Optional[Callable[[datetime, str, str, float], object]] = None) -> None:
        self.on_trade = on_trade                # (now, code, name, 매수가) → 모의·실전 매수 신호로 넘김
        self.conn = store.conn
        self.market = market
        self.client = client
        self.today = today
        self.ctx = ctx
        self.notify = notify or (lambda text: None)
        self.conn.execute(SCHEMA)
        self.ledger = Ledger(self.conn, BOOK, TAG, today, START_CASH, SLOTS, notify=self.notify)   # 공용 가상 장부
        self.reported = self.ledger.reported()
        self.checked: set[str] = {c for (c,) in self.conn.execute("SELECT DISTINCT code FROM cafe_checks WHERE date = ?", [today]).fetchall()}
        self.pending: dict[str, dict] = {}      # code → 눌림 지정가 대기 {level, until, info}
        self.limits: dict[str, int] = {}
        self.hits: dict[str, tuple] = {c: (n, th, ts) for c, n, th, ts in self.conn.execute(
            "SELECT code, name, theme, ts FROM cafe_leader_hits WHERE date = ? ORDER BY ts", [today]).fetchall()}

    # ------------------------------------------------------------ 상태
    def cash(self) -> float:
        return self.ledger.cash()

    def open_trades(self):
        return self.ledger.open_trades()

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
        if TOP_START <= tm <= TOP_END and self.ctx.stocks:
            try:
                self._capture_tops(now, value_top)
            except Exception:
                logging.exception("카페: 테마 1등 포착 실패")
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            self.ledger.mark_reported(self._note())
            sink = getattr(self, "summary_sink", None)   # 15:42 가상 장부 마감 한 통으로 묶음 (run_intraday, 2026-10-27 사용자)
            (sink.append if sink is not None else self.notify)(self.summary())

    def leaders(self, value_top) -> dict[str, tuple[str, int, float]]:
        """지금 테마 대장 → {code: (테마, +4%↑ 종목 수, 등락률)} (지금 대금 상위 200 안 종목으로 판단)."""
        rows = [(r.code, r.change_rate, r.trade_value) for r in value_top
                if r.code in self.ctx.stocks and r.code not in self.ctx.new_listed and r.change_rate is not None and r.trade_value]
        return theme_leaders(rows, self.ctx.themes, UP_MIN, LEAD_MIN)

    def tops(self, value_top, risers=()) -> dict[str, tuple[str, int, float]]:
        """👑 지금 테마 등락률 1등 (대상 = 대금 상위 200 + 등락률 상위, 신규 상장 20거래일 안 제외)."""
        rows = {}
        for r in list(value_top) + list(risers):
            if r.code in rows or r.code not in self.ctx.stocks or r.code in self.ctx.new_listed:
                continue
            if r.change_rate is not None and r.trade_value:
                rows[r.code] = (r.code, r.change_rate, r.trade_value)
        return top_by_chg(rows.values(), self.ctx.themes)

    def _capture_tops(self, now: datetime, value_top) -> None:
        try:
            risers = self.market.risers(min_value_cond=RISER_VALUE, stex_tp="3")
        except Exception as exc:
            logging.warning("카페: 등락률 상위 조회 실패 (대금 상위로만 테마 1등 판단): %s", exc)
            risers = []
        tops = self.tops(value_top, risers)
        if not tops:
            return
        by_value = self.leaders(value_top)
        vals = {r.code: r.trade_value for r in list(risers) + list(value_top) if r.trade_value}
        naive = now.replace(tzinfo=None)
        for code, (th, n_up, chg) in tops.items():
            if code in self.hits:
                continue
            st = self.ctx.stocks[code]
            vl = code in by_value
            note = ("①(테마 안 대금 1위)도 맞음 → ③⑥ 맞으면 매수" if vl and naive.time() <= LAST_BUY
                    else "기록만 — 매수는 ①(테마 안 대금 1위)③⑥ 일 때")
            if chg >= LIMIT_TIE:
                note += " · 상한가 근처"
            self.hits[code] = (st.name, th, naive)
            self.conn.execute("INSERT INTO cafe_leader_hits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              [self.today, naive, code, st.name, th, n_up, chg, vals.get(code), code in self.ctx.top200, vl, note])
            logging.info("👑 테마 1등 포착 %s(%s) '%s' %+.1f%% (+4%%↑ %s종목, 대금 %.0f억, 전날 200위 %s) — %s", st.name, code, th, chg * 100,
                         n_up, (vals.get(code) or 0) / 1e8, "안" if code in self.ctx.top200 else "밖", note)

    def tops_line(self) -> str:
        rows = self.conn.execute("SELECT name, theme, ts, chg FROM cafe_leader_hits WHERE date = ? ORDER BY ts", [self.today]).fetchall()
        if not rows:
            return "  오늘 테마 1등 포착: 없음"
        big = [r for r in rows if r[3] is not None and r[3] >= 0.10]
        show = ", ".join(f"{n}({ts:%H:%M} {th} {c:+.0%})" for n, th, ts, c in (big or rows)[:12])
        return f"  👑 오늘 테마 1등 포착 {len(rows)}종목 (+10%↑ {len(big)}): {show} — 기록만"

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
        th, n_up, chg = lead
        level_chg = hi * (1 + chg) / x["close"] - 1 if x["close"] else chg   # 눌림 지정가(돌파 고점)의 어제 대비
        chase = level_chg > CHASE_MAX
        all_ok = not self.ledger.full() and not chase   # 2026-10-30 사용자 '15일 박스 아님 조건도 빼줘' — ④ 는 표시만
        decision = (f"눌림 지정가 {hi:,.0f} 대기 (10분)" if all_ok
                    else f"돌파 고점이 어제 대비 {level_chg:+.0%} — +{CHASE_MAX:.0%} 넘어 안 삼(추격)" if chase
                    else f"오늘 {SLOTS}종목 다 참")
        self.checked.add(code)
        th = th if code in self.ctx.top200 else f"{th} (전날 대금 200위 밖)"
        self.conn.execute("INSERT INTO cafe_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          [self.today, now.replace(tzinfo=None), code, st.name, th, n_up, chg, st.inst3, pre_value, box, hi,
                           fo, ins, pg, decision])
        if all_ok:
            self.pending[code] = dict(level=hi, until=x["ts"] + timedelta(minutes=PULL_BARS), name=st.name)
        logging.info("카페 체크 %s %s → %s (프리장 %.0f억)", st.name, x["ts"], decision, pre_value / 1e8)
        if chase:      # 규칙상 매매 대상 아님 → 알림 없이 기록만 (텔레그램 원칙)
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
            f"  ④ 일봉 박스 돌파 {ok(box)} {BOX_DAYS}일 고가 {hi15} (폭 {width}) — 참고, 10-30 부터 매수 조건 아님\n"
            f"  ⑤ 오늘 수급(잠정): 외국인 {fmt(fo)} · 기관 {fmt(ins)} · 프로그램 {fmt(pg)} (참고)\n"
            f"  ⑥ 1분봉 고점 {hi:,.0f} 돌파 + 햄버거 {bv / 1e8:,.0f}억 ✅\n"
            f"  → {decision} (①③⑥ 이면 가상 장부·모의·실전 매수 · 1년 601건 건당 +0.24%)")

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
        try:
            q = self.market.quote(code, integrated=False)
            lim = upper_limit(float(q.base_price)) if q and q.base_price else price * 1.3
        except Exception:
            lim = price * 1.3
        self.ledger.buy(now, code, name, price,
                        Plan(stop=price * (1 - STOP), half_at=price * (1 + HALF_TP), target=float(lim), next_day=True),
                        note=f"돌파 고점 눌림 체결 {ts:%H:%M} (상한가 {lim:,.0f} 닿으면 전부)")
        if self.on_trade is not None:
            try:
                self.on_trade(now, code, name, float(price))
            except Exception:
                logging.exception("카페: 모의·실전 신호 넘기기 실패 %s", name)

    def _manage(self, now: datetime, value_top) -> None:
        self.ledger.manage(now, price_source(self.market, value_top))

    def _note(self) -> str:
        rows = self.conn.execute("SELECT name, decision FROM cafe_checks WHERE date = ? ORDER BY ts", [self.today]).fetchall()
        return "; ".join(f"{n} {d}" for n, d in rows) if rows else "테마 대장 돌파 없음"

    def summary(self) -> str:
        return (f"{TAG} 1천만 가상 장부 {self.today:%m-%d} 마감\n" + self.ledger.summary_line()
                + f"\n  오늘 체크: {self._note()}\n" + self.tops_line())
