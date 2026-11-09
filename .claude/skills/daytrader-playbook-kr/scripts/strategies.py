"""전략 구현. 각 전략의 규칙 원문/가정 구분은 references/ 의 해당 문서를 따른다.

규칙:
- plans_for_day(day) 는 그날 바 데이터만 보고 TradePlan 목록을 만든다.
- i 번째 바 '종가'까지의 정보로만 신호를 판단한다 (i+1 이후 값 참조 금지).
- 파라미터 기본값은 DEFAULTS 에 있고, 각 키 옆 주석의 [S]=출처 규칙, [A]=구현 가정(튜닝 대상).
"""
from __future__ import annotations

import copy
import datetime as dt

from data import Day, parse_time, resample
from engine import TradePlan, next_unblocked, simulate_exit
from indicators import (VolumeProfile, atr, bar_delta, macd, percentile, pivot_highs, pivot_lows, rsi, sma,
                        vwap)
from krx import vi_blocked


def _merge(defaults, params):
    p = copy.deepcopy(defaults)
    for k, v in (params or {}).items():
        if k not in p:
            raise KeyError(f"unknown param {k}")
        p[k] = v
    return p


class Strategy:
    name = "base"
    DEFAULTS: dict = {}
    markets = ("KRX_STOCK",)

    def __init__(self, inst, params=None):
        self.inst = inst
        self.p = _merge(self.DEFAULTS, params)

    def plans_for_day(self, day: Day) -> list:
        raise NotImplementedError

    def _targets(self, entry, stop, side, target_r):
        sgn = 1 if side == "long" else -1
        if self.p.get("target_pct"):  # [A] 진입가 대비 % 익절 (있으면 target_r 대신 사용)
            return [(self.inst.round_tick(entry * (1 + sgn * pct / 100)), f) for pct, f in self.p["target_pct"]]
        risk = abs(entry - stop)
        return [(self.inst.round_tick(entry + sgn * r * risk), f) for r, f in target_r]


def _rr_target(day, bars, i, entry, stop, levels, min_rr, or_minutes=30):
    """손익비 자리 [A]: 진입가 위 가장 가까운 저항선(levels 중)을 목표로, (목표-진입)/(진입-손절) >= min_rr 이면
    (목표가, 이름, 손익비) 반환. 저항선은 신호 바 종가 시점까지 알 수 있는 값만 쓴다."""
    cands = []
    if "day_high" in levels:
        cands.append((max(b.h for b in bars[:i + 1]), "day_high"))
    if "prev_high" in levels and day.hist:
        cands.append((day.hist[-1].h, "prev_high"))
    if "or30_high" in levels:
        first = day.bars[0].t
        end = first + dt.timedelta(minutes=or_minutes)
        sig_close = bars[i].t + (bars[1].t - bars[0].t if len(bars) > 1 else dt.timedelta(minutes=1))
        orb = [b for b in day.bars if b.t < end]
        if orb and sig_close >= end:
            cands.append((max(b.h for b in orb), "or30_high"))
    above = [(px, nm) for px, nm in cands if px > entry]
    if not above or entry <= stop:
        return None
    px, nm = min(above)
    rr = (px - entry) / (entry - stop)
    return (px, nm, rr) if rr >= min_rr else None


def _daily_trend_ok(day, ma_n, slope_days):
    closes = [d.c for d in day.hist]
    if len(closes) < ma_n + slope_days:
        return False
    ma = sma(closes, ma_n)
    return closes[-1] > ma[-1] and ma[-1] > ma[-1 - slope_days]


