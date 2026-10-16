"""🎯 주도주 모양 매수 신호 — 10-16 사용자가 고른 주도주 9종목의 1분봉 모양을 정형화했다 (2026-10-17).

9종목: HT로보틱스, 한선엔지니어링, NAVER, 셀트리온, 알테오젠, 한화시스템, 현대차, 한화에어로스페이스, 삼성바이오로직스.
"크게 갭을 띄우지 않고 시가 근처에서 출발해, VWAP(그날 평균 단가) 위에서 흔들림 없이 고점을 계속 높여 가는 종목".

판정 (09:30~10:30 매 1분, 마감된 KRX 1분봉 09:00~ 기준, 그날 종목당 1번):
- 대금 순위(KRX 누적) 100위 안
- 매끄러움 = (현재가 − 시가) ÷ 1분 종가 움직임 절대값 합 ≥ 0.15
- 시가 대비 +2% 이상, 갭(시가 ÷ 전일 종가) +4% 이하
- 09:05 이후 봉의 60% 이상이 VWAP 위에서 마감
- 신고가 갱신 5번 이상
- 눌림 비율 = 고점 대비 최대 하락 ÷ (고점 − 시가) ≤ 3

검증 (10-13~10-16, 그 시점 대금 100위 안 후보, 09:30 판정 → 다음 봉 매수 → 15:19 정리, 비용 0.25%):
- 10-16: 9종목 전부 + 2종목, 11종목 평균 +1.57%
- 규칙을 만들 때 안 본 날 — 10-13: 13종목 +0.40%(후보 평균 −0.65%), 10-14: 17종목 −1.63%(−2.19%), 10-15: 1종목 +7.82%(−2.09%)
- 나흘 모두 후보 평균보다 나았지만 42건 평균은 +0.06% 로 본전 근처다. 시장이 오후에 밀린 날(10-14)은 손실. 1년 검증 전까지 실험용.

매도(사용자 2026-10-17): 1분봉 차트로 종목마다 — 매수 뒤 '큰 음봉'(몸통 평소 3배↑·대금 2배↑)이 나오면 다음 확인 때 매도 (big_red_exit).
손절 = 직전 10분 저가 −0.5% (매수가 대비 −2% ~ −5%), 남으면 15:19 정리.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import RankItem

KIND = "주도주 모양"


@dataclass(frozen=True)
class LeaderShapeConfig:
    start: time = time(9, 30)
    end: time = time(10, 30)
    max_rank: int = 100
    recheck_minutes: int = 2        # 같은 종목 1분봉은 2분에 한 번만 다시 받는다 (100종목 × 매분이면 1분 주기가 밀림)
    min_eff: float = 0.15
    min_from_open: float = 0.02
    max_gap: float = 0.04
    min_vwap_share: float = 0.6
    min_new_highs: int = 5
    max_pull: float = 3.0
    stop_lookback: int = 10
    stop_buffer: float = 0.005
    stop_min: float = 0.02
    stop_max: float = 0.05


def features(bars: list[dict[str, Any]], prev_close: float) -> Optional[dict[str, float]]:
    """09:00 부터의 마감된 1분봉(시간순)으로 모양 특징. 봉이 8개 미만이면 None."""
    up = [b for b in bars if b["ts"].time() >= time(9, 0)]
    if len(up) < 8 or not prev_close:
        return None
    o = up[0]["open"]
    cl = [b["close"] for b in up]
    p = cl[-1]
    pv = v = 0.0
    above = n5 = 0
    for b in up:
        tp = (b["high"] + b["low"] + b["close"]) / 3
        pv += tp * b["volume"]
        v += b["volume"]
        vw = pv / v if v else tp
        if b["ts"].time() >= time(9, 5):
            n5 += 1
            above += b["close"] > vw
    new_highs, run_high, pull = 0, 0, 0.0
    for b in up:
        if b["high"] > run_high:
            new_highs += 1
            run_high = b["high"]
    run_high = up[0]["high"]
    for b in up:
        run_high = max(run_high, b["high"])
        pull = max(pull, (run_high - b["low"]) / max(run_high - o, o * 0.005))
    moves = sum(abs(cl[j] - cl[j - 1]) for j in range(1, len(cl)))
    return {
        "eff": (p - o) / moves if moves else 0.0,
        "from_open": p / o - 1,
        "gap": o / prev_close - 1,
        "chg": p / prev_close - 1,
        "vwap_share": above / n5 if n5 else 0.0,
        "new_highs": new_highs,
        "pull": pull,
        "price": p,
        "low10": min(b["low"] for b in up[-10:]),
    }


def failed(f: dict[str, float], rank: int, cfg: LeaderShapeConfig) -> Optional[str]:
    """통과하면 None, 아니면 첫 번째로 걸린 조건."""
    checks = [
        (rank <= cfg.max_rank, f"대금 {rank}위"),
        (f["gap"] <= cfg.max_gap, f"갭 {f['gap']:+.1%}"),
        (f["from_open"] >= cfg.min_from_open, f"시가 대비 {f['from_open']:+.1%}"),
        (f["eff"] >= cfg.min_eff, f"매끄러움 {f['eff']:.2f}"),
        (f["vwap_share"] >= cfg.min_vwap_share, f"VWAP 위 {f['vwap_share']:.0%}"),
        (f["new_highs"] >= cfg.min_new_highs, f"신고가 {f['new_highs']}번"),
        (f["pull"] <= cfg.max_pull, f"눌림 {f['pull']:.1f}배"),
    ]
    return next((why for ok, why in checks if not ok), None)


def stop_price(price: float, low10: float, cfg: LeaderShapeConfig) -> float:
    return min(price * (1 - cfg.stop_min), max(price * (1 - cfg.stop_max), low10 * (1 - cfg.stop_buffer)))


class LeaderShapeWatcher:
    """매분 대금 상위 100위 안 종목(종목마다 2분에 한 번)의 KRX 1분봉으로 모양 판정 → 신호 (종목당 하루 1번)."""

    def __init__(self, client: KiwoomDailyClient, today: date, prev_close: dict[str, float],
                 config: Optional[LeaderShapeConfig] = None, done: Optional[set[str]] = None) -> None:
        self.client = client
        self.today = today
        self.prev_close = prev_close
        self.config = config or LeaderShapeConfig()
        self.done: set[str] = set(done or ())       # 오늘 이미 신호를 낸 종목
        self.excluded: dict[str, str] = {}           # 그날 다시 바뀌지 않는 조건(갭)에 걸린 종목
        self.last_check: dict[str, datetime] = {}
        self.cache: dict[str, list] = {}               # 같은 분에 받은 KRX 1분봉 (주도주 모양·눌림 돌파가 함께 씀, run_once 가 매분 비움)

    def _bars(self, code: str) -> list:
        if code not in self.cache:
            self.cache[code] = fetch_minute_bars(self.client, code, self.today, "KRX")
        return self.cache[code]

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        cfg = self.config
        t = now.time()
        if not (cfg.start <= t <= cfg.end):
            return []
        minute_start = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for item in value_top:
            if item.rank > cfg.max_rank or item.code in self.done or item.code in self.excluded:
                continue
            last = self.last_check.get(item.code)
            if last and (minute_start - last).total_seconds() < cfg.recheck_minutes * 60:
                continue
            prev = self.prev_close.get(item.code)
            if not prev:
                continue
            self.last_check[item.code] = minute_start
            try:
                bars = [b for b in self._bars(item.code) if b["ts"] < minute_start]
            except Exception as exc:
                logging.warning("주도주 모양 1분봉 조회 실패 %s: %s", item.code, exc)
                continue
            f = features(bars, prev)
            if f is None:
                continue
            if f["gap"] > cfg.max_gap:
                self.excluded[item.code] = f"갭 {f['gap']:+.1%}"
                continue
            if failed(f, item.rank, cfg):
                continue
            self.done.add(item.code)
            sig_ts = bars[-1]["ts"]
            stop = stop_price(f["price"], f["low10"], cfg)
            reason = (f"대금 {item.rank}위 · 시가 대비 {f['from_open']:+.1%}(갭 {f['gap']:+.1%}) · 매끄러움 {f['eff']:.2f} · "
                      f"VWAP 위 {f['vwap_share']:.0%} · 신고가 {f['new_highs']}번 · 눌림 {f['pull']:.1f}배 — 매도: 큰 음봉(몸통 3배·대금 2배) 또는 손절, 남으면 15:19")
            out.append((item.code, item.name, KIND, Signal(sig_ts, KIND, float(f["price"]), float(f["low10"]), float(stop), reason)))
        return out


# ---------------------------------------------------------------- 매도: 1분봉 큰 음봉 (2026-10-17 사용자: 차트·음봉 추이로 종목마다 다른 매도)
BIG_RED_BODY = 3.0      # 음봉 몸통 ≥ 직전 20봉 평균 몸통 × 3
BIG_RED_VALUE = 2.0     # 그 봉 대금 ≥ 직전 20봉 평균 대금 × 2


def big_red_exit(bars: list[dict[str, Any]], buy_ts: datetime) -> Optional[str]:
    """매수 뒤 마지막 마감 봉이 '큰 음봉'(몸통·대금 모두 평소보다 크게 나온 음봉)이면 사유, 아니면 None.

    비교 (주도주 모양 진입, 처음 손절·15:19 공통):
    - 10-16 사용자 주도주 9종목 + 하이브: 큰 음봉 +2.33% / 끝까지 보유 +1.67% / 20분선 2봉 이탈 +1.30% / 고점 −3% +0.98%
      (한화시스템 11:03, 셀트리온 14:01, 현대차 13:52 매도, HT로보틱스는 끝까지 보유 — 종목마다 매도 시각이 다르다)
    - 35일 편향 없는 표본(736건): 모든 매도 방식이 −0.14~−0.32% 로 비슷 → 매수 신호 자체의 우위가 먼저다.
    """
    if not bars or bars[-1]["ts"] <= buy_ts:
        return None
    j = len(bars) - 1
    b = bars[j]
    prior = bars[max(0, j - 20):j]
    if len(prior) < 5 or b["close"] >= b["open"]:
        return None
    body = b["open"] - b["close"]
    avg_body = sum(abs(x["close"] - x["open"]) for x in prior) / len(prior)
    value = b["close"] * b["volume"]
    avg_value = sum(x["close"] * x["volume"] for x in prior) / len(prior)
    if avg_body > 0 and avg_value > 0 and body >= avg_body * BIG_RED_BODY and value >= avg_value * BIG_RED_VALUE:
        return f"큰 음봉 {b['ts']:%H:%M} (몸통 평소 {body / avg_body:.1f}배, 대금 {value / avg_value:.1f}배)"
    return None
