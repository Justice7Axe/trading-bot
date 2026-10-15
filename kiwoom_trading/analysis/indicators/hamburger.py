"""불개미 '햄버거' 매매 규칙 (파이널 특강 9·10·12·13강) — 순수 함수.

근거 문서: docs/hamburger_lectures.md (강의 정리, 실제 1분봉 대조), docs/hamburger_design.md (설계).

흐름
  1. pick_reference_days : 매매일 D 이전 20거래일에서 '기준 캔들 날'(대금이 터진 장대양봉일) 후보를 고른다.
     전날 대금 환경(터짐/마름)이 D 와 같은 날을 먼저, 그다음 가까운 날 순서.
  2. reference_bar       : 기준 캔들 날 1분봉(통합 AL)에서 '햄버거 기준봉'을 고른다.
     무지성 수급 제외: 장 극초반(시작 후 10분, 30% 차감), 가분수(큰 양봉 연속 3번째부터), 고점 구간(15%↑ & 고가의 80%↑),
     윗꼬리 50% 이상, 15:20 이후. (뉴스빵·상빵은 뉴스 데이터가 없어 거르지 못한다)
     꼬리 보정: 조정 대금 = 대금 × (0.5 + 0.5 × 몸통 / 봉 길이).
  3. simulate_day        : 매매일 1분봉으로 인과적 시뮬레이션.
     햄버거(기준봉 × 배수 이상) → 시간 규칙(장 시작 15분 뒤 당일 고점 갱신) → 끼 안쪽이면
     돌파한 전고점에 지정가 눌림 매수 → 익절 3%(초대형 2%) / 전저점 손절(-2~-5%) / 15:19 정리.

1분봉 대금은 거래량 × (고+저+종)/3 로 추정한다. 강의 예시 40건이 같은 분봉에서 ±1억 안으로 맞았다(문서 7장).
"""
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Optional


@dataclass(frozen=True)
class BurgerParams:
    # 기준 캔들 날
    lookback: int = 20                  # 거래일
    big_high_pct: float = 0.08          # 고가 등락률 ≥ 8% 이고 양봉
    big_value_mult: float = 2.0         # 그날 대금 ≥ 직전 20일 평균 × 2 (대금이 터진 날)
    burst_k: float = 3.0                # '전날 대금이 터졌다' = 전날 대금 ≥ 그 직전 20일 평균 × k   [백테스트 선정: 3 > 2 > 1.5]
    env_mult: float = 1.2               # 오늘 전날은 터졌는데 기준일 전날은 말랐으면 필요한 배수     [백테스트 선정: 1.2 > 1.3]
    max_refs: int = 2                   # 같은 환경의 최근 후보 몇 개를 열어 더 센 쪽을 쓸지
    # 기준봉
    open_window_min: int = 10           # 장 극초반(08:00, 09:00 시작 후 10분)
    open_haircut: float = 0.3           # 극초반 봉은 30% 차감
    gabunsu_n: int = 3                  # 큰 양봉 연속 상승 3번째부터 가분수
    gabunsu_ratio: float = 0.3          #   '큰 봉' = 이 봉 대금의 30% 이상
    gabunsu_gap: int = 1                #   사이에 작은 봉 1개까지 허용
    max_upper_wick: float = 0.5         # 윗꼬리가 봉 길이의 50% 이상이면 기준봉에서 제외 (이수스페셜티 10:51, 보성파워텍 09:47)
    top_zone: float = 0.8               # 봉 종가 등락률 ≥ 그날 고가 등락률 × 0.8 이고
    top_abs: float = 0.15               #   15% 이상이면 고점 구간 (강의: 고가 25% 날의 20~22% 구간, 15% 전후가 가장 정확)
    # 매매일
    nxt_switch: float = 1 / 3           # NXT 1분봉 대금 ≥ 기준봉 × x 이면 그 시각을 '9시'로   [백테스트 선정: 1/3 > 1/2]
    nxt_skip_15: bool = False           # NXT 시간에 '9시'가 되어도 15분 규칙 적용               [백테스트 선정: 적용 > 생략]
    wait_min: int = 15                  # 9시 15분 규칙
    kki_over: float = 0.03              # 햄버거가 기준의 2배 이상이면 끼를 3%p 넘어도 허용
    entry_window_min: int = 60          # 고점 갱신 뒤 눌림 체결을 기다리는 시간
    last_entry: time = time(14, 30)
    tp: float = 0.03                    # 익절 (중소형 3%)
    tp_large: float = 0.02              # 시총 10조 이상
    large_cap: float = 10e12
    stop_min: float = 0.02              # 손절 폭: 전저점 기준, 최소 2% ~ 최대 5%
    stop_lookback: int = 10             # 전저점 = 돌파 봉 직전 N분 최저가 (강의: 매수가 대비 보통 −2~3%)
    stop_max: float = 0.05
    exit_at: time = time(15, 19)
    cost: float = 0.0025


def bar_value(b: dict) -> float:
    return b["volume"] * (b["high"] + b["low"] + b["close"]) / 3


