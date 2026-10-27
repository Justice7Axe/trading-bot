"""🎯 매수 신호 모의투자 — 키움 모의 서버(mockapi.kiwoom.com) 정규장 실주문 + NXT 프리·애프터장 가상 체결.

규칙 (2026-10-15 사용자 확정):
- 매수: 품질 필터를 통과해 알림한 🎯 신호만, 시장가. 현재가가 신호가(신호 봉 종가)보다 +1% 넘게 올랐으면 추격하지 않는다.
- 금액: 종목당 100만 원 안에서 살 수 있는 만큼. 1주 가격이 100만 원을 넘으면 1주 (상한 없음).
- 동시 보유 최대 10종목(눌림 돌파는 2종목), 이미 보유한 종목은 추가 매수 안 함.
- 하루 손실 한도: 실현 + 평가 손익이 그날 시작 자산의 -3% 에 닿으면 새로 사지 않는다.
- 🎯 눌림 돌파는 사지 않는다(알림만). 🎯 주도주 모양은 강한 상승장 + 전날 외인·기관 둘 다 순매수 종목만 (2026-10-24 사용자, 1년 조건 겹치기 검증).
- 09:10 시장 분위기 판정 전(정규장 09:00~09:10, 판정 스냅샷이 늦으면 늦어도 09:15)에는 차트 신호를 사지 않는다.
  대형주 수급·인버스 갭과 NXT 가상 체결은 예외 (2026-10-24 사용자).
- Nada 손실 관리 (2026-10-24 사용자, nada-trading-kr 스킬 1절 3항): 매수 신호·매도 규칙은 그대로 두고 금액만 줄인다.
    · 그날 손익 -2% 이하 또는 이번 주(월요일~) 손익 -3% 이하 → 이후 매수 금액 절반
    · 오늘 손실로 끝난 종목을 다시 사면 → 금액 절반 (복수 매매 방지). 두 조건이 겹치면 1/4
    · 1주 가격이 줄인 금액보다 크면 1주
- 매도:
    · 돈이 평소 5배↑ 붙은 신호('추적'): 처음 손절 -5%, +5% 도달 뒤 고점 대비 -3% 에 청산
    · 그 밖('기본'): 신호 손절가
    · 15:19 남은 종목은 모두 시장가 정리 (15:20 부터는 장 마감 동시호가)
- 가상 체결 (2026-10-15 사용자 선택 1번): 모의 서버가 지원하지 않는 NXT 프리장(08:00~08:50)·애프터장(15:30~20:00)은
  주문 없이 그 시점 통합(_AL) 시세로 사고판 것으로 기록한다. 매도 규칙은 같고, 프리장 물량은 08:49, 애프터장 물량은 19:50 에 정리.
  (신호 박스 고점은 09:00 이후로 잡으므로 프리장 신호는 사실상 나오지 않는다. 애프터장 신호는 15:30~19:30 만 통과)
- 텔레그램 리포트 두 번 (2026-10-15 사용자): 15:40 정규장 마감, 19:55 최종(애프터장 포함). 당일 결과 + 누적 결과 (실주문·가상 구분).

모의 서버 제약 (2026-10-15 확인): NXT·SOR 주문, KRX 시간외(장전·장후·단일가) 주문 모두 미지원 → 09:00~15:30 정규장만 실주문.
주문 API 는 초당 1회 제한이 있어 모의 서버 호출은 1.05초 간격으로 보낸다.
시세는 실서버 클라이언트(KiwoomMarket, KRX 시세)로 본다. 주문·잔고만 모의 서버.

    .venv\\Scripts\\python.exe -m kiwoom_trading.execution.paper --status            # 모의 계좌 잔고·예수금
    .venv\\Scripts\\python.exe -m kiwoom_trading.execution.paper --report [YYYYMMDD] # 리포트 콘솔 미리보기
"""
import argparse
import html
import logging
import os
import sys
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, load_env
from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, _to_int
from kiwoom_trading.screener.daily_summary import _pct, _table
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.strategies.bigcap_flow.live import KIND as BIGCAP_KIND, TARGET as BIGCAP_TARGET
from kiwoom_trading.strategies.early_nine.live import KIND as NINE_KIND
from kiwoom_trading.strategies.hamburger.live import KIND as BURGER_KIND
from kiwoom_trading.strategies.inverse.live import KIND as INVERSE_KIND, WEAK_KIND, WEAK_TP
from kiwoom_trading.strategies.contra_close.live import KIND as CONTRA_KIND
from kiwoom_trading.strategies.danswer.rebreak import KIND as REBREAK_KIND
from kiwoom_trading.strategies.danswer.close import KIND as DANSWER_KIND
from kiwoom_trading.strategies.resistance_retest.live import RETEST_KIND, RETEST_TP
from kiwoom_trading.strategies.regime_plays.live import BLOCK_KIND, NEWHIGH_KIND, UP_BUDGET, UP_HALF_TP, UP_KIND, UP_TOP_N, UP_TRAIL
from kiwoom_trading.strategies.premarket_reclaim.live import HALF_R as RECLAIM_HALF_R, KIND as RECLAIM_KIND, TRAIL as RECLAIM_TRAIL
from kiwoom_trading.strategies.trend_hold.live import BUDGET as TREND_BUDGET, BUY_END as TREND_BUY_END, KIND as TREND_KIND, MAX_HOLD as TREND_MAX, TREND_POOL
from kiwoom_trading.screener.market_regime import BIGCAP_MAX_WHEN_DOWN, CHECKS, CONSERVATIVE_LOSS_LIMIT, UP_ONLY_KINDS, WINDOW_MIN
from kiwoom_trading.strategies.leader_shape.live import KIND as LEADER_KIND, big_red_exit
from kiwoom_trading.strategies.pullback_breakout.live import KIND as PULLBACK_KIND, exit_reason as pullback_exit
from kiwoom_trading.screener.market_data import KiwoomMarket, _code
from kiwoom_trading.screener.store import ScreenerStore


MOCK_BASE_URL = "https://mockapi.kiwoom.com"
BUDGET_PER_STOCK = 1_000_000
LEAD_MULT, NONLEAD_MULT = 2.0, 0.5   # 🏆 주도주 신고가 금액: 테마 대장 / 아님 (홍인기·카페 '종목 고르기', 2026-10-27)
MAX_POSITIONS = 10            # 키움 제한이 아니라 우리 규칙. 모의 계좌 약 1천만 원 ÷ 종목당 100만 원 (2026-10-20, 10-19 복기: 5종목 한도로 신호 85건 건너뜀)
NEXT_DAY_KINDS = (RETEST_KIND, UP_KIND, BLOCK_KIND, NEWHIGH_KIND, CONTRA_KIND, WEAK_KIND, REBREAK_KIND, DANSWER_KIND, RECLAIM_KIND)   # '다음날' 매도: 익절가 / 손절가 / 다음 날 09:00 (2026-10-25 시장 상황별 매매표)
NEXT_DAY_TP = {RECLAIM_KIND: None, UP_KIND: None, NEWHIGH_KIND: None, WEAK_KIND: WEAK_TP, REBREAK_KIND: None, DANSWER_KIND: None}   # '다음날' 익절가 — 기본 +7%. 📈 상승장 장 초·🏆 주도주 신고가·🌙 종가 재돌파·🧭 디앤서 종가는 익절 없음, 약세장 인버스 +5% (2026-10-25)
OVERNIGHT_VIRTUAL = (REBREAK_KIND,)   # NXT 애프터장에 가상으로 사서 밤을 넘기는 신호 (모의 서버는 애프터장 주문 불가)
KIND_BUDGET = {UP_KIND: UP_BUDGET, TREND_KIND: TREND_BUDGET}   # 📈 상승장 장 초: 종목당 25만 원, 보유 한도(10종목) 예외로 40종목까지 (2026-10-25 사용자)
KIND_LIMIT = {PULLBACK_KIND: 2}  # 눌림 돌파는 장 초부터 자주 나와 자리를 차지 → 동시 2종목까지 (1년 −0.34%, 10-19 유일한 마이너스 −0.08%)
DAILY_LOSS_LIMIT = 0.03
NADA_DAY_DD = 0.02            # Nada: 그날 손익 -2% 부터 매수 금액 절반
NADA_WEEK_DD = 0.03           # Nada: 이번 주 손익 -3% 부터 매수 금액 절반
MAX_CHASE = 0.01              # 신호가 대비 +1% 넘게 오르면 추격 안 함
STRONG_FLOW = 5.0             # 평소 5배↑ → '추적' 방식
STRONG_STOP = 0.05            # 추적: 처음 손절 -5%
TRAIL_START = 0.05            # 추적: +5% 도달 뒤
TRAIL_GAP = 0.03              # 추적: 고점 대비 -3%
COST = 0.0025                 # 추정 왕복 비용 (수수료+세금, 백테스트와 같은 값)
HALF_TP = 0.02                # '반반'(🎯 주도주 모양): +2% 에서 절반 매도, 나머지는 손절 또는 15:19 (2026-10-17 사용자)

