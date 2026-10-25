"""🔴 실전 ⑤ 약세장 인버스 — 키움 실계좌로 TIGER 인버스(123310)만 사고판다 (2026-10-25 사용자: "10만 원 시드로 실전 매매, 월요일부터").

켜는 법: .env.local 에 KIWOOM_REAL_TRADING=inverse (없거나 다른 값이면 아무 주문도 하지 않는다).
규칙 (모의투자 ⑤ 와 같음):
- 장중 스캐너의 ⑤ 신호(하락 흐름 보통 날 09:11~09:16, inverse_gap.WeakInverseWatcher)가 오면 시장가 매수.
  금액 = min(시드 10만 원 + 이 매매의 실현 손익, 계좌 주문 가능 금액, 주문 상한 20만 원). 하루 1번, 보유 중이면 안 삼.
- 매도: 산 날 +5% 익절 / −3% 손절 (1분마다 현재가 확인), 못 닿으면 15:19 에 팔지 않고 다음 날 09:00 첫 확인 때 시장가.
안전장치:
- 123310 외 종목은 주문하지 않는다. 팔 때는 이 매매로 산 수량만 (계좌의 다른 보유분·직접 산 것은 건드리지 않음).
- 주문 한 번 20만 원 상한(REAL_MAX_ORDER), 체결 확인 전에는 다시 사지 않는다.
- 모든 주문·체결·건너뜀을 🔴 텔레그램과 real_trades 표(screener.duckdb)에 남긴다.
1년 백테스트 (스크래치 inv10.py): 10만 원 → 161,414원 (+61%), 56건, 최대 낙폭 10.4%. 최근 석 달(8~10월) +13%.
"""
import logging
import os
import time as _time
from datetime import datetime, time
from typing import Any, Callable, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, _to_int
from kiwoom_trading.screener.inverse_gap import CODE, WEAK_KIND, WEAK_STOP, WEAK_TP

