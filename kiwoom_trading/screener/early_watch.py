"""두산테스나형 종목을 '일찍' 감시 목록에 올리는 조기 발굴 로직.

매수 신호(1분봉 지지 반등 / 돌파 후 눌림)가 진입을 거르는 최종 필터이므로, 감시 목록은 넓고 빠르게 잡는다.

  ① 쉬어 가는 주도주 (장 마감 후 선정 → 관심 종목으로 최대 20거래일 감시, 쉬는 날 종가 -20% 이탈 시 해제) — find_rest_leaders
     최근 10거래일 +20%↑ 강하게 오른 뒤, 오늘은 -3%~+3% 로 쉬었지만 거래대금 순위 50위 이내 유지,
     최근 5일 중 하루 이상 거래대금 1,000억↑, 오늘 대금 ≥ 5일 최대의 50%, 종가가 10일 고가의 90%↑ (고점 근처에서 쉼)
     (두산테스나 10-12: 10일 +33%, +0.3%, 대금 887억 = 49위 = 5일 최대 1,266억의 70%, 고가 대비 92%)
     쉬는 기간은 천차만별: 20일 안에 재점화(+8%↑ 일)한 85% 중 첫날이 D+1 20%, D+2~3 25%, D+4~5 16%, D+6~10 22%, D+11~20 18%
     → 날짜를 정하지 않고 관심 종목으로 두고 1분봉 매수 패턴이 나올 때 신호. 해제 -20% 는 재점화의 78/85 를 지키며 21% 를 정리
  ② 조회 급등 (장중) — 실시간 조회 순위(1분) 10위 이내 + 하락 중 아님 + KRX 거래대금 순위 50위 이내
     (프리마켓 08:00~09:00 에는 KRX 대금이 없으므로 +3%↑ 로 대신)
  ③ 거래대금 가속 (장중 09:05~14:30) — 오늘의 주도주 '포착'용 (매수 신호 아님). 상세: accel_trigger 참고
     최근 5분 KRX 대금 ≥ 300억, 시간대 보정 평소 5분 대금의 5배↑, 5분 가격 +1%↑, 당일 하락 아님
  ⑤ 조기 주도주 (장중 09:00~09:15) — KRX 누적 대금 500억 & +3% 를 09:15 이전에 달성
     25일 × 대금 상위 200 검증(09:15): 하루 약 9종목, 그날 주도주(대금 30위 & +5%) 정밀도 38%(앞 31%/뒤 45%), 주도주의 39% 포착.
     이후 장중 외국인 잠정치(09:20 무렵 첫 갱신)·기관 잠정치(09:50 무렵)로 수급 확인 → 🏁✅ (gate_flow.py 로 누적 검증)
     같은 관문을 하루 중 아무 때나 통과하면 정밀도 15% → '얼마나 일찍 통과했나'가 핵심. 주도주 통과 중앙 09:22, 비주도 11:04
  ④ 프리마켓 주목 (08:50 1회 요약) — 08:00~08:50 조회 순위(1분) 20위 안에 3번↑ 오른 종목 + 쉬는 주도주의 프리마켓 갭

10-13 재생: 두산테스나 ② 09:25, ③ 09:28 → 첫 매수 타점 10:41 보다 1시간 이상 앞섬 (기존 스크리너는 18:46).
"""
import logging
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

import duckdb

from kiwoom_trading.screener.history import HistStats
from kiwoom_trading.screener.market_data import KiwoomMarket, RankItem


# ------------------------------------------------------------------ ① 쉬어 가는 주도주
@dataclass(frozen=True)
class RestLeaderConfig:
    min_run_10d: float = 0.20            # 10거래일 전 종가 대비 +20%↑
    min_peak_value_5d: int = 100_000_000_000   # 최근 5일(오늘 포함) 중 거래대금 1,000억↑ 인 날
    max_abs_change: float = 0.03         # 오늘 등락 -3%~+3% (쉬는 날)
    min_value_vs_peak: float = 0.5       # 오늘 대금 ≥ 5일 최대 대금 × 0.5
    min_close_vs_high10: float = 0.9     # 종가 ≥ 10일 고가 × 0.9
    max_value_rank: int = 50             # 오늘 거래대금 순위 50위 이내 (전 종목 중)