# =====================================================================
# KR-S1  Breitstein: 재료주(in-play) VWAP 추세 눌림 (롱 전용)
# =====================================================================
class KRS1InplayVWAP(Strategy):
    name = "kr_s1_inplay_vwap_pullback"
    DEFAULTS = {
        "min_change_pct": 5.0,        # [A] 전일종가 대비 등락률 하한 (in-play 근사)
        "min_rvol": 3.0,              # [A] 같은 시각 누적거래량 / 20일 평균
        "min_value": 0,               # [A] 신호 시점 누적 거래대금 하한(원). 예: 3e10
        "require_catalyst": False,    # [S] 뉴스 재료 종목만 매매. 데이터에 catalyst 컬럼 있을 때 True 권장
        "entry_start": "09:15",       # [S] 丁伟锋: 개장 후 15분 매매 금지
        "entry_end": "15:00",         # [A]
        "lookback": 30,               # [A] VWAP 위 '꾸준히' 판정 구간(분)
        "above_ratio": 0.8,           # [A] 그 구간 중 VWAP 위 종가 비율
        "pullback_bars": 5,           # [A]
        "pullback_atr": 0.5,          # [A] 눌림 저가가 VWAP + k*ATR 이내
        "vwap_buffer_atr": 0.3,       # [A] 눌림 중 종가가 VWAP - k*ATR 아래로 가면 무효
        "atr_n": 14,
        "max_stop_pct": 3.0,          # [A]
        "exit_closes_below_vwap": 2,  # [S] VWAP 아래 '꾸준히' 머물면 롱 금지 -> 보유 중이면 청산 (연속 N봉 = 가정)
        "target_r": [[2.0, 0.5]],     # [A] 2R 에서 절반 익절
        "rr_levels": [],              # [A] 손익비 자리: ["day_high","prev_high","or30_high"] 중. 주면 목표=가장 가까운 저항, 청산=목표/손절/시간만
        "min_rr": 2.0,                # [A] 손익비 자리 최소 배수
        "target_pct": [],             # [A] 예 [[2,1.0]]=+2% 전량, [[2,0.5],[5,0.5]]=+2% 절반·+5% 나머지. 비우면 target_r
        "be_after_first": True,       # [A]
        "max_trades_per_day": 2,      # [A]
        "grade_rvol_a": 5.0,          # [A] 등급 가점: RVOL
        "grade_change_a": 10.0,       # [A] 등급 가점: 등락률
        "grade_ma_n": 20,             # [S] 다중 시간대 정렬(일봉 추세) / 20일선 = 가정
        "grade_mult": {"A": 1.0, "B": 0.5, "C": 0.25, "D": 0.0},  # [S] 등급별 비중 차등 / 배수 = 가정
    }

    def plans_for_day(self, day):
        p, inst, bars = self.p, self.inst, day.bars
        n, L = len(bars), p["lookback"]
        if n < L + 5 or not day.prev_close:
            return []
        vw, at = vwap(bars), atr(bars, p["atr_n"])
        blocked = vi_blocked(bars, inst)
        upper = inst.upper_limit(day.prev_close)
        t0, t1 = parse_time(p["entry_start"]), parse_time(p["entry_end"])
        flat = parse_time(inst.flat_time)
        daily_up = _daily_trend_ok(day, p["grade_ma_n"], 1)
        cumv = cumval = 0.0
        cumv_l, cumval_l, cat_l, c = [], [], [], 0
        for b in bars:
            cumv += b.v
            cumval += b.value
            c = max(c, b.catalyst)
            cumv_l.append(cumv)
            cumval_l.append(cumval)
            cat_l.append(c)
        plans, i = [], L
        while i < n - 1 and len(plans) < p["max_trades_per_day"]:
            b = bars[i]
            if not (t0 <= b.t.time() <= t1):
                i += 1
                continue
            chg = (b.c / day.prev_close - 1) * 100
            base = day.rvol_base.get(b.t.strftime("%H:%M"))
            rv = cumv_l[i] / base if base else 0.0
            inplay = chg >= p["min_change_pct"] and rv >= p["min_rvol"] and cumval_l[i] >= p["min_value"]
            if p["require_catalyst"] and not cat_l[i]:
                inplay = False
            if not inplay:
                i += 1
                continue
            above = sum(1 for j in range(i - L + 1, i + 1) if bars[j].c > vw[j])
            trend = above >= p["above_ratio"] * L and vw[i] > vw[i - L]
            pb = range(i - p["pullback_bars"] + 1, i + 1)
            touched = min(bars[j].l for j in pb) <= vw[i] + p["pullback_atr"] * at[i]
            held = all(bars[j].c >= vw[j] - p["vwap_buffer_atr"] * at[j] for j in pb)
            trigger = b.c > bars[i - 1].h and b.c > vw[i] and b.c > b.o
            if not (trend and touched and held and trigger):
                i += 1
                continue
            e = next_unblocked(i + 1, n, blocked)
            if e is None:
                break
            entry = inst.slip(bars[e].o, +1)
            stop = inst.round_tick(min(bars[j].l for j in pb) - inst.tick_at(entry), "down")
            if entry <= stop or (entry - stop) / entry * 100 > p["max_stop_pct"] or (upper and entry >= upper):
                i += 1
                continue
            score = int(bool(cat_l[i])) + int(rv >= p["grade_rvol_a"]) + int(chg >= p["grade_change_a"]) + int(daily_up)
            grade = "A" if score >= 3 else "B" if score == 2 else "C" if score == 1 else "D"
            k = p["exit_closes_below_vwap"]

            def exit_fn(x, k=k):
                if x - k + 1 < 0:
                    return None
                return "vwap_lost" if all(bars[j].c < vw[j] for j in range(x - k + 1, x + 1)) else None

            targets, be, xfn, tags = self._targets(entry, stop, "long", p["target_r"]), p["be_after_first"], exit_fn, {}
            if p["rr_levels"]:
                rt = _rr_target(day, bars, i, entry, stop, p["rr_levels"], p["min_rr"])
                if rt is None:
                    i += 1
                    continue
                targets, be, xfn = [(inst.round_tick(rt[0], "down"), 1.0)], False, None
                tags = {"level": rt[1], "rr": round(rt[2], 2)}
            legs, xi = simulate_exit(bars, e, "long", entry, stop, inst, targets=targets,
                                     be_after_first=be, exit_on_close=xfn, flat_time=flat, blocked=blocked)
            plans.append(TradePlan(self.name, day.symbol, "long", b.t, bars[e].t, entry, stop, legs,
                                   risk_mult=p["grade_mult"][grade], grade=grade,
                                   tags={"chg": round(chg, 2), "rvol": round(rv, 2), "score": score, **tags}))
            i = xi + 1
        return plans


