"""🔴 실전 매매 — 키움 실계좌로 6️⃣ 주도주 신고가 · 2️⃣ 저항 돌파 · 5️⃣ 약세장 인버스 · 📕 홍인기 상한가 풀림 중 그날 먼저 온 신호를 산다
(2026-10-25 사용자: "10만 원 시드로 실전 매매, 월요일부터" → 처음엔 5️⃣ 만, 같은 날 "인버스 타이밍이 아니면 다른 기법도 — 6️⃣2️⃣5️⃣ 로 넓혀라".
 2026-10-27 사용자: "홍인기 매매를 바로 실전에 — 6️⃣2️⃣5️⃣ 와 하나로 합침" → 📕 를 네 번째 신호로 추가,
 같은 날 "1 을 실전에도 매매 적용" → 1️⃣ 상승장 장 초(강한 상승장 09:10 대금 40위·시가 위)를 다섯 번째로 추가 — 익절 없음 · −4% · 다음 날 09:00).

켜는 법 (.env.local KIWOOM_REAL_TRADING):
  combo   = 6️⃣·2️⃣·5️⃣ (💰 10만 원 가상 계좌와 같은 규칙)      inverse = 5️⃣ 만      그 밖 / 없음 = 주문 안 함
규칙:
- 들고 있는 종목이 없고 오늘 아직 안 샀으면, 신호가 온 순서대로 첫 신호를 시장가로 산다 (정규장 09:00~15:19).
  금액 = min(시드 10만 원 + 실전 실현 손익, 계좌 주문 가능 금액, 주문 상한 20만 원). 1주도 못 사면 다음 신호. 신호가 +1% 넘게 오른 뒤면 추격 안 함.
  2026-10-28 사용자 'B': 1️⃣ 상승장 장 초는 하루 1종목 대신 UP_SLOTS(4)종목까지, 종목당 (시드+손익)/4. 1️⃣ 을 산 날 다른 신호는 안 산다.
  → 2026-10-30 사용자 '하루 1종목 규칙을 없애줘, 3만 원 안에서는 1주 이상, 3만 원 넘으면 1주만': 하루 종목 수·1️⃣ 칸 규칙 없음.
    신호마다 같은 종목을 들고 있지 않고(같은 날 같은 종목은 한 번) 예수금이 되면 산다. 수량 = 지정가 ≤ 3만 원이면 3만 원 안에서 최대, 넘으면 1주 (가격 상한 없음).
  2026-10-30 사용자 '제안대로, 키움 실계좌로 NXT·KRX 애프터장 거래가 된다(종목별로 다름)': 4️⃣ 역행 강세 종가(강한 하락장 15:15~15:19 KRX)·
    🌙 종가 재돌파(17~18시 NXT 애프터마켓 지정가, 통합 현재가 +1%)를 실전에 추가 — 둘 다 익절·손절 없이 다음 날 09:00 KRX 시가 매도.
  같은 날 '증거금 문제 해소': 매수는 현재가 +1% 지정가 (시장가는 상한가 기준 증거금이라 덜 샀음), 2분 안에 다 안 채워지면 남은 수량 취소.
- 📕 신호 = 홍인기 가상 장부 '수급 없이' 매수 판단 (첫 상한가 · 5분↑ 잠김 뒤 풀림, hong_account.py). 지금가가 상한가면(다시 잠김) 안 산다.
- 매도 (체결가 기준, 1분마다 현재가 확인): 6️⃣ 익절 없음 · −4% / 2️⃣ +7% · −5% / 5️⃣ +5% · −3% / 📕 익절·손절 없음 (1년: 손절 넣으면 나빠짐,
  전부 다음 날 09:00 870건 건당 +1.93%, 호가 2칸 미끄러짐 포함),
  그날 못 닿으면 15:19 에 팔지 않고 다음 날 09:00 첫 확인 때 시장가.
안전장치:
- 그날 신호로 받은 종목만 주문한다 (RealClient.allowed). 팔 때는 이 매매로 산 수량만 (계좌의 다른 보유분은 건드리지 않음).
- 주문 한 번 20만 원 상한(REAL_MAX_ORDER), 체결 확인 전에는 다시 사지 않는다.
- LIQUIDATE_ENV 날짜(YYYY-MM-DD)의 09:00 첫 확인 때 계좌 보유 종목 전체를 한 번 시장가로 판다 (2026-10-26 물려 있던 종목 손절, 사용자 요청).
- 모든 주문·체결·건너뜀을 🔴 텔레그램과 real_trades 표(screener.duckdb)에 남긴다.
1년 백테스트 (스크래치 small.py·small2.py·inv10.py, 10만 원 복리·정수 주): 6️⃣2️⃣5️⃣ 808,902원(8.1배, 낙폭 18%) / 5️⃣ 만 161,414원(+61%).
"""
import logging
import os
import re
from datetime import datetime, time
from typing import Any, Callable, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, _to_int
from kiwoom_trading.strategies.hong_limitup.live import HONG_KIND
from kiwoom_trading.strategies.inverse.live import CODE as INVERSE_CODE, WEAK_KIND, WEAK_STOP, WEAK_TP
from kiwoom_trading.execution import split_exit, strict_select
from kiwoom_trading.strategies.cafe_leader.live import KIND as CAFE_KIND
from kiwoom_trading.strategies.contra_close.live import KIND as CONTRA_KIND
from kiwoom_trading.strategies.danswer.rebreak import KIND as REBREAK_KIND
from kiwoom_trading.strategies.trend_hold.live import KIND as TREND_KIND
from kiwoom_trading.strategies.premarket_reclaim.live import KIND as RECLAIM_KIND
from kiwoom_trading.strategies.regime_plays.live import NEWHIGH_KIND, NEWHIGH_STOP, UP_HALF_TP, UP_KIND, UP_MAX_PREV_GAIN, UP_STOP, UP_TRAIL
from kiwoom_trading.strategies.resistance_retest.live import RETEST_KIND, RETEST_STOP, RETEST_TP

