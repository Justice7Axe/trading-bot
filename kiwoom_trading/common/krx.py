"""KRX 가격 규칙 — 호가 단위·상한가 (백테스트·실시간 공용, docs/architecture.md 3단계)."""


def tick_size(price: float) -> int:
    """KRX 호가 단위 (2023-01-25 부터, 코스피·코스닥 같음)."""
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if price < lim:
            return t
    return 1000


def upper_limit(base: float) -> int:
    """상한가 = 기준가 × 1.3 을 그 가격대 호가 단위로 내림. 예: 루닛 2026-10-26 기준가 11,300 → 14,690."""
    raw = base * 1.3
    t = tick_size(raw)
    return int(raw // t * t)