# =====================================================================
# KR-S2  Breitstein: 투매(capitulation) 후 V자 오른쪽 반등 매수 (롱 전용)
# =====================================================================
class KRS2Capitulation(Strategy):
    name = "kr_s2_capitulation_reversal"
    DEFAULTS = {
        "n_days": 3,                # [S] A,B,C 3일 연속 대량 거래 급변 후 D일 갭 (하락 방향으로 적용 = 가정)
        "min_daily_drop_pct": 4.0,  # [A] 각 일자 전일 대비 하락률
        "vol_mult": 1.5,            # [A] 각 일자 거래량 >= 직전 20일 평균 * k
        "vol_avg_n": 20,
        "min_cum_drop_pct": 15.0,   # [A]
        "min_gap_down_pct": 3.0,    # [S] D일 갭 / 크기 = 가정
        "min_rvol": 2.0,            # [S] D일 거래량이 더 큼 -> 장중엔 같은 시각 RVOL 로 근사(가정)
        "entry_start": "09:15",     # [S] 丁伟锋 개장 15분 회피
        "entry_end": "11:30",       # [A]
        "min_bars_after_low": 2,    # [S] 'V자 오른쪽' 확인 후 진입 / 숫자 = 가정
        "max_bars_after_low": 30,   # [A]
        "climax_mult": 3.0,         # [A] 저점 부근 1분 거래량 >= 당일 평균 * k (투매 확인)
        "max_stop_pct": 6.0,        # [A]
        "target_r": [[1.5, 0.5]],   # [A]
        "be_after_first": True,
        "trail_atr": 3.0,           # [A] 남은 물량 ATR 트레일링
        "atr_n": 14,
    }

    def _setup_ok(self, day):
        p, h = self.p, day.hist
        need = p["n_days"] + p["vol_avg_n"] + 1
        if len(h) < need or not day.prev_close:
            return False
        last = h[-p["n_days"]:]
        prev = h[-p["n_days"] - 1:-1]
        avgv = sum(d.v for d in h[-need:-p["n_days"]]) / p["vol_avg_n"]
        for d, pdv in zip(last, prev):
            if (d.c / pdv.c - 1) * 100 > -p["min_daily_drop_pct"] or d.v < p["vol_mult"] * avgv:
                return False
        cum = (h[-1].c / h[-p["n_days"] - 1].c - 1) * 100
        gap = (day.bars[0].o / day.prev_close - 1) * 100
        return cum <= -p["min_cum_drop_pct"] and gap <= -p["min_gap_down_pct"]

    def plans_for_day(self, day):
        p, inst, bars = self.p, self.inst, day.bars
        n = len(bars)
        if n < 30 or not self._setup_ok(day):
            return []
        at, blocked = atr(bars, p["atr_n"]), vi_blocked(bars, inst)
        t0, t1, flat = parse_time(p["entry_start"]), parse_time(p["entry_end"]), parse_time(inst.flat_time)
        cumv = 0.0
        for i in range(1, n - 1):
            b = bars[i]
            cumv += bars[i - 1].v
            if not (t0 <= b.t.time() <= t1):
                continue
            j = min(range(i + 1), key=lambda k: bars[k].l)
            gap = i - j
            if gap < p["min_bars_after_low"] or gap > p["max_bars_after_low"]:
                continue
            avgv = (cumv + b.v) / (i + 1)
            climax = max(bars[k].v for k in range(max(0, j - 2), min(i, j + 2) + 1)) >= p["climax_mult"] * avgv
            base = day.rvol_base.get(b.t.strftime("%H:%M"))
            rv = (cumv + b.v) / base if base else 0.0
            right_side = b.c > max(bars[k].h for k in range(j, i))
            if not (climax and rv >= p["min_rvol"] and right_side):
                continue
            e = next_unblocked(i + 1, n, blocked)
            if e is None:
                return []
            entry = inst.slip(bars[e].o, +1)
            stop = inst.round_tick(bars[j].l - inst.tick_at(bars[j].l), "down")
            if entry <= stop or (entry - stop) / entry * 100 > p["max_stop_pct"]:
                continue
            legs, _ = simulate_exit(bars, e, "long", entry, stop, inst,
                                    targets=self._targets(entry, stop, "long", p["target_r"]),
                                    be_after_first=p["be_after_first"], trail_atr=p["trail_atr"], atr_vals=at,
                                    flat_time=flat, blocked=blocked)
            return [TradePlan(self.name, day.symbol, "long", b.t, bars[e].t, entry, stop, legs,
                              tags={"low_t": bars[j].t.strftime("%H:%M"), "rvol": round(rv, 2)})]
        return []


