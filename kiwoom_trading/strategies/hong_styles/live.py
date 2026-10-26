"""📕 [홍인기] 상따 밖 매매 — 1년 백테스트를 통과한 세 가지를 1천만 원 가상 장부로 (주문 없음).
(2026-10-27 사용자: "홍인기 매매 모두 분석 — 눌림부터 전부 다 해줘". 1년 결과: run_hong_styles_backtest.py, 스킬 hong 6장)

장부 (각 1천만, 하루 최대 3건, 건당 잔고 ÷ 3, 비용 0.25%):
  돌파·대장 = 테마 대장(☕ cafe_leader 판단: 네이버 테마 안 지금 대금 1위·+5%↑, 같은 테마 +4%↑ 2종목↑)이면서 지금 대금 10위 안인 종목이
           60일 신고가를 아래에서 위로 넘으면 그 가격에 매수 → 손절 −2% 즉시, 아니면 다음 날 09:00.
           (1년 212건 건당 +1.00%, 앞 +0.78 / 뒤 +1.24 — 같은 조건 + 대형주면 77건 +1.62%. 일지: "주도테마 대장주 신고가 돌파")
  돌파   = 대형주(전날 시총 30위 안)가 장중 60일 신고가(직전 60거래일 고가)를 아래에서 위로 넘으면 → 그 가격에 지정가, 30분 안에 눌려 닿으면 체결.
           손절 −2% 즉시, 아니면 다음 날 09:00. (1년 422건 건당 +0.50%, 앞 +0.47 / 뒤 +0.55)
           일지: "신고가 앞둔 대장주 돌파 … 첫 눌림 매수", "대형주는 프로그램·기관 수급을 더 중요히" — 돌파는 대형주에서만 플러스였다.
  강한 쪽 = 10:00 SK하이닉스·삼성전자 중 전일 대비 더 강한 쪽이 상승 중이면 매수 → 다음 날 09:00. (161건 +0.64%, 앞 +0.54 / 뒤 +0.75)
           일지: "SK하이닉스 vs 삼성전자 상대 강도 비교, 약한 쪽 줄이고 강한 쪽 집중"(거의 매일).
  애프터 급락 = 전날 시총 5위 종목이 애프터(15:40~19:55, 통합 시세)에서 정규장 종가 대비 −3% 닿으면 매수 →
           하락폭 절반 회복(그 세션)에 매도, 아니면 다음 날 09:00. (51건 +1.53%, 앞 +0.44 / 뒤 +2.76 — 건수 적음)
           일지: "애프터시장 정규장 종가대비 2% 이상 추가하락해 분할매수 … 하락폭 절반가량 회복시 수익실현".
시세는 매분 받는 KRX 대금 상위 200 가격(1분 간격) — 백테스트의 1분봉 저가·고가와 달라 체결이 덜 될 수 있다.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from kiwoom_trading.execution.ledger import Ledger, Plan, price_source

TAG = "📕 [홍인기·상따 밖]"
BOOKS = ("돌파·대장", "돌파", "강한 쪽", "애프터 급락")
START_CASH = 10_000_000
SLOTS = 3
COST = 0.0025
B_FROM, B_TO, B_PULL_MIN, B_STOP = time(9, 5), time(14, 30), 30, 0.02
S_AT = time(10, 0)
C_FROM, C_TO, C_DROP = time(15, 40), time(19, 55), 0.03
OPEN, CLOSE, REPORT_AT = time(9, 0), time(15, 30), time(19, 58)
PAIR = ("000660", "005930")




@dataclass
class HsContext:
    day: Optional[date]
    big30: dict = field(default_factory=dict)     # code → (이름, 60일 고가) — 전날 시총 30위 안
    big5: dict = field(default_factory=dict)      # code → 이름 — 전날 시총 5위 안
    hi60: dict = field(default_factory=dict)      # code → (이름, 60일 고가) — 전 종목 (돌파·대장용)


def load_hs_context(conn, today: date) -> HsContext:
    day = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [today]).fetchone()[0]
    if day is None:
        return HsContext(None)
    rows = conn.execute("""
        WITH cap AS (SELECT d.code, s.name, d.close * s.listed_shares AS mc FROM daily_ohlcv d JOIN stocks s USING (code)
                     WHERE d.date = ? AND s.listed_shares > 0 AND right(d.code, 1) NOT IN ('5', '7', '9', 'K')),
             r AS (SELECT *, row_number() OVER (ORDER BY mc DESC) AS rk FROM cap),
             days AS (SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date <= ? ORDER BY date DESC LIMIT 60),
             hi AS (SELECT code, max(high) AS h, count(*) AS n FROM daily_ohlcv WHERE date IN (SELECT date FROM days) GROUP BY code)
        SELECT r.code, r.name, r.rk, hi.h, hi.n FROM r JOIN hi USING (code) ORDER BY r.rk""", [day, day]).fetchall()
    hi60 = {c: (n, float(h)) for c, n, rk, h, cnt in rows if cnt == 60}
    big30 = {c: v for c, n, rk, h, cnt in rows if rk <= 30 and (v := hi60.get(c))}
    big5 = {c: n for c, n, rk, h, cnt in rows if rk <= 5}
    return HsContext(day, big30, big5, hi60)


class HongStylesAccount:
    def __init__(self, store, market, today: date, ctx: HsContext, notify: Optional[Callable[[str], object]] = None,
                 leaders: Optional[Callable] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.today = today
        self.ctx = ctx
        self.notify = notify or (lambda text: None)
        self.leaders = leaders                  # value_top → {code: (테마, +4%↑ 수, 등락률)} (☕ CafeLeaderWatcher.leaders)
        self.books = {b: Ledger(self.conn, b, TAG, today, START_CASH, SLOTS, notify=self.notify) for b in BOOKS}   # 공용 가상 장부
        self.reported = all(l.reported() for l in self.books.values())
        self.last_px: dict[str, float] = {}
        self.last_lead_px: dict[str, float] = {}
        self.pending: dict[str, tuple[float, datetime]] = {}    # 돌파: code → (지정가, 기다림 끝)
        self.s_done = self._bought("강한 쪽")
        self.closes: dict[str, float] = {}                        # 애프터: 정규장 종가

    # ------------------------------------------------------------ 상태
    def cash(self, book: str) -> float:
        return self.books[book].cash()

    def _bought(self, book: str, code: Optional[str] = None) -> bool:
        return self.books[book].bought_today(code)

    def open_trades(self):
        return [dict(t, book=b) for b, l in self.books.items() for t in l.open_trades()]

    def _quote(self, code: str, integrated: bool = False):
        try:
            q = self.market.quote(code, integrated=integrated)
            return q if q and q.price else None
        except Exception:
            logging.warning("홍인기 상따 밖: %s 시세 조회 실패", code)
            return None

    # ------------------------------------------------------------ 매분
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        px = {r.code: float(r.price) for r in value_top if r.price}
        price_of = price_source(self.market, value_top)
        for l in self.books.values():
            l.manage(now, price_of)
        if B_FROM <= tm <= B_TO or self.pending:
            self._breakout(now, px)
        if B_FROM <= tm <= B_TO and self.leaders is not None:
            self._leader_breakout(now, value_top)
        if tm >= S_AT and not self.s_done:
            self.s_done = True
            self._strong_side(now)
        if C_FROM <= tm <= C_TO:
            self._after_drop(now)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            for l in self.books.values():
                l.mark_reported()
            self.notify(self.summary())

    def _buy(self, now, book, code, name, price, stop=None, target=None, note="") -> None:
        after = book == "애프터 급락"
        self.books[book].buy(now, code, name, price, Plan(stop=stop, target=target, next_day=True,
                                                          session="after" if after else "regular", until=C_TO.strftime("%H:%M") if after else None),
                             note=note)

    def _breakout(self, now, px) -> None:
        tm = now.time()
        for code, (name, lvl) in self.ctx.big30.items():
            p = px.get(code)
            if p is None:
                continue
            prev = self.last_px.get(code)
            self.last_px[code] = p
            if code in self.pending:
                limit_px, until = self.pending[code]
                if now.replace(tzinfo=None) > until:
                    self.pending.pop(code)
                    logging.info("홍인기 돌파: %s 30분 안에 %s 까지 안 눌림", name, limit_px)
                elif p <= limit_px:
                    self.pending.pop(code)
                    self._buy(now, "돌파", code, name, limit_px, stop=limit_px * (1 - B_STOP),
                              note=f"60일 신고가 {lvl:,.0f} 돌파 뒤 첫 눌림")
                continue
            if prev is not None and B_FROM <= tm <= B_TO and prev <= lvl < p and not self._bought("돌파", code):
                self.pending[code] = (lvl, now.replace(tzinfo=None) + timedelta(minutes=B_PULL_MIN))
                logging.info("홍인기 돌파: %s 60일 신고가 %s 돌파 (%s) → 30분 안 눌림 지정가", name, lvl, p)

    def _leader_breakout(self, now, value_top) -> None:
        lead = self.leaders(value_top)
        for r in value_top:
            code, p = r.code, float(r.price or 0)
            prev = self.last_lead_px.get(code)
            self.last_lead_px[code] = p
            v = self.ctx.hi60.get(code)
            if not v or code not in lead or not p or r.rank > 10 or prev is None:
                continue
            name, lvl = v
            if prev <= lvl < p and not self._bought("돌파·대장", code):
                th, n_up, ch = lead[code]
                self._buy(now, "돌파·대장", code, r.name or name, p, stop=p * (1 - B_STOP),
                          note=f"테마 '{th}' 대장(+4%↑ {n_up}종목) · 대금 {r.rank}위 · 60일 신고가 {lvl:,.0f} 돌파")

    def _strong_side(self, now) -> None:
        got = {}
        for c in PAIR:
            q = self._quote(c)
            if q and q.base_price:
                got[c] = (q.price / q.base_price - 1, q)
        if len(got) < 2:
            return
        c = max(got, key=lambda k: got[k][0])
        ch, q = got[c]
        other = min(v[0] for v in got.values())
        if ch <= 0:
            logging.info("홍인기 강한 쪽: 둘 다 하락 (%+.1f%% / %+.1f%%) → 안 삼", ch * 100, other * 100)
            return
        self._buy(now, "강한 쪽", c, q.name or c, float(q.price), note=f"10:00 {q.name} {ch:+.1%} vs 다른 쪽 {other:+.1%}")

    def _after_drop(self, now) -> None:
        for code, name in self.ctx.big5.items():
            if self._bought("애프터 급락", code):
                continue
            if code not in self.closes:
                q = self._quote(code)                  # 장 마감 뒤 KRX 현재가 = 정규장 종가
                if not q:
                    continue
                self.closes[code] = float(q.price)
            rc = self.closes[code]
            q = self._quote(code, integrated=True)     # 애프터(NXT) 가격
            if q and q.price <= rc * (1 - C_DROP):
                buy = float(q.price)
                self._buy(now, "애프터 급락", code, name, buy, target=buy + (rc - buy) / 2,
                          note=f"애프터 {buy / rc - 1:+.1%} (정규장 종가 {rc:,.0f})")

    def summary(self) -> str:
        return f"{TAG} 가상 장부 {self.today:%m-%d} 마감\n" + "\n".join(l.summary_line() for l in self.books.values())
