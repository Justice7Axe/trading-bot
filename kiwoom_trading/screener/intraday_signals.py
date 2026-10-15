"""1분봉 매수 타점: 박스권 50% 지지 반등 / 박스 상단 돌파 후 눌림.

두산테스나 2026-10-13 차트의 매수 동그라미를 정형화한 것.
  ① 지지 반등: 당일 저점(L)과 박스 고점(H)의 중간값 S = (L+H)/2 까지 눌렸다가 버티는 봉
     - 박스 확정: H 를 만든 뒤 box_age_bars 분 동안 H 를 넘지 못함, 박스 폭 (H-L)/L ≥ min_box_pct
       (H 는 KRX 정규장 09:00 이후 고가로 잡는다 — 프리마켓의 얇은 박스는 제외. L 은 당일 전체 저가)
     - 터치: 저가 ≤ S×(1+support_touch_tol), 저가 ≥ S×(1-max_pierce) (너무 깊게 깨지면 지지 실패)
       (지지선을 정확히 찍지 않고 살짝 위에서 받쳐도 지지 — 기준 차트 11:45 자리는 지지선 +0.2%)
     - 지지 확인: 종가 > S (선을 지키고 마감)
     - 같은 눌림에서 중복 신호 금지: 신호 후 고가가 S×(1+reset_pct, 1.0%) 를 넘어야 다음 터치 인정
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
    touch_tol: float = 0.001        # 돌파 후 눌림: 돌파선 +0.1% 이내로 내려오면 터치
    support_min_gap: int = 10       # 지지 반등 신호 사이 최소 10분 (같은 눌림 안 꼬리 반등 중복 방지, 기준 차트 간격 19~44분)
    support_touch_tol: float = 0.003  # 지지 반등: 지지선 +0.3% 이내 (2026-10-15 사용자 기준 차트의 4번째 지지 자리 11:45 = +0.2%)
    max_pierce: float = 0.008       # 지지선 -0.8% 넘게 깨지면 지지 실패
    reset_pct: float = 0.010        # 지지 반등: 다음 터치로 인정하려면 +1.0% 이상 반등했다 와야 함 (기준 차트: 같은 눌림 안 +0.7%, 새 반등 +1.4% — 2026-10-15 1.5%→1.0%)
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


@dataclass(frozen=True)
class QualityConfig:
    """신호 품질 필터 — '기준 차트(두산테스나 10-13)처럼 근거가 명확한 타점'만 알림 (2026-10-14 복기 반영).

    기준 차트 5개 타점(10:41·11:00·12:14 지지 반등, 12:49·13:02 돌파 후 눌림)은 모두 통과해야 한다:
      - 기준 지지 반등은 전일 종가 아래(-1.1%)였지만 09:00 시가(119,600) 위, 박스 76~169분 유지, 지지선 한 번도 안 깨짐
      - 같은 지지선 반복 터치·돌파 후 두 번째 눌림도 정상 타점 → '반복 금지'가 아니라 '앞 신호가 손절되면 반복 금지'
    10-14 복기: 89건 중 하락 차트(시가 아래)·이미 깨진 지지선·손절 후 반복(국제약품 9회)·애프터마켓 신호가 손실 대부분.
    1년 2,191 신호 검증: 지지선 온전 여부는 1년 평균에선 차이 없음(-0.48% vs -0.49%),
      지지 반등 + 박스 60분↑ -0.32%, 90분↑ +0.01%(앞 -0.35%/뒤 +0.41%) — 필터는 알림을 줄이지만 아직 수익 신호는 아님.
    """
    above_open: bool = True              # 09:00 시가 위에서만 (하락 차트 제외) — 전일 종가 기준은 기준 타점까지 걸러서 쓰지 않음
    support_intact: bool = True          # 지지 반등: 박스 고점 이후 종가가 지지선 -0.8% 아래로 마감한 적 없어야 (깨진 지지선은 근거 아님)
    min_box_minutes: int = 60            # 지지 반등: 박스 고점 이후 60분↑ 유지 (기준 76분)
    max_from_high: float = 0.06          # 당일 고가 대비 -6% 넘게 빠진 눌림 제외 (추세 훼손)
    no_repeat_after_stop: bool = True    # 같은 종류 앞 신호가 손절가에 닿았으면 반복 신호 금지
    breakout_above_prev_close: bool = True   # 돌파 후 눌림: 돌파선이 전일 종가 이상일 때만 (오늘 박스만 넘고 전일 종가·고가 매물대 아래면 진짜 돌파 아님)
    start: time = time(9, 0)
    end: time = time(14, 30)             # 이후 신호는 상승 여지 작음, 애프터마켓(NXT) 신호는 거래 얇음


def reject_reason(bars: list[dict[str, Any]], s: Signal, earlier: list[Signal],
                  config: Optional[QualityConfig] = None, prev_close: Optional[float] = None) -> Optional[str]:
    """신호가 품질 필터에 걸리면 사유, 통과하면 None.

    bars: 당일 1분봉(신호 봉 이후가 섞여 있어도 신호 시각까지만 사용), earlier: 같은 종목 오늘 앞서 통과한 신호들.
    """
    q = config or QualityConfig()
    if not (q.start <= s.ts.time() <= q.end):
        return f"시간 {s.ts:%H:%M} (허용 {q.start:%H:%M}~{q.end:%H:%M})"
    upto = [b for b in bars if b["ts"] <= s.ts]
    regular = [b for b in upto if b["ts"].time() >= q.start]
    if not regular:
        return "정규장 봉 없음"
    if q.above_open and s.price < regular[0]["open"]:
        return f"09:00 시가 {regular[0]['open']:,} 아래 (하락 차트)"
    high = max(b["high"] for b in regular)
    if s.price < high * (1 - q.max_from_high):
        return f"당일 고가 대비 {s.price / high - 1:+.1%} (깊은 눌림)"
    if s.kind == "돌파 후 눌림" and q.breakout_above_prev_close and prev_close and s.level < prev_close:
        # 2026-10-15 이수스페셜티: 오늘 박스 고점 89,700 돌파 → 전일 종가 91,700·고가 92,900 아래라 매물대에 막힘
        return f"돌파선 {s.level:,.0f} 이 전일 종가 {prev_close:,.0f} 아래 (오늘 박스만 넘은 반등)"
    if q.no_repeat_after_stop:
        for e in earlier:
            if e.kind == s.kind and any(b["low"] <= e.stop for b in upto if e.ts < b["ts"] < s.ts):
                return f"{e.ts:%H:%M} {e.kind} 신호가 손절된 뒤 반복"
    if s.kind == "지지 반등":
        hi_idx = max(range(len(upto)), key=lambda k: upto[k]["high"] if upto[k]["ts"].time() >= q.start else -1)
        box_minutes = len(upto) - 1 - hi_idx
        if box_minutes < q.min_box_minutes:
            return f"박스 {box_minutes}분 (최소 {q.min_box_minutes}분)"
        if q.support_intact and any(b["close"] < s.level * (1 - 0.008) for b in upto[hi_idx + 1:-1]):
            return f"지지선 {s.level:,.0f} 이 이미 깨졌던 자리"
    return None


def detect_signals(bars: list[dict[str, Any]], config: Optional[SignalConfig] = None) -> list[Signal]:
    """bars: 시간 오름차순 1분봉 dict(ts, open, high, low, close, volume). 각 봉 마감 시점에 판단 (미래 봉 사용 안 함)."""
    cfg = config or SignalConfig()
    signals: list[Signal] = []
    day_low = float("inf")
    box_high = 0.0
    box_high_idx = -1

    support_armed = True             # 지지 반등: 다음 터치를 받을 준비
    last_support = -10**9            # 마지막 지지 반등 신호 봉 위치
    breakout: Optional[dict] = None  # {"level", "idx", "armed", "last_signal"}

    for i, b in enumerate(bars):
        # ---- 돌파 후 눌림 (현재 봉 판단은 갱신 전 박스 기준)
        if breakout is not None:
            level = breakout["level"]
            if i - breakout["idx"] > cfg.retest_window:
                breakout = None
            elif i > breakout["idx"] and b["close"] < level * (1 - cfg.max_retest_drop):
                # 돌파 후 돌파선 -1.5% 아래로 마감 = 돌파 실패 → 이후 다시 튀어도 '돌파 후 눌림' 아님 (2026-10-15 레메디·서산 복기)
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
            touched = b["low"] <= support * (1 + cfg.support_touch_tol)
            held = b["low"] >= support * (1 - cfg.max_pierce) and b["close"] > support
            if support_armed and touched and held and b["high"] < box_high and i - last_support >= cfg.support_min_gap:
                signals.append(Signal(
                    b["ts"], "지지 반등", b["close"], support, min(b["low"], support * (1 - cfg.max_pierce)) * (1 - cfg.stop_buffer),
                    f"박스 {day_low:,.0f}~{box_high:,.0f} 의 50% {support:,.0f} 지지 (저가 {b['low']:,} = {b['low'] / support - 1:+.1%})",
                ))
                support_armed = False
                last_support = i

        # ---- 상태 갱신 (봉 마감 후)
        if b["low"] < day_low:
            day_low = b["low"]
        if b["ts"].time() >= cfg.box_start and b["high"] > box_high:
            box_high, box_high_idx = b["high"], i
            support_armed = True
    return signals