@dataclass(frozen=True)
class RestLeader:
    code: str
    name: str
    close: int
    change: float
    run_10d: float
    value: int
    peak_value_5d: int
    close_vs_high10: float
    sector: Optional[str]
    value_rank: int

    @property
    def reason(self) -> str:
        return (f"10일 {self.run_10d:+.0%}, 오늘 {self.change:+.1%} 쉼, 대금 {self.value / 1e8:,.0f}억 {self.value_rank}위"
                f"(5일 최대 {self.peak_value_5d / 1e8:,.0f}억의 {self.value / self.peak_value_5d:.0%}), 10일 고가 대비 {self.close_vs_high10 - 1:+.1%}")


def find_rest_leaders(conn: duckdb.DuckDBPyConnection, day: date, config: Optional[RestLeaderConfig] = None) -> list[RestLeader]:
    """day 의 확정 일봉 기준 '쉬어 가는 주도주' (다음 거래일 매수 신호 감시 대상)."""
    cfg = config or RestLeaderConfig()
    rows = conn.execute(
        """
        WITH d AS (
            SELECT o.code, o.date, o.high, o.close, o.value,
                   rank() OVER (PARTITION BY o.date ORDER BY o.value DESC) AS value_rank,
                   lag(o.close) OVER w AS prev_close,
                   lag(o.close, 10) OVER w AS close_10,
                   max(o.value) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS peak_value_5d,
                   max(o.high) OVER (w ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS high_10
            FROM daily_ohlcv o JOIN stocks s USING (code)
            WHERE NOT s.delisted AND o.date <= ? AND o.date >= ? - INTERVAL 40 DAY
            WINDOW w AS (PARTITION BY o.code ORDER BY o.date)
        )
        SELECT d.code, s.name, d.close, d.close / d.prev_close - 1, d.close / d.close_10 - 1, d.value, d.peak_value_5d,
               d.close / d.high_10, s.sector, d.value_rank
        FROM d JOIN stocks s USING (code)
        WHERE d.date = ? AND d.prev_close > 0 AND d.close_10 > 0
          AND d.close / d.close_10 - 1 >= ?
          AND d.peak_value_5d >= ?
          AND abs(d.close / d.prev_close - 1) <= ?
          AND d.value >= d.peak_value_5d * ?
          AND d.close >= d.high_10 * ?
          AND d.value_rank <= ?
        ORDER BY d.value DESC
        """,
        [day, day, day, cfg.min_run_10d, cfg.min_peak_value_5d, cfg.max_abs_change,
         cfg.min_value_vs_peak, cfg.min_close_vs_high10, cfg.max_value_rank],
    ).fetchall()
    return [RestLeader(*r) for r in rows]


REST_HOLD_DAYS = 20       # 관심 종목 유지 기간 상한 (재점화의 40% 가 D+6~D+20 — 2년 일봉 검증)
REST_MAX_DROP = 0.20      # 최근 종가가 쉬는 날 종가 대비 -20% 아래면 이탈로 보고 해제 (-10% 는 재점화 1/4 을 놓침)


def active_rest_leaders(store, day: date, hold_days: int = REST_HOLD_DAYS, max_drop: float = REST_MAX_DROP,
                        db_path: Optional[str] = None) -> dict[str, tuple[str, int]]:
    """day 에 감시할 쉬어 가는 주도주: day 이전 hold_days 거래일 안에 뽑혔고, 아직 이탈하지 않은 종목.

    반환: 코드 → (이름, 쉬는 날 이후 경과 거래일 1~hold_days)
    """
    from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH

    try:
        conn = duckdb.connect(db_path or DEFAULT_DB_PATH, read_only=True)
        try:
            days = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM daily_ohlcv WHERE date < ? ORDER BY date DESC LIMIT ?", [day, hold_days]).fetchall()]
            last_close = dict(conn.execute(
                "SELECT code, arg_max(close, date) FROM daily_ohlcv WHERE date < ? AND date >= ? GROUP BY code",
                [day, days[-1] if days else day]).fetchall())
        finally:
            conn.close()
    except duckdb.Error as exc:   # 일봉 DB 가 잠겨 있으면 이탈 판정 없이 최근 기준일만으로
        logging.warning("쉬는 주도주 이탈 판정 생략 (일봉 DB 접근 실패): %s", exc)
        days, last_close = [], {}
    if not days:
        row = store.conn.execute("SELECT max(date) FROM rest_leaders WHERE date < ?", [day]).fetchone()
        days = [row[0]] if row and row[0] else []
    if not days:
        return {}
    out: dict[str, tuple[str, int]] = {}
    for d, code, name, close in store.rest_leaders_since(days[-1], day):
        if code in out:
            continue                       # 여러 번 뽑혔으면 가장 최근 쉬는 날 기준
        latest = last_close.get(code)
        if latest is not None and close and latest < close * (1 - max_drop):
            continue
        out[code] = (name, days.index(d) + 1 if d in days else 1)
    return out


