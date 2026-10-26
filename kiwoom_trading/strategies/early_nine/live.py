"""🎯 장 초 공통점 — 10-16 사용자가 고른 주도주 9종목이 09:30 에 공통으로 보인 특징을 묶은 규칙 (2026-10-18, 실험용).

9종목: HT로보틱스, 한선엔지니어링, NAVER, 셀트리온, 알테오젠, 한화시스템, 현대차, 한화에어로스페이스, 삼성바이오로직스.
'끝까지 갈 종목'을 맞히려는 규칙이 아니라, 장 초에 보이는 대금·차트·일봉 위치·수급의 공통점이다.

판정 (09:30 한 번, 09:30 전에 마감된 통합 1분봉 기준, 대상 = 전날 대금 상위 200):
- 1분봉 모양: 시가 대비 +2%↑, 갭(시가 ÷ 전일 종가) +4%↓, 신고가 4번↑, 매끄러움 ≥ 0.25, 전일 고가 −1% 위
- 거래대금: 대상 종목 안 대금 순위 40위 안, 09:30 까지 대금 ≥ 20일 평균 하루 대금의 19%
- 일봉: 전일 종가가 5일선 −8% 안
- 수급: 전날 기관 순매수 (9종목 중 8개, 사용자 선택 2026-10-18)

검증 (스크래치 early_common.py, 전날 대금 상위 200, 09:30 판정 → 다음 봉 매수 → 마감, 비용 0.25%):
- 10-16: 131종목 중 11종목 통과 (9종목 전부 + 에이피알·하이브)
- 2025-11-07~2026-04-10: 284건(하루 약 3건), 마감까지 +0.30% (표본 전체 −0.38%), 앞 +0.68% / 뒤 −0.13%, 10:30 까지는 −0.22%
→ 표본보다 낫지만 절대 수익 근거는 약하다. 1년 검증 전까지 실험용.

매도(사용자 2026-10-18): 주도주 모양과 같은 '차트' — 큰 음봉(몸통 평소 3배↑·대금 2배↑)이면 매도, 손절 직전 10분 저가 −0.5%(−2~−5%), 남으면 15:19.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.strategies.leader_shape.live import LeaderShapeConfig, stop_price
from kiwoom_trading.screener.market_data import RankItem

KIND = "장 초 공통점"


@dataclass(frozen=True)
class EarlyNineConfig:
    at: time = time(9, 30)            # 이 시각 전에 마감된 봉으로 판정
    last_check: time = time(9, 36)    # 스캐너가 늦게 돌면 이 시각까지만 판정 (그 뒤는 그날 건너뜀)
    universe: int = 200               # 전날 대금 상위 N
    max_rank: int = 40                # 대상 종목 안 대금 순위
    min_from_open: float = 0.02
    max_gap: float = 0.04
    min_new_highs: int = 4
    min_eff: float = 0.25
    min_vs_prev_high: float = -0.01
    min_value_ratio: float = 0.19     # 09:30 까지 대금 ÷ 20일 평균 하루 대금
    min_daily_ma5: float = -0.08      # 전일 종가 ÷ 5일선 − 1


def load_context(day: date, top: int = 200, db_path: str = DEFAULT_DB_PATH) -> dict[str, dict[str, float]]:
    """day 개장 전에 아는 것: 전날 대금 상위 N 종목의 전일 종가·고가, 5일선, 20일 평균 대금, 전날 기관 순매수."""
    conn = duckdb.connect(db_path, read_only=True)
    try:
        prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE date < ?", [day]).fetchone()[0]
        rows = conn.execute(
            """
            WITH u AS (SELECT code FROM (SELECT code, rank() OVER (ORDER BY value DESC) rk FROM daily_ohlcv
                                         WHERE date = ? AND value > 0) WHERE rk <= ?),
                 d AS (SELECT o.code, o.date, o.high, o.close, o.value,
                              row_number() OVER (PARTITION BY o.code ORDER BY o.date DESC) rn
                       FROM daily_ohlcv o JOIN u USING (code) WHERE o.date <= ?)
            SELECT d.code,
                   max(close) FILTER (WHERE rn = 1), max(high) FILTER (WHERE rn = 1),
                   avg(close) FILTER (WHERE rn <= 5), avg(value) FILTER (WHERE rn <= 20),
                   max(i.institution)
            FROM d LEFT JOIN investor_daily i ON i.code = d.code AND i.date = ?
            WHERE rn <= 20 GROUP BY d.code
            """, [prev, top, prev, prev]).fetchall()
    finally:
        conn.close()
    return {c: {"prev_close": pc, "prev_high": ph, "ma5": ma5, "v20": v20, "inst1": inst or 0}
            for c, pc, ph, ma5, v20, inst in rows if pc and ph and ma5 and v20}


def features(bars: list[dict[str, Any]], ctx: dict[str, float]) -> Optional[dict[str, float]]:
    """09:00 부터 판정 시각 전까지 마감된 1분봉(시간순)으로 특징. 09:02 넘어 시작하거나 5봉 미만이면 None."""
    up = [b for b in bars if b["ts"].time() >= time(9, 0)]
    if len(up) < 5 or up[0]["ts"].time() > time(9, 2):
        return None
    o, pc = up[0]["open"], ctx["prev_close"]
    cl = [b["close"] for b in up]
    p = cl[-1]
    run, new_highs = up[0]["high"], 0
    for b in up[1:]:
        if b["high"] > run:
            run, new_highs = b["high"], new_highs + 1
    moves = sum(abs(cl[k] - cl[k - 1]) for k in range(1, len(cl))) + abs(cl[0] - o)
    return {
        "price": p, "gap": o / pc - 1, "from_open": p / o - 1, "new_highs": new_highs,
        "eff": (p - o) / moves if moves else 0.0, "vs_prev_high": p / ctx["prev_high"] - 1,
        "value_ratio": sum(b["close"] * b["volume"] for b in up) / ctx["v20"],
        "daily_ma5": pc / ctx["ma5"] - 1, "inst1": ctx["inst1"],
        "low10": min(b["low"] for b in up[-10:]),
    }


def failed(f: dict[str, float], rank: int, cfg: EarlyNineConfig) -> Optional[str]:
    """통과하면 None, 아니면 첫 번째로 걸린 조건."""
    checks = [
        (rank <= cfg.max_rank, f"대상 안 대금 {rank}위"),
        (f["gap"] <= cfg.max_gap, f"갭 {f['gap']:+.1%}"),
        (f["from_open"] >= cfg.min_from_open, f"시가 대비 {f['from_open']:+.1%}"),
        (f["new_highs"] >= cfg.min_new_highs, f"신고가 {f['new_highs']}번"),
        (f["eff"] >= cfg.min_eff, f"매끄러움 {f['eff']:.2f}"),
        (f["vs_prev_high"] >= cfg.min_vs_prev_high, f"전일 고가 대비 {f['vs_prev_high']:+.1%}"),
        (f["value_ratio"] >= cfg.min_value_ratio, f"대금 평소 하루의 {f['value_ratio']:.0%}"),
        (f["daily_ma5"] >= cfg.min_daily_ma5, f"5일선 대비 {f['daily_ma5']:+.1%}"),
        (f["inst1"] > 0, f"전날 기관 {f['inst1'] / 1e8:+,.0f}억"),
    ]
    return next((why for ok, why in checks if not ok), None)


class EarlyNineWatcher:
    """09:30 에 한 번: 전날 대금 상위 200 중 지금 대금 40위 안 종목의 통합 1분봉으로 판정 → 신호 (종목당 하루 1번)."""

    def __init__(self, client: KiwoomDailyClient, today: date, context: Optional[dict[str, dict[str, float]]] = None,
                 config: Optional[EarlyNineConfig] = None, done: Optional[set[str]] = None) -> None:
        self.client = client
        self.today = today
        self.config = config or EarlyNineConfig()
        self.context = context if context is not None else load_context(today, self.config.universe)
        self.done: set[str] = set(done or ())
        self.checked = False

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        cfg = self.config
        if self.checked or not (cfg.at <= now.time() <= cfg.last_check):
            return []
        self.checked = True
        cutoff = datetime.combine(self.today, cfg.at)
        ranked = [item for item in sorted(value_top, key=lambda x: x.rank) if item.code in self.context]
        out, misses = [], []
        for rank, item in enumerate(ranked[:cfg.max_rank], 1):
            if item.code in self.done:
                continue
            ctx = self.context[item.code]
            try:
                bars = [b for b in fetch_minute_bars(self.client, item.code, self.today, "AL") if b["ts"] < cutoff]
            except Exception as exc:
                logging.warning("장 초 공통점 1분봉 조회 실패 %s: %s", item.code, exc)
                continue
            f = features(bars, ctx)
            if f is None:
                continue
            why = failed(f, rank, cfg)
            if why:
                misses.append(f"{item.name}({why})")
                continue
            self.done.add(item.code)
            stop = stop_price(f["price"], f["low10"], LeaderShapeConfig())
            reason = (f"대상 안 대금 {rank}위(평소 하루의 {f['value_ratio']:.0%}) · 시가 대비 {f['from_open']:+.1%}(갭 {f['gap']:+.1%}) · "
                      f"신고가 {f['new_highs']}번 · 매끄러움 {f['eff']:.2f} · 전일 고가 대비 {f['vs_prev_high']:+.1%} · "
                      f"5일선 대비 {f['daily_ma5']:+.1%} · 전날 기관 {f['inst1'] / 1e8:+,.0f}억 — 매도: 큰 음봉 또는 손절, 남으면 15:19")
            out.append((item.code, item.name, KIND, Signal(bars[-1]["ts"], KIND, float(f["price"]), float(f["low10"]), float(stop), reason)))
        logging.info("장 초 공통점 판정: 대상 %s종목 중 상위 %s 확인 → 통과 %s | 탈락 %s", len(ranked), min(len(ranked), cfg.max_rank),
                     ", ".join(n for _, n, _, _ in out) or "없음", ", ".join(misses[:15]))
        return out