SESSION_OPEN = time(9, 0)
REGIME_FIRST = CHECKS[0]      # 09:10 강한 하락장 첫 판정 — 그 전에는 차트 신호를 사지 않는다 (2026-10-24 사용자, 10-23 09:07·09:08 매수 −2% 손절)
REGIME_WAIT_END = time(REGIME_FIRST.hour, REGIME_FIRST.minute + WINDOW_MIN)
LIQUIDATE_AT = time(15, 19)   # 15:20 부터 장 마감 동시호가
SESSION_CLOSE = time(15, 30)
PRE = (time(8, 0), time(8, 45), time(8, 49))        # NXT 프리장 가상 체결: 시작, 매수 마감, 정리
AFTER = (time(15, 30), time(19, 45), time(19, 50))  # NXT 애프터장 가상 체결
CLOSE_REPORT_AT = time(15, 40)   # 정규장 마감 리포트
REPORT_AT = time(19, 55)         # 최종 리포트 (애프터장 가상 체결 포함)
FILL_TIMEOUT_SEC = 300        # 시장가 주문이 5분 안에 체결 확인되지 않으면 실패 처리
TICK_SECONDS = 15             # 보유 종목 가격 확인 주기

ACTIVE = ("ordered", "open", "selling")


def session(t: time) -> Optional[str]:
    """'real' = KRX 정규장(실주문), 'pre'/'after' = NXT 프리·애프터장(가상 체결), None = 매매 없음."""
    if SESSION_OPEN <= t < SESSION_CLOSE:
        return "real"
    if PRE[0] <= t < SESSION_OPEN:
        return "pre"
    if AFTER[0] <= t < time(20, 0):
        return "after"
    return None