def adj_value(b: dict) -> float:
    """꼬리 보정 대금: 꼬리(매도 물량)가 길수록 깎는다. 꼬리 없으면 100%, 몸통 0 이면 50%."""
    rng = b["high"] - b["low"]
    body = abs(b["close"] - b["open"])
    return bar_value(b) * (0.5 + 0.5 * (body / rng if rng else 1.0))


# --------------------------------------------------------------------------- 1. 기준 캔들 날
def _avg_value(rows: list[dict], i: int, n: int = 20) -> Optional[float]:
    prev = [r["value"] for r in rows[max(0, i - n):i] if r.get("value")]
    return sum(prev) / len(prev) if len(prev) >= 5 else None


def burst(rows: list[dict], i: int, k: float) -> bool:
    """rows[i] 날 대금이 그 직전 20일 평균의 k배 이상인가 ('전날 대금이 터졌다' 판정용)."""
    avg = _avg_value(rows, i)
    return bool(avg and rows[i].get("value") and rows[i]["value"] >= avg * k)


def pick_reference_days(daily: list[dict], d: date, p: BurgerParams) -> tuple[list[dict], bool]:
    """daily: 한 종목 일봉(date 오름차순, value 포함). 매매일 d 직전까지만 본다.

    반환: (후보 목록 [{date, high_pct, env_burst, prev_close}] 우선순위 순, 오늘 전날이 터졌는지)
    """
    rows = [r for r in daily if r["date"] < d]
    if len(rows) < 25:
        return [], False
    today_env = burst(rows, len(rows) - 1, p.burst_k)
    cands = []
    for i in range(max(1, len(rows) - p.lookback), len(rows)):
        r, pc = rows[i], rows[i - 1]["close"]
        if not pc:
            continue
        high_pct = r["high"] / pc - 1
        if high_pct < p.big_high_pct or r["close"] <= r["open"]:
            continue
        avg = _avg_value(rows, i)
        if not avg or (r.get("value") or 0) < avg * p.big_value_mult:
            continue
        if i >= 2 and rows[i - 2]["close"] and rows[i - 1]["close"] / rows[i - 2]["close"] - 1 >= 0.29:
            continue                                   # 상한가 다음 날은 기준일로 쓰지 않는다
        cands.append({"date": r["date"], "high_pct": high_pct, "prev_close": pc,
                      "env_burst": burst(rows, i - 1, p.burst_k), "age": len(rows) - i})
    cands.sort(key=lambda c: (c["env_burst"] != today_env, c["age"]))
    return cands, today_env


# --------------------------------------------------------------------------- 2. 기준봉
def _gabunsu_rank(bars: list[dict], i: int, p: "BurgerParams") -> int:
    """bars[i] 가 '큰 양봉이 연달아 오르는' 흐름에서 몇 번째인지 (강의: 30→40→50→70억, 3번째부터 가분수).

    큰 봉 = 이 봉 대금의 30% 이상인 양봉. 큰 봉 사이에 작은 봉이 1개까지 끼어도 연속으로 본다.
    작은 봉(잔챙이)이 연달아 오른 것은 세지 않는다(DB하이텍 4/24 08:13, 비나텍 4/14 09:36 은 1번째).
    """
    vi = bar_value(bars[i])
    rank, gap, last_close = 1, 0, bars[i]["close"]
    for j in range(i - 1, -1, -1):
        b = bars[j]
        if b["close"] > b["open"] and bar_value(b) >= vi * p.gabunsu_ratio and b["close"] < last_close:
            rank, gap, last_close = rank + 1, 0, b["close"]
        else:
            gap += 1
            if gap > p.gabunsu_gap:
                break
    return rank


def _upper_wick(b: dict) -> float:
    rng = b["high"] - b["low"]
    return (b["high"] - max(b["open"], b["close"])) / rng if rng else 0.0


def _in_open_window(ts: datetime, p: BurgerParams) -> bool:
    t = ts.time()
    for start in (time(8, 0), time(9, 0)):
        s = datetime.combine(ts.date(), start)
        if s <= ts < s + timedelta(minutes=p.open_window_min):
            return True
    return False


def reference_bar(bars: list[dict], prev_close: float, p: BurgerParams) -> Optional[dict]:
    """기준 캔들 날 1분봉 → {ts, value(조정), raw, pct}. 08:00~15:20 봉만 쓴다."""
    day = [b for b in bars if time(8, 0) <= b["ts"].time() < time(15, 20)]
    if not day or not prev_close:
        return None
    hi_pct = max(b["high"] for b in day) / prev_close - 1
    best = None
    for i, b in enumerate(day):
        if b["close"] <= b["open"] or _upper_wick(b) >= p.max_upper_wick or _gabunsu_rank(day, i, p) >= p.gabunsu_n:
            continue
        pct = b["close"] / prev_close - 1
        if hi_pct > 0 and pct >= hi_pct * p.top_zone and pct >= p.top_abs:
            continue
        v = adj_value(b) * ((1 - p.open_haircut) if _in_open_window(b["ts"], p) else 1.0)
        if best is None or v > best["value"]:
            best = {"ts": b["ts"], "value": v, "raw": bar_value(b), "pct": pct}
    return best


