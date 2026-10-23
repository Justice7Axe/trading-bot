"""🧯 강한 하락장 장 초 판정 → 보수적 매매 (2026-10-20 사용자: 강한 하락장일 때는 아주 보수적으로, 때로는 매매하지 않는 게 낫다).

판정: 09:10 과 09:20 두 번 (각 시각 뒤 5분 안 첫 스냅샷), KRX 대금 상위 200 중 주식만(ETF·인버스 제외)의
      전일 대비 등락 중앙값 ≤ −1.5% 이면 그날 '강한 하락장' (그날 끝까지 유지).
      1년: 09:10 만 → 39일 정밀도 74% 포착 50% / 09:10 또는 09:20 → 46일 정밀도 72% 포착 57% (추가 7일 종가 중앙 −2.5%)
           / 09:30 까지 더하면 50일 정밀도 66% 로 떨어진다.
      ⚠️ 매분 판정으로 하면 10-19(09:29 −1.5%, 종가 +1.3% 반등일)를 잘못 판정한다 → 정해진 두 시점만.
근거 (스크래치 regime_early.py / regime_signals.py, 1년 246일, 전날 대금 상위 200):
- 09:10 중앙 ≤ −1.5% → 그날 종가 중앙 −1.5%↓ 강한 하락장 정밀도 74%, 강한 하락장 58일 중 50% 포착 (판정일 종가 중앙 −3.6%).
- 판정된 날 차트 신호가 더 나쁘다: 주도주 모양 −0.72% (다른 날 −0.36%), 눌림 돌파 −0.46% (−0.34%), 앞·뒤 기간 모두.
- 대형주 09:30 +2% 매매는 판정일에도 −0.24% 로 다른 날(−0.29%)보다 나쁘지 않다 (장 초 빠진 대형주 반등 경향).
보수적 매매 (paper_trader 가 적용):
- 차트·박스 신호(주도주 모양, 눌림 돌파, 장 초 공통점, 지지 반등, 돌파 후 눌림) 새 매수 안 함 — 알림과 기록만 (복기에서 가상 매매로 검증)
- 🎯 대형주 수급은 하루 1종목까지
- 하루 손실 한도 −3% → −1.5%
- 이미 산 종목은 원래 매도 규칙 그대로

📈 강한 상승장 판정 (2026-10-23 사용자 B안: 차트 신호 3종은 강한 상승장에만 산다):
      같은 두 시점에 중앙값 ≥ +2% 이면 그날 '강한 상승장' (그날 끝까지 유지).
      그날만 지지 반등·돌파 후 눌림·주도주 모양을 실제 주문으로 산다. 다른 날은 알림·기록만 (복기에서 가상 매매로 검증).
근거: 모의매매 5거래일(10-16~22) 이 셋 85건 −0.8% 안팎으로 손실 대부분. 1년: 09:10 중앙 ≥ +2% 22일에
      주도주 모양 +0.25% vs 다른 날 −0.52% (스크래치 regime_up.py).
⚠️ 10-19 처럼 약하게 출발해 크게 오른 날은 못 잡는다 (09:10 −1.49%). 10-21 은 +2.7% 출발 뒤 밀린 예외.
"""
import logging
from datetime import datetime, time
from typing import Callable, Iterable, Optional

from kiwoom_trading.screener.market_data import RankItem

CHECKS = (time(9, 10), time(9, 20))   # 각 시각부터 5분 안 첫 스냅샷에서 한 번씩
WINDOW_MIN = 5
STRONG_DOWN = -0.015
STRONG_UP = 0.02
UP_ONLY_KINDS = ("지지 반등", "돌파 후 눌림", "주도주 모양")   # 강한 상승장에만 실제 주문
CONSERVATIVE_LOSS_LIMIT = 0.015
BIGCAP_MAX_WHEN_DOWN = 1


class MarketRegime:
    def __init__(self, stock_codes: Iterable[str], notify: Optional[Callable[[str], None]] = None) -> None:
        self.stocks = set(stock_codes)
        self.notify = notify or (lambda text: None)
        self.strong_down = False
        self.strong_up = False
        self.last_median: Optional[float] = None
        self.decided_at: Optional[datetime] = None
        self.done: set[time] = set()

    def update(self, now: datetime, value_top: list[RankItem]) -> None:
        if self.strong_down or self.strong_up:
            return
        mins = now.hour * 60 + now.minute
        due = [c for c in CHECKS if c not in self.done and c.hour * 60 + c.minute <= mins < c.hour * 60 + c.minute + WINDOW_MIN]
        if not due:
            return
        xs = sorted(i.change_rate for i in value_top if i.code in self.stocks and i.change_rate is not None)
        if len(xs) < 50:
            return
        self.done.update(due)
        n = len(xs)
        med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
        self.last_median = med
        logging.info("시장 분위기 판정 %s: 대금 상위 주식 %s종목 중앙 %+.2f%% → %s", f"{now:%H:%M}", n, med * 100,
                     "강한 하락장" if med <= STRONG_DOWN else "강한 상승장" if med >= STRONG_UP else "보통")
        if med >= STRONG_UP:
            self.strong_up, self.decided_at = True, now
            self.notify(f"📈 강한 상승장 판정 {now:%H:%M} — 대금 상위 주식 {n}종목 중앙 {med:+.1%} (기준 {STRONG_UP:+.1%})\n"
                        f"오늘은 차트 신호({'·'.join(UP_ONLY_KINDS)})도 모의 매수합니다. 강한 상승장이 아닌 날은 알림·기록만.")
        if med <= STRONG_DOWN:
            self.strong_down, self.decided_at = True, now
            self.notify(f"🧯 강한 하락장 판정 {now:%H:%M} — 대금 상위 주식 {n}종목 중앙 {med:+.1%} (기준 {STRONG_DOWN:+.1%})\n"
                        f"오늘은 보수적으로: 차트 신호(주도주 모양·눌림 돌파·장 초 공통점·지지 반등·돌파 후 눌림)는 새로 사지 않고 알림만, "
                        f"대형주 수급은 {BIGCAP_MAX_WHEN_DOWN}종목까지, 하루 손실 한도 −{CONSERVATIVE_LOSS_LIMIT:.1%}. 보유 종목은 원래 매도 규칙대로.\n"
                        f"(1년: 이렇게 판정된 날 74% 가 강한 하락장, 차트 신호 −0.72% vs 다른 날 −0.36%)")
