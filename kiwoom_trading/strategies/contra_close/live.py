"""🌙 역행 강세 종가 — 강한 하락장 날 시장을 거스른 종목을 장 마감 때 사서 다음 날 시초가에 판다
(2026-10-25 사용자: "조정·약세장이라도 지투지바이오 같은 종목은 매매하는 게 맞다, 이런 패턴이 포착되게 하라").

지투지바이오 10-23: 09:10 시장 중앙 −4.4%(강한 하락장)인데 +20.4% 마감, 전날까지 기관 4일 연속 순매수, 외인 순매도.
장중에 사는 것은 1년 내내 손실이었다 (스크래치 contra.py / contra_an.py, 1분봉 1년, 그 분의 시장 중앙 대비 강도로 미래 정보 없이):
- 약한 날(조정·약세장 보통 + 강한 하락장) 5일 고점 돌파 순간 시장 대비 +3~10%p: 건당 −0.6~−1.1%, 기관 연속·대금 급증을 붙여도 −0.4~−1.2%.
- 09:30~11:00 에 시장 대비 강한 종목을 사도 −0.3~−1.0%.
→ 이런 종목은 '그날 장 마감 때' 사서 다음 날 시가 갭을 먹는 쪽이 맞다 (스크래치 contra_close.py, 종가배팅 데이터 1년, 다음 날 시가 매도, 비용 0.25%):
| 강한 하락장 날 (47일) | 건수 | 건당 | 앞 / 뒤 |
|---|---|---|---|
| 대금 상위 200 전체 | 9,143 | +0.69% | +1.38 / +0.28 |
| **시장 대비 +3%p↑ & 대금 30위** | 422 | **+0.85%** | +1.32 / +0.56 |
| 시장 대비 +10%p↑ & 대금 30위 | 137 | +0.79% | +1.02 / +0.62 |
| 대금 10위 · 상승 마감 | 175 | +1.05% | +1.26 / +0.94 |
- 하락 흐름 보통 날은 같은 조건이 −0.2~−0.4% → 강한 하락장 날에만 쓴다. (상승 흐름 보통 날 +0.40%, 강한 상승장 +0.37% 는 종가배팅 스킬 쪽)

규칙 (고정): 강한 하락장 판정일, 15:15~15:19 첫 KRX 대금 상위 스냅샷에서 주식만 대금 순서 30위 안,
           전일 대비 − 주식 중앙값 ≥ +3%p, 상한가(+29.5%↑) 제외,
           **고가 부근 마감**(KRX 정규장 (현재가−저가)/(고가−저가) ≥ 0.8, 2026-10-26 사용자 '④ 에 고가 부근 마감 조건도 넣어줘') → 🌙 알림·기록.
재검증 (2026-10-26, 바로잡은 엔진·운영과 같은 09:10/09:20 판정 54일, 스킬 danswer 10-4 scripts/t_contra.py):
  고가 부근 조건 없이 488건 +0.90% (앞 +0.84 / 뒤 +0.99) → 고가 부근 ≥0.8 140건 +1.48% (앞 +1.22 / 뒤 +1.66, 최고 5일 빼면 +14만),
  고가에서 밀린(<0.5) 130건 +0.63%. 건수가 1/3 로 줄고 몇몇 큰 날 몫이 커서 모의 체결로 계속 확인.
매수는 15:20~15:30 종가 동시호가, 매도는 다음 날 시초가 (갭 상승 노림).
⚠️ 모의투자는 아직 하룻밤 보유를 지원하지 않아 알림·기록만 한다 (paper_trader 가 건너뜀). 종가배팅 스킬(closing-bet) 참고.
"""
import logging
from datetime import datetime, time
from typing import Iterable

from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import RankItem

KIND = "역행 강세 종가"
START, END = time(15, 15), time(15, 19)
TOP_N = 30
REL_MIN = 0.03
LIMIT_UP = 0.295
NEAR_HIGH = 0.8


class ContraCloseWatcher:
    def __init__(self, stock_codes: Iterable[str], regime=None, done: bool = False, market=None) -> None:
        self.stocks = set(stock_codes)
        self.market = market        # KRX 정규장 고가·저가 조회 (고가 부근 판단)
        self.pos: dict[str, float] = {}
        self.regime = regime
        self.checked = done

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        if self.checked or not (START <= now.time() <= END):
            return []
        if self.regime is None or not self.regime.strong_down:
            self.checked = True
            logging.info("역행 강세 종가: 강한 하락장 아님 → 해당 없음")
            return []
        stocks = sorted((i for i in value_top if i.code in self.stocks and i.change_rate is not None), key=lambda i: i.rank)
        if len(stocks) < 50:
            return []
        self.checked = True
        xs = sorted(i.change_rate for i in stocks)
        n = len(xs)
        med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
        picks = [i for i in stocks[:TOP_N] if i.change_rate - med >= REL_MIN and i.change_rate < LIMIT_UP and i.price]
        near, far = [], []
        for i in picks:
            pos = self._close_pos(i.code)
            if pos is None or pos < NEAR_HIGH:
                far.append(f"{i.name}({'고가 부근 ' + format(pos, '.0%') if pos is not None else '시세 없음'})")
                continue
            self.pos[i.code] = pos
            near.append(i)
        if far:
            logging.info("역행 강세 종가: 고가 부근(%.0f%%↑) 아니라 뺌 %s", NEAR_HIGH * 100, ", ".join(far))
        picks = near
        logging.info("역행 강세 종가 %s: 주식 중앙 %+.2f%%, 대금 %s위 안 시장 대비 +%.0f%%p↑ %s종목: %s", f"{now:%H:%M}", med * 100,
                     TOP_N, REL_MIN * 100, len(picks), ", ".join(f"{i.name} {i.change_rate:+.1%}" for i in picks))
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for i in picks:
            reason = (f"강한 하락장 날 시장을 거스른 종목 — 전일 대비 {i.change_rate:+.1%} vs 주식 중앙 {med:+.1%} "
                      f"(+{(i.change_rate - med) * 100:.1f}%p), 대금 {i.rank}위, 고가 부근 {self.pos.get(i.code, 0):.0%}. 종가 동시호가 매수 → 다음 날 시초가 매도 "
                      f"(1년 강한 하락장 판정 54일: 고가 부근 140건 +1.48%, 조건 없이 488건 +0.90%)")
            out.append((i.code, i.name, KIND, Signal(ts, KIND, float(i.price), float(i.price), 0.0, reason)))
        return out

    def _close_pos(self, code: str):
        if self.market is None:
            return None
        try:
            q = self.market.quote(code, integrated=False)
        except Exception:
            logging.warning("역행 강세 종가: 시세 조회 실패 %s", code)
            return None
        if not q or q.high <= q.low:
            return 1.0 if q else None
        return (q.price - q.low) / (q.high - q.low)
