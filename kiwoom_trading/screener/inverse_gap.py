"""🎯 인버스 갭 — 시가 갭이 크게 빠진 날 TIGER 인버스(1배)를 장 초에 사서 15:19 까지 보유 (2026-10-20 사용자 결정, 실험용·가설).

규칙 (결과를 보기 전에 고정):
- 09:00~09:05 첫 KRX 대금 상위 200 스냅샷에서 주식만(ETF 제외)의 전일 대비 등락 중앙값 ≤ −1%
  (장 시작 직후라 시가 갭 중앙과 거의 같다)
- → TIGER 인버스(123310) 시장가 매수, 손절 없이 15:19 정리 (모의투자 mode='보유')
근거 (스크래치 inv_fetch.py / inv_an.py, 1분봉 246일, 비용 0.05%·ETF 거래세 없음):
- 시가 갭 중앙(전날 대금 상위 200) ≤ −1% → 09:01 매수 → 종가: 42일 +0.71% (앞 +0.44% / 뒤 +0.95%), 승률 52%, 중앙 +0.46%
- 약점: 상위 3일 빼면 +0.33%, 기준을 −1.5%/−2% 로 강하게 하면 +0.36/+0.13% 로 오히려 줄어 일관성이 없다. 익절·손절 방식은 0 근처.
- 09:10 강한 하락장 판정 뒤 매수는 39일 −0.00% (이미 +0.66% 오른 뒤, 대형주 반등 경향) → 쓰지 않는다.
한 달에 3~4번 나오므로 몇 달 쌓아야 판단할 수 있다.
"""
import logging
from datetime import datetime, time
from typing import Iterable, Optional

from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import KiwoomMarket, RankItem

KIND = "인버스 갭"
CODE, NAME = "123310", "TIGER 인버스"
START, END = time(9, 0), time(9, 5)
GAP_DOWN = -0.01


class InverseGapWatcher:
    def __init__(self, market: KiwoomMarket, stock_codes: Iterable[str], done: bool = False) -> None:
        self.market = market
        self.stocks = set(stock_codes)
        self.checked = done

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        if self.checked or not (START <= now.time() <= END):
            return []
        xs = sorted(i.change_rate for i in value_top if i.code in self.stocks and i.change_rate is not None)
        if len(xs) < 50:
            return []
        self.checked = True
        n = len(xs)
        med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
        logging.info("인버스 갭 판정 %s: 대금 상위 주식 %s종목 중앙 %+.2f%% → %s", f"{now:%H:%M}", n, med * 100,
                     "인버스 매수" if med <= GAP_DOWN else "해당 없음")
        if med > GAP_DOWN:
            return []
        q = self.market.quote(CODE, integrated=False)
        if not q:
            logging.warning("인버스 갭: %s 시세 조회 실패", NAME)
            return []
        reason = (f"장 시작 대금 상위 주식 {n}종목 중앙 {med:+.1%} (기준 {GAP_DOWN:+.0%}) — 시가 갭 하락일 인버스, "
                  f"손절 없이 15:19 정리 (1년 42일 +0.71%, 승률 52% · 가설 검증 중)")
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        return [(CODE, NAME, KIND, Signal(ts, KIND, float(q.price), float(q.open), 0.0, reason))]
