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

매도(사용자 2026-10-17): 반반 — +2% 에서 절반, 나머지는 15:19 정리. 손절 = 직전 10분 저가 −0.5% (매수가 대비 −2% ~ −5%).
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
                bars = [b for b in fetch_minute_bars(self.client, item.code, self.today, "KRX") if b["ts"] < minute_start]
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
                      f"VWAP 위 {f['vwap_share']:.0%} · 신고가 {f['new_highs']}번 · 눌림 {f['pull']:.1f}배 — 반반 매도(+2% 절반, 나머지 15:19)")
            out.append((item.code, item.name, KIND, Signal(sig_ts, KIND, float(f["price"]), float(f["low10"]), float(stop), reason)))
        return out
