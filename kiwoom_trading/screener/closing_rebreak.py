"""🌙 종가 재돌파 — 정규장 대금 상위 10위 상승 마감 종목이 17시 이후 애프터마켓(NXT)에서 정규장 종가 위로 올라오면 사서
다음 날 09:00 에 판다 (2026-10-25 사용자: 디앤서 「실전 시황 트레이딩」 인터뷰 영상의 종가배팅을 그대로 반영).

영상 규칙: 13시까지 지켜본 강한 종목을 17시 이후 '정규장 종가를 지켜주는지' 보고, 종가를 다시 넘는 자리부터 산다.
1년 백테스트 (통합 1분봉 15:40~20:00 애프터마켓 포함, 비용 0.25%, 다음 날 09:00 시가 매도, closing-bet 스킬 scripts/dans_an.py):
| 대상 · 매수 | 건수 | 건당 | 앞 / 뒤 | 합계(건당 100만) | 낙폭 |
|---|---|---|---|---|---|
| 대금 10위 · 상승 마감 · 정규장 종가 매수 (지금까지 규칙) | 1,470 | +0.38% | +0.30 / +0.46 | +553만 | 129만 |
| **대금 10위 · 상승 마감 · 17시 이후 종가 위** | 700 | **+0.58%** | +0.35 / +0.79 | +404만 | **65만** |
| 대금 10위 · 상승 마감 · 17시 이후 종가 재돌파(아래 있다가 위로) | 627 | +0.53% | +0.32 / +0.72 | +330만 | 67만 |
| 영상 그대로 (+8%↑) · 재돌파 | 276 | +0.58% | +0.41 / +0.75 | +159만 | 35만 |
- 영상의 '애프터마켓 저가 이탈 손절'은 수익을 거의 다 없앤다 (+0.53% → +0.03%) → 손절 없이 다음 날까지 본다 (영상: 다음 날 시세까지는 무조건 본다).
- +8% 조건은 건당이 같고 건수만 줄어 → 상승 마감이면 산다. 3번 나눠 사기·코스피 하락일만·연속성 조건은 나빠졌다.
2026-10-25 보완 (scripts/rebreak_feat.py): **18시 전에 종가를 되찾은 종목만** 산다.
- 18시 이후에야 종가 위로 온 종목 121건 −0.22% (네 분기 중 세 분기 손실) → 빼면 554건 +0.79% (앞 +0.47 / 뒤 +1.07), 합계 +435만, 낙폭 57만.
- 17시 직전(16:55~16:59) 애프터 가격이 이미 종가 위였던 종목은 349건 +0.89%, 낙폭 42만 → ★ 표시 (금액은 같음).
매수는 NXT 애프터마켓이라 키움 모의 서버로 주문할 수 없어 가상 체결로 기록하고, 다음 날 09:00 정규장 시세로 가상 매도한다.
"""
import logging
from datetime import datetime, time
from typing import Iterable, Optional

from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import KiwoomMarket, RankItem

KIND = "종가 재돌파"
FREEZE_AT = time(15, 35)          # KRX 종가 동시호가(15:30) 뒤 대금 순위·종가가 굳는 때
START, END = time(17, 0), time(18, 0)    # 영상: 17시 이후 진입 / 18시까지 종가를 못 되찾으면 안 산다 (보완 2026-10-25)
PRE17 = time(16, 55)                      # 17시 직전 애프터 가격 확인 → ★
TOP_N = 10
LIMIT_UP = 0.295


class ClosingRebreakWatcher:
    def __init__(self, market: KiwoomMarket, stock_codes: Iterable[str], done: Iterable[str] = ()) -> None:
        self.market = market
        self.stocks = set(stock_codes)
        self.done = set(done)
        self.cands: Optional[list[RankItem]] = None
        self.pre17: dict[str, int] = {}

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        tm = now.time()
        if self.cands is None and tm >= FREEZE_AT and value_top:
            stocks = sorted((i for i in value_top if i.code in self.stocks), key=lambda i: i.rank)[:TOP_N]
            self.cands = [i for i in stocks if i.change_rate is not None and 0 < i.change_rate < LIMIT_UP and i.price]
            logging.info("종가 재돌파 후보 (정규장 대금 %s위 안 상승 마감) %s종목: %s", TOP_N, len(self.cands),
                         ", ".join(f"{i.name} {i.change_rate:+.1%} {i.price:,}" for i in self.cands))
        if self.cands and PRE17 <= tm < START:
            for i in self.cands:
                if i.code not in self.pre17:
                    try:
                        q = self.market.quote(i.code, integrated=True)
                        if q:
                            self.pre17[i.code] = q.price
                    except Exception:
                        logging.warning("종가 재돌파 17시 전 시세 조회 실패 %s", i.code)
        if not self.cands or not (START <= tm < END):
            return []
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for i in self.cands:
            if i.code in self.done:
                continue
            try:
                q = self.market.quote(i.code, integrated=True)
            except Exception:
                logging.warning("종가 재돌파 시세 조회 실패 %s", i.code)
                continue
            if not q or q.price <= i.price:
                continue
            self.done.add(i.code)
            star = self.pre17.get(i.code, 0) > i.price
            reason = (f"{'★17시 전부터 종가 위 ' if star else ''}정규장 대금 {i.rank}위 · {i.change_rate:+.1%} 마감, 17시 이후 애프터마켓 {q.price:,}원이 정규장 종가 {i.price:,}원 위 "
                      f"({q.price / i.price - 1:+.1%}). 손절 없이 다음 날 09:00 매도 "
                      f"(1년 18시 전 진입 554건 +0.79%, 앞 +0.47 / 뒤 +1.07{', ★ 349건 +0.89%' if star else ''} · 애프터마켓이라 가상 체결)")
            out.append((i.code, i.name, KIND, Signal(ts, KIND, float(q.price), float(i.price), 0.0, reason)))
        return out