def format_rest_leaders(leaders: list[RestLeader]) -> str:
    lines = [f"😴 쉬어 가는 주도주 {len(leaders)}종목 — 관심 종목 등록 → 최대 {REST_HOLD_DAYS}거래일 1분봉 매수 패턴 감시",
             "조건: 10일 +20%↑ · 5일 내 대금 1,000억↑ · 오늘 ±3% 쉼 · 대금 50위·유지 50%↑ · 10일 고가 90%↑"]
    if not leaders:
        lines.append("해당 없음")
    for x in leaders:
        lines.append(f"· {x.name}({x.code}) {x.close:,} — {x.reason}" + (f" [{x.sector}]" if x.sector else ""))
    return "\n".join(lines)


# ------------------------------------------------------------------ ③ 거래대금 가속
# KRX 정규장 5분 구간별 시장 거래대금 비중(‰): 09:00~09:05 가 7.5%, 점심 무렵 0.7%, 장 마감 전 1.6%.
# 2025-10~2026-10 표본 25일 × 대금 상위 200 종목 1분봉으로 계산. 평평한 기준(390분 균등)은 장 초반을 과대평가한다.
VALUE_PROFILE_5M = (75.31, 38.55, 33.64, 28.88, 25.14, 23.0, 22.46, 20.17, 19.16, 18.82, 17.23, 16.93, 16.86, 15.35, 13.7, 13.48, 12.92, 12.64, 13.13, 12.24, 11.93, 12.38, 12.13, 11.85, 11.07, 10.8, 10.27, 10.02, 9.36, 9.49, 9.45, 8.57, 7.89, 8.02, 7.44, 7.53, 7.93, 7.35, 7.2, 7.09, 7.45, 7.0, 7.56, 7.27, 7.06, 7.51, 7.76, 7.67, 8.43, 8.2, 9.0, 8.9, 8.87, 8.91, 9.33, 9.71, 8.85, 8.93, 9.52, 10.2, 10.67, 10.58, 10.47, 10.07, 10.56, 10.16, 11.48, 12.33, 12.22, 12.26, 12.77, 12.49, 13.89, 14.3, 14.17, 16.05, 0.0, 0.0)