# =====================================================================
# KR-S3  丁伟锋: 개장 5분 범위 방향 + 패턴 완성 돌파 (롱 전용, 5분봉)
# =====================================================================
class KRS3ORBPattern(Strategy):
    name = "kr_s3_orb5_pattern"
    DEFAULTS = {
        "tf": 5,                     # [A] 패턴 판단 봉(분)
        "or_minutes": 5,             # [S] 개장 첫 5분 범위
        "entry_start": "09:15",      # [S] 개장 후 15분 매매 금지
        "entry_end": "15:05",        # [S] 연속매매 종료(15:20) 전 15분 매매 금지
        "ma_n": 20,                  # [S] 큰 그림(일봉)으로 방향 / 20일선 = 가정
        "ma_slope_days": 5,          # [A]
        "use_box": True, "box_bars": 6, "box_max_pct": 2.5, "box_vol_mult": 1.5,      # [S] 박스 돌파 / 숫자 = 가정
        "use_w": True, "w_left": 2, "w_right": 2, "w_lookback": 24, "w_tol_pct": 0.7, "w_min_sep": 3,  # [S] W바닥 넥라인 돌파
        "use_triangle": True, "tri_bars": 8,                                            # [S] 삼각수렴 돌파
        "climax_mult": 4.0, "climax_lookback": 12,  # [S] 급격한 대량 거래 바 = 추세 끝 신호 / 숫자 = 가정
        "max_stop_pct": 3.0,         # [S] 1회 손실 3% 이하 (계좌 기준 상한은 포트폴리오에서 별도)
        "target_r": [],              # [S] 고정 목표 없음: 손절 또는 반대 패턴 출현 시 청산
        "target_pct": [],            # [A] % 익절 변형(원 기법 아님). 예 [[2,1.0]]
        "rr_levels": [],             # [A] 손익비 자리 (S1 과 같은 의미, 원 기법 아님)
        "min_rr": 2.0,               # [A]
        "be_after_first": False,     # [A] 첫 익절 뒤 손절을 본전으로
        "max_trades_per_day": 2,     # [A]
    }

    def plans_for_day(self, day):
        p, inst = self.p, self.inst
        if not day.prev_close or not _daily_trend_ok(day, p["ma_n"], p["ma_slope_days"]):
            return []
        anchor = parse_time(inst.session_start)
        or_end = (anchor.hour * 60 + anchor.minute + p["or_minutes"])
        or_bars = [b for b in day.bars if b.t.hour * 60 + b.t.minute < or_end]
        if not or_bars:
            return []
        or_high = max(b.h for b in or_bars)
        bars = resample(day.bars, p["tf"], anchor)
        n = len(bars)
        if n < 10:
            return []
        blocked = vi_blocked(bars, inst, p["tf"])
        upper = inst.upper_limit(day.prev_close)
        t0, t1, flat = parse_time(p["entry_start"]), parse_time(p["entry_end"]), parse_time(inst.flat_time)
        lows, highs = [b.l for b in bars], [b.h for b in bars]
        plo = pivot_lows(lows, p["w_left"], p["w_right"])
        phi = pivot_highs(highs, p["w_left"], p["w_right"])
        plans, i = [], 3
        while i < n - 1 and len(plans) < p["max_trades_per_day"]:
            b = bars[i]
            if not (t0 <= b.t.time() <= t1) or b.c <= or_high:
                i += 1
                continue
            stop, pattern = self._pattern(bars, i, plo)
            if stop is None:
                i += 1
                continue
            e = next_unblocked(i + 1, n, blocked)
            if e is None:
                break
            entry = inst.slip(bars[e].o, +1)
            stop = inst.round_tick(stop - inst.tick_at(stop), "down")
            if entry <= stop or (entry - stop) / entry * 100 > p["max_stop_pct"] or (upper and entry >= upper):
                i += 1
                continue

            def exit_fn(x, entry=entry):
                lb = p["climax_lookback"]
                if x >= lb:
                    avgv = sum(bars[k].v for k in range(x - lb, x)) / lb
                    if bars[x].v >= p["climax_mult"] * avgv and bars[x].c > entry:
                        return "climax_volume"
                bb = p["box_bars"]
                if x >= bb and bars[x].c < min(bars[k].l for k in range(x - bb, x)):
                    return "box_breakdown"
                if self._m_top(bars, x, phi):
                    return "m_top"
                return None

            targets, be, xfn, tags = self._targets(entry, stop, "long", p["target_r"]), p["be_after_first"], exit_fn, {}
            if p["rr_levels"]:
                rt = _rr_target(day, bars, i, entry, stop, p["rr_levels"], p["min_rr"])
                if rt is None:
                    i += 1
                    continue
                targets, be, xfn = [(inst.round_tick(rt[0], "down"), 1.0)], False, None
                tags = {"level": rt[1], "rr": round(rt[2], 2)}
            legs, xi = simulate_exit(bars, e, "long", entry, stop, inst, targets=targets,
                                     be_after_first=be, exit_on_close=xfn, flat_time=flat, blocked=blocked)
            plans.append(TradePlan(self.name, day.symbol, "long", b.t, bars[e].t, entry, stop, legs,
                                   tags={"pattern": pattern, "or_high": or_high, **tags}))
            i = xi + 1
        return plans

    def _pattern(self, bars, i, plo):
        p = self.p
        bb = p["box_bars"]
        if p["use_box"] and i >= bb:
            win = bars[i - bb:i]
            hi, lo = max(x.h for x in win), min(x.l for x in win)
            avgv = sum(x.v for x in win) / bb
            if (hi - lo) / lo * 100 <= p["box_max_pct"] and bars[i].c > hi and bars[i].v >= p["box_vol_mult"] * avgv:
                return lo, "box"
        if p["use_w"]:
            conf = [k for k in plo if k + p["w_right"] <= i and k >= i - p["w_lookback"]]
            if len(conf) >= 2:
                k1, k2 = conf[-2], conf[-1]
                l1, l2 = bars[k1].l, bars[k2].l
                if k2 - k1 >= p["w_min_sep"] and abs(l2 - l1) / l1 * 100 <= p["w_tol_pct"]:
                    neck = max(x.h for x in bars[k1:k2 + 1])
                    if bars[i].c > neck >= bars[i - 1].c:
                        return min(l1, l2), "w_bottom"
        tb = p["tri_bars"]
        if p["use_triangle"] and i >= tb:
            win = bars[i - tb:i]
            xs = list(range(tb))
            sh, sl = _slope(xs, [x.h for x in win]), _slope(xs, [x.l for x in win])
            if sh < 0 < sl and bars[i].c > max(x.h for x in win):
                return min(x.l for x in win[-3:]), "triangle"
        return None, None

    def _m_top(self, bars, x, phi):
        p = self.p
        conf = [k for k in phi if k + p["w_right"] <= x and k >= x - p["w_lookback"]]
        if len(conf) < 2:
            return False
        k1, k2 = conf[-2], conf[-1]
        h1, h2 = bars[k1].h, bars[k2].h
        if k2 - k1 < p["w_min_sep"] or abs(h2 - h1) / h1 * 100 > p["w_tol_pct"]:
            return False
        neck = min(b.l for b in bars[k1:k2 + 1])
        return bars[x].c < neck <= bars[x - 1].c


