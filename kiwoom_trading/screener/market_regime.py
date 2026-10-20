"""🧯 강한 하락장 장 초 판정 → 보수적 매매 (2026-10-20 사용자: 강한 하락장일 때는 아주 보수적으로, 때로는 매매하지 않는 게 낫다).

판정: 09:10 에 한 번 (스캐너가 늦으면 09:20 까지 첫 스냅샷), KRX 대금 상위 200 중 주식만(ETF·인버스 제외)의
      전일 대비 등락 중앙값 ≤ −1.5% 이면 그날 '강한 하락장' (그날 끝까지 유지).
      ⚠️ 09:10~10:00 매분 판정으로 하면 10-19(09:29 −1.5%, 종가 +1.3% 반등일)를 잘못 판정한다 → 1년 검증과 같은 '09:10 한 번'.
근거 (스크래치 regime_early.py / regime_signals.py, 1년 246일, 전날 대금 상위 200):
- 09:10 중앙 ≤ −1.5% → 그날 종가 중앙 −1.5%↓ 강한 하락장 정밀도 74%, 강한 하락장 58일 중 50% 포착 (판정일 종가 중앙 −3.6%).
- 판정된 날 차트 신호가 더 나쁘다: 주도주 모양 −0.72% (다른 날 −0.36%), 눌림 돌파 −0.46% (−0.34%), 앞·뒤 기간 모두.
- 대형주 09:30 +2% 매매는 판정일에도 −0.24% 로 다른 날(−0.29%)보다 나쁘지 않다 (장 초 빠진 대형주 반등 경향).
보수적 매매 (paper_trader 가 적용):
- 차트·박스 신호(주도주 모양, 눌림 돌파, 장 초 공통점, 지지 반등, 돌파 후 눌림) 새 매수 안 함 — 알림과 기록만 (복기에서 가상 매매로 검증)
- 🎯 대형주 수급은 하루 1종목까지
- 하루 손실 한도 −3% → −1.5%
- 이미 산 종목은 원래 매도 규칙 그대로
"""
import logging
from datetime import datetime, time
from typing import Callable, Iterable, Optional

from kiwoom_trading.screener.market_data import RankItem

START, END = time(9, 10), time(9, 20)
STRONG_DOWN = -0.015
CONSERVATIVE_LOSS_LIMIT = 0.015
BIGCAP_MAX_WHEN_DOWN = 1


class MarketRegime:
    def __init__(self, stock_codes: Iterable[str], notify: Optional[Callable[[str], None]] = None) -> None:
        self.stocks = set(stock_codes)
        self.notify = notify or (lambda text: None)
        self.strong_down = False
        self.last_median: Optional[float] = None
        self.decided_at: Optional[datetime] = None
        self.checked = False

    def update(self, now: datetime, value_top: list[RankItem]) -> None:
        if self.checked or not (START <= now.time() <= END):
            return
        xs = sorted(i.change_rate for i in value_top if i.code in self.stocks and i.change_rate is not None)
        if len(xs) < 50:
            return
        self.checked = True
        n = len(xs)
        med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
        self.last_median = med
        logging.info("시장 분위기 판정 %s: 대금 상위 주식 %s종목 중앙 %+.2f%% → %s", f"{now:%H:%M}", n, med * 100,
                     "강한 하락장" if med <= STRONG_DOWN else "보통")
        if med <= STRONG_DOWN:
            self.strong_down, self.decided_at = True, now
            self.notify(f"🧯 강한 하락장 판정 {now:%H:%M} — 대금 상위 주식 {n}종목 중앙 {med:+.1%} (기준 {STRONG_DOWN:+.1%})\n"
                        f"오늘은 보수적으로: 차트 신호(주도주 모양·눌림 돌파·장 초 공통점·지지 반등·돌파 후 눌림)는 새로 사지 않고 알림만, "
                        f"대형주 수급은 {BIGCAP_MAX_WHEN_DOWN}종목까지, 하루 손실 한도 −{CONSERVATIVE_LOSS_LIMIT:.1%}. 보유 종목은 원래 매도 규칙대로.\n"
                        f"(1년: 이렇게 판정된 날 74% 가 강한 하락장, 차트 신호 −0.72% vs 다른 날 −0.36%)")
