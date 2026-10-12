"""주도주 스크리너 조건 판정 (API 호출 없는 순수 로직).

필수: ① 시장 관심  ② 거래대금·변동성  ⑥ 진입/손절 시나리오
선택: ③ 비슷한 종목 동반(테마)  ④ 재료 연속성  ⑤ 신고가·의미 있는 가격대  → min_optional 개 이상
"""
from dataclasses import dataclass, field
from typing import Optional

from kiwoom_trading.screener.history import HistStats
from kiwoom_trading.screener.market_data import Theme


@dataclass(frozen=True)
class ScreenerConfig:
    # ① 관심
    max_search_rank: int = 20               # 실시간 조회 순위 이내
    max_value_rank: int = 50                # 거래대금 순위 이내
    # ② 거래대금·변동성
    min_trade_value: int = 50_000_000_000   # 500억
    min_change_rate: float = 0.03           # 당일 +3% 이상
    min_day_range: float = 0.06             # 당일 진폭 (고가-저가)/전일종가
    min_atr_pct: float = 0.04               # 또는 최근 14일 ATR%
    # ③ 테마 동반
    min_theme_change: float = 0.02          # 테마 등락률 +2% 이상
    min_theme_rising_ratio: float = 0.6     # 테마 종목 60% 이상 상승
    min_theme_members: int = 3
    peer_min_change: float = 0.05           # 업종 동반: 같은 업종에서 +5% 이상 오른 종목이
    min_peers: int = 2                      #           2개 이상 (키움 테마에 없는 종목 보완)
    # ④ 재료 연속성
    continuity_days_needed: int = 2         # 최근 3일 중 거래대금 상위 일수
    min_close_position: float = 0.6         # (현재가-저가)/(고가-저가): 고가권 유지
    # ⑤ 가격 위치
    near_high_ratio: float = 0.97           # 250일 고가의 97% 이상
    # ⑥ 시나리오
    min_stop_pct: float = 0.015
    max_stop_pct: float = 0.08
    reward_risk: float = 2.0                # 목표가 = 진입 + 위험폭 × 2
    # 판정
    min_optional: int = 2


@dataclass
class Candidate:
    code: str
    name: str
    price: int
    open: int
    high: int
    low: int
    prev_close: int
    trade_value: int
    hist: Optional[HistStats]
    search_rank: Optional[int] = None
    value_rank: Optional[int] = None
    themes: list[Theme] = field(default_factory=list)
    sector: Optional[str] = None
    peers: list[str] = field(default_factory=list)   # 같은 업종에서 함께 강하게 오른 종목 이름 (자기 제외)

    @property
    def change_rate(self) -> float:
        return self.price / self.prev_close - 1 if self.prev_close else 0.0


@dataclass(frozen=True)
class Scenario:
    name: str            # '눌림' / '돌파'
    entry: float
    stop: float
    target: float

    @property
    def stop_pct(self) -> float:
        return 1 - self.stop / self.entry


@dataclass
class Evaluation:
    candidate: Candidate
    checks: dict[str, tuple[bool, str]]
    scenarios: list[Scenario]
    best_theme: Optional[Theme]

    REQUIRED = ("관심", "거래대금·변동성", "시나리오")
    OPTIONAL = ("테마 동반", "재료 연속성", "가격 위치")

    def optional_passed(self) -> int:
        return sum(self.checks[k][0] for k in self.OPTIONAL)

    def passed(self, config: ScreenerConfig) -> bool:
        return all(self.checks[k][0] for k in self.REQUIRED) and self.optional_passed() >= config.min_optional

    @property
    def score(self) -> int:
        return sum(ok for ok, _ in self.checks.values())


def build_scenarios(c: Candidate, config: ScreenerConfig) -> list[Scenario]:
    """다음 날(또는 장중 이후) 진입 시나리오. 손절 폭이 [min, max] 안에 드는 것만."""
    raw = [
        ("눌림", (c.open + c.price) / 2, c.low),       # 몸통 중간까지 눌리면 진입, 당일 저가 이탈 손절
        ("돌파", c.high, c.price),                    # 당일 고가 돌파 진입, 당일 종가(현재가) 이탈 손절
    ]
    out = []
    for name, entry, stop in raw:
        if entry <= 0 or stop >= entry:
            continue
        risk = entry - stop
        scenario = Scenario(name, entry, stop, entry + risk * config.reward_risk)
        if config.min_stop_pct <= scenario.stop_pct <= config.max_stop_pct:
            out.append(scenario)
    return out


