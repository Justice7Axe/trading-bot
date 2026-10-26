"""📕 홍인기(대왕개미) 매매일지 전략 — 상한가 풀림 매수 (상따) 규칙 함수.

일지(2026-10-26 루닛 등)에 나온 방식:
  상한가에 잠긴 종목이 잠깐 풀리면 비중을 낮춰 산다. 사기 전에 기관 가집계 순매수·프로그램 순매수가 + 인지 본다.
  다시 상한가에 들어가면 절반을 상한가에 팔고, 나머지는 하루 넘겨 다음 날 판다.

1분봉 한 개 = (time, open, high, low, close, volume). 가격은 1분봉 가격(받은 날 기준) 그대로 쓴다.
백테스트(run_hong_backtest.py)와 실시간 가상 계좌(screener/hong_account.py)가 같은 숫자를 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time


@dataclass(frozen=True)
class HongParams:
    min_lock: int = 1            # 풀리기 전 상한가에 통째로 잠긴(저가 = 상한가) 연속 분 수
    t_from: time = time(9, 0)    # 풀림 매수 시작 시각
    t_to: time = time(15, 0)     # 이 시각 뒤 풀림은 안 삼
    entry: str = "close"         # "close" 풀린 봉 종가 / "next" 다음 봉 시가 (둘 다 상한가면 못 삼 → 다음 풀림 기다림)
    min_dip: float = 0.0         # 풀림 깊이 최소 (저가 ≤ 상한가 × (1 − min_dip))
    half_at_limit: bool = True   # 다시 상한가 닿으면 절반 상한가에 매도
    all_at_limit: bool = False   # 다시 상한가 닿으면 전부 매도 (half 보다 먼저)
    stop_pct: float | None = None  # 장중 손절 (매수가 대비), 닿으면 남은 물량 즉시
    slip_ticks: int = 0          # 매수가를 호가 n칸 비싸게 (체결 미끄러짐 점검, 상한가는 넘지 않음)
    stop_vs_limit: float | None = None  # 손절가 = 상한가 × 이 값 (일지: 전일 대비 +25% 아래면 손절 → 1.25/1.30 ≈ 0.9615)

    def with_(self, **kw) -> "HongParams":
        return replace(self, **kw)


def tick_size(price: float) -> int:
    """KRX 호가 단위 (2023-01-25 부터, 코스피·코스닥 같음)."""
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if price < lim:
            return t
    return 1000


def upper_limit(base: float) -> int:
    """상한가 = 기준가 × 1.3 을 그 가격대 호가 단위로 내림. 예: 루닛 2026-10-26 기준가 11,300 → 14,690."""
    raw = base * 1.3
    t = tick_size(raw)
    return int(raw // t * t)


def find_entry(reg, limit, p: HongParams):
    """정규장 1분봉 reg 에서 첫 매수 자리 → (j, buy_price, buy_bar_index_for_exit_start, locked_run) 또는 None.
    j = 풀린 봉 위치. 매도 검사는 entry='close' 면 j+1 봉부터, 'next' 면 j+1 봉(그 봉 시가에 삼)부터."""
    touched = False
    run = 0          # 지금까지 연속으로 통째로 잠긴 분 수
    best_run = 0     # 이번 풀림 직전 잠김 길이
    for j, (t, o, h, l, c, v) in enumerate(reg):
        if not touched:
            if h >= limit:
                touched = True
                run = 1 if l >= limit else 0
            continue
        if l >= limit:
            run += 1
            continue
        # 풀림 (저가 < 상한가)
        best_run, run = run, 0
        if best_run < p.min_lock or not (p.t_from <= t <= p.t_to):
            continue
        if l > limit * (1 - p.min_dip):
            continue
        if p.entry == "close":
            if c < limit:
                return j, _slip(c, limit, p), j + 1, best_run
        else:
            if j + 1 < len(reg) and reg[j + 1][1] < limit:
                return j, _slip(reg[j + 1][1], limit, p), j + 1, best_run
    return None


def _slip(price, limit, p: HongParams):
    for _ in range(p.slip_ticks):
        price = min(price + tick_size(price), limit)
    return price


def simulate_exit(reg, start, buy, limit, p: HongParams):
    """start 봉부터 정규장 끝까지 매도 → [(비율, 가격 또는 None=다음 날 매도, 이유)].
    같은 봉에 손절과 상한가가 함께 있으면 손절 먼저 (메모리 backtest-exit-rules)."""
    left = 1.0
    out = []
    sp = buy * (1 - p.stop_pct) if p.stop_pct else None
    if p.stop_vs_limit:
        sp = max(sp or 0, limit * p.stop_vs_limit)
    half_done = False
    for (t, o, h, l, c, v) in reg[start:]:
        if sp and l <= sp:
            out.append((left, min(o, sp), "손절"))
            return out
        if h >= limit:
            if p.all_at_limit:
                out.append((left, limit, "상한가 전부"))
                return out
            if p.half_at_limit and not half_done:
                out.append((left / 2, limit, "상한가 절반"))
                left /= 2
                half_done = True
    out.append((left, None, "다음 날"))
    return out


def flow_ok(inst_net: float | None, prog_net: float | None, need_prog: bool = True) -> bool:
    """매수 전 수급 확인: 기관 가집계 순매수 > 0, 프로그램 순매수 > 0 (프로그램 자료가 없으면 need_prog=False 로 기관만)."""
    if inst_net is None or inst_net <= 0:
        return False
    if need_prog:
        return prog_net is not None and prog_net > 0
    return True
