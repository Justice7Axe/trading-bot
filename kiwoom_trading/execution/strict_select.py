"""당일 매매 엄격한 종목 선정 — 모의는 A안, 실전은 B안 (2026-10-30 사용자 '데이 트레이딩은 더 엄격하게 종목 선정을 해서 줄여줘' → '그대로 적용').

모두 매수 전에 아는 정보 (전날 외인·기관 순매수, 전날 대금 순위, 전날 시총, 신호 순간 대금 순위).
1년 백테스트 (research/strict_select, data/strict_select/choose.txt, 1건 100만):
| 매매 | 조건 | 기준 → 거른 뒤 |
|---|---|---|
| 1️⃣ 상승장 장 초 | 신호 순간 대금 20위 안 | 559건 +1.03% → 273건 +1.64% ★ (40→30→20→10위 단조) |
| 2️⃣ 저항 돌파 | 시총 3천억↑ & 전날 기관 순매수 | 73건 +1.77% → 31건 +2.17% (표본 적음) |
| ☕ 카페 대장 | 전날 대금 50위 안 | 601건 +0.24% → 300건 +0.47% ★ (빠지는 301건 +0.02%) |
| 🔁 시가 탈환 | 전날 기관 순매수 | 2,273건 +0.33% → 1,394건 +0.44% |
| 6️⃣ 주도주 신고가 (B만) | 전날 기관 순매수 | 367건 +2.33% → 255건 +2.73% (빠지는 112건도 +1.40%) |
| 📕 상한가 풀림 (B만) | 전날 외인 순매수 | 870건 +1.93% → 405건 +2.81% (빠지는 465건도 +1.17%) |
계좌 1년: 모의 1천만 A 1억 1,871만 → 1억 3,792만 (낙폭 15.1 → 17.8%) / 실전 10만 새 규칙 B 68.9만 → 91.5만 (낙폭 17.9 → 12.9%).
⚠️ 조건 약 150개 중 고른 값 — 우연 섞일 수 있음, 자료는 대부분 상승장 1년.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.strategies.cafe_leader.live import KIND as CAFE_KIND
from kiwoom_trading.strategies.hong_limitup.live import HONG_KIND
from kiwoom_trading.strategies.premarket_reclaim.live import KIND as RECLAIM_KIND
from kiwoom_trading.strategies.regime_plays.live import NEWHIGH_KIND, UP_KIND
from kiwoom_trading.strategies.resistance_retest.live import RETEST_KIND

TAG = "엄격 선정"          # 건너뜀 이유 앞머리 — paper.RULE_SKIPS 에 들어 있어 알림 없이 기록만
UP_RANK = 20
RETEST_MCAP = 3e11
CAFE_PREV_RANK = 50
PLAN_A = (UP_KIND, RETEST_KIND, CAFE_KIND, RECLAIM_KIND)
PLAN_B = PLAN_A + (NEWHIGH_KIND, HONG_KIND)


@dataclass
class Context:
    day: Optional[date] = None
    flow: dict = field(default_factory=dict)      # code → (외인, 기관) 순매수 원
    rank: dict = field(default_factory=dict)      # code → 전날 주식 대금 순위
    mcap: dict = field(default_factory=dict)      # code → 전날 종가 × 상장주식수


def load_context(today: date, db_path: str = DEFAULT_DB_PATH) -> Context:
    try:
        conn = duckdb.connect(db_path, read_only=True)
        try:
            prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [today]).fetchone()[0]
            fday = conn.execute("SELECT max(date) FROM investor_daily WHERE date < ?", [today]).fetchone()[0]
            flow = {c: (f, i) for c, f, i in conn.execute("SELECT code, foreign_, institution FROM investor_daily WHERE date = ?", [fday]).fetchall()}
            rows = conn.execute("""SELECT d.code, rank() OVER (ORDER BY d.value DESC), d.close * coalesce(s.listed_shares, 0)
                                   FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL""", [prev]).fetchall()
        finally:
            conn.close()
        ctx = Context(prev, flow, {c: int(r) for c, r, _ in rows}, {c: float(m or 0) for c, _, m in rows})
        logging.info("엄격 선정 준비: 전날 %s, 수급 %s종목 (%s), 대금 순위 %s종목", prev, len(flow), fday, len(rows))
        return ctx
    except Exception:
        logging.exception("엄격 선정 자료 읽기 실패 — 엄격 조건 대상 매매는 사지 않음")
        return Context()


def _pos(v) -> bool:
    return v is not None and v > 0


def skip_reason(ctx: Context, kind: str, code: str, reason: str, plan: tuple) -> Optional[str]:
    """엄격 조건에 걸리면 이유, 통과하면 None. plan = PLAN_A(모의) / PLAN_B(실전)."""
    if kind not in plan:
        return None
    f, i = ctx.flow.get(code, (None, None))
    if kind == UP_KIND:
        m = re.search(r"대금 (\d+)위", reason or "")
        rk = int(m.group(1)) if m else 999
        return None if rk <= UP_RANK else f"{TAG} — 1️⃣ 은 신호 순간 대금 {UP_RANK}위 안만 (지금 {rk}위)"
    if kind == RETEST_KIND:
        mc = ctx.mcap.get(code, 0)
        if mc >= RETEST_MCAP and _pos(i):
            return None
        return f"{TAG} — 2️⃣ 는 시총 3천억↑ & 전날 기관 순매수만 (시총 {mc / 1e8:,.0f}억, 기관 {_won(i)})"
    if kind == CAFE_KIND:
        rk = ctx.rank.get(code, 9999)
        return None if rk <= CAFE_PREV_RANK else f"{TAG} — ☕ 는 전날 대금 {CAFE_PREV_RANK}위 안만 (전날 {rk}위)"
    if kind in (RECLAIM_KIND, NEWHIGH_KIND):
        return None if _pos(i) else f"{TAG} — 전날 기관 순매수 종목만 (기관 {_won(i)})"
    if kind == HONG_KIND:
        return None if _pos(f) else f"{TAG} — 📕 는 전날 외인 순매수 종목만 (외인 {_won(f)})"
    return None


def _won(v) -> str:
    return "자료 없음" if v is None else f"{v / 1e8:+,.0f}억"