ENV_FLAG = "KIWOOM_REAL_TRADING"
LIQUIDATE_ENV = "KIWOOM_REAL_LIQUIDATE_DATE"   # YYYY-MM-DD: 그날 09:00 첫 확인 때 계좌 보유 종목을 모두 시장가로 한 번 판다 (2026-10-25 사용자 "내일 시초에 보유 종목 모두 매도")
SEED = 100_000
REAL_MAX_ORDER = 200_000
COST = 0.0005               # ETF: 수수료만 (거래세 없음) — 손익 기록용 추정
OPEN, LAST, CLOSE = time(9, 0), time(15, 19), time(15, 30)

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_trades (    -- 🔴 실전 ⑤ 약세장 인버스 (키움 실계좌)
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
    note           VARCHAR
);
"""


def enabled() -> bool:
    from kiwoom_trading.common.daily_store import load_env
    load_env()
    return os.getenv(ENV_FLAG, "").strip().lower() == "inverse"


class RealClient(KiwoomDailyClient):
    """실서버(api.kiwoom.com) 계좌·주문. 123310 외 주문은 막는다."""

    def __init__(self, base_url: str, app_key: str, secret_key: str) -> None:
        if "mockapi" in base_url:
            raise RuntimeError("실전 클라이언트에 모의 서버 주소가 들어왔습니다")
        super().__init__(base_url, app_key, secret_key)

    def cash(self) -> int:
        payload, _, _ = self._post("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})
        return _to_int(payload.get("ord_alow_amt")) or 0

    def holding_qty(self, code: str) -> int:
        payload, _, _ = self._post("/api/dostk/acnt", "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        for row in payload.get("acnt_evlt_remn_indv_tot") or []:
            if str(row.get("stk_cd") or "").strip().lstrip("A") == code:
                return _to_int(row.get("trde_able_qty")) or 0
        return 0

    def holdings(self) -> list[tuple[str, str, int]]:
        """[(코드, 이름, 매도 가능 수량)]"""
        payload, _, _ = self._post("/api/dostk/acnt", "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        return [(str(r.get("stk_cd") or "").strip().lstrip("A"), str(r.get("stk_nm") or "").strip(), _to_int(r.get("trde_able_qty")) or 0)
                for r in payload.get("acnt_evlt_remn_indv_tot") or []]

    def sell_any(self, code: str, qty: int) -> str:
        """한 번만 쓰는 전체 정리용 시장가 매도 (liquidate_once 에서만 부른다)."""
        payload, _, _ = self._post("/api/dostk/ordr", "kt10001", {"dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(qty),
                                                               "ord_uv": "", "trde_tp": "3", "cond_uv": ""})
        no = str(payload.get("ord_no") or "")
        if not no:
            raise RuntimeError(f"주문 거부: {payload.get('return_code')} {payload.get('return_msg')}")
        return no

    def market_order(self, side: str, code: str, qty: int) -> str:
        if code != CODE:
            raise RuntimeError(f"실전 주문은 {CODE} 만 허용: {code}")
        api = {"buy": "kt10000", "sell": "kt10001"}[side]
        payload, _, _ = self._post("/api/dostk/ordr", api, {"dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(qty),
                                                            "ord_uv": "", "trde_tp": "3", "cond_uv": ""})
        no = str(payload.get("ord_no") or "")
        if not no:
            raise RuntimeError(f"주문 거부: {payload.get('return_code')} {payload.get('return_msg')}")
        return no

    def fill_price(self, order_no: str, code: str) -> Optional[float]:
        payload, _, _ = self._post("/api/dostk/acnt", "ka10076", {"stk_cd": code, "qry_tp": "1", "sell_tp": "0", "ord_no": "", "stex_tp": "0"})
        qty = amount = 0
        for row in payload.get("cntr") or []:
            if str(row.get("ord_no") or "").lstrip("0") == order_no.lstrip("0"):
                q, p = _to_int(row.get("cntr_qty")) or 0, _to_int(row.get("cntr_pric")) or 0
                qty, amount = qty + q, amount + q * p
        return amount / qty if qty else None


def build_real_client() -> RealClient:
    return RealClient(os.getenv("KIWOOM_BASE_URL", "https://api.kiwoom.com"), os.environ["KIWOOM_APP_KEY"], os.environ["KIWOOM_SECRET_KEY"])


class RealInverseTrader:
    def __init__(self, client, market, store, today, notify: Optional[Callable[[str], Any]] = None) -> None:
        self.client = client
        self.market = market
        self.conn = store.conn
        self.today = today
        self.notify = notify or (lambda text: None)
        self.conn.execute(SCHEMA)
        self.conn.execute("CREATE TABLE IF NOT EXISTS real_liquidations (date DATE, code VARCHAR, name VARCHAR, qty INTEGER, order_no VARCHAR, ts TIMESTAMP, note VARCHAR)")

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

    def active(self) -> Optional[tuple]:
        return self.conn.execute("""SELECT id, date, qty, buy_order_no, buy_price, sell_order_no, status FROM real_trades
                                    WHERE status IN ('ordered', 'open', 'selling') ORDER BY buy_ts LIMIT 1""").fetchone()

    def bought_today(self) -> bool:
        return bool(self.conn.execute("SELECT count(*) FROM real_trades WHERE date = ? AND status <> 'failed'", [self.today]).fetchone()[0])

    def _set(self, tid: str, **kw) -> None:
        cols = ", ".join(f"{k} = ?" for k in kw)
        self.conn.execute(f"UPDATE real_trades SET {cols} WHERE id = ?", [*kw.values(), tid])

    # ------------------------------------------------------------ 매수
    def on_signals(self, now: datetime, items) -> None:
        sig = next((x for x in items if x[3].kind == WEAK_KIND and x[0] == CODE), None)
        if sig is None or not (OPEN <= now.time() < LAST):
            return
        if self.active() or self.bought_today():
            return
        tid = f"{now:%Y%m%d}-{CODE}"
        try:
            q = self.market.quote(CODE, integrated=False)
            price = float(q.price) if q and q.price else None
            cash = self.client.cash()
            budget = min(SEED + self.realized(), cash, REAL_MAX_ORDER)
            qty = int(budget // price) if price else 0
            if qty < 1:
                why = f"주문 가능 금액 부족 (주문 가능 {cash:,}원, 시드+손익 {SEED + self.realized():,.0f}원, 현재가 {price or 0:,.0f}원)"
                self.conn.execute("INSERT OR REPLACE INTO real_trades (id, date, code, qty, status, note) VALUES (?, ?, ?, 0, 'failed', ?)",
                                  [tid, self.today, CODE, why])
                self.notify(f"🔴 실전 ⑤ 인버스 매수 못 함 — {why}")
                return
            no = self.client.market_order("buy", CODE, qty)
            self.conn.execute("""INSERT OR REPLACE INTO real_trades (id, date, code, qty, buy_order_no, buy_ts, buy_price, status)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, 'ordered')""", [tid, self.today, CODE, qty, no, now.replace(tzinfo=None), price])
            self.notify(f"🔴 실전 매수 주문 TIGER 인버스({CODE}) {qty}주 × 약 {price:,.0f}원 = {qty * price:,.0f}원 (주문 {no})\n"
                        f"  [⑤ 약세장 인버스] 익절 +{WEAK_TP:.0%} / 손절 −{WEAK_STOP:.0%}, 못 닿으면 다음 날 09:00 매도")
            logging.info("실전 매수 주문 %s %s주 (주문 %s)", CODE, qty, no)
        except Exception as exc:
            logging.exception("실전 매수 실패")
            self.conn.execute("INSERT OR REPLACE INTO real_trades (id, date, code, qty, status, note) VALUES (?, ?, ?, 0, 'failed', ?)",
                              [tid, self.today, CODE, f"오류: {exc}"[:300]])
            self.notify(f"⚠️ 실전 매수 실패 TIGER 인버스 — {exc}"[:500])

    # ------------------------------------------------------------ 체결 확인·매도
    def tick(self, now: datetime) -> None:
        self.liquidate_once(now)
        t = self.active()
        if not t:
            return
        tid, d, qty, buy_no, buy_price, sell_no, status = t
        tm = now.time()
        try:
            if status == "ordered":
                px = self.client.fill_price(buy_no, CODE)
                if px:
                    self._set(tid, buy_price=px, status="open")
                    self.notify(f"🔴 실전 매수 체결 TIGER 인버스 {qty}주 × {px:,.0f}원 — 손절 {px * (1 - WEAK_STOP):,.0f}원 · 익절 {px * (1 + WEAK_TP):,.0f}원")
                return
            if status == "selling":
                px = self.client.fill_price(sell_no, CODE)
                if px:
                    pnl = qty * (px - buy_price) - qty * buy_price * COST
                    self._set(tid, sell_price=px, pnl=pnl, status="closed")
                    self.notify(f"🔴 실전 매도 체결 TIGER 인버스 {qty}주 × {px:,.0f}원 — {px / buy_price - 1 - COST:+.2%} ({pnl:+,.0f}원)\n"
                                f"  ⑤ 실전 누적 실현 손익 {self.realized():+,.0f}원")
                return
            if not (OPEN <= tm < CLOSE):
                return
            reason = None
            if d < self.today:
                reason = "다음 날 시초 매도"
            elif tm < LAST:
                q = self.market.quote(CODE, integrated=False)
                if q and q.price:
                    if q.price <= buy_price * (1 - WEAK_STOP):
                        reason = f"손절 −{WEAK_STOP:.0%}"
                    elif q.price >= buy_price * (1 + WEAK_TP):
                        reason = f"익절 +{WEAK_TP:.0%}"
            if reason:
                held = self.client.holding_qty(CODE)
                sell_qty = min(qty, held)
                if sell_qty < 1:
                    self._set(tid, status="failed", note=f"팔 수량 없음 (계좌 {held}주)")
                    self.notify(f"⚠️ 실전 매도 못 함 TIGER 인버스 — 계좌 매도 가능 {held}주 (직접 확인 필요)")
                    return
                no = self.client.market_order("sell", CODE, sell_qty)
                self._set(tid, sell_order_no=no, sell_ts=now.replace(tzinfo=None), reason=reason, status="selling", qty=sell_qty)
                self.notify(f"🔴 실전 매도 주문 TIGER 인버스 {sell_qty}주 — {reason} (주문 {no})")
                logging.info("실전 매도 주문 %s %s주 %s", CODE, sell_qty, reason)
        except Exception as exc:
            logging.exception("실전 인버스 확인 실패")
            self.notify(f"⚠️ 실전 인버스 확인 실패 — {exc}"[:500])
