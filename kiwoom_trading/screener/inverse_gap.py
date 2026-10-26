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


# ---------------------------------------------------------------- ⑤ 약세장 인버스 (2026-10-25 사용자 '가 나 다 모두 적용')
WEAK_KIND = "약세장 인버스"
WEAK_TP, WEAK_STOP = 0.05, 0.03
WEAK_START, WEAK_END = time(9, 11), time(9, 16)


class WeakInverseWatcher:
    """하락 흐름 보통 날(09:10 판정이 강한 상승장·하락장이 아니고 코스피가 52주 고점 대비 −10% 밖) 09:11 에 TIGER 인버스 매수.
    매도는 paper_trader '다음날' 방식: +5% 익절 / −3% 손절 / 둘 다 아니면 다음 날 09:00.
    근거 (스크래치 nm_ideas_a.py / nm_ideas_b.py, 인버스 1분봉, 조정·약세장 보통 날 56일, 비용 0.05%):
      +5/−3 56건 +0.92% (앞 +1.05 / 뒤 +0.79), 최고일 빼도 +43만(100만/건), 최대 낙폭 11만, 7개월 중 5개월 +.
      매수 09:01~10:01·익절/손절 5조합 모두 +. 다른 날 구분에선 모두 − (상승 흐름 보통 날 −0.47, 강한 상승장 −0.63, 강한 하락장 −0.45).
      09:10 코스피가 약한 날로 좁히면 오히려 나빠짐 → 거르지 않는다.
    🇺🇸 간밤 미국 지수(2026-10-27 사용자 '인버스 살 때 잘 체크'): 매수 전 간밤 방향별 1년 상승 21건 +0.80% · 혼조 17건 +1.07% ·
      하락 18건 +0.92% → 결과 차이 없음(이미 09:00 시가·09:10 판정에 들어감). 결과를 가르는 건 들고 넘어가는 그날 밤 미국
      (상승 −0.31% / 하락 +2.41%)인데, 한국장 중 나스닥 선물로는 그 밤을 못 맞춤(상관 −0.12). → 거르지 않고 알림·기록에 표시만."""

    def __init__(self, market: KiwoomMarket, regime=None, done: bool = False, us=None) -> None:
        self.market = market
        self.regime = regime
        self.checked = done
        self.us = us     # common.us_market.Overnight (없으면 None)

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        r = self.regime
        if self.checked or r is None or not (WEAK_START <= now.time() <= WEAK_END):
            return []
        from kiwoom_trading.screener.market_regime import CHECKS
        if r.strong_up or r.strong_down or CHECKS[0] not in r.done:
            self.checked = r.strong_up or r.strong_down
            return []
        self.checked = True
        if not r.trend_weak:
            return []
        q = self.market.quote(CODE, integrated=False)
        if not q:
            logging.warning("약세장 인버스: %s 시세 조회 실패", NAME)
            return []
        reason = (f"하락 흐름 보통 날 ({r.trend_text()}) — 09:11 인버스, +{WEAK_TP:.0%} 익절 / −{WEAK_STOP:.0%} 손절, 못 닿으면 다음 날 09:00 "
                  f"(1년 하락 흐름 보통 날 56건 +0.92%)")
        if self.us is not None:
            reason += (f"\n  {self.us.text()} — 매수 전 간밤 방향은 1년 결과와 무관(상승 +0.80 · 혼조 +1.07 · 하락 +0.92%), "
                       f"오늘 밤 미국이 오르면 내일 시가가 불리")
        logging.info("약세장 인버스: %s", reason)
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        return [(CODE, NAME, WEAK_KIND, Signal(ts, WEAK_KIND, float(q.price), float(q.open), float(q.price) * (1 - WEAK_STOP), reason))]