# --------------------------------------------------------------------------- 3. 매매일 시뮬레이션
def simulate_day(bars: list[dict], prev_close: float, ref_value: float, kki: float, mult: float,
                 p: BurgerParams, large: bool = False) -> dict[str, Any]:
    """매매일 1분봉(시간순, 08:00~)으로 진입·청산을 인과적으로 시뮬레이션. 반환 dict 의 status:
    'no_burger' | 'no_breakout' | 'kki_over' | 'no_fill' | 'traded'."""
    bars = [b for b in bars if b["ts"].time() <= p.exit_at]
    thr = ref_value * mult
    out: dict[str, Any] = {"thr": thr, "status": "no_burger"}
    if not bars or not prev_close or thr <= 0:
        return out
    # '9시' 시점: NXT 시간에 기준봉의 x 이상이 터진 첫 봉, 없으면 KRX 09:00
    start = next((b["ts"] for b in bars if b["ts"].time() < time(9, 0) and bar_value(b) >= ref_value * p.nxt_switch), None)
    nxt_start = start is not None
    if start is None:
        start = next((b["ts"] for b in bars if b["ts"].time() >= time(9, 0)), bars[0]["ts"])
    gate = start if (nxt_start and p.nxt_skip_15) else start + timedelta(minutes=p.wait_min)
    out["start"] = start

    burger = None                 # 첫 햄버거 봉
    run_high = None               # 고점 갱신 판정용 당일 고가 (NXT 로 9시가 바뀌면 KRX 09:00 봉 고가는 무시)
    recent: list[float] = []
    breakout = None               # (ts, 전고점 = 지정가)
    entry = None
    for i, b in enumerate(bars):
        t = b["ts"]
        v = adj_value(b)
        recent = (recent + [v])[-3:]
        if burger is None and b["close"] > b["open"] and (v >= thr or (len(recent) == 3 and min(recent) >= thr * 0.5 and sum(recent) >= thr * 1.5)):
            burger = {"ts": t, "value": v, "strength": v / thr, "pct": b["close"] / prev_close - 1}
            out["burger"] = burger
        if entry is None:
            if breakout is None:
                prev_high = run_high
                if not (nxt_start and t.time() == time(9, 0)):
                    run_high = b["high"] if run_high is None else max(run_high, b["high"])
                if (burger and prev_high is not None and t >= gate and b["high"] > prev_high
                        and t.time() <= p.last_entry):
                    allow = kki + (p.kki_over if burger["strength"] >= 2 else 0)
                    if prev_high / prev_close - 1 > allow:
                        out["status"] = "kki_over"
                        continue
                    base_low = min(x["low"] for x in bars[max(0, i - p.stop_lookback):i + 1])
                    breakout = {"ts": t, "limit": prev_high, "base_low": base_low}
                    out["breakout"] = breakout
                continue
            # 눌림 지정가 체결 대기
            if (t - breakout["ts"]).total_seconds() > p.entry_window_min * 60 or t.time() > p.last_entry:
                out["status"] = "no_fill"
                return out
            if t > breakout["ts"] and b["low"] <= breakout["limit"]:
                px = min(breakout["limit"], b["open"])
                stop = min(px * (1 - p.stop_min), max(px * (1 - p.stop_max), breakout["base_low"] * 0.995))
                entry = {"ts": t, "price": px, "stop": stop, "tp": px * (1 + (p.tp_large if large else p.tp))}
                out.update(status="traded", entry=entry)
                if b["low"] <= stop:                    # 체결 봉에서 바로 손절가까지 밀림 (보수적)
                    return _close(out, t, stop, "손절", p)
            continue
        # 보유 중
        if b["low"] <= entry["stop"]:
            return _close(out, t, min(entry["stop"], b["open"]), "손절", p)
        if b["high"] >= entry["tp"]:
            return _close(out, t, max(entry["tp"], b["open"]), "익절", p)
    if entry is not None:
        return _close(out, bars[-1]["ts"], bars[-1]["close"], "장 마감", p)
    if breakout is None and burger is not None and out["status"] == "no_burger":
        out["status"] = "no_breakout"
    return out


def _close(out: dict, ts: datetime, price: float, reason: str, p: BurgerParams) -> dict:
    e = out["entry"]
    out["exit"] = {"ts": ts, "price": price, "reason": reason}
    out["ret"] = price / e["price"] - 1 - p.cost
    return out


VARIANTS = {   # 강의에서 엇갈리는 부분 — 2026-10-15 표본(09-01~10-15, 572건)에서 앞·뒤 기간 순위가 같게 나온 값을 기본값으로 정했다
    "nxt_skip_15": [False, True],
    "nxt_switch": [1 / 3, 1 / 2],
    "burst_k": [1.5, 2.0, 3.0],
    "env_mult": [1.2, 1.3],
}


def with_params(p: BurgerParams, **kw) -> BurgerParams:
    return replace(p, **kw)
