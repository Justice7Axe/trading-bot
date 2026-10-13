"""1분봉 매수 타점: 박스권 50% 지지 반등 / 박스 상단 돌파 후 눌림.

두산테스나 2026-10-13 차트의 매수 동그라미를 정형화한 것.
  ① 지지 반등: 당일 저점(L)과 박스 고점(H)의 중간값 S = (L+H)/2 까지 눌렸다가 버티는 봉
     - 박스 확정: H 를 만든 뒤 box_age_bars 분 동안 H 를 넘지 못함, 박스 폭 (H-L)/L ≥ min_box_pct
       (H 는 KRX 정규장 09:00 이후 고가로 잡는다 — 프리마켓의 얇은 박스는 제외. L 은 당일 전체 저가)
     - 터치: 저가 ≤ S×(1+touch_tol), 저가 ≥ S×(1-max_pierce) (너무 깊게 깨지면 지지 실패)
     - 지지 확인: 종가 > S (선을 지키고 마감)
     - 같은 눌림에서 중복 신호 금지: 신호 후 고가가 S×(1+reset_pct) 를 넘어야 다음 터치 인정
  ② 돌파 후 눌림: 종가가 H 를 넘고 거래량이 직전 20분 평균의 vol_mult 배 이상 → 돌파 확정
     - 이후 retest_window 분 안에 저가가 돌파선 H 근처(H×(1+touch_tol) 이하)까지 눌림
       (직전 봉에서 눌렸어도 됨, 단 H×(1-max_retest_drop) 아래로는 깨지지 않음)
     - 양봉(종가 > 시가)이 돌파선 위(종가 ≥ H)에서 마감하면 매수 → '눌렸다가 돌파선을 되찾는' 봉
     - 같은 눌림 중복 금지: 신호 후 고가가 신호가×(1+breakout_reset_pct) 를 넘어야 다음 눌림 인정
"""
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Optional


@dataclass(frozen=True)
class SignalConfig:
    box_age_bars: int = 30          # 박스 고점 이후 최소 경과 분
    min_box_pct: float = 0.05       # 박스 폭 (H-L)/L 최소 5%
    support_ratio: float = 0.5      # 지지선 = L + (H-L) × 0.5
    touch_tol: float = 0.001        # 지지선/돌파선 +0.1% 이내로 내려오면 터치
    max_pierce: float = 0.008       # 지지선 -0.8% 넘게 깨지면 지지 실패
    reset_pct: float = 0.015        # 지지 반등: 다음 터치로 인정하려면 +1.5% 이상 반등했다 와야 함
    breakout_reset_pct: float = 0.008  # 돌파 후 눌림: 다음 눌림 인정 조건 (신호가 +0.8%)
    box_start: time = time(9, 0)    # 박스 고점은 KRX 정규장부터
    vol_mult: float = 3.0           # 돌파 봉 거래량 ≥ 직전 20분 평균 × 3
    vol_lookback: int = 20
    retest_window: int = 30         # 돌파 후 눌림 인정 시간(분)
    max_retest_drop: float = 0.015  # 돌파선 -1.5% 까지 눌림 허용
    stop_buffer: float = 0.005      # 손절 = 신호 봉 저가 -0.5% (또는 기준선 아래)


@dataclass(frozen=True)
class Signal:
    ts: datetime
    kind: str            # '지지 반등' | '돌파 후 눌림'
    price: float         # 진입가 (신호 봉 종가)
    level: float         # 기준선 (지지선 S 또는 돌파선 H)
    stop: float
    reason: str


def detect_signals(bars: list[dict[str, Any]], config: Optional[SignalConfig] = None) -> list[Signal]:
    """bars: 시간 오름차순 1분봉 dict(ts, open, high, low, close, volume). 각 봉 마감 시점에 판단 (미래 봉 사용 안 함)."""
    cfg = config or SignalConfig()
    signals: list[Signal] = []
    day_low = float("inf")
    box_high = 0.0
    box_high_idx = -1

    support_armed = True             # 지지 반등: 다음 터치를 받을 준비
    breakout: Optional[dict] = None  # {"level", "idx", "armed", "last_signal"}

    for i, b in enumerate(bars):
        # ---- 돌파 후 눌림 (현재 봉 판단은 갱신 전 박스 기준)
        if breakout is not None:
            level = breakout["level"]
            if i - breakout["idx"] > cfg.retest_window:
                breakout = None
            else:
                # 눌림은 (돌파 봉 또는 재무장 봉) '이후' 봉의 저가만 센다: 현재 봉 또는 직전 봉
                dip_low = min(b["low"], bars[i - 1]["low"]) if i - 1 > breakout["since"] else b["low"]
                dipped = dip_low <= level * (1 + cfg.touch_tol)
                held = dip_low >= level * (1 - cfg.max_retest_drop)
                reclaimed = b["close"] > b["open"] and b["close"] >= level
                if breakout["armed"] and i > breakout["since"] and dipped and held and reclaimed:
                    signals.append(Signal(
                        b["ts"], "돌파 후 눌림", b["close"], level, min(dip_low, level * (1 - cfg.max_retest_drop)) * (1 - cfg.stop_buffer),
                        f"{bars[breakout['idx']]['ts']:%H:%M} 돌파선 {level:,.0f} 재확인 (눌림 저가 {dip_low:,} = {dip_low / level - 1:+.1%})",
                    ))
                    breakout["armed"] = False
                    breakout["last_signal"] = b["close"]
                elif not breakout["armed"] and b["high"] >= breakout["last_signal"] * (1 + cfg.breakout_reset_pct):
                    breakout["armed"] = True     # 다음 봉부터 새 눌림을 받는다
                    breakout["since"] = i

        # ---- 박스 확정 상태에서 돌파 감지 / 지지 반등
        box_ready = (
            box_high_idx >= 0 and i - box_high_idx >= cfg.box_age_bars
            and day_low < float("inf") and (box_high - day_low) / day_low >= cfg.min_box_pct
        )
        if box_ready:
            avg_vol = sum(x["volume"] for x in bars[max(0, i - cfg.vol_lookback):i]) / max(1, min(cfg.vol_lookback, i))
            if b["close"] > box_high and avg_vol > 0 and b["volume"] >= avg_vol * cfg.vol_mult and breakout is None:
                breakout = {"level": box_high, "idx": i, "since": i, "armed": True, "last_signal": b["close"]}

            support = day_low + (box_high - day_low) * cfg.support_ratio
            if not support_armed and b["high"] >= support * (1 + cfg.reset_pct):
                support_armed = True
            touched = b["low"] <= support * (1 + cfg.touch_tol)
            held = b["low"] >= support * (1 - cfg.max_pierce) and b["close"] > support
            if support_armed and touched and held and b["high"] < box_high:
                signals.append(Signal(
                    b["ts"], "지지 반등", b["close"], support, min(b["low"], support * (1 - cfg.max_pierce)) * (1 - cfg.stop_buffer),
                    f"박스 {day_low:,.0f}~{box_high:,.0f} 의 50% {support:,.0f} 지지 (저가 {b['low']:,} = {b['low'] / support - 1:+.1%})",
                ))
                support_armed = False

        # ---- 상태 갱신 (봉 마감 후)
        if b["low"] < day_low:
            day_low = b["low"]
        if b["ts"].time() >= cfg.box_start and b["high"] > box_high:
            box_high, box_high_idx = b["high"], i
            support_armed = True
    return signals