def usual_value(avg_value_20: float, end: time, minutes: int = 5) -> float:
    """20일 평균 대금 × (end 직전 minutes 분의 시간대 비중) = 이 시간대의 '평소' 대금."""
    m_end = (end.hour - 9) * 60 + end.minute          # end 분 봉까지 포함
    share = 0.0
    for m in range(m_end - minutes + 1, m_end + 1):
        if 0 <= m < 390:
            share += VALUE_PROFILE_5M[m // 5] / 1000 / 5
    return avg_value_20 * share


def accel_trigger(value_5m: float, price: Optional[int], price_5m_ago: Optional[int], change_rate: Optional[float],
                  avg_value_20: float, now: time, config: Optional["EarlyConfig"] = None) -> Optional[str]:
    """거래대금 가속 판정 (조건을 모두 만족하면 사유 문자열, 아니면 None).

    1) 최근 5분 KRX 거래대금 ≥ 300억                     — 절대 규모: 진짜 주도주만 (50억이면 하루 50건, 최종 50위 46%)
    2) 최근 5분 대금 ≥ 시간대 보정 평소 5분 대금 × 5       — 그 종목 기준으로도 이례적
    3) 5분 전 대비 가격 +1%↑                             — 매도 폭주가 아니라 매수 쪽 가속
    4) 당일 등락 ≥ 0%                                    — 하락 중인 종목 제외
    검증(25일 표본): 하루 약 6건, 그날 최종 대금 50위 적중 95%.
    단, 트리거 시점 매수는 손실(당일 종가 청산 -1.6%) → '오늘의 주도주 포착'으로만 쓰고 진입은 별도 신호로.
    """
    cfg = config or EarlyConfig()
    if value_5m < cfg.accel_min_value or not price or not price_5m_ago or change_rate is None or change_rate < 0:
        return None
    usual = usual_value(avg_value_20, now, cfg.accel_minutes)
    momentum = price / price_5m_ago - 1
    if usual <= 0 or value_5m < usual * cfg.accel_mult or momentum < cfg.accel_min_momentum:
        return None
    return (f"최근 {cfg.accel_minutes}분 대금 {value_5m / 1e8:,.0f}억 = 이 시간대 평소의 {value_5m / usual:,.0f}배, "
            f"5분 {momentum:+.1%}, 당일 {change_rate:+.1%}")


# ------------------------------------------------------------------ ②③④ 장중 조기 트리거
@dataclass(frozen=True)
class EarlyConfig:
    # ② 조회 급등
    max_search_rank: int = 10
    max_value_rank: int = 50                    # KRX 누적 대금 순위 50위 이내 (09:00 이후)
    premarket_min_change: float = 0.03          # 프리마켓은 +3%↑ 로 대신
    # ③ 거래대금 가속
    accel_minutes: int = 5
    accel_min_value: int = 30_000_000_000       # 최근 5분 대금 300억↑ (최종 대금 50위 적중 95%)
    accel_mult: float = 5.0                     # 시간대 보정 평소 5분 대금의 5배↑
    accel_min_momentum: float = 0.01            # 5분 전 대비 가격 +1%↑ (매수 쪽 가속만)
    accel_start: time = time(9, 5)
    accel_end: time = time(14, 30)
    # ④ 프리마켓 요약
    premarket_end: time = time(9, 0)
    premarket_summary_at: time = time(8, 50)
    premarket_rank: int = 20
    premarket_min_hits: int = 3
    # ⑤ 조기 주도주 (이른 관문 통과)
    gate_value: int = 50_000_000_000            # KRX 누적 대금 500억
    gate_change: float = 0.03                   # +3%
    gate_deadline: time = time(9, 15)           # 이 시각까지 통과한 종목만 (사용자 요청 2026-10-14: 09:20 → 09:15)
    # 공통
    max_watch_adds: int = 60                    # 하루 조기 감시 추가 상한 (1분봉 조회 부담)


@dataclass(frozen=True)
class EarlyHit:
    code: str
    name: str
    source: str          # '조회 급등' | '대금 가속' | '프리마켓 주목'
    reason: str


class EarlyDetector:
    def __init__(self, hist: dict[str, HistStats], names: dict[str, str], config: Optional[EarlyConfig] = None) -> None:
        self.hist = hist
        self.names = names
        self.config = config or EarlyConfig()
        self._values: dict[str, deque] = {}       # code → deque[(ts, KRX 누적 대금)]
        self.premarket_hits: dict[str, int] = {}

    def update(self, now: datetime, search_1m: list[RankItem], value_top: list[RankItem]) -> list[EarlyHit]:
        """매 주기 호출. 조건을 만족한 종목(중복 포함, 호출 측에서 걸러냄)."""
        cfg = self.config
        t = now.time()
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        values = {i.code: i for i in value_top if i.trade_value is not None}
        hits: list[EarlyHit] = []

        # ④ 프리마켓 조회 순위 누적
        if t < cfg.premarket_end:
            for item in search_1m:
                if item.rank <= cfg.premarket_rank and item.code in self.names:
                    self.premarket_hits[item.code] = self.premarket_hits.get(item.code, 0) + 1

        # ② 조회 급등
        for item in search_1m:
            if item.rank > cfg.max_search_rank or item.code not in self.names or item.change_rate is None:
                continue
            if t < cfg.premarket_end:
                if item.change_rate >= cfg.premarket_min_change:
                    hits.append(EarlyHit(item.code, self.names[item.code], "조회 급등",
                                         f"프리마켓 조회 {item.rank}위, {item.change_rate:+.1%}"))
                continue
            v = values.get(item.code)
            if item.change_rate >= 0 and v and v.rank <= cfg.max_value_rank:
                hits.append(EarlyHit(item.code, self.names[item.code], "조회 급등",
                                     f"조회 {item.rank}위, {item.change_rate:+.1%}, 대금 {v.trade_value / 1e8:,.0f}억({v.rank}위)"))

        # ⑤ 조기 주도주: 09:20 이전에 누적 대금 500억 & +3%
        if cfg.premarket_end <= t.replace(second=0, microsecond=0) <= cfg.gate_deadline:   # 09:15분 스냅샷까지 포함
            for code, v in values.items():
                if code in self.names and v.trade_value >= cfg.gate_value and (v.change_rate or 0) >= cfg.gate_change:
                    h = self.hist.get(code)
                    tags = []
                    if h and h.value_rank_1 and h.value_rank_1 <= 50:
                        tags.append(f"전일 대금 {h.value_rank_1}위")
                    hits.append(EarlyHit(code, self.names[code], "조기 주도주",
                                         f"{t:%H:%M} 누적 대금 {v.trade_value / 1e8:,.0f}억({v.rank}위), {v.change_rate:+.1%}"
                                         + (f" · {' · '.join(tags)}" if tags else "")))

        # ③ 거래대금 가속 (KRX 누적 대금·가격 스냅샷의 5분 차이)
        for code, v in values.items():
            q = self._values.setdefault(code, deque())
            q.append((minute, v.trade_value, v.price))
            while q and q[0][0] < minute - timedelta(minutes=cfg.accel_minutes + 5):
                q.popleft()
            if not (cfg.accel_start <= t <= cfg.accel_end) or code not in self.names:
                continue
            past = [(val, px) for ts, val, px in q if ts <= minute - timedelta(minutes=cfg.accel_minutes)]
            h = self.hist.get(code)
            if not past or not h or not h.avg_value_20:
                continue
            reason = accel_trigger(v.trade_value - past[-1][0], v.price, past[-1][1], v.change_rate, h.avg_value_20, minute.time(), cfg)
            if reason:
                hits.append(EarlyHit(code, self.names[code], "대금 가속", reason))
        return hits

    def premarket_focus(self, market: KiwoomMarket, rest: dict[str, str]) -> list[EarlyHit]:
        """④ 08:50 프리마켓 주목: 조회 순위 반복 상위 + 쉬는 주도주 — 통합(NXT) 시세로 갭/프리마켓 대금 표시."""
        cfg = self.config
        codes = [c for c, n in sorted(self.premarket_hits.items(), key=lambda x: -x[1]) if n >= cfg.premarket_min_hits]
        codes += [c for c in rest if c not in codes]
        out = []
        for code in codes:
            try:
                q = market.quote(code)
            except Exception as exc:
                logging.warning("프리마켓 시세 조회 실패 %s: %s", code, exc)
                continue
            if not q or not q.base_price:
                continue
            tags = []
            if code in rest:
                tags.append("쉬는 주도주")
            if self.premarket_hits.get(code, 0) >= cfg.premarket_min_hits:
                tags.append(f"조회 20위 안 {self.premarket_hits[code]}회")
            out.append(EarlyHit(code, self.names.get(code, q.name), "프리마켓 주목",
                                f"{' · '.join(tags)} | 갭 {q.price / q.base_price - 1:+.1%}, 프리마켓 대금 {q.volume * q.price / 1e8:,.0f}억"))
        return out


def format_premarket(now: datetime, hits: list[EarlyHit]) -> str:
    lines = [f"🌅 프리마켓 주목 {now:%H:%M} ({len(hits)}종목) — 09:00 부터 1분봉 매수 신호 감시"]
    lines += [f"· {h.name}({h.code}) {h.reason}" for h in hits] or ["해당 없음"]
    return "\n".join(lines)


def format_watch_adds(now: datetime, adds: list[EarlyHit]) -> str:
    lines = [f"👀 조기 감시 추가 ~{now:%H:%M} ({len(adds)}종목) — 매수 신호가 나오면 🎯 로 알림"]
    lines += [f"· {h.name}({h.code}) [{h.source}] {h.reason}" for h in adds]
    return "\n".join(lines)