def _slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


# =====================================================================
# FUT-F1  Fabio Valentini: 경매이론(AMT) 오더플로우 - 1분봉 근사판
# =====================================================================
class FUTF1FabioAMT(Strategy):
    name = "fut_f1_fabio_amt_proxy"
    markets = ("NQ", "MNQ", "K200F", "MK200F")
    DEFAULTS = {
        "state_offset_min": 30,     # [A] 개장 후 N분 시점에 균형/불균형 판정
        "bin_ticks": 4,             # [A] 볼륨 프로파일 bin = 틱 * k
        "value_area": 0.70,         # [S] 가치영역 70% (AMT 표준)
        "lvn_frac": 0.35,           # [A] LVN 판정
        "touch_tol_ticks": 2,       # [A] 레벨 터치 허용 오차
        "stop_buffer_ticks": 4,     # [A]
        "delta_pctl": 0.8,          # [S] 공격성(Aggression) 확인 / 상위 20% = 가정
        "delta_lookback": 60,       # [A]
        "target_r": [[1.0, 1.0]],   # [S] '1:1 트레이드를 여러 번 쌓는다' (홈런 1번보다)
        "max_trades_per_day": 6,    # [A]
        "use_trend_model": True,    # [S] 불균형(추세) 모델
        "use_mr_model": True,       # [S] 균형(평균회귀) 모델
        "entry_end_offset_min": 30, # [A] 장 종료 N분 전 이후 신규 진입 금지
    }

    def plans_for_day(self, day):
        p, inst, bars = self.p, self.inst, day.bars
        n = len(bars)
        if n < 60 or not day.prev_bars:
            return []
        tick = inst.tick_at(bars[0].o)
        prof = VolumeProfile(tick * p["bin_ticks"])
        for b in day.prev_bars:
            prof.add(b)
        va = prof.value_area(p["value_area"])
        if not va:
            return []
        val, poc, vah = va
        k = min(p["state_offset_min"], n - 1)
        open_px = bars[0].o
        if bars[k].c > vah and min(b.l for b in bars[:k + 1]) > poc:
            state = "imbalance_up"
        elif bars[k].c < val and max(b.h for b in bars[:k + 1]) < poc:
            state = "imbalance_down"
        else:
            state = "balance"
        deltas = [bar_delta(b) for b in bars]
        flat = parse_time(inst.flat_time)
        end_t = parse_time(inst.session_end)
        cutoff = (end_t.hour * 60 + end_t.minute) - p["entry_end_offset_min"]
        today = VolumeProfile(tick * p["bin_ticks"])
        for b in bars[:k + 1]:
            today.add(b)
        plans, i = [], k + 1
        tol, buf = p["touch_tol_ticks"] * tick, p["stop_buffer_ticks"] * tick
        while i < n - 1 and len(plans) < p["max_trades_per_day"]:
            b = bars[i]
            today.add(b)
            if b.t.hour * 60 + b.t.minute >= cutoff:
                break
            lb = deltas[max(0, i - p["delta_lookback"]):i]
            thr = percentile([abs(x) for x in lb], p["delta_pctl"]) if len(lb) >= 20 else float("inf")
            sig = None
            if p["use_trend_model"] and state == "imbalance_up":
                levels = [vah] + [x for x in today.lvns(p["lvn_frac"]) if vah < x < bars[i - 1].c]
                for lv in sorted(levels, reverse=True):
                    if b.l <= lv + tol and b.c > lv and deltas[i] >= thr:
                        sig = ("long", min(b.l, lv) - buf, None, "trend_lvn" if lv != vah else "trend_vah")
                        break
            elif p["use_trend_model"] and state == "imbalance_down":
                levels = [val] + [x for x in today.lvns(p["lvn_frac"]) if bars[i - 1].c < x < val]
                for lv in sorted(levels):
                    if b.h >= lv - tol and b.c < lv and -deltas[i] >= thr:
                        sig = ("short", max(b.h, lv) + buf, None, "trend_lvn" if lv != val else "trend_val")
                        break
            elif p["use_mr_model"] and state == "balance":
                if b.h > vah and b.c < vah and -deltas[i] >= thr:
                    sig = ("short", b.h + buf, poc, "mr_vah")
                elif b.l < val and b.c > val and deltas[i] >= thr:
                    sig = ("long", b.l - buf, poc, "mr_val")
            if not sig:
                i += 1
                continue
            side, stop, tgt, model = sig
            e = i + 1
            sgn = 1 if side == "long" else -1
            entry = inst.slip(bars[e].o, sgn)
            stop = inst.round_tick(stop, "down" if side == "long" else "up")
            risk = (entry - stop) * sgn
            if risk <= 0:
                i += 1
                continue
            if tgt is not None:
                if (tgt - entry) * sgn < risk:  # [A] POC 까지 1R 미만이면 패스
                    i += 1
                    continue
                targets = [(inst.round_tick(tgt), 1.0)]
            else:
                targets = self._targets(entry, stop, side, p["target_r"])
            legs, xi = simulate_exit(bars, e, side, entry, stop, inst, targets=targets, flat_time=flat)
            plans.append(TradePlan(self.name, day.symbol, side, b.t, bars[e].t, entry, stop, legs,
                                   tags={"state": state, "model": model, "vah": round(vah, 2), "val": round(val, 2),
                                         "poc": round(poc, 2), "delta_real": b.buy_v is not None}))
            for x in bars[i + 1:xi + 1]:
                today.add(x)
            i = xi + 1
        return plans