ENV_FLAG = "KIWOOM_REAL_TRADING"
LIQUIDATE_ENV = "KIWOOM_REAL_LIQUIDATE_DATE"
SEED = 100_000
REAL_MAX_ORDER = 200_000
MAX_CHASE = 0.01
PER_STOCK = 30_000            # 2026-10-30 사용자: 종목당 3만 원 안에서 여러 주, 1주가 3만 원 넘으면 1주만, 하루 종목 수 제한 없음 (옛 1️⃣ UP_SLOTS 4칸 규칙 없앰)
LIMIT_UP = 0.01               # 2026-10-28 사용자 '증거금 문제 해소': 매수는 시장가(상한가 기준 증거금) 대신 현재가 +1% 지정가
FILL_WAIT_SEC = 120           # 지정가가 2분 안에 다 안 채워지면 남은 수량 취소
ETF_CODES = {INVERSE_CODE}
REAL_OFF = (RECLAIM_KIND, CAFE_KIND)   # ☕: 2026-10-30 사용자 '☕는 실전에서 빼자' — 94% 가 1주 3만 원 넘어 1주씩만 사고 절반 익절이 안 됨, 1년 실전 새 규칙 −3~−9만 (research/strict_select). 🔁: 2026-10-29 사용자 '권장대로': 🔁 은 09:0x 에 먼저 와 하루 1칸을 차지 → 6️⃣·📕 를 못 삼 (1년 시드 10만 34만 → 562만, research/account_alloc)
OPEN, LAST, CLOSE = time(9, 0), time(15, 19), time(15, 30)
AFTER_BUY = (time(17, 0), time(18, 0))   # 🌙 종가 재돌파: NXT 애프터마켓 매수 시간 (2026-10-30 사용자 '키움 실계좌로 NXT 애프터장 거래가 된다, 종목별로 다름')
NXT_KINDS = (REBREAK_KIND,)               # NXT 거래소로 주문하는 매매 (지정가 = 통합 현재가 +1%), 다음 날 09:00 매도는 KRX
PLAYS = {   # 종류 → (이름, 익절, 손절)
    NEWHIGH_KIND: ("6️⃣ 주도주 신고가", None, NEWHIGH_STOP),
    RETEST_KIND: ("2️⃣ 저항 돌파", RETEST_TP, RETEST_STOP),
    WEAK_KIND: ("5️⃣ 약세장 인버스", WEAK_TP, WEAK_STOP),
    HONG_KIND: ("📕 홍인기 상한가 풀림", None, None),
    UP_KIND: ("1️⃣ 상승장 장 초", None, UP_STOP),     # 2026-10-27 사용자 '1 을 실전에도'
    RECLAIM_KIND: ("🔁 시가 탈환", None, None),        # 2026-10-27 사용자 '모의·실전 모두' — 손절·익절은 split_exit
    CAFE_KIND: ("☕ 카페 테마 대장", None, None),
    CONTRA_KIND: ("4️⃣ 역행 강세 종가", None, None),      # 2026-10-30 사용자 '제안대로' — 강한 하락장 15:15~15:19 매수, 다음 날 09:00 (1년 422건 +0.85%)
    REBREAK_KIND: ("🌙 종가 재돌파", None, None),
    TREND_KIND: ("7️⃣ 주도주 추세", None, None),         # 2026-10-30 사용자 '7번 매매를 실전으로' — 09:00 매수, 종가 20일선 이탈 다음 날 09:00 매도 (며칠~몇 주 보유)        # 2026-10-30 — 17~18시 NXT 애프터장에서 정규장 종가 위 매수, 다음 날 09:00 (1년 554건 +0.79%)
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_trades (    -- 🔴 실전 매매 (키움 실계좌)
    id             VARCHAR PRIMARY KEY,
    date           DATE,
    code           VARCHAR,
    qty            INTEGER,
    buy_order_no   VARCHAR,
    buy_ts         TIMESTAMP,
    buy_price      DOUBLE,
    sell_order_no  VARCHAR,
    sell_ts        TIMESTAMP,
    sell_price     DOUBLE,
    reason         VARCHAR,
    pnl            DOUBLE,
    status         VARCHAR,   -- ordered / open / selling / closed / failed
    note           VARCHAR,
    kind           VARCHAR,
    name           VARCHAR
);
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS kind VARCHAR;
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS name VARCHAR;
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS part_qty INTEGER;     -- 1️⃣ +7% 에 먼저 판 절반 수량
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS part_price DOUBLE;
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS peak DOUBLE;           -- 매수 뒤 가장 높은 값 (트레일링용)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS stop_px DOUBLE;        -- 🔁 처음 손절가 (흔들기 저가)
CREATE TABLE IF NOT EXISTS real_liquidations (date DATE, code VARCHAR, name VARCHAR, qty INTEGER, order_no VARCHAR, ts TIMESTAMP, note VARCHAR);
"""


def mode() -> str:
    from kiwoom_trading.common.daily_store import load_env
    load_env()
    m = os.getenv(ENV_FLAG, "").strip().lower()
    return m if m in ("combo", "inverse") else ""


def enabled() -> bool:
    return bool(mode())


def _cost(code: str) -> float:
    return 0.0005 if code in ETF_CODES else 0.0025


def tick_up(price: float) -> int:
    """KRX 호가 단위로 올림."""
    unit = 1 if price < 2_000 else 5 if price < 5_000 else 10 if price < 20_000 else 50 if price < 50_000 \
        else 100 if price < 200_000 else 500 if price < 500_000 else 1_000
    return int(-(-price // unit) * unit)


class RealClient(KiwoomDailyClient):
    """실서버(api.kiwoom.com) 계좌·주문. allowed 에 없는 종목은 주문하지 않는다."""

    def __init__(self, base_url: str, app_key: str, secret_key: str) -> None:
        if "mockapi" in base_url:
            raise RuntimeError("실전 클라이언트에 모의 서버 주소가 들어왔습니다")
        super().__init__(base_url, app_key, secret_key)
        self.allowed: set[str] = set()

    def cash(self) -> int:
        """증거금 100% 종목 주문 가능 금액 — 매도 대금(정산 전)까지 포함, 빌리는 돈 없음.
        ord_alow_amt 는 예수금만이라 아침에 판 돈이 안 잡힌다 (2026-10-26 09:06 639원 vs 83,897원)."""
        payload, _, _ = self._post("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})
        return max(_to_int(payload.get("100stk_ord_alow_amt")) or 0, _to_int(payload.get("ord_alow_amt")) or 0)

    def holdings(self) -> list[tuple[str, str, int]]:
        """[(코드, 이름, 매도 가능 수량)]"""
        payload, _, _ = self._post("/api/dostk/acnt", "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        return [(str(r.get("stk_cd") or "").strip().lstrip("A"), str(r.get("stk_nm") or "").strip(), _to_int(r.get("trde_able_qty")) or 0)
                for r in payload.get("acnt_evlt_remn_indv_tot") or []]

    def holding_qty(self, code: str) -> int:
        return next((q for c, _, q in self.holdings() if c == code), 0)

    def _order(self, api: str, code: str, qty: int, limit: Optional[int] = None, exchange: str = "KRX") -> str:
        payload, _, _ = self._post("/api/dostk/ordr", api, {"dmst_stex_tp": exchange, "stk_cd": code, "ord_qty": str(qty),
                                                            "ord_uv": str(limit) if limit else "", "trde_tp": "0" if limit else "3",
                                                            "cond_uv": ""})
        no = str(payload.get("ord_no") or "")
        if not no:
            raise RuntimeError(f"주문 거부: {payload.get('return_code')} {payload.get('return_msg')}")
        return no

    def sell_any(self, code: str, qty: int) -> str:
        """한 번만 쓰는 전체 정리용 시장가 매도 (liquidate_once 에서만 부른다)."""
        return self._order("kt10001", code, qty)

    def market_order(self, side: str, code: str, qty: int) -> str:
        if code not in self.allowed:
            raise RuntimeError(f"실전 주문 허용 종목이 아님: {code}")
        return self._order({"buy": "kt10000", "sell": "kt10001"}[side], code, qty)

    def limit_buy(self, code: str, qty: int, price: int, exchange: str = "KRX") -> str:
        """지정가 매수 — 증거금이 주문 가격 기준이라 시장가(상한가 기준)보다 많이 살 수 있다. exchange='NXT' 면 NXT 애프터마켓."""
        if code not in self.allowed:
            raise RuntimeError(f"실전 주문 허용 종목이 아님: {code}")
        return self._order("kt10000", code, qty, limit=price, exchange=exchange)

    def cancel(self, order_no: str, code: str, exchange: str = "KRX") -> str:
        """남은 수량 전부 취소."""
        payload, _, _ = self._post("/api/dostk/ordr", "kt10003", {"dmst_stex_tp": exchange, "orig_ord_no": order_no, "stk_cd": code, "cncl_qty": "0"})
        return str(payload.get("ord_no") or "")

    def fill_info(self, order_no: str, code: str) -> tuple[int, Optional[float]]:
        """(체결 수량, 평균 체결가)."""
        payload, _, _ = self._post("/api/dostk/acnt", "ka10076", {"stk_cd": code, "qry_tp": "1", "sell_tp": "0", "ord_no": "", "stex_tp": "0"})
        qty = amount = 0
        for row in payload.get("cntr") or []:
            if str(row.get("ord_no") or "").lstrip("0") == order_no.lstrip("0"):
                q, p = _to_int(row.get("cntr_qty")) or 0, _to_int(row.get("cntr_pric")) or 0
                qty, amount = qty + q, amount + q * p
        return qty, (amount / qty if qty else None)

    def fill_price(self, order_no: str, code: str) -> Optional[float]:
        return self.fill_info(order_no, code)[1]


def build_real_client() -> RealClient:
    return RealClient(os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com"), os.environ["KIWOOM_APP_KEY"], os.environ["KIWOOM_SECRET_KEY"])


class RealTrader:
    def __init__(self, client, market, store, today, notify: Optional[Callable[[str], Any]] = None, kinds=None) -> None:
        self.client = client
        self.market = market
        self.conn = store.conn
        self.today = today
        self.notify = notify or (lambda text: None)
        self.strict = strict_select.load_context(today)   # 당일 매매 엄격 선정 B안 (2026-10-30 사용자)
        self.trend_exit: dict = {}               # 7️⃣ 실전 보유 중 전날 종가 20일선 이탈 {code: (날짜, 종가, 20일선)} — run_intraday 가 넣어 줌
        self.kinds = tuple(k for k in (kinds or PLAYS) if k not in REAL_OFF)
        self.conn.execute(SCHEMA)
        for t in self.actives():                # 들고 있는 종목은 팔 수 있게 허용
            if hasattr(self.client, "allowed"):
                self.client.allowed.add(t[2])

    # ------------------------------------------------------------ 한 번 전체 정리
    def liquidate_once(self, now: datetime) -> None:
        day = os.getenv(LIQUIDATE_ENV, "").strip()
        if day != f"{self.today:%Y-%m-%d}" or not (OPEN <= now.time() < LAST):
            return
        if self.conn.execute("SELECT count(*) FROM real_liquidations WHERE date = ?", [self.today]).fetchone()[0]:
            return
        try:
            hold = [(c, n, q) for c, n, q in self.client.holdings() if q > 0]
        except Exception as exc:
            logging.exception("실전 전체 정리: 잔고 조회 실패")
            self.notify(f"⚠️ 실전 전체 정리 잔고 조회 실패 — {exc}"[:400])
            return
        if not hold:
            self.conn.execute("INSERT INTO real_liquidations VALUES (?, '', '', 0, '', ?, '보유 없음')", [self.today, now.replace(tzinfo=None)])
            self.notify("🔴 실전 전체 정리: 보유 종목 없음")
            return
        lines = []
        for code, name, qty in hold:
            try:
                no = self.client.sell_any(code, qty)
                note = "주문"
                lines.append(f"- {name}({code}) {qty}주 시장가 매도 (주문 {no})")
            except Exception as exc:
                no, note = "", f"실패: {exc}"[:200]
                lines.append(f"- {name}({code}) {qty}주 매도 실패 — {exc}"[:200])
            self.conn.execute("INSERT INTO real_liquidations VALUES (?, ?, ?, ?, ?, ?, ?)", [self.today, code, name, qty, no, now.replace(tzinfo=None), note])
        self.notify("🔴 실전 계좌 보유 종목 전체 시초 손절 매도 (사용자 요청 한 번)\n" + "\n".join(lines))
        logging.info("실전 전체 정리: %s", lines)

    # ------------------------------------------------------------ 상태
    def realized(self) -> float:
        return self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM real_trades WHERE status = 'closed'").fetchone()[0] or 0

    def actives(self) -> list[tuple]:
        return self.conn.execute("""SELECT id, date, code, coalesce(name, code), coalesce(kind, ?), qty, buy_order_no, buy_price, sell_order_no, status, buy_ts
                                    FROM real_trades WHERE status IN ('ordered', 'open', 'selling') ORDER BY buy_ts""",
                                 [WEAK_KIND]).fetchall()

    def active(self) -> Optional[tuple]:
        a = self.actives()
        return a[0] if a else None

    def today_kinds(self) -> list[str]:
        return [k for (k,) in self.conn.execute("SELECT coalesce(kind, '') FROM real_trades WHERE date = ? AND status <> 'failed'", [self.today]).fetchall()]

    def bought_today(self) -> bool:
        return bool(self.today_kinds())

    def _set(self, tid: str, **kw) -> None:
        cols = ", ".join(f"{k} = ?" for k in kw)
        self.conn.execute(f"UPDATE real_trades SET {cols} WHERE id = ?", [*kw.values(), tid])

    # ------------------------------------------------------------ 매수
    def _skip_note(self, skipped: list[str], why: str = "") -> None:
        """실전 대상 신호인데 못 산 것 — 한 번에 묶어 알림·로그 (2026-10-27 사용자 '못 산 이유도 알림')."""
        if skipped:
            logging.info("실전 못 삼 %s: %s", why, "; ".join(skipped))
            self.notify(f"⏭ 실전 매수 못 함 {len(skipped)}건{(' — ' + why) if why else ''}\n" + "\n".join(f"  {x}" for x in skipped[:15]))

    def on_signals(self, now: datetime, items) -> None:
        tm = now.time()
        cands = sorted((x for x in items if x[3].kind in self.kinds
                        and (AFTER_BUY[0] <= tm < AFTER_BUY[1] if x[3].kind in NXT_KINDS else OPEN <= tm < LAST)), key=lambda x: x[3].ts)
        if not cands:
            return
        held = self.actives()   # 2026-10-30 사용자 '하루 1종목 규칙을 없애줘' — 같은 종목만 안 겹치게, 예수금 안에서 신호마다 산다
        bought = {c for (c,) in self.conn.execute("SELECT code FROM real_trades WHERE date = ? AND status <> 'failed'", [self.today]).fetchall()}
        skipped = []
        try:
            cash = self.client.cash()
        except Exception as exc:
            logging.exception("실전: 예수금 조회 실패")
            self.notify(f"⚠️ 실전 예수금 조회 실패 — {exc}"[:400])
            return
        for code, name, _source, s in cands:
            label, tp, sl = PLAYS[s.kind]
            if any(t[2] == code for t in held) or code in bought:   # real_trades id 가 날짜-종목이라 같은 날 같은 종목은 한 번
                continue
            why = strict_select.skip_reason(self.strict, s.kind, code, s.reason, strict_select.PLAN_B)   # 2026-10-30 엄격 선정 B안 — 규칙상 대상 아님이라 알림 없이 로그만
            if why:
                logging.info("실전 안 삼 %s [%s]: %s", name, label, why)
                continue
            try:
                nxt = s.kind in NXT_KINDS
                q = self.market.quote(code, integrated=nxt)   # 🌙 는 애프터마켓 체결이 반영된 통합 시세
                price = float(q.price) if q and q.price else None
                if not price:
                    continue
                if s.kind == HONG_KIND and s.level and price >= s.level:
                    logging.info("실전: %s 다시 상한가 %s — 풀림 아님, 안 삼", name, s.level)
                    continue
                base = float(getattr(q, "base_price", 0) or 0)
                if s.kind == UP_KIND and base and price > base * (1 + UP_MAX_PREV_GAIN):
                    skipped.append(f"{name}({code}) [{label} {s.ts:%H:%M}] 전일 대비 {price / base - 1:+.1%} — 이미 많이 오름 · 포착: {(s.reason or '')[:120]}")
                    continue
                if s.kind != UP_KIND and price > s.price * (1 + MAX_CHASE):   # 1️⃣ 은 신호가 대비 추격 제한 없음 (2026-10-28)
                    skipped.append(f"{name}({code}) [{label} {s.ts:%H:%M}] 신호가보다 {price / s.price - 1:+.1%} — 추격 안 함 · 포착: {(s.reason or '')[:120]}")
                    continue
                limit = tick_up(price * (1 + LIMIT_UP))   # 현재가 +1% 지정가 — 증거금이 이 가격 기준 (시장가는 상한가 기준이라 덜 삼, 2026-10-28)
                qty = min(max(1, int(PER_STOCK // limit)), int(cash // limit))   # 3만 원 안에서 여러 주, 1주가 3만 원 넘으면 1주 — 예수금 안에서
                if qty < 1:
                    skipped.append(f"{name}({code}) [{label} {s.ts:%H:%M}] 1주 {limit:,.0f}원 > 예수금 {cash:,.0f}원 · 포착: {(s.reason or '')[:120]}")
                    continue
                self.client.allowed.add(code)
                try:
                    no = self.client.limit_buy(code, qty, limit, exchange="NXT" if nxt else "KRX")
                except RuntimeError as exc:   # '[2000](855056:매수증거금이 부족합니다. 46주 매수가능)' (2026-10-26)
                    m = re.search(r"(\d+)주 매수가능", str(exc))
                    if not m or not 0 < int(m.group(1)) < qty:
                        raise
                    logging.info("실전: %s %s주 증거금 부족 → %s주로 다시 주문", name, qty, m.group(1))
                    qty = int(m.group(1))
                    no = self.client.limit_buy(code, qty, limit, exchange="NXT" if nxt else "KRX")
                tid = f"{now:%Y%m%d}-{code}"
                self.conn.execute("""INSERT OR REPLACE INTO real_trades (id, date, code, name, kind, qty, buy_order_no, buy_ts, buy_price, status, stop_px)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ordered', ?)""",
                                  [tid, self.today, code, name, s.kind, qty, no, now.replace(tzinfo=None), price,
                                   float(s.stop) if s.kind == RECLAIM_KIND and s.stop else None])
                how = (split_exit.plan_text(s.kind, price, s.stop if s.kind == RECLAIM_KIND else None)
                       if s.kind in split_exit.KINDS else
                       "손절·익절 없이 종가가 20일선 아래로 마감한 다음 날 09:00 매도 (며칠~몇 주 보유)" if s.kind == TREND_KIND else
                       f"익절 +{tp:.0%} / 손절 −{sl:.0%}, 못 닿으면 다음 날 09:00 매도" if tp
                       else f"장중 익절 없이 다음 날 09:00 시가 매도 (−{sl:.0%} 손절)" if sl
                       else "익절·손절 없이 다음 날 09:00 시가 매도")
                self.notify(f"🔴 실전 매수 주문 {name}({code}) {qty}주 × 약 {price:,.0f}원 = {qty * price:,.0f}원 (지정가 {limit:,}원{', NXT 애프터마켓' if nxt else ''}, 주문 {no})\n"
                            f"  [{label} {s.ts:%H:%M}] {how}"
                            + "".join(f"\n{l}" for l in (getattr(s, "reason", "") or "").splitlines() if "🇺🇸" in l))
                logging.info("실전 매수 주문 %s %s %s주 지정가 %s (주문 %s)", label, name, qty, limit, no)
                cash -= qty * limit
                held.append((tid, self.today, code)); bought.add(code)
            except Exception as exc:
                logging.exception("실전 매수 실패 %s", name)
                self.notify(f"⚠️ 실전 매수 실패 {name}({code}) [{label}] — {exc}"[:500])
                continue
        self._skip_note(skipped, "")

    # ------------------------------------------------------------ 체결 확인·매도
    def tick(self, now: datetime) -> None:
        self.liquidate_once(now)
        if getattr(self, "reporter", None) is not None:   # 🔴 15:45 실전 성과 리포트 (real_report.py, 2026-10-30 사용자)
            self.reporter.tick(now)
        for t in self.actives():   # 1️⃣ 은 여러 종목일 수 있다 (2026-10-28 B)
            self._tick_one(now, t)

    def _tick_one(self, now: datetime, t: tuple) -> None:
        tid, d, code, name, kind, qty, buy_no, buy_price, sell_no, status, buy_ts = t
        label, tp, sl = PLAYS.get(kind, PLAYS[WEAK_KIND])
        tm = now.time()
        try:
            if status == "ordered":
                got, px = self.client.fill_info(buy_no, code)
                waited = (now.replace(tzinfo=None) - buy_ts).total_seconds() if buy_ts else 0
                if got and got < qty and waited < FILL_WAIT_SEC:
                    return                                   # 지정가 일부만 체결 — 조금 더 기다림
                if got < qty and waited >= FILL_WAIT_SEC:    # 2분 지나도 다 안 채워짐 → 남은 수량 취소
                    try:
                        self.client.cancel(buy_no, code, exchange="NXT" if kind in NXT_KINDS else "KRX")
                    except Exception:
                        logging.exception("실전 매수 남은 수량 취소 실패 %s", name)
                    got, px = self.client.fill_info(buy_no, code)
                    if not got:
                        self._set(tid, status="failed", note=f"지정가 {FILL_WAIT_SEC // 60}분 미체결 → 취소")
                        self.notify(f"⏭ 실전 매수 취소 {name}({code}) [{label}] — 지정가 {FILL_WAIT_SEC // 60}분 안에 체결 안 됨 (가격이 +1% 넘게 오름)")
                        return
                    self.notify(f"🔴 실전 매수 일부만 체결 {name} {got}/{qty}주 — 남은 수량 취소")
                    qty = got
                    self._set(tid, qty=got)
                if px and got >= qty:
                    self._set(tid, buy_price=px, status="open")
                    self.notify(f"🔴 실전 매수 체결 {name} {qty}주 × {px:,.0f}원 [{label}] — "
                                + (f"손절 {px * (1 - sl):,.0f}원" if sl else "손절 없음")
                                + (f" · {px * (1 + UP_HALF_TP):,.0f}원에 절반 익절, 남은 절반 트레일링" if kind == UP_KIND and UP_HALF_TP
                                   else f" · 익절 {px * (1 + tp):,.0f}원" if tp
                                   else " · 종가가 20일선 아래로 마감한 다음 날 09:00 매도 (그 전까지 들고 감)" if kind == TREND_KIND
                                   else " · 장중 익절 없이 다음 날 09:00 시가 매도"))
                return
            part, ppx, peak, stop_px = self.conn.execute("SELECT coalesce(part_qty, 0), part_price, peak, stop_px FROM real_trades WHERE id = ?", [tid]).fetchone()
            if status == "selling":
                px = self.client.fill_price(sell_no, code)
                if px:
                    pnl = (qty - part) * (px - buy_price) + part * ((ppx or px) - buy_price) - qty * buy_price * _cost(code)
                    self._set(tid, sell_price=px, pnl=pnl, status="closed")
                    self.notify(f"🔴 실전 매도 체결 {name} {qty}주 × {px:,.0f}원 [{label}] — {px / buy_price - 1 - _cost(code):+.2%} ({pnl:+,.0f}원)\n"
                                f"  실전 누적 실현 손익 {self.realized():+,.0f}원")
                return
            if not (OPEN <= tm < CLOSE):
                return
            reason = None
            if d < self.today and kind == TREND_KIND:   # 7️⃣ 은 전날 종가가 20일선 아래일 때만 09:00 매도, 아니면 계속 들고 감 (손절·익절 없음)
                brk = self.trend_exit.get(code)
                if not brk:
                    return
                reason = f"20일선 이탈 ({brk[0]:%m-%d} 종가 {brk[1]:,.0f} < 20일선 {brk[2]:,.0f}) — 시초 매도"
            elif d < self.today:
                reason = "다음 날 시초 매도"
            elif tm < LAST:
                q = self.market.quote(code, integrated=False)
                if q and q.price and kind in split_exit.KINDS:   # 나눠 팔기 (1️⃣ +7%·🔁 +2R·☕ +2.5% 절반 익절 → 남은 절반 트레일링/상한가)
                    peak = max(peak or buy_price, float(q.price))
                    self._set(tid, peak=peak)
                    act, why = split_exit.decide(kind, buy_price, stop_px, peak, part, float(q.price), getattr(q, "upper", None))
                    if act == "half":
                        if qty < 2:
                            reason = f"{why} (1주라 전부)"
                        else:
                            half = qty // 2
                            self.client.allowed.add(code)
                            no = self.client.market_order("sell", code, half)
                            self._set(tid, part_qty=half, part_price=float(q.price))
                            self.notify(f"🔴 실전 절반 익절 {name}({code}) {half}주 × 약 {q.price:,.0f}원 ({q.price / buy_price - 1:+.1%}, 주문 {no}) [{label}]")
                            logging.info("실전 절반 익절 %s %s주", name, half)
                            return
                    elif act == "sell":
                        reason = why
                elif q and q.price:
                    if sl and q.price <= buy_price * (1 - sl):
                        reason = f"손절 −{sl:.0%}"
                    elif tp and q.price >= buy_price * (1 + tp):
                        reason = f"익절 +{tp:.0%}"
            if reason:
                held = self.client.holding_qty(code)
                sell_qty = min(qty - part, held)
                if sell_qty < 1:
                    self._set(tid, status="failed", note=f"팔 수량 없음 (계좌 {held}주)")
                    self.notify(f"⚠️ 실전 매도 못 함 {name}({code}) — 계좌 매도 가능 {held}주 (직접 확인 필요)")
                    return
                self.client.allowed.add(code)
                no = self.client.market_order("sell", code, sell_qty)
                self._set(tid, sell_order_no=no, sell_ts=now.replace(tzinfo=None), reason=reason, status="selling", qty=sell_qty + part)
                self.notify(f"🔴 실전 매도 주문 {name}({code}) {sell_qty}주 [{label}] — {reason} (주문 {no})")
                logging.info("실전 매도 주문 %s %s주 %s", name, sell_qty, reason)
        except Exception as exc:
            logging.exception("실전 확인 실패")
            self.notify(f"⚠️ 실전 매매 확인 실패 {name} — {exc}"[:500])


RealInverseTrader = RealTrader   # 예전 이름