def evaluate(c: Candidate, config: ScreenerConfig) -> Evaluation:
    checks: dict[str, tuple[bool, str]] = {}
    h = c.hist

    # ① 관심
    attn = []
    if c.search_rank and c.search_rank <= config.max_search_rank:
        attn.append(f"조회 {c.search_rank}위")
    if c.value_rank and c.value_rank <= config.max_value_rank:
        attn.append(f"대금 {c.value_rank}위")
    checks["관심"] = (bool(attn), ", ".join(attn) or "순위 밖")

    # ② 거래대금·변동성
    day_range = (c.high - c.low) / c.prev_close if c.prev_close else 0
    atr = h.atr14_pct if h else None
    vol_ok = day_range >= config.min_day_range or (atr is not None and atr >= config.min_atr_pct)
    ok2 = c.trade_value >= config.min_trade_value and c.change_rate >= config.min_change_rate and vol_ok
    checks["거래대금·변동성"] = (ok2, f"대금 {c.trade_value / 1e8:,.0f}억, {c.change_rate:+.1%}, 진폭 {day_range:.1%}"
                                   + (f", ATR {atr:.1%}" if atr is not None else ""))

    # ③ 테마 동반
    good = [
        t for t in c.themes
        if t.members >= config.min_theme_members and t.change_rate is not None
        and t.change_rate >= config.min_theme_change and t.rising / t.members >= config.min_theme_rising_ratio
    ]
    best = max(good or c.themes, key=lambda t: t.change_rate if t.change_rate is not None else -9, default=None)
    parts = []
    if best and best.change_rate is not None:
        parts.append(f"테마 {best.name} {best.change_rate:+.1%} (상승 {best.rising}/{best.members})")
    if c.peers:
        parts.append(f"업종 {c.sector} 동반 {len(c.peers)}종목({', '.join(c.peers[:3])})")
    checks["테마 동반"] = (bool(good) or len(c.peers) >= config.min_peers, " / ".join(parts) or "테마·업종 동반 없음")

    # ④ 재료 연속성: 최근 3일 중 거래대금 상위 일수 + 고가권 마감
    top_days = sum(
        1 for r in (c.value_rank, h.value_rank_1 if h else None, h.value_rank_2 if h else None)
        if r is not None and r <= config.max_value_rank
    )
    position = (c.price - c.low) / (c.high - c.low) if c.high > c.low else 1.0
    ok4 = top_days >= config.continuity_days_needed and position >= config.min_close_position
    checks["재료 연속성"] = (ok4, f"3일 중 대금 상위 {top_days}일, 고가권 위치 {position:.0%}")

    # ⑤ 가격 위치: 250일 신고가 근처 또는 60일 고가 돌파
    reasons = []
    if h and h.prior_high_250:
        high_250 = max(h.prior_high_250, c.high)
        if c.price >= high_250 * config.near_high_ratio:
            reasons.append("신고가" if c.high >= h.prior_high_250 else f"250일 고가 {c.price / high_250 - 1:+.1%}")
    if h and h.prior_high_60 and c.price > h.prior_high_60:
        reasons.append("60일 고가 돌파")
    checks["가격 위치"] = (bool(reasons), ", ".join(reasons) or "고가권 아님")

    # ⑥ 시나리오
    scenarios = build_scenarios(c, config)
    checks["시나리오"] = (
        bool(scenarios),
        " / ".join(f"{s.name} 손절 -{s.stop_pct:.1%}" for s in scenarios) or f"손절 폭이 {config.min_stop_pct:.1%}~{config.max_stop_pct:.0%} 밖",
    )
    return Evaluation(c, checks, scenarios, best)


def format_evaluation(e: Evaluation) -> str:
    c = e.candidate
    mark = lambda ok: "✔" if ok else "✖"  # noqa: E731
    lines = [
        f"{c.name}({c.code}) {c.price:,} ({c.change_rate:+.1%}) 대금 {c.trade_value / 1e8:,.0f}억 | 점수 {e.score}/6",
        "  " + " ".join(f"{mark(ok)}{k}" for k, (ok, _) in e.checks.items()),
    ]
    for key in ("관심", "테마 동반", "재료 연속성", "가격 위치"):
        lines.append(f"  · {key}: {e.checks[key][1]}")
    for s in e.scenarios:
        lines.append(f"  ▶ {s.name}: 진입 {s.entry:,.0f} / 손절 {s.stop:,.0f} (-{s.stop_pct:.1%}) / 목표 {s.target:,.0f}")
    return "\n".join(lines)