# =====================================================================
# FUT-F2  David Trullas Vila: MACD/RSI 다이버전스 + 피보나치 + 거래량
# =====================================================================
class FUTF2TrullasDivergence(Strategy):
    name = "fut_f2_trullas_divergence"
    markets = ("NQ", "MNQ", "K200F", "MK200F")
    DEFAULTS = {
        "tf": 5,                    # [A]
        "rsi_n": 14,                # [A] 표준값
        "macd": [12, 26, 9],        # [A] 표준값
        "piv_left": 3, "piv_right": 3,  # [A]
        "min_sep": 5, "max_sep": 60,    # [A] 두 피벗 간격(바)
        "use_regular": True,        # [S] 일반 다이버전스
        "use_hidden": True,         # [S] 히든 다이버전스
        "fib_min": 0.382, "fib_max": 0.786,  # [S] 피보나치 / 구간 = 가정 (히든 다이버전스의 되돌림 위치)
        "regular_volume_filter": True,       # [S] 거래량 / 2번째 저점 거래량 감소 조건 = 가정
        "stop_buffer_ticks": 4,     # [A]
        "target_r": [[1.0, 0.5], [2.0, 0.5]],  # [A]
        "be_after_first": True,     # [A]
        "sizing": "per_divergence", # [S] 다이버전스 1개당 1계약. "risk" 로 바꾸면 리스크% 사이징
        "max_trades_per_day": 4,    # [A]
        "entry_start_offset_min": 15,  # [A]
        "entry_end_offset_min": 30,    # [A]
    }

    def plans_for_day(self, day):
        p, inst = self.p, self.inst
        anchor = parse_time(inst.session_start)
        bars = resample(day.bars, p["tf"], anchor)
        n = len(bars)
        if n < 40:
            return []
        closes = [b.c for b in bars]
        osc = {"rsi": rsi(closes, p["rsi_n"]), "macd_hist": macd(closes, *p["macd"])[2]}
        R = p["piv_right"]
        plo = pivot_lows([b.l for b in bars], p["piv_left"], R)
        phi = pivot_highs([b.h for b in bars], p["piv_left"], R)
        tick = inst.tick_at(bars[0].o)
        flat = parse_time(inst.flat_time)
        s_min = anchor.hour * 60 + anchor.minute + p["entry_start_offset_min"]
        end_t = parse_time(inst.session_end)
        e_min = end_t.hour * 60 + end_t.minute - p["entry_end_offset_min"]
        plans, busy_until = [], -1
        for i in range(R, n - 1):
            if len(plans) >= p["max_trades_per_day"]:
                break
            if i <= busy_until:
                continue
            tmin = bars[i].t.hour * 60 + bars[i].t.minute + p["tf"]
            if not (s_min <= tmin <= e_min):
                continue
            sig = self._check(bars, osc, plo, i, "long") or self._check(bars, osc, phi, i, "short")
            if not sig:
                continue
            side, kind, cnt, piv = sig
            sgn = 1 if side == "long" else -1
            e = i + 1
            entry = inst.slip(bars[e].o, sgn)
            stop = bars[piv].l - p["stop_buffer_ticks"] * tick if side == "long" else bars[piv].h + p["stop_buffer_ticks"] * tick
            stop = inst.round_tick(stop, "down" if side == "long" else "up")
            if (entry - stop) * sgn <= 0:
                continue
            legs, xi = simulate_exit(bars, e, side, entry, stop, inst,
                                     targets=self._targets(entry, stop, side, p["target_r"]),
                                     be_after_first=p["be_after_first"], flat_time=flat)
            plans.append(TradePlan(self.name, day.symbol, side, bars[i].t, bars[e].t, entry, stop, legs,
                                   fixed_qty=cnt if p["sizing"] == "per_divergence" else None,
                                   tags={"kind": kind, "n_div": cnt}))
            busy_until = xi
        return plans

    def _check(self, bars, osc, pivots, i, side):
        p = self.p
        R = p["piv_right"]
        newp = [k for k in pivots if k + R == i]
        if not newp:
            return None
        p2 = newp[0]
        prior = [k for k in pivots if p["min_sep"] <= p2 - k <= p["max_sep"]]
        if not prior:
            return None
        p1 = prior[-1]
        px = (lambda k: bars[k].l) if side == "long" else (lambda k: bars[k].h)
        reg = hid = 0
        for o in osc.values():
            if o[p1] is None or o[p2] is None:
                continue
            if side == "long":
                if px(p2) < px(p1) and o[p2] > o[p1]:
                    reg += 1
                elif px(p2) > px(p1) and o[p2] < o[p1]:
                    hid += 1
            else:
                if px(p2) > px(p1) and o[p2] < o[p1]:
                    reg += 1
                elif px(p2) < px(p1) and o[p2] > o[p1]:
                    hid += 1
        if reg and p["use_regular"]:
            if p["regular_volume_filter"] and not bars[p2].v < bars[p1].v:
                return None
            return side, "regular", reg, p2
        if hid and p["use_hidden"]:
            if side == "long":
                H = max(b.h for b in bars[p1:p2 + 1])
                leg = H - bars[p1].l
                retr = (H - bars[p2].l) / leg if leg > 0 else 0
            else:
                Lo = min(b.l for b in bars[p1:p2 + 1])
                leg = bars[p1].h - Lo
                retr = (bars[p2].h - Lo) / leg if leg > 0 else 0
            if p["fib_min"] <= retr <= p["fib_max"]:
                return side, "hidden", hid, p2
        return None


REGISTRY = {c.name: c for c in (KRS1InplayVWAP, KRS2Capitulation, KRS3ORBPattern, FUTF1FabioAMT,
                                FUTF2TrullasDivergence)}
