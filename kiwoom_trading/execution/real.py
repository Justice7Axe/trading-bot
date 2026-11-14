"""🔴 실전 매매 — 2026-11-16 부터 실전 매수는 1️⃣ 상승장 장 초 · 🪜 애프터 정배열 두 매매만 (REAL_ON, 2026-11-14 사용자 승인 '개선점과 앞으로 할 일').
  나머지(6️⃣ 주도주 신고가·📕 상한가 풀림·5️⃣ 약세장 인버스·4️⃣ 역행 강세 종가·2️⃣ 저항 돌파·🌙 종가 재돌파·7️⃣ 주도주 추세 등)는 실전에서 끄고 모의·가상은 그대로.
  🪜 애프터 정배열 실전 = 모의와 같은 규칙: 익절 없음 · 손절 매수(체결)가 −3% · 못 닿으면 다음 날 09:00 시가 매도 (+ 공통 VWAP 5봉 이탈 매도).
  실전 자동 멈춤 (auto_stop_check): 2026-11-16 이후 실전 끝난 매매 5연패 또는 이번 주(월~금) 실현 손익 ≤ 시드의 −3% → 새 매수 멈춤,
  보유 종목 매도는 계속, 다시 켜는 건 사용자가 텔레그램 '실전 재개' (자동 재개 없음).
  체결 차이 기록: real_trades.signal_price·order_price·fill_price·ask1·bid1 / sell_signal_price·sell_order_price·sell_ask1·sell_bid1.

(아래는 지난 기록) 키움 실계좌로 6️⃣ 주도주 신고가 · 2️⃣ 저항 돌파 · 5️⃣ 약세장 인버스 · 📕 홍인기 상한가 풀림 중 그날 먼저 온 신호를 산다
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
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient, _to_int
from kiwoom_trading.strategies.hong_limitup.live import HONG_KIND
from kiwoom_trading.strategies.inverse.live import CODE as INVERSE_CODE, WEAK_KIND, WEAK_STOP, WEAK_TP
from kiwoom_trading.common.krx import upper_limit
from kiwoom_trading.strategies.after_align.live import KIND as ALIGN_KIND, STOP as ALIGN_STOP
from kiwoom_trading.execution import hold_manage, split_exit, strict_select
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
# REAL_OFF = PLAYS 정의 뒤에서 REAL_ON 으로 계산 (2026-11-14). 옛 기록: (RECLAIM_KIND, CAFE_KIND, TREND_KIND, UP_KIND)   # 1️⃣: 2026-11-10 사용자 '모두 다 해줘' — 실전이 살 수 있는 5.5만 원 이하 종목은 모의에서도 9건 −0.82%(모의 수익은 5.5만↑ 29건에서 나옴), 실전 3건 −903원 → 모의에서만. # 4️⃣ 는 같은 날 계좌 시뮬로 다시 넣음(아래 2026-10-31 '조건 없이 복귀'). 7️⃣: 2026-10-31 사용자 '추천대로' — 4️⃣ 최고 5일 빼면 −·최근 3달 −0.61%, 7️⃣ 45건뿐·앞뒤 검증 못 함·모의 계좌 계산 −171만 → 모의에서만 쌓음 (6️⃣📕5️⃣ 핵심, 1️⃣2️⃣🌙 보조). # ☕: 2026-10-30 사용자 '☕는 실전에서 빼자' — 94% 가 1주 3만 원 넘어 1주씩만 사고 절반 익절이 안 됨, 1년 실전 새 규칙 −3~−9만 (research/strict_select). 🔁: 2026-10-29 사용자 '권장대로': 🔁 은 09:0x 에 먼저 와 하루 1칸을 차지 → 6️⃣·📕 를 못 삼 (1년 시드 10만 34만 → 562만, research/account_alloc)
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
    CONTRA_KIND: ("4️⃣ 역행 강세 종가", None, None),   # 2026-10-31 실전 복귀·고가 부근 조건 없이 (10만 1년: 4️⃣ 없음 153만 · 고가 부근만 161만 · 조건 없이 312만, research/early_rise/apply 계좌 시뮬)      # 2026-10-30 사용자 '제안대로' — 강한 하락장 15:15~15:19 매수, 다음 날 09:00 (1년 422건 +0.85%)
    REBREAK_KIND: ("🌙 종가 재돌파", None, None),
    ALIGN_KIND: ("🪜 애프터 정배열", None, ALIGN_STOP),   # 2026-11-14 사용자 승인 — 모의와 같은 규칙(익절 없음·−3%·다음 날 09:00)으로 실전에 추가
    TREND_KIND: ("7️⃣ 주도주 추세", None, None),         # 2026-10-30 사용자 '7번 매매를 실전으로' — 09:00 매수, 종가 20일선 이탈 다음 날 09:00 매도 (며칠~몇 주 보유)        # 2026-10-30 — 17~18시 NXT 애프터장에서 정규장 종가 위 매수, 다음 날 09:00 (1년 554건 +0.79%)
}
# 실전 매수는 이 두 매매만 (2026-11-14 사용자 승인, 11-16 부터): 1️⃣ 상승장 장 초(기존 실전 조건 그대로 — 외인·기관 둘 다 매도 제외 등) · 🪜 애프터 정배열.
# 나머지는 실전에서 끄고 모의·가상은 그대로. 실전 실적 12건 3승 9패·7연패 뒤 범위를 좁혀 새로 시작.
REAL_ON = (UP_KIND, ALIGN_KIND)
REAL_OFF = tuple(k for k in PLAYS if k not in REAL_ON)
# 산 뒤 관리 R2~R5 대상 (hold_manage.py, 2026-11-13 사용자 '전부'): 매수일 뒤에도 들고 가는 실전 매매. 다른 실전 매매는 원래 규칙대로 다음 날 09:00 에 팔아 해당 없음.
# 실전은 R6 추가 매수 없음 — R3 −20% 에 바로 매도.
REAL_HOLD_KINDS = (TREND_KIND,)

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
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS signal_price DOUBLE;   -- 매수 신호가 (신호가 난 봉·판정 가격)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS order_price DOUBLE;    -- 매수 주문가 (지정가 = 현재가 +1% 호가 올림, 상한가로 자름)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS fill_price DOUBLE;     -- 실제 평균 체결가 (체결 확인 뒤 buy_price 도 같은 값으로 바뀜, 주문 때 buy_price 는 주문 순간 현재가)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS ask1 DOUBLE;           -- 매수 주문 순간 매도 1호가 (ka10004 sel_fpr_bid, 조회 실패면 NULL)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS bid1 DOUBLE;           -- 매수 주문 순간 매수 1호가 (ka10004 buy_fpr_bid)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS sell_signal_price DOUBLE;   -- 매도 판단 순간 현재가 (손절·VWAP·다음 날 09:00 등 매도하기로 한 때의 KRX 현재가)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS sell_order_price DOUBLE;    -- 매도 주문가 — 지금 매도는 전부 시장가라 NULL (지정가 매도가 생기면 그 값)
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS sell_ask1 DOUBLE;      -- 매도 주문 순간 매도 1호가
ALTER TABLE real_trades ADD COLUMN IF NOT EXISTS sell_bid1 DOUBLE;      -- 매도 주문 순간 매수 1호가 (시장가 매도는 보통 여기 근처에서 체결)
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

    def best_quote(self, code: str) -> tuple[Optional[float], Optional[float]]:
        """(매도 1호가, 매수 1호가) — ka10004 주식호가요청 (KRX). 체결 차이 기록용, 값이 없으면 None."""
        payload, _, _ = self._post("/api/dostk/mrkcond", "ka10004", {"stk_cd": code})
        ask, bid = (abs(_to_int(payload.get(k)) or 0) for k in ("sel_fpr_bid", "buy_fpr_bid"))
        return (float(ask) if ask else None), (float(bid) if bid else None)


# 당일 차트 흐름 대응 — VWAP 이탈 매도 (2026-11-11 사용자 '당일 수급·차트 흐름에 바로 대응' → '가장 추천하는 기준으로 넣어줘').
# 그날 산 실전 종목이 매수 10분 뒤부터 1분봉 종가가 그날 VWAP(거래량 가중 평균가) 아래로 5개 연속 마감하면 시장가 매도.
# 7️⃣ 주도주 추세(며칠 보유)·🌙 종가 재돌파(애프터 매수)는 제외. 손절·익절은 그대로 먼저 봄.
VWAP_BARS, VWAP_WAIT_MIN = 5, 10


def vwap_break(bars: list, buy_ts: datetime, now: datetime, n: int = VWAP_BARS, wait_min: int = VWAP_WAIT_MIN) -> Optional[str]:
    """bars = 그날 KRX 1분봉(시간 오름차순, ts = 봉 시작). 다 끝난 봉만 보고, 매수 wait_min 분 뒤 봉부터 n개 연속 VWAP 아래 마감이면 이유 문자열."""
    from datetime import timedelta
    done = [b for b in bars if b["ts"] + timedelta(minutes=1) <= now.replace(tzinfo=None) and b["ts"].time() >= OPEN and b["volume"]]
    pv = vol = 0.0
    run = []
    for b in done:
        pv += (b["high"] + b["low"] + b["close"]) / 3 * b["volume"]
        vol += b["volume"]
        run.append((b, pv / vol))
    after = [(b, v) for b, v in run if b["ts"] >= buy_ts + timedelta(minutes=wait_min)]
    if len(after) < n or not all(b["close"] < v for b, v in after[-n:]):
        return None
    b, v = after[-1]
    return f"VWAP 이탈 — 1분봉 {n}개 연속 VWAP 아래 마감 (종가 {b['close']:,.0f} < VWAP {v:,.0f})"


# 사람 20% 스위치 (2026-11-10 사용자 '1번' — 서태준 틀: 시스템 80%·사람 20%, 사람은 오늘 켤지/끌지만 정함).
# 텔레그램 '실전 쉼' → 그날 새 매수만 멈춤 (손절·익절·다음 날 매도는 그대로), '실전 재개' → 다시 삼. 날마다 켜진 채로 시작.
PAUSE_SCHEMA = "CREATE TABLE IF NOT EXISTS real_pause (date DATE PRIMARY KEY, paused BOOLEAN, ts TIMESTAMP)"


def set_pause(conn, day: date, paused: bool) -> None:
    conn.execute(PAUSE_SCHEMA)
    conn.execute("INSERT OR REPLACE INTO real_pause VALUES (?, ?, ?)", [day, paused, datetime.now()])
    if not paused:   # '실전 재개' = 자동 멈춤도 풂 (연패·주간 손실은 이때부터 다시 셈)
        clear_auto_stop(conn, datetime.now())


def is_paused(conn, day: date) -> bool:
    """그날 '실전 쉼' 이거나 실전 자동 멈춤이 걸려 있으면 True."""
    try:   # 읽기 전용 사본(screener_snapshot)에서도 쓰므로 표를 만들지 않음 — 없으면 켜짐
        r = conn.execute("SELECT paused FROM real_pause WHERE date = ?", [day]).fetchone()
    except Exception:
        r = None
    return bool(r and r[0]) or bool(auto_stop_active(conn))


# 실전 자동 멈춤 (2026-11-14 사용자 승인 '개선점과 앞으로 할 일' 2번).
# 실전 끝난 매매가 5연패가 되거나 이번 주(월~금) 실전 실현 손익이 시드의 −3% 이하가 되면(먼저 오는 것) 새 매수를 멈추고 텔레그램 한 번.
# 보유 종목 매도는 계속. 판정은 매도 체결 확정 때와 스캐너 시작 때. 주가 바뀌어도 자동으로 다시 켜지 않음 — 사용자가 '실전 재개'.
# 셈은 AUTO_START(이 규칙 시작일, 범위를 1️⃣·🪜 로 바꾼 새 출발) 이후 실전 매매부터, '실전 재개' 뒤에는 그 시각부터 다시.
AUTO_START = date(2026, 11, 16)
AUTO_STREAK = 5
AUTO_WEEK_LOSS = 0.03
AUTO_SCHEMA = "CREATE TABLE IF NOT EXISTS real_auto_stop (ts TIMESTAMP, reason VARCHAR, cleared_ts TIMESTAMP)"


def auto_stop_active(conn) -> Optional[str]:
    """걸려 있는 자동 멈춤 사유 (없으면 None). 표가 없어도(읽기 전용 사본) None."""
    try:
        r = conn.execute("SELECT reason FROM real_auto_stop WHERE cleared_ts IS NULL ORDER BY ts DESC LIMIT 1").fetchone()
    except Exception:
        return None
    return r[0] if r else None


def clear_auto_stop(conn, now: datetime) -> None:
    conn.execute(AUTO_SCHEMA)
    conn.execute("UPDATE real_auto_stop SET cleared_ts = ? WHERE cleared_ts IS NULL", [now.replace(tzinfo=None)])


def auto_stop_reason(conn, today: date) -> Optional[str]:
    """지금 멈춰야 하면 사유 문장('머리 — 설명'), 아니면 None. 기록만 읽음."""
    conn.execute(AUTO_SCHEMA)
    base = datetime.combine(AUTO_START, time(0, 0))
    last = conn.execute("SELECT max(cleared_ts) FROM real_auto_stop").fetchone()[0]
    if last and last > base:
        base = last
    rows = conn.execute("""SELECT pnl, sell_ts FROM real_trades WHERE status = 'closed' AND pnl IS NOT NULL AND sell_ts >= ? AND date >= ?
                           ORDER BY sell_ts""", [base, AUTO_START]).fetchall()   # 11-16 전에 산 것은 새 출발 셈에 안 넣음
    n = 0
    for p, _ in reversed(rows):
        if p > 0:
            break
        n += 1
    if n >= AUTO_STREAK:
        return f"{n}연패 — 실전 끝난 매매가 {n}번 연속 손실(합 {sum(p for p, _ in rows[-n:]):+,.0f}원)"
    week0 = datetime.combine(today - timedelta(days=today.weekday()), time(0, 0))
    wk = [p for p, ts in rows if ts >= week0]
    week = sum(wk)
    if wk and week <= -SEED * AUTO_WEEK_LOSS:
        return (f"이번 주 손실 {week:+,.0f}원 — 이번 주 실전 실현 손익 {week:+,.0f}원이 "
                f"시드 {SEED:,}원의 −{AUTO_WEEK_LOSS:.0%}({-SEED * AUTO_WEEK_LOSS:+,.0f}원) 이하")
    return None


def auto_stop_check(conn, today: date, now: datetime, notify: Optional[Callable[[str], Any]] = None) -> Optional[str]:
    """자동 멈춤 판정. 이미 걸려 있으면 오늘도 '쉼'으로 맞추고(알림 없음) 사유를 돌려줌, 새로 걸리면 기록·쉼·알림 한 번."""
    cur = auto_stop_active(conn)
    if not cur:
        cur = auto_stop_reason(conn, today)
        if not cur:
            return None
        conn.execute("INSERT INTO real_auto_stop VALUES (?, ?, NULL)", [now.replace(tzinfo=None), cur])
        logging.warning("실전 자동 멈춤: %s", cur)
        if notify:
            head, _, body = cur.partition(" — ")
            notify(f"🛑 실전 자동 멈춤 — {head}\n"
                   f"{body}이라 실전 새 매수를 멈춤.\n"
                   f"들고 있는 종목의 손절·매도는 그대로 함. 주가 바뀌어도 저절로 다시 켜지지 않음.\n"
                   f"다시 사려면 텔레그램에 '실전 재개' 라고 보내 주세요.")
    conn.execute(PAUSE_SCHEMA)
    conn.execute("INSERT OR REPLACE INTO real_pause VALUES (?, ?, ?)", [today, True, datetime.now()])
    return cur


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
        self.hold_time_exit: dict = {}           # R4 시간 손절 {real_trades.id: 사유} — run_intraday 가 스캐너 시작 때 넣어 줌
        self.r2: dict = {}                       # R2 다시 고르기 {코드: (탈락 목록, 요약)} — HoldRecheck 가 09:10 판정 뒤 넣어 줌
        self.kinds = tuple(k for k in (kinds or PLAYS) if k not in REAL_OFF)
        self.conn.execute(SCHEMA)
        for t in self.actives():                # 들고 있는 종목은 팔 수 있게 허용
            if hasattr(self.client, "allowed"):
                self.client.allowed.add(t[2])
        self.check_auto_stop(datetime.now())    # 스캐너 시작 때 자동 멈춤 판정 (이미 걸려 있으면 오늘도 쉼)

    def check_auto_stop(self, now: datetime) -> Optional[str]:
        try:
            return auto_stop_check(self.conn, self.today, now, self.notify)
        except Exception:
            logging.exception("실전 자동 멈춤 판정 실패")
            return None

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

    def realized_today(self) -> float:
        """오늘 판(청산 끝난) 실전 매매의 실현 손익 합계 — R7 금액 제한."""
        return self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM real_trades WHERE status = 'closed' AND CAST(sell_ts AS DATE) = ?",
                                 [self.today]).fetchone()[0] or 0

    def r2_codes(self) -> list[str]:
        """R2 대상: 전날 이전에 산 며칠 보유 실전 매매 (7️⃣)."""
        return [t[2] for t in self.actives() if t[4] in REAL_HOLD_KINDS and t[1] < self.today and t[9] == "open"]

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
        if is_paused(self.conn, self.today):
            names = ", ".join(f"{n}[{PLAYS[s.kind][0]}]" for _, n, _, s in cands)
            auto = auto_stop_active(self.conn)
            logging.info("실전 쉼 — 새 매수 안 함%s: %s", f" (자동 멈춤: {auto})" if auto else "", names)
            self.notify(((f"🛑 실전 자동 멈춤 중이라 안 삼 ({auto.split(' — ')[0]}): {names}" if auto else f"⏸ 실전 쉼 중이라 안 삼: {names}")
                         + "\n(다시 사려면 '실전 재개')")[:400])
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
            fx = getattr(self, "fractal", None)
            why = fx.skip_reason(code) if fx is not None and s.kind not in (WEAK_KIND,) else None   # 🌀 무너지는 국면 (2026-11-11 사용자 '3')
            if why:
                logging.info("실전 안 삼 %s [%s]: %s", name, label, why)
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
                cap = upper_limit(base) if base else (int(s.level) if s.kind == HONG_KIND and s.level else 0)
                if cap and limit > cap:   # 지정가가 상한가를 넘으면 주문 거부 (2026-11-09 박셀바이오 📕 4,845 > 상한가 4,835 → 5회 거부) → 상한가로
                    limit = cap
                factor = 1.0   # 실전은 금액 배수가 없음 — R7(12:00 뒤 오늘 실현 손실이면 1배 넘게 안 키움) 장치만 둠 (2026-11-13)
                try:
                    factor, why7 = hold_manage.r7_cap(factor, now, self.realized_today())
                    if why7:
                        logging.info("실전 %s: %s", name, why7)
                except Exception:
                    logging.exception("실전 R7 확인 실패 %s", name)
                qty = min(max(1, int(PER_STOCK * factor // limit)), int(cash // limit))   # 3만 원 안에서 여러 주, 1주가 3만 원 넘으면 1주 — 예수금 안에서
                if qty < 1:
                    skipped.append(f"{name}({code}) [{label} {s.ts:%H:%M}] 1주 {limit:,.0f}원 > 예수금 {cash:,.0f}원 · 포착: {(s.reason or '')[:120]}")
                    continue
                how = (split_exit.plan_text(s.kind, price, s.stop if s.kind == RECLAIM_KIND else None)
                       if s.kind in split_exit.KINDS else
                       "손절·익절 없이 종가가 20일선 아래로 마감한 다음 날 09:00 매도 (며칠~몇 주 보유)" if s.kind == TREND_KIND else
                       f"익절 +{tp:.0%} / 손절 −{sl:.0%}, 못 닿으면 다음 날 09:00 매도" if tp
                       else f"장중 익절 없이 다음 날 09:00 시가 매도 (−{sl:.0%} 손절)" if sl
                       else "익절·손절 없이 다음 날 09:00 시가 매도")
                plan = self._plan(s.kind, price, s, how)   # R1: 사기 전에 대응 계획, 못 만들면 안 삼
                if not plan:
                    skipped.append(f"{name}({code}) [{label} {s.ts:%H:%M}] 대응 계획 없음 (R1)")
                    continue
                self.client.allowed.add(code)
                ask1, bid1 = self._book(code)   # 체결 차이 기록용 주문 순간 1호가 (실패해도 삼)
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
                self.conn.execute("""INSERT OR REPLACE INTO real_trades (id, date, code, name, kind, qty, buy_order_no, buy_ts, buy_price, status, stop_px, note,
                                                                         signal_price, order_price, ask1, bid1)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ordered', ?, ?, ?, ?, ?, ?)""",
                                  [tid, self.today, code, name, s.kind, qty, no, now.replace(tzinfo=None), price,
                                   float(s.stop) if s.kind == RECLAIM_KIND and s.stop else None, plan,
                                   float(s.price) if s.price else None, float(limit), ask1, bid1])
                if s.kind in REAL_HOLD_KINDS:
                    how += " · " + hold_manage.hold_plan_extra("추세", True, paper=False)[1]
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

    def _book(self, code: str) -> tuple[Optional[float], Optional[float]]:
        """주문 순간 (매도 1호가, 매수 1호가) — 기록용이라 실패하면 (None, None)."""
        fn = getattr(self.client, "best_quote", None)
        if fn is None:
            return None, None
        try:
            return fn(code)
        except Exception:
            logging.warning("실전 호가 조회 실패 %s (체결 차이 기록만 빠짐)", code)
            return None, None

    def _plan(self, kind: str, price: float, s, how: str) -> Optional[str]:
        """R1 대응 계획 한 줄 (real_trades.note 에 남김). 만들다 실패하면 None → 안 삼."""
        try:
            _, tp, sl = PLAYS[kind]
            stop = float(s.stop) if kind == RECLAIM_KIND and s.stop else price * (1 - sl) if sl else None
            tp_txt = (f"+{UP_HALF_TP:.0%} 절반" if kind == UP_KIND and UP_HALF_TP else f"+{tp:.0%}" if tp else "")
            hold, add = how, "없음"
            if kind in REAL_HOLD_KINDS:
                tp_r, extra = hold_manage.hold_plan_extra("추세", True, paper=False)
                tp_txt, hold = ", ".join(x for x in (tp_txt, tp_r) if x), f"{how} · {extra}"
            return hold_manage.plan_text(stop, tp_txt, hold, add)
        except Exception:
            logging.exception("실전 R1 대응 계획 만들기 실패 %s", kind)
            return None

    def _hold_reason(self, now: datetime, tid: str, code: str, name: str, d: date, qty: int, part: int,
                     buy_price: float, label: str) -> Optional[str]:
        """며칠 보유 실전 매매(7️⃣)를 원래 규칙으로 안 팔 때: R3 −20% 매도 → R5 1/4 익절(여기서 직접 주문) → R2 다시 고르기 → R4 시간 손절.
        팔 이유를 돌려주면 _tick_one 이 남은 수량 전부 매도. 실전은 R6 추가 매수 없음."""
        if not (OPEN <= now.time() < LAST):
            return None
        try:
            q = self.market.quote(code, integrated=False)
            if not q or not q.price:
                return None
            price = float(q.price)
            key = f"real:{tid}"
            st = hold_manage.get_state(self.conn, key)
            act = hold_manage.loss_action(price, buy_price, False, paper=False)
            if act:
                return act[1] + " — 실전은 추가 매수 없이 매도"
            lvl = hold_manage.tp_step(price, buy_price, st["steps"])
            if lvl is not None:
                step = st["steps"] + 1
                held = self.client.holding_qty(code)
                remaining = min(qty - part, held)
                n, all_ = hold_manage.tp_qty(qty, remaining)
                st["steps"] = step
                if all_:
                    hold_manage.put_state(self.conn, key, st)
                    return f"R5 +{lvl:.0%} 나눠 익절 {step}단계 — 남은 {remaining}주 전부"
                self.client.allowed.add(code)
                no = self.client.market_order("sell", code, n)   # 실패하면 예외 → 단계 저장 안 함, 다음 확인 때 다시
                hold_manage.put_state(self.conn, key, st)
                ppx = self.conn.execute("SELECT part_price FROM real_trades WHERE id = ?", [tid]).fetchone()[0]
                avg = ((ppx or price) * part + price * n) / (part + n)
                note = self.conn.execute("SELECT coalesce(note, '') FROM real_trades WHERE id = ?", [tid]).fetchone()[0]
                self._set(tid, part_qty=part + n, part_price=avg, note=(note + " · " if note else "") + f"R5단계 {step} {now:%m-%d} {n}주 × {price:,.0f}")
                self.notify(f"🔴 실전 1/4 익절 {name}({code}) {n}주 × 약 {price:,.0f}원 ({price / buy_price - 1:+.1%}, R5 {step}단계, 주문 {no}) [{label}]")
                logging.info("실전 R5 1/4 익절 %s %s단계 %s주", name, step, n)
                return None
            r2 = self.r2.get(code) if d < self.today else None
            if r2 is not None and st["r2_date"] != self.today:
                fails, text = r2
                st["r2_date"] = self.today
                hold_manage.put_state(self.conn, key, st)
                logging.info("실전 R2 다시 고르기 %s: %s · 지금가 %s / 매수가 %s", name, text, f"{price:,.0f}", f"{buy_price:,.0f}")
                if len(fails) >= hold_manage.R2_FAILS and price < buy_price:
                    return f"R2 다시 고르면 안 삼 — {', '.join(fails)} (지금가 {price:,.0f} < 매수가 {buy_price:,.0f})"
            return self.hold_time_exit.get(tid)
        except Exception:
            logging.exception("실전 산 뒤 관리 확인 실패 %s", name)
            return None

    # ------------------------------------------------------------ 체결 확인·매도
    def tick(self, now: datetime) -> None:
        self.liquidate_once(now)
        if getattr(self, "reporter", None) is not None:   # 🔴 15:45 실전 성과 리포트 (real_report.py, 2026-10-30 사용자)
            self.reporter.tick(now)
        for t in self.actives():   # 1️⃣ 은 여러 종목일 수 있다 (2026-10-28 B)
            self._tick_one(now, t)

    def _vwap_reason(self, code: str, buy_ts: datetime, now: datetime) -> Optional[str]:
        """1분에 한 번만 1분봉을 받아 VWAP 이탈을 봄 (종목별 캐시)."""
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        key = now.strftime("%H%M")
        cache = getattr(self, "_vwap_cache", {})
        self._vwap_cache = cache
        if cache.get(code, ("", None))[0] != key:
            try:
                cache[code] = (key, vwap_break(fetch_minute_bars(self.market.client, code, self.today, "KRX"), buy_ts, now))
            except Exception:
                logging.exception("실전 VWAP 확인 실패 %s", code)
                cache[code] = (key, None)
        return cache[code][1]

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
                    self._set(tid, buy_price=px, fill_price=px, peak=px, status="open")
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
                    self.check_auto_stop(now)   # 매도 체결 확정 때 자동 멈춤 판정 (5연패 · 이번 주 −3%)
                return
            if not (OPEN <= tm < CLOSE):
                return
            reason = None
            q = None
            if kind in REAL_HOLD_KINDS:   # 7️⃣ 은 전날 종가가 20일선 아래일 때만 09:00 매도, 아니면 산 뒤 관리 R3 → R5 → R2 → R4 (원래 손절·익절 없음)
                brk = self.trend_exit.get(code) if d < self.today else None
                if brk:
                    reason = f"20일선 이탈 ({brk[0]:%m-%d} 종가 {brk[1]:,.0f} < 20일선 {brk[2]:,.0f}) — 시초 매도"
                else:
                    reason = self._hold_reason(now, tid, code, name, d, qty, part, buy_price, label)
                    if not reason:
                        return
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
                    if float(q.price) > (peak or buy_price):   # 산 뒤 가장 높은 값 — 일지 손실 원인('산 뒤 최고 수익률')용
                        peak = float(q.price)
                        self._set(tid, peak=peak)
                    if sl and q.price <= buy_price * (1 - sl):
                        reason = f"손절 −{sl:.0%}"
                    elif tp and q.price >= buy_price * (1 + tp):
                        reason = f"익절 +{tp:.0%}"
                if reason is None and kind not in (TREND_KIND, REBREAK_KIND) and buy_ts:
                    reason = self._vwap_reason(code, buy_ts, now)
            if reason:
                held = self.client.holding_qty(code)
                sell_qty = min(qty - part, held)
                if sell_qty < 1:
                    self._set(tid, status="failed", note=f"팔 수량 없음 (계좌 {held}주)")
                    self.notify(f"⚠️ 실전 매도 못 함 {name}({code}) — 계좌 매도 가능 {held}주 (직접 확인 필요)")
                    return
                self.client.allowed.add(code)
                sig_px = None   # 매도 판단 순간 현재가 (체결 차이 기록용)
                try:
                    sq = q if (q is not None and getattr(q, "price", None)) else self.market.quote(code, integrated=False)
                    sig_px = float(sq.price) if sq and sq.price else None
                except Exception:
                    logging.warning("실전 매도 판단가 조회 실패 %s", code)
                sask, sbid = self._book(code)
                no = self.client.market_order("sell", code, sell_qty)
                self._set(tid, sell_order_no=no, sell_ts=now.replace(tzinfo=None), reason=reason, status="selling", qty=sell_qty + part,
                          sell_signal_price=sig_px, sell_order_price=None, sell_ask1=sask, sell_bid1=sbid)
                self.notify(f"🔴 실전 매도 주문 {name}({code}) {sell_qty}주 [{label}] — {reason} (주문 {no})")
                logging.info("실전 매도 주문 %s %s주 %s", name, sell_qty, reason)
        except Exception as exc:
            logging.exception("실전 확인 실패")
            self.notify(f"⚠️ 실전 매매 확인 실패 {name} — {exc}"[:500])


RealInverseTrader = RealTrader   # 예전 이름