class MockClient(KiwoomDailyClient):
    """모의 서버 전용 클라이언트. 실서버 주소면 만들지 않는다 (실계좌 주문 방지)."""

    MIN_GAP = 1.05

    def __init__(self, base_url: str, app_key: str, secret_key: str) -> None:
        if "mockapi" not in base_url:
            raise RuntimeError(f"모의투자는 모의 서버에서만 실행합니다: {base_url}")
        super().__init__(base_url, app_key, secret_key)
        self._last_mock = 0.0

    def _post(self, path: str, api_id: str, body: dict[str, Any], cont_yn: str = "N", next_key: str = ""):
        wait = self.MIN_GAP - (_time.monotonic() - self._last_mock)
        if wait > 0:
            _time.sleep(wait)
        try:
            return super()._post(path, api_id, body, cont_yn, next_key)
        finally:
            self._last_mock = _time.monotonic()

    # ------------------------------------------------------------ 계좌·주문
    def account(self) -> tuple[int, dict[str, tuple[int, float, int, str]]]:
        """kt00018 → (추정 예탁자산, {코드: (보유수량, 매입단가, 주문가능수량, 이름)})"""
        payload, _, _ = self._post("/api/dostk/acnt", "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        holdings = {}
        for row in payload.get("acnt_evlt_remn_indv_tot") or []:
            qty = _to_int(row.get("rmnd_qty")) or 0
            if qty > 0:
                holdings[_code(row.get("stk_cd"))] = (qty, float(_to_int(row.get("pur_pric")) or 0),
                                                      _to_int(row.get("trde_able_qty")) or 0, str(row.get("stk_nm") or "").strip())
        return _to_int(payload.get("prsm_dpst_aset_amt")) or 0, holdings

    def cash(self) -> int:
        """kt00001 주문 가능 금액."""
        payload, _, _ = self._post("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})
        return _to_int(payload.get("ord_alow_amt")) or 0

    def market_order(self, side: str, code: str, qty: int) -> str:
        """시장가 주문 → 주문번호. side: 'buy' | 'sell'"""
        api = {"buy": "kt10000", "sell": "kt10001"}[side]
        payload, _, _ = self._post("/api/dostk/ordr", api, {"dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(qty),
                                                            "ord_uv": "", "trde_tp": "3", "cond_uv": ""})
        return str(payload.get("ord_no") or "")

    def fill_price(self, order_no: str, code: str) -> Optional[float]:
        """ka10076 체결 내역(그 종목만)에서 주문번호의 평균 체결가."""
        payload, _, _ = self._post("/api/dostk/acnt", "ka10076", {"stk_cd": code, "qry_tp": "1", "sell_tp": "0", "ord_no": "", "stex_tp": "0"})
        qty = amount = 0
        for row in payload.get("cntr") or []:
            if str(row.get("ord_no") or "").lstrip("0") == order_no.lstrip("0"):
                q, p = _to_int(row.get("cntr_qty")) or 0, _to_int(row.get("cntr_pric")) or 0
                qty, amount = qty + q, amount + q * p
        return amount / qty if qty else None


def build_mock_client() -> MockClient:
    load_env()
    app_key, secret = os.getenv("KIWOOM_MOCK_APP_KEY", ""), os.getenv("KIWOOM_MOCK_SECRET_KEY", "")
    if not app_key or not secret:
        raise RuntimeError("KIWOOM_MOCK_APP_KEY / KIWOOM_MOCK_SECRET_KEY 를 .env.local 에 설정해주세요.")
    return MockClient(os.getenv("KIWOOM_MOCK_BASE_URL", MOCK_BASE_URL), app_key, secret)


def mock_configured() -> bool:
    load_env()
    return bool(os.getenv("KIWOOM_MOCK_APP_KEY") and os.getenv("KIWOOM_MOCK_SECRET_KEY"))


def load_prev_flow(day: date, db_path: str = DEFAULT_DB_PATH) -> dict[str, tuple[Optional[int], Optional[int]]]:
    """day 전 거래일의 종목별 (외인, 기관) 순매수 금액 — 20:00 일봉 업데이트가 넣은 investor_daily. 못 읽으면 빈 dict(주도주 모양은 안 삼)."""
    try:
        conn = duckdb.connect(db_path, read_only=True)
        try:
            prev = conn.execute("SELECT max(date) FROM investor_daily WHERE date < ?", [day]).fetchone()[0]
            rows = conn.execute("SELECT code, foreign_, institution FROM investor_daily WHERE date = ?", [prev]).fetchall()
        finally:
            conn.close()
        logging.info("전날 외인·기관 수급 %s종목 (%s)", len(rows), prev)
        return {c: (f, i) for c, f, i in rows}
    except Exception:
        logging.exception("전날 외인·기관 수급 읽기 실패 — 오늘 주도주 모양은 사지 않음")
        return {}


def _next_day_how(tp: Optional[float], stop: Optional[float], kind: str = "") -> str:
    if kind == UP_KIND:
        return (f"+{UP_HALF_TP:.0%} 에 절반 익절 → 남은 절반 고점 −{UP_TRAIL:.0%} 트레일링 / 처음 손절 {stop:,.0f}원, "
                f"못 닿으면 다음 날 09:00 매도")
    tp_txt = f"+{tp:.0%} 익절" if tp is not None else "익절 없음"
    return f"{tp_txt} / 손절 {stop:,.0f}원, 못 닿으면 다음 날 09:00 매도" if stop else f"{tp_txt}, 손절 없이 다음 날 09:00 매도"


def _flow_txt(x: Optional[int]) -> str:
    return "자료 없음" if x is None else f"{x / 1e8:+,.0f}억"


# ---------------------------------------------------------------- 규칙 (순수 함수)
def order_qty(price: float, budget: int = BUDGET_PER_STOCK) -> int:
    """100만 원 안에서 살 수 있는 수량, 1주가 100만 원을 넘으면 1주."""
    return max(1, int(budget // price))


def exit_check(mode: str, buy_price: float, stop: float, peak: float, price: float,
               tp: Optional[float] = RETEST_TP) -> tuple[float, float, Optional[str]]:
    """현재가로 (새 손절가, 새 고점, 매도 사유|None). 추적 방식은 +5% 도달 뒤 손절가를 고점 -3% 로 따라 올린다.
    목표 방식(🎯 대형주 수급)은 +2% 에 전부 판다. '다음날' 방식의 익절가는 tp (None 이면 익절 없음)."""
    peak = max(peak, price)
    if mode == "추적" and peak >= buy_price * (1 + TRAIL_START):
        stop = max(stop, peak * (1 - TRAIL_GAP))
    if mode == "목표" and price >= buy_price * (1 + BIGCAP_TARGET):
        return stop, peak, f"목표 +{BIGCAP_TARGET:.0%}"
    if mode == "다음날" and tp is not None and price >= buy_price * (1 + tp):     # 익절, 못 닿으면 다음 날 09:00
        return stop, peak, f"익절 +{tp:.0%}"
    if price <= stop:
        trailing = mode == "추적" and stop > buy_price * (1 - STRONG_STOP) + 1e-9
        return stop, peak, ("고점 대비 -3%" if trailing else "손절")
    return stop, peak, None


@dataclass
class Trade:
    id: str
    date: date
    code: str
    name: str
    kind: str
    source: str
    signal_ts: Optional[datetime]
    signal_price: Optional[float]
    flow_mult: Optional[float]
    mode: str
    status: str
    qty: int = 0
    buy_ts: Optional[datetime] = None
    buy_order_no: str = ""
    buy_price: Optional[float] = None
    stop: Optional[float] = None
    peak: Optional[float] = None
    sell_ts: Optional[datetime] = None
    sell_order_no: str = ""
    sell_price: Optional[float] = None
    sell_reason: str = ""
    note: str = ""
    virtual: bool = False       # NXT 프리·애프터장 가상 체결 (주문 없음)
    part_qty: int = 0           # '반반' 방식에서 먼저 판 절반 수량
    part_price: Optional[float] = None
    part_order_no: str = ""


FIELDS = list(Trade.__dataclass_fields__)


def save_trade(store: ScreenerStore, t: Trade) -> None:
    cols = ", ".join(FIELDS)
    store.conn.execute(f"INSERT OR REPLACE INTO paper_trades ({cols}) VALUES ({', '.join('?' * len(FIELDS))})",
                       [getattr(t, f) for f in FIELDS])


def load_trades(store: ScreenerStore, where: str, params: list) -> list[Trade]:
    rows = store.conn.execute(f"SELECT {', '.join(FIELDS)} FROM paper_trades WHERE {where} ORDER BY coalesce(buy_ts, signal_ts)", params).fetchall()
    return [Trade(*[(v or "") if FIELDS[k] in ("buy_order_no", "sell_order_no", "sell_reason", "note", "part_order_no")
                    else (v or 0) if FIELDS[k] == "part_qty" else v
                    for k, v in enumerate(r)]) for r in rows]


def net_pnl(t: Trade, price: Optional[float] = None) -> Optional[float]:
    """원 단위 손익 (추정 비용 0.25% 차감). price 를 주면 평가 손익."""
    exit_price = price if price is not None else t.sell_price
    if not t.buy_price or not exit_price or not t.qty:
        return None
    part = min(t.part_qty or 0, t.qty)   # '반반': 먼저 판 절반은 그 체결가로
    gain = (exit_price - t.buy_price) * (t.qty - part) + ((t.part_price or exit_price) - t.buy_price) * part
    return gain - t.buy_price * t.qty * COST


def net_ret(t: Trade) -> Optional[float]:
    pnl = net_pnl(t)
    return pnl / (t.buy_price * t.qty) if pnl is not None else None


# ---------------------------------------------------------------- 실행
class PaperTrader:
    def __init__(self, mock: MockClient, market: KiwoomMarket, store: ScreenerStore, today: date,
                 notify: Optional[Callable[[str], Any]] = None) -> None:
        self.mock = mock
        self.market = market
        self.store = store
        self.today = today
        self.notify = notify or (lambda text: None)
        self.lead_now: dict = {}   # 지금 테마 대장 {code: (테마, +4%↑ 수, 등락률)} — run_intraday 가 매분 ☕ cafe_leader 판단으로 채움
        self.halted = False
        self.regime = None                      # MarketRegime (run_intraday 가 넣어 줌) — 강한 하락장이면 보수적 매매
        self.prev_flow = load_prev_flow(today)  # 전날 외인·기관 순매수 (주도주 모양 매수 조건)
        self.trend_picks: int = 0                  # 오늘 ⑦ 매수 대상 수 (run_intraday 가 넣어 줌) — 0 이면 ⑦ 몫을 남겨 두지 않음
        self.trend_exit: dict[str, tuple] = {}   # ⑦ 주도주 추세: 전날 종가가 20일선 아래인 보유 종목 → 오늘 09:00 매도 (run_intraday 가 넣어 줌)
        self.last_price: dict[str, float] = {}
        self._last_tick = 0.0
        self._chart_checked: dict[str, datetime] = {}   # '차트' 매도: 거래별 마지막으로 본 분
        # 오늘 기록 + 전날 끝나지 않은 기록(장애로 정리 못 한 경우)
        self.trades = load_trades(store, "date = ? OR status IN ('ordered', 'open', 'selling')", [today])
        asset, holdings = mock.account()
        row = store.conn.execute("SELECT asset_start, reported, reported_close FROM paper_days WHERE date = ?", [today]).fetchone()
        if row is None:
            store.conn.execute("INSERT INTO paper_days (date, asset_start) VALUES (?, ?)", [today, asset])
        self.asset_start = row[0] if row else asset
        self.reported = bool(row[1]) if row else False          # 19:55 최종
        self.reported_close = bool(row[2]) if row else False    # 15:40 정규장 마감
        monday = today - timedelta(days=today.weekday())   # 이번 주 앞선 날들의 실현 손익 (Nada 주간 드로다운)
        self.week_prior = sum(net_pnl(t) or 0 for t in load_trades(store, "date >= ? AND date < ? AND status = 'closed'", [monday, today]))
        tracked = {t.code for t in self.active()}
        for code, (qty, avg, _, name) in holdings.items():       # 기록 없이 남아 있는 보유분 → 첫 정규장에 정리
            if code not in tracked:
                t = Trade(f"{today:%Y%m%d}-{code}-carry", today, code, name, "이월", "이월", None, None, None, "이월", "open",
                          qty=qty, buy_ts=datetime.combine(today, SESSION_OPEN), buy_price=avg, stop=None, peak=avg,
                          note="기록 없는 보유분 — 첫 정규장에 정리")
                self.trades.append(t)
                save_trade(store, t)
        logging.info("모의투자 준비: 추정자산 %s원, 보유 %s종목, 오늘 기록 %s건", f"{asset:,}", len(holdings), len(self.trades))

    def active(self) -> list[Trade]:
        return [t for t in self.trades if t.status in ACTIVE]

    # ------------------------------------------------------------ 매수
    def on_signals(self, now: datetime, items: list[tuple[str, str, str, Signal]],
                   flow: dict[tuple[str, datetime], tuple[float, Optional[float]]]) -> None:
        for code, name, source, s in items:
            mult = (flow.get((code, s.ts)) or (None, None))[1]
            mode = "추세" if s.kind == TREND_KIND else "다음날" if s.kind in NEXT_DAY_KINDS else "보유" if s.kind == INVERSE_KIND else "목표" if s.kind in (BIGCAP_KIND, BURGER_KIND) else "차트" if s.kind in (LEADER_KIND, NINE_KIND) else "눌림" if s.kind == PULLBACK_KIND else "추적" if mult is not None and mult >= STRONG_FLOW else "기본"
            t = Trade(f"{s.ts:%Y%m%d}-{code}-{s.ts:%H%M}-{s.kind}", self.today, code, name, s.kind, source, s.ts, s.price,
                      mult, mode, "skipped", stop=s.stop)
            if any(x.id == t.id for x in self.trades):
                continue
            try:
                self._buy(now, t, s)
            except Exception as exc:
                logging.exception("모의 매수 실패 %s", name)
                t.status, t.note = "failed", f"주문 오류: {exc}"[:300]
                self.notify(f"⚠️ 모의 매수 실패 {name}({code}) — {t.note}")
            self.trades.append(t)
            save_trade(self.store, t)

    def _skip_reason(self, now: datetime, t: Trade) -> Optional[str]:
        tm = now.time()
        if not (SESSION_OPEN <= tm < LIQUIDATE_AT or PRE[0] <= tm < PRE[1] or AFTER[0] <= tm < AFTER[1]):
            return "매수 시간 아님 (정규장 09:00~15:19, 가상 08:00~08:45·15:30~19:45)"
        if self.halted:
            return f"하루 손실 한도 -{self._loss_limit():.1%} 도달"
        if not t.virtual and t.kind not in (BIGCAP_KIND, INVERSE_KIND, WEAK_KIND, TREND_KIND, RECLAIM_KIND) and self._before_regime(tm):
            return f"시장 분위기 판정({REGIME_FIRST:%H:%M}) 전 — 차트 신호는 사지 않음"
        if self.regime is not None and self.regime.strong_down and not t.virtual and t.kind not in (RETEST_KIND, CONTRA_KIND, DANSWER_KIND, TREND_KIND, RECLAIM_KIND):   # 🔁 시초 회복은 1년 모든 날 검증 · 저항 돌파·디앤서 종가·주도주 추세는 모든 날, 역행 강세 종가는 강한 하락장 날 산다
            if t.kind not in (BIGCAP_KIND, INVERSE_KIND):
                return "강한 하락장 — 차트 신호는 새로 사지 않음 (보수적 매매)"
            bought = sum(1 for x in self.trades if x.date == self.today and x.kind == BIGCAP_KIND and x.buy_ts)
            if bought >= BIGCAP_MAX_WHEN_DOWN:
                return f"강한 하락장 — 대형주 수급은 {BIGCAP_MAX_WHEN_DOWN}종목까지 (보수적 매매)"
        r = self.regime
        if (r is not None and r.trend_weak and not r.strong_up and not t.virtual and t.kind not in (INVERSE_KIND, RETEST_KIND, CONTRA_KIND, WEAK_KIND, DANSWER_KIND, TREND_KIND, RECLAIM_KIND)
                and not self._before_regime(tm)):
            return f"하락 흐름 보통 날 ({r.trend_text()}) — 이 신호는 쉼 (저항 돌파·약세장 인버스만 삼)"
        if t.kind == PULLBACK_KIND:
            return "눌림 돌파는 알림만 — 1년 어떤 조건에서도 손실 (2026-10-24)"
        if t.kind == DANSWER_KIND:
            return ("[디앤서] 14:30 주도주 종가는 알림만 — 단독 1년 +0.96%/건이지만 6️⃣ 주도주 신고가와 같은 종목이 많아 "
                    "계좌 보탬이 작음(+55만, 낙폭 +1.2%p) → 알림으로 쌓아 보고 결정 (2026-10-25)")
        if t.kind in UP_ONLY_KINDS and not t.virtual and not (self.regime is not None and self.regime.strong_up):
            return "강한 상승장 아님 — 이 차트 신호는 강한 상승장에만 삼"
        if t.kind == LEADER_KIND and not t.virtual:
            f, i = self.prev_flow.get(t.code, (None, None))
            if not (f and f > 0 and i and i > 0):
                return ("전날 외인·기관 둘 다 순매수 아님 — 주도주 모양은 둘 다 순매수 종목만 삼 "
                        f"(외인 {_flow_txt(f)}, 기관 {_flow_txt(i)})")
        if t.kind == UP_KIND and not t.virtual:
            f, i = self.prev_flow.get(t.code, (None, None))
            if f is not None and i is not None and f < 0 and i < 0:
                return (f"전날 외인·기관 둘 다 순매도 — {UP_KIND}에서 뺌 (외인 {_flow_txt(f)}, 기관 {_flow_txt(i)}; "
                        "1년 강한 상승장 이런 종목 −0.04%, 나머지 +0.86%)")
        if any(x.code == t.code and not (t.kind == TREND_KIND and x.status == "selling") for x in self.active()):
            return "이미 보유 중"   # ⑦ 은 09:00 에 파는 중인 같은 종목(전날 '다음날' 매매)은 막지 않는다
        if t.kind == UP_KIND:
            if sum(1 for x in self.active() if x.kind == UP_KIND) >= UP_TOP_N:
                return f"{UP_KIND} 최대 {UP_TOP_N}종목 보유 중"
        elif t.kind == TREND_KIND:
            if sum(1 for x in self.active() if x.kind == TREND_KIND) >= TREND_MAX:
                return f"{TREND_KIND} 최대 {TREND_MAX}종목 보유 중"
        elif sum(1 for x in self.active() if x.kind not in (UP_KIND, TREND_KIND)) >= MAX_POSITIONS:
            return f"최대 {MAX_POSITIONS}종목 보유 중"
        cap = KIND_LIMIT.get(t.kind)
        if cap is not None and sum(1 for x in self.active() if x.kind == t.kind) >= cap:
            return f"{t.kind} 동시 {cap}종목 보유 중"
        return None

    def _before_regime(self, tm: time) -> bool:
        """정규장인데 아직 09:10 강한 하락장 판정을 못 봤는가. 09:10 판정은 09:10~09:15 첫 스냅샷에서 하므로
        그 판정이 끝나기 전(늦어도 09:15)까지는 기다린다."""
        if not SESSION_OPEN <= tm < REGIME_WAIT_END:
            return False
        if tm < REGIME_FIRST:
            return True
        r = self.regime
        return r is not None and not (r.strong_down or r.strong_up) and REGIME_FIRST not in r.done

    def _buy(self, now: datetime, t: Trade, s: Signal) -> None:
        t.virtual = session(now.time()) != "real"   # _skip_reason 이 가상 여부를 보므로 먼저
        reason = self._skip_reason(now, t)
        price = None
        if reason is None:
            q = self.market.quote(t.code, integrated=t.virtual)   # 가상은 NXT 체결까지 반영한 통합 시세
            price = q.price if q else None
            if not price:
                reason = "시세 조회 실패"
            elif t.kind == RECLAIM_KIND and (not s.stop or price <= s.stop):
                reason = "이미 흔들기 저가(손절선) 아래"
            elif price > s.price * (1 + MAX_CHASE):
                reason = f"현재가 {price:,}원이 신호가보다 {price / s.price - 1:+.1%} — 추격 안 함"
        if reason is None:
            factor, why = self._nada_factor(t) if t.kind != TREND_KIND else (1.0, "")   # ⑦ 은 정한 금액 그대로 (사용자 2026-10-25)
            if t.kind == NEWHIGH_KIND:   # 🏆 주도주 신고가: 테마 대장이면 2배, 아니면 절반 (2026-10-27, 1년 계좌 5,048만 → 5,423만, 스킬 hong 8장)
                lead = self.lead_now.get(t.code)
                factor *= LEAD_MULT if lead else NONLEAD_MULT
                why = ((why + " · ") if why else "") + (f"👑 테마 대장 '{lead[0]}' → {LEAD_MULT:g}배" if lead else f"테마 대장 아님 → {NONLEAD_MULT:g}배")
            t.qty = order_qty(price, int(KIND_BUDGET.get(t.kind, BUDGET_PER_STOCK) * factor))
            if why:
                t.note = f"금액 {factor:g}배: {why}"
                logging.info("모의 매수 금액 축소 %s: %s", t.name, t.note)
            cash = self.mock.cash() if not t.virtual else t.qty * price
            used = self._trend_used()
            keep = self._trend_keep(now, used)
            if t.kind == TREND_KIND and used + t.qty * price > TREND_POOL:
                reason = f"7️⃣ 몫 {TREND_POOL / 1e4:,.0f}만 원 중 {used / 1e4:,.0f}만 원 사용 중 — {t.qty * price / 1e4:,.0f}만 원 더 못 삼"
            elif t.kind != TREND_KIND and not t.virtual and keep and cash - keep < t.qty * price:
                reason = (f"주문 가능 금액 부족 ({cash:,}원 중 7️⃣ 몫 {keep:,.0f}원은 남겨 둠 < {t.qty * price:,}원)")
            elif cash < t.qty * price:
                reason = f"주문 가능 금액 부족 ({cash:,}원 < {t.qty * price:,}원)"
        if reason:
            t.note = reason
            logging.info("모의 매수 건너뜀 %s: %s", t.name, reason)
            self.notify(f"⏭ 모의 매수 건너뜀 {t.name}({t.code}) [{t.kind} {s.ts:%H:%M}] — {reason}")
            return
        if t.virtual:
            t.status, t.buy_ts, t.buy_price, t.peak = "open", now.replace(tzinfo=None), float(price), float(price)
            if t.mode == "추적":
                t.stop = t.buy_price * (1 - STRONG_STOP)
            self.last_price[t.code] = price
            logging.info("가상 매수 %s %s주 × %s", t.name, t.qty, price)
            self.notify(f"🟣 가상 매수 {t.name}({t.code}) {t.qty}주 × {price:,}원 = {t.qty * price / 1e4:,.0f}만 원 "
                        f"(NXT {'프리장' if now.time() < SESSION_OPEN else '애프터장'}, 주문 없이 기록만)\n"
                        f"  [{t.kind} {s.ts:%H:%M}] "
                        + (_next_day_how(NEXT_DAY_TP.get(t.kind, RETEST_TP), s.stop, t.kind) if t.mode == "다음날"
                           else f"손절 {t.stop:,.0f}원 ({t.stop / price - 1:+.1%})" if t.stop else "손절 없음") + f" — {t.source}"
                        + (f"\n  📏 {t.note}" if t.note else ""))
            return
        t.buy_order_no = self.mock.market_order("buy", t.code, t.qty)
        t.status, t.buy_ts, t.peak = "ordered", now.replace(tzinfo=None), float(price)
        self.last_price[t.code] = price
        how = (f"손절 -{STRONG_STOP:.0%}, +{TRAIL_START:.0%} 뒤 고점 -{TRAIL_GAP:.0%} (평소 {t.flow_mult:.1f}배)"
               if t.mode == "추적" else "손절·익절 없음, 종가가 20일선 아래면 다음 날 09:00 매도" if t.mode == "추세" else _next_day_how(NEXT_DAY_TP.get(t.kind, RETEST_TP), s.stop, t.kind) if t.mode == "다음날" else "손절 없음, 15:19 정리" if not s.stop else f"손절 {s.stop:,.0f}원 ({s.stop / price - 1:+.1%})")
        logging.info("모의 매수 주문 %s %s주 (주문 %s)", t.name, t.qty, t.buy_order_no)
        self.notify(f"🟢 모의 매수 {t.name}({t.code}) {t.qty}주 × 약 {price:,}원 = {t.qty * price / 1e4:,.0f}만 원\n"
                    f"  [{t.kind} {s.ts:%H:%M}] {how} — {t.source}"
                    + (f"\n  📏 {t.note}" if t.note else ""))

    # ------------------------------------------------------------ 보유·매도
    def tick(self, now: datetime, force: bool = False) -> None:
        """보유 종목 가격 확인 → 손절·추적·15:19 정리(가상은 08:49·19:50), 주문 체결 확인, 19:55 리포트. 15초에 한 번만 실행."""
        if not force and _time.monotonic() - self._last_tick < TICK_SECONDS:
            return
        self._last_tick = _time.monotonic()
        t_now = now.time()
        sess = session(t_now)
        # 체결 확인은 정규장 밖에서도 한다: 15:19 정리 주문은 15:30 동시호가에 체결되므로
        # 15:30 이후에 확인하지 않으면 '매도 중'으로 남아 애프터장 보유 한도를 막는다.
        if any(t.status in ("ordered", "selling") and not t.virtual for t in self.trades):
            self._reconcile(now)
        if sess:
            for t in [x for x in self.trades if x.status == "open" and (x.virtual or sess == "real")]:
                self._watch(now, t, sess)
            self._check_halt()
        if t_now >= REPORT_AT and not self.reported:
            self.send_report(now)
        elif t_now >= CLOSE_REPORT_AT and not self.reported_close and not self.reported:
            self.send_report(now, final=False)

    def _watch(self, now: datetime, t: Trade, sess: str) -> None:
        tm = now.time()
        if t.mode == "추세":                                  # ⑦ 손절·익절·15:19 정리 없음 — 전날 종가 20일선 이탈 때만 09:00 매도
            brk = self.trend_exit.get(t.code) if t.date < self.today else None
            if brk:
                return self._sell(now, t, f"20일선 이탈 ({brk[0]:%m-%d} 종가 {brk[1]:,.0f} < 20일선 {brk[2]:,.0f}) — 시초 매도")
            return
        if t.date < self.today or t.mode == "이월":
            if t.kind in OVERNIGHT_VIRTUAL and sess != "real":   # 🌙 애프터장 가상 매수는 다음 날 09:00 정규장 시세로 판다
                return
            return self._sell(now, t, "다음 날 시초 매도" if t.mode == "다음날" else "전날 남은 물량 정리")
        if t.virtual and t.kind in OVERNIGHT_VIRTUAL:
            pass                                               # 19:50 에 정리하지 않고 밤을 넘겨 들고 간다
        elif t.virtual:
            bought = session(t.buy_ts.time())
            if bought != sess or tm >= {"pre": PRE[2], "after": AFTER[2]}[sess]:
                return self._sell(now, t, "가상 시간 끝 정리")
        elif tm >= LIQUIDATE_AT and t.mode != "다음날":     # '다음날' 은 15:19 에 팔지 않고 들고 넘어간다
            return self._sell(now, t, "장 마감 정리")
        elif tm >= LIQUIDATE_AT:
            return
        q = self.market.quote(t.code, integrated=t.virtual)
        if not q:
            return
        self.last_price[t.code] = q.price
        stop, peak, reason = exit_check(t.mode, t.buy_price, t.stop, t.peak or t.buy_price, q.price, NEXT_DAY_TP.get(t.kind, RETEST_TP))
        if (stop, peak) != (t.stop, t.peak):
            t.stop, t.peak = stop, peak
            save_trade(self.store, t)
        if reason:
            if t.kind == UP_KIND and t.part_qty and reason == "손절":
                reason = f"트레일링 고점 −{UP_TRAIL:.0%} (절반 익절 뒤)"
            return self._sell(now, t, reason)
        if t.kind == RECLAIM_KIND and t.mode == "다음날":   # 🔁 +2R 절반 익절 → 남은 절반 고점 −3% 트레일링 (손절선은 매수 뒤 안 바뀌므로 R 은 지금 손절가로)
            if not t.part_qty:
                R = t.buy_price - (t.stop or 0)
                if 0 < R and q.price >= t.buy_price + RECLAIM_HALF_R * R:
                    return self._sell_half(now, t, q.price, (RECLAIM_HALF_R * R) / t.buy_price,
                                           f"고점 −{RECLAIM_TRAIL:.0%} 트레일링(본전 아래로 안 내림), 못 닿으면 다음 날 09:00")
            else:
                new = max(t.stop or 0, (t.peak or t.buy_price) * (1 - RECLAIM_TRAIL), t.buy_price)
                if new > (t.stop or 0) + 1e-9:
                    t.stop = new
                    save_trade(self.store, t)
            return
        if t.kind == UP_KIND and t.mode == "다음날":        # 1️⃣: +7% 절반 익절 → 남은 절반 고점 −4% 트레일링 (2026-10-27 사용자 'B 방식')
            if not t.part_qty and q.price >= t.buy_price * (1 + UP_HALF_TP):
                return self._sell_half(now, t, q.price, UP_HALF_TP,
                                       f"고점 −{UP_TRAIL:.0%} 트레일링(본전 아래로 안 내림), 못 닿으면 다음 날 09:00")
            if t.part_qty:
                new = max(t.stop or 0, (t.peak or t.buy_price) * (1 - UP_TRAIL), t.buy_price)
                if new > (t.stop or 0) + 1e-9:
                    t.stop = new
                    save_trade(self.store, t)
            return
        if t.mode in ("차트", "눌림") and not t.virtual:
            why = self._chart_exit(now, t)
            if why:
                return self._sell(now, t, why)
        if t.mode == "반반" and not t.part_qty and q.price >= t.buy_price * (1 + HALF_TP):
            self._sell_half(now, t, q.price)

    def _chart_exit(self, now: datetime, t: Trade) -> Optional[str]:
        """'차트'·'눌림' 매도: 새 1분봉이 마감될 때마다 그 종목 KRX 1분봉을 받아 매도 음봉인지 본다 (1분에 한 번).
        차트(주도주 모양) = 몸통 직전 20봉 평균 3배·대금 2배 음봉, 눌림(눌림 돌파) = 5분선 아래 마감 + 몸통 직전 5봉 평균 2배 음봉."""
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        if self._chart_checked.get(t.id) == minute:
            return None
        self._chart_checked[t.id] = minute
        try:
            bars = [b for b in fetch_minute_bars(self.market.client, t.code, self.today, "KRX") if b["ts"] < minute]
        except Exception:
            logging.warning("차트 매도 1분봉 조회 실패 %s", t.code)
            return None
        buy_minute = t.buy_ts.replace(second=0, microsecond=0)
        return pullback_exit(bars, buy_minute) if t.mode == "눌림" else big_red_exit(bars, buy_minute)

    def _sell_half(self, now: datetime, t: Trade, price: float, tp: float = HALF_TP, rest: str = "") -> None:
        """절반 매도 ('반반' +2%, 1️⃣ +7%). 1주뿐이면 전부 판다. 나머지는 rest 설명대로 (기본: 원래 손절가 또는 15:19 정리)."""
        if t.virtual:
            if t.qty < 2:
                return self._sell(now, t, f"익절 +{tp:.0%}")
            t.part_qty, t.part_price = t.qty // 2, float(price)
        else:
            try:
                _, holdings = self.mock.account()
                held = holdings.get(t.code)
                if not held or not held[2]:
                    return
                if held[0] < 2:
                    return self._sell(now, t, f"익절 +{tp:.0%} (1주라 전부)")
                half = held[0] // 2
                order_no = self.mock.market_order("sell", t.code, half)
                t.part_qty, t.part_order_no = half, order_no
                t.part_price = self.mock.fill_price(order_no, t.code) or float(price)
            except Exception as exc:
                logging.exception("모의 절반 매도 실패 %s", t.name)
                self.notify(f"⚠️ 모의 절반 매도 실패 {t.name}({t.code}) — 다음 확인 때 다시 시도\n  {exc}"[:300])
                return
        save_trade(self.store, t)
        logging.info("%s 절반 매도 %s %s주 × %s", "가상" if t.virtual else "모의", t.name, t.part_qty, t.part_price)
        self.notify(f"💰 {'가상' if t.virtual else '모의'} 절반 익절 {t.name} {t.part_qty}주 × {t.part_price:,.0f}원 "
                    f"({t.part_price / t.buy_price - 1:+.1%}) — 나머지 {t.qty - t.part_qty}주는 " + (rest or f"손절 {t.stop:,.0f}원 또는 15:19 정리"))

    def _sell(self, now: datetime, t: Trade, reason: str) -> None:
        try:   # 매도 직전 시세: 실주문은 체결가를 못 받을 때 쓸 추정가, 가상은 이 값이 체결가
            q = self.market.quote(t.code, integrated=t.virtual)
            if q:
                self.last_price[t.code] = q.price
        except Exception:
            logging.warning("매도 전 시세 조회 실패 %s", t.code)
        if t.virtual:
            if t.code not in self.last_price:
                return                                  # 다음 확인 때 다시
            t.status, t.sell_ts, t.sell_reason = "closed", now.replace(tzinfo=None), reason
            t.sell_price = float(self.last_price[t.code])
            save_trade(self.store, t)
            self._notify_closed(t)
            return
        try:
            _, holdings = self.mock.account()
            held = holdings.get(t.code)
            if not held or not held[2]:
                # 보유가 없으면 이미 팔렸고, 매도 가능 수량이 0 이면 앞서 낸 매도 주문이 아직 걸려 있다
                # (2026-10-16 아모레퍼시픽: 동시호가 중 재주문 → '매도가능수량 부족' 반복).
                # 새로 주문하지 않고 체결 확인(_reconcile)으로 넘긴다.
                if t.status != "selling":
                    t.status, t.sell_ts, t.sell_reason = "selling", now.replace(tzinfo=None), reason
                    save_trade(self.store, t)
                    logging.info("모의 매도 대기 %s: %s", t.name, "이미 팔림" if not held else "앞선 매도 주문 체결 대기")
                return
            qty = held[2]
            if (held[0] + t.part_qty, held[1]) != (t.qty, t.buy_price):   # 체결 확인 뒤 늘어난 수량·바뀐 평균 단가를 기록에 맞춘다 (먼저 판 절반 포함)
                logging.info("모의 보유 수량 보정 %s: %s주 × %s → %s주 × %s", t.name, t.qty, t.buy_price, held[0] + t.part_qty, held[1])
                t.qty, t.buy_price = held[0] + t.part_qty, held[1]
            t.sell_order_no = self.mock.market_order("sell", t.code, qty)
        except Exception as exc:
            logging.exception("모의 매도 주문 실패 %s", t.name)
            t.note = f"매도 오류: {exc}"[:300]
            save_trade(self.store, t)
            self.notify(f"⚠️ 모의 매도 실패 {t.name}({t.code}) — {reason}, 다음 확인 때 다시 시도\n  {t.note}")
            return
        t.status, t.sell_ts, t.sell_reason = "selling", now.replace(tzinfo=None), reason
        save_trade(self.store, t)
        logging.info("모의 매도 주문 %s %s주 (%s, 주문 %s)", t.name, qty, reason, t.sell_order_no)

    def _reconcile(self, now: datetime) -> None:
        """주문 체결 확인: 매수 → 계좌 보유 수량·매입단가, 매도 → 보유 사라짐 + 체결가."""
        _, holdings = self.mock.account()
        naive = now.replace(tzinfo=None)
        for t in [x for x in self.trades if x.status in ("ordered", "selling")]:
            held = holdings.get(t.code)
            if t.status == "ordered":
                timed_out = (naive - t.buy_ts).total_seconds() > FILL_TIMEOUT_SEC
                if held and held[0] < t.qty and not timed_out:
                    continue   # 주문 수량보다 적게 잡히면(일부 체결·잔고 반영 지연) 다 찰 때까지 기다린다 (2026-10-16 하나마이크론 24주 → 2주 기록)
                if held:
                    t.qty, t.buy_price = held[0], held[1]
                    t.peak = t.buy_price
                    if t.mode == "추적":
                        t.stop = t.buy_price * (1 - STRONG_STOP)
                    t.status = "open"
                    self.notify(f"✅ 모의 매수 체결 {t.name} {t.qty}주 × {t.buy_price:,.0f}원, 손절 {t.stop:,.0f}원")
                elif timed_out:
                    t.status, t.note = "failed", "5분 안에 체결 확인 안 됨"
                    self.notify(f"⚠️ 모의 매수 미체결 {t.name} — {t.note}")
            elif not held:
                t.sell_price = (self.mock.fill_price(t.sell_order_no, t.code) if t.sell_order_no else None) or self.last_price.get(t.code)
                if t.part_order_no:   # 절반 매도 체결가를 다시 확인 (주문 직후엔 체결 내역이 늦게 잡힐 수 있다)
                    t.part_price = self.mock.fill_price(t.part_order_no, t.code) or t.part_price
                t.status = "closed"
                self._notify_closed(t)
            elif held[2] and (naive - t.sell_ts).total_seconds() > FILL_TIMEOUT_SEC:
                # 매도 가능 수량이 다시 생겼다 = 주문이 취소·거부됐다 → 다시 감시해 다음 확인 때 재주문.
                # 매도 가능 0 이면 주문이 아직 걸려 있으니(15:20~15:30 동시호가 등) 체결될 때까지 기다린다.
                t.status = "open"
                t.note = "매도 미체결 — 재시도"
            save_trade(self.store, t)

    def _notify_closed(self, t: Trade) -> None:
        pnl, ret = net_pnl(t), net_ret(t)
        icon = "🔴" if (pnl or 0) < 0 else "🔵"
        price = f"{t.sell_price:,.0f}원" if t.sell_price else "체결가 확인 안 됨"
        result = f"{_pct(ret)}% ({pnl:+,.0f}원, 비용 0.25% 포함)" if pnl is not None else "손익 계산 불가"
        part = f" (먼저 판 절반 {t.part_qty}주 × {t.part_price:,.0f}원 포함)" if t.part_qty and t.part_price else ""
        self.notify(f"{icon} {'가상' if t.virtual else '모의'} 매도 {t.name} {t.qty - t.part_qty}주 × {price} — {t.sell_reason}{part}\n"
                    f"  매수 {t.buy_price:,.0f}원 → {result}")

    def _loss_limit(self) -> float:
        return CONSERVATIVE_LOSS_LIMIT if self.regime is not None and self.regime.strong_down else DAILY_LOSS_LIMIT

    def _day_pnl(self) -> float:
        """오늘 실현 + 평가 손익 (추정 비용 0.25% 차감)."""
        today = [t for t in self.trades if t.date == self.today and t.buy_price]
        return sum((net_pnl(t) or 0) if t.status == "closed" else (net_pnl(t, self.last_price.get(t.code)) or 0) for t in today)

    def _trend_keep(self, now: datetime, used: float) -> float:
        """다른 매매가 남겨 둘 ⑦ 몫. 오늘 ⑦ 매수 대상이 있고 ⑦ 매수 시간(09:00~09:30) 안일 때만 남긴다 —
        대상이 없거나 시간이 지나면 ⑦ 은 오늘 더 못 사므로 다른 매매에 풀어 쓴다 (2026-10-27 사용자 '제안대로')."""
        if not self.trend_picks or now.time() > TREND_BUY_END:
            return 0.0
        return max(0.0, TREND_POOL - used)

    def _trend_used(self) -> float:
        """⑦ 주도주 추세로 들고 있는(주문 중 포함) 원금 합계."""
        return sum((x.buy_price or x.signal_price or 0) * x.qty for x in self.active() if x.kind == TREND_KIND)

    def _nada_factor(self, t: Trade) -> tuple[float, str]:
        """Nada 손실 관리 → (매수 금액 배수, 이유). 드로다운 절반 × 오늘 손실 종목 재매수 절반."""
        factor, why = 1.0, []
        if self.asset_start:
            day = self._day_pnl()
            week = self.week_prior + day
            if day <= -self.asset_start * NADA_DAY_DD:
                why.append(f"오늘 손익 {day / self.asset_start:+.1%} (−{NADA_DAY_DD:.0%} 부터 절반)")
            elif week <= -self.asset_start * NADA_WEEK_DD:
                why.append(f"이번 주 손익 {week / self.asset_start:+.1%} (−{NADA_WEEK_DD:.0%} 부터 절반)")
            if why:
                factor /= 2
        if any(x.code == t.code and x.date == self.today and x.status == "closed" and (net_pnl(x) or 0) < 0 for x in self.trades):
            factor /= 2
            why.append("오늘 손실로 끝난 종목 다시 매수")
        return factor, " · ".join(why)

    def _check_halt(self) -> None:
        if self.halted or not self.asset_start:
            return
        pnl = self._day_pnl()
        if pnl <= -self.asset_start * self._loss_limit():
            self.halted = True
            self.notify(f"⛔ 모의투자 하루 손실 한도 도달 ({pnl:+,.0f}원) — 오늘은 새로 사지 않습니다 (보유 종목 매도 규칙은 계속)")

    # ------------------------------------------------------------ 리포트
    def send_report(self, now: datetime, final: bool = True) -> None:
        """final=False: 15:40 정규장 마감 리포트, True: 19:55 최종 리포트."""
        try:
            asset, _ = self.mock.account()
        except Exception:
            logging.exception("모의 계좌 조회 실패 (리포트는 기록만으로 작성)")
            asset = None
        if asset:
            self.store.conn.execute("UPDATE paper_days SET asset_end = ? WHERE date = ?", [asset, self.today])
        for msg in build_report(self.store, self.today, final):
            self.notify(msg)
        column = "reported" if final else "reported_close"
        self.store.conn.execute(f"UPDATE paper_days SET {column} = true WHERE date = ?", [self.today])
        if final:
            self.reported = True
        else:
            self.reported_close = True
        logging.info("모의투자 %s 리포트 전송", "최종" if final else "정규장 마감")

    def status_message(self) -> str:
        """'정리' 명령에 붙이는 현재 보유 현황."""
        held = [t for t in self.active() if t.buy_price]
        if not held:
            done = [t for t in self.trades if t.date == self.today and t.status == "closed"]
            pnl = sum(net_pnl(t) or 0 for t in done)
            return f"💼 모의투자: 보유 없음 · 오늘 청산 {len(done)}건 {pnl:+,.0f}원"
        rows = []
        for t in held:
            px = self.last_price.get(t.code)
            rows.append((t.buy_ts.strftime("%H:%M") if t.buy_ts else "", t.name,
                         _pct(px / t.buy_price - 1 if px else None), f"{t.stop:,.0f}" if t.stop else "-"))
        return f"💼 모의투자 보유 {len(held)}종목" + _table(rows, ("매수", "종목", "현재%", "손절가"), (5, 14, 6, 9))


def _won(x: float) -> str:
    return f"{x / 1e4:+,.1f}만"


def build_report(store: ScreenerStore, day: date, final: bool = True) -> list[str]:
    """장 마감 후 리포트: 당일 결과 + 누적 결과 (HTML <pre> 표). final=False 면 15:40 정규장 마감 리포트."""
    today = load_trades(store, "date = ?", [day])
    done = [t for t in today if t.status == "closed" and t.buy_price and t.sell_price]
    skipped = [t for t in today if t.status in ("skipped", "failed")]
    days = dict((d, (a0, a1)) for d, a0, a1 in store.conn.execute("SELECT date, asset_start, asset_end FROM paper_days ORDER BY date").fetchall())
    a0, a1 = days.get(day, (None, None))

    pnl = sum(net_pnl(t) for t in done)
    wins = sum(1 for t in done if net_pnl(t) > 0)
    n_virtual = sum(1 for t in done if t.virtual)
    title = "최종 (애프터장 포함)" if final else "정규장 마감 (애프터장 가상 매매는 19:55 최종 리포트에)"
    lines = [f"📒 모의투자 당일 결과 {day:%m-%d} — {title}",
             f"매매 {len(done)}건" + (f"(가상 {n_virtual})" if n_virtual else "")
             + f" · 이긴 매매 {wins}건 · 손익 {pnl:+,.0f}원 (추정 비용 0.25% 포함)"]
    if a0 and a1:
        lines.append(f"계좌 추정자산 {a0:,} → {a1:,}원 ({a1 - a0:+,}원, {a1 / a0 - 1:+.2%})")
    msgs = ["\n".join(lines)]
    if done:
        rows = [(t.buy_ts.strftime("%H:%M"), ("◇" if t.virtual else "") + t.name, _pct(net_ret(t)), _won(net_pnl(t)), t.sell_reason)
                for t in done]
        msgs[-1] += _table(rows, ("매수", "종목", "수익%", "손익", "사유"), (5, 12, 6, 7, 16))
        if any(t.virtual for t in done):
            msgs[-1] += "\n◇ = NXT 프리·애프터장 가상 체결 (주문 없음, 계좌 자산에는 반영 안 됨)"
    if skipped:
        counts: dict[str, int] = {}
        for t in skipped:
            key = t.note.split(" (")[0].split("원이")[0] if t.note else "?"
            key = "추격 안 함 (+1% 초과)" if "추격" in t.note else key
            counts[key] = counts.get(key, 0) + 1
        msgs[-1] += "\n건너뛴 신호 " + str(len(skipped)) + "건: " + ", ".join(f"{k} {n}" for k, n in counts.items())

    allt = [t for t in load_trades(store, "status = 'closed'", []) if t.buy_price and t.sell_price and t.mode != "이월"]
    if allt:
        total = sum(net_pnl(t) for t in allt)
        win = sum(1 for t in allt if net_pnl(t) > 0)
        avg = sum(net_ret(t) for t in allt) / len(allt)
        first = min(days) if days else day
        lines = [f"📚 모의투자 누적 ({first:%m-%d}~{day:%m-%d}, {len({t.date for t in allt})}거래일)",
                 f"매매 {len(allt)}건 · 승률 {win / len(allt):.0%} · 평균 {avg:+.2%} · 합계 {total:+,.0f}원"]
        start_asset = days[first][0] if days else None
        last_asset = next((a for d, (_, a) in sorted(days.items(), reverse=True) if a), None)
        if start_asset and last_asset:
            lines.append(f"계좌 추정자산 {start_asset:,} → {last_asset:,}원 ({last_asset / start_asset - 1:+.2%}, 정규장 주문만·실제 수수료·세금 반영)")
        groups = []
        for label, key in (("거래", lambda t: "가상(NXT)" if t.virtual else "정규장 주문"), ("방식", lambda t: t.mode),
                           ("신호", lambda t: t.kind)):
            for g in sorted({key(t) for t in allt}):
                xs = [t for t in allt if key(t) == g]
                groups.append((label, g, str(len(xs)), f"{sum(1 for t in xs if net_pnl(t) > 0) / len(xs):.0%}",
                               _pct(sum(net_ret(t) for t in xs) / len(xs)), _won(sum(net_pnl(t) for t in xs))))
        table = _table([g[1:] for g in groups], ("구분", "건수", "승률", "평균%", "손익"), (12, 4, 4, 6, 8))
        by_day: dict[date, list[Trade]] = {}
        for t in allt:
            by_day.setdefault(t.date, []).append(t)
        day_rows = [(d.strftime("%m-%d"), str(len(xs)), f"{sum(1 for t in xs if net_pnl(t) > 0)}", _won(sum(net_pnl(t) for t in xs)))
                    for d, xs in sorted(by_day.items())]
        msgs.append("\n".join(lines) + table + "\n날짜별" + _table(day_rows, ("날짜", "건수", "승", "손익"), (5, 4, 4, 8), latest=True))
    return msgs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="매수 신호 모의투자 점검")
    parser.add_argument("--status", action="store_true", help="모의 계좌 잔고·예수금")
    parser.add_argument("--report", nargs="?", const="", default=None, help="리포트 미리보기 (YYYYMMDD, 기본 오늘)")
    args = parser.parse_args()
    from kiwoom_trading.common.config import KST

    if args.status:
        mock = build_mock_client()
        asset, holdings = mock.account()
        print(f"추정자산 {asset:,}원 · 주문 가능 {mock.cash():,}원")
        for code, (qty, avg, sellable, name) in holdings.items():
            print(f"  {name}({code}) {qty}주 × {avg:,.0f}원 (매도 가능 {sellable})")
    if args.report is not None:
        day = datetime.strptime(args.report, "%Y%m%d").date() if args.report else datetime.now(KST).date()
        store = ScreenerStore()
        try:
            for m in build_report(store, day):
                print(html.unescape(m.replace("<pre>", "\n").replace("</pre>", "\n")), "\n")
        finally:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
