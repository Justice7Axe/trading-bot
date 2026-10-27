"""🎯 주도주 모양 — 더 일찍 판정하면 나아지나? (2026-10-27)

모의 매매에서 매수가가 평균 시가 대비 +5.8% 로 이미 많이 오른 뒤였다 → 판정 시간을 앞당기고 조건을 풀어 1년 시험.

표본·판정 (미래 정보 없음):
- 날짜 D 의 대상 = 전날(D-1) 일봉 대금 상위 200 보통주 (engine.value_rank(prev_day)).
- '그 시점 누적 대금 100위' = 이 200종목 안에서 판정 분 전까지 누적 대금(전형가 × 거래량)으로 매긴 순위 (실전은 KRX 전 종목 순위).
- 특징값은 live.features 와 같은 정의를 1분봉 하나씩 쌓아 계산 (일부를 live.features 로 다시 계산해 맞는지 확인).
- 전일 종가(갭) = 일봉 전일 종가 × engine.factor(그날 1분봉 기준으로 맞춤).
- 종목당 하루 1번, 창 안에서 처음 통과한 분 → 그 분 봉 시가 매수.
- 판정 창: 09:10~09:20 / 09:15~09:30 / 09:20~09:40 / 09:30~10:30(원래, 기준).
- 조건: 매끄러움 ≥0.15, VWAP 위 ≥60%(09:05 이후 봉, 창이 09:10 전에 시작하면 09:00 이후, 5봉 이상), 갭 ≤+4%, 눌림 ≤3 은 그대로.
  신고가 ≥2/3/5, 시가 대비 ≥+1/+2%, 시가 대비 ≤+5% 상한 있음/없음.
- 강한 상승장(U, regime.cls: 09:10 코스피 z≥1 또는 대금 상위 중앙값 ≥+2%) + 전날 외인·기관 둘 다 순매수(investor_daily, 10-13 까지) 를 따로 집계.

매도 (backtest-rules: 종가 매도 없음, 같은 봉 손절 먼저, 비용 0.25%, |수익률|>35% 뺌):
- 손절: 직전 10분 저가 −0.5% (판정가 대비 −2~−5%, live.stop_price). 손절 없으면 다음 날 09:00 시가.
- 절반 +2R → 나머지 3% 추적 (max(손절, 본전, 고점×0.97)), 남으면 다음 날 09:00 시가.
- 절반 +2% → 나머지 3% 추적, 남으면 다음 날 09:00 시가.
- (기준 창만) 반반 +2%·15:19 정리 — validate_leader_shape 재현 확인용 (규칙상 쓰지 않는 매도).

    .venv\\Scripts\\python.exe -m kiwoom_trading.strategies.leader_shape.early
결과: data/leader_shape/early.txt
"""
import bisect
import os
import random
from collections import defaultdict
from datetime import datetime, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook import regime as RG
from kiwoom_trading.strategies.leader_shape.live import LeaderShapeConfig, features, stop_price

CFG = LeaderShapeConfig()
TOP = 200
OUT_DIR = os.path.join(E.DATA, "leader_shape")
os.makedirs(OUT_DIR, exist_ok=True)

WINDOWS = [(time(9, 10), time(9, 20)), (time(9, 15), time(9, 30)), (time(9, 20), time(9, 40)), (time(9, 30), time(10, 30))]
NEW_HIGHS = [2, 3, 5]
FROM_OPEN = [0.01, 0.02]
CAPS = [None, 0.05]
EXITS = ["손절·다음날", "절반+2R·추적", "절반+2%·추적"]
T_END = time(10, 30)


def wname(w):
    return f"{w[0]:%H:%M}~{w[1]:%H:%M}"


def prefix_features(reg, prev_close, vwap_from):
    """reg = 정규장 1분봉 [(t,o,h,l,c,v)]. k 번째 원소 = reg[:k] 로 본 특징 (live.features 정의, 봉 8개 미만이면 None)."""
    out = [None] * (len(reg) + 1)
    o = reg[0][1]
    pv = v = 0.0
    above = n5 = 0
    nh, mx = 0, 0.0
    run_high = reg[0][2]
    pull = 0.0
    moves = 0.0
    for i, (t, bo, h, l, c, vol) in enumerate(reg):
        tp = (h + l + c) / 3
        pv += tp * vol; v += vol
        vw = pv / v if v else tp
        if t >= vwap_from:
            n5 += 1; above += c > vw
        if h > mx:
            nh += 1; mx = h
        run_high = max(run_high, h)
        pull = max(pull, (run_high - l) / max(run_high - o, o * 0.005))
        if i:
            moves += abs(c - reg[i - 1][4])
        k = i + 1
        if k >= 8:
            out[k] = (
                (c - o) / moves if moves else 0.0,       # eff
                c / o - 1,                                 # from_open
                o / prev_close - 1,                        # gap
                above / n5 if n5 >= 5 else -1.0,           # vwap_share (5봉 미만이면 실패)
                nh, pull, c,
                min(x[3] for x in reg[max(0, k - 10):k]),  # low10
            )
        if t > T_END:
            break
    return out


def simulate(reg, k, stop, c, d, mode):
    """reg[k] 시가 매수. mode: EXITS 중 하나 또는 '반반15:19'. → 수익률(비용 뺌) 또는 None(다음 날 가격 없음)."""
    buy = reg[k][1]
    if mode == "손절·다음날":
        tgt = None
    elif mode == "절반+2R·추적":
        tgt = buy + 2 * (buy - stop)
    else:
        tgt = buy * 1.02
    half = None
    cur = stop
    peak = buy
    for j in range(k, len(reg)):
        t, o, h, l, cl, _ = reg[j]
        if mode == "반반15:19" and t > time(15, 19):
            last = reg[j - 1][4]
            return ((half or last) + last) / 2 / buy - 1 - E.COST
        if l <= cur:
            px = min(o, cur)
            if half is None:
                return px / buy - 1 - E.COST
            return (half + px) / 2 / buy - 1 - E.COST
        if tgt and half is None and h >= tgt:
            half = max(o, tgt)
            peak = max(peak, h)
            if mode != "반반15:19":
                cur = max(cur, buy, peak * 0.97)   # 다음 봉부터 적용 (체결 봉 안에서는 순서를 모름)
            continue
        peak = max(peak, h)
        if half is not None and mode != "반반15:19":
            cur = max(cur, buy, peak * 0.97)
    if mode == "반반15:19":
        last = reg[-1][4]
        return ((half or last) + last) / 2 / buy - 1 - E.COST
    ex = E.next_day_exits(c, d, buy)
    if "09:00 시가" not in ex:
        return None
    rest = ex["09:00 시가"] + E.COST + 1     # 가격 비율
    if half is None:
        r = rest - 1 - E.COST
    else:
        r = (half / buy + rest) / 2 - 1 - E.COST
    return r if abs(r) <= 0.35 else None


def main():
    days = E.days()
    trades = []          # dict
    sim_cache = {}
    checked = 0
    mism = 0
    for di, d in enumerate(days):
        if E.next_day(d) is None:
            continue
        p = E.prev_day(d)
        vr = E.value_rank(p)
        uni = [c for c, r in vr.items() if r <= TOP and E.is_common(c)]
        B = E.load_day(uni, d)
        dprev = E.daily_day(p)
        regs, pcs = {}, {}
        for c in uni:
            reg = E.regular(B[c])
            if len(reg) < 30 or c not in dprev:
                continue
            f = E.factor(c, d)
            if not f:
                continue
            regs[c] = reg; pcs[c] = dprev[c][3] * f
        if len(regs) < 50:
            continue
        codes = list(regs)
        # 판정 분 목록과 그 시점 누적 대금 순위 (표본 안)
        minutes = sorted({x[0] for c in codes for x in regs[c] if time(9, 10) <= x[0] <= T_END})
        cum = {}
        for c in codes:
            acc, ts, cs = 0.0, [], []
            for x in regs[c]:
                if x[0] > T_END:
                    break
                acc += x[5] * (x[2] + x[3] + x[4]) / 3
                ts.append(x[0]); cs.append(acc)
            cum[c] = (ts, cs)
        rank = {}
        for t in minutes:
            vals = []
            for c in codes:
                ts, cs = cum[c]
                j = bisect.bisect_left(ts, t) - 1
                vals.append(cs[j] if j >= 0 else 0.0)
            order = np.argsort(-np.array(vals), kind="stable")
            rk = np.empty(len(codes), int); rk[order] = np.arange(1, len(codes) + 1)
            rank[t] = rk
        regime_u = RG.cls(d) == "U"
        for ci, c in enumerate(codes):
            reg = regs[c]
            tl = [x[0] for x in reg]
            pf = {vf: prefix_features(reg, pcs[c], vf) for vf in (time(9, 5),)}   # 모든 창이 09:10 이후 시작 → 09:05 기준
            pf = pf[time(9, 5)]
            # 분별 특징 표
            rows = []
            for t in minutes:
                k = bisect.bisect_left(tl, t)
                if k >= len(reg) or pf[k] is None:
                    continue
                rows.append((t, k, rank[t][ci], *pf[k]))
            if not rows:
                continue
            T = np.array([r[0].hour * 60 + r[0].minute for r in rows])
            K = np.array([r[1] for r in rows]); RK = np.array([r[2] for r in rows])
            A = np.array([r[3:] for r in rows], float)
            eff, fo, gap, vws, nh, pull = A[:, 0], A[:, 1], A[:, 2], A[:, 3], A[:, 4], A[:, 5]
            base = (RK <= CFG.max_rank) & (gap <= CFG.max_gap) & (eff >= CFG.min_eff) & (vws >= CFG.min_vwap_share) & (pull <= CFG.max_pull)
            if not base.any():
                continue
            both = E.both_buy(c, p)
            for w in WINDOWS:
                inw = (T >= w[0].hour * 60 + w[0].minute) & (T <= w[1].hour * 60 + w[1].minute) & base
                if not inw.any():
                    continue
                for n_h in NEW_HIGHS:
                    for fmin in FROM_OPEN:
                        for cap in CAPS:
                            m = inw & (nh >= n_h) & (fo >= fmin)
                            if cap is not None:
                                m &= fo <= cap
                            if not m.any():
                                continue
                            i = int(np.argmax(m)); k = int(K[i])
                            price, low10 = A[i, 6], A[i, 7]
                            stop = stop_price(price, low10, CFG)
                            buy = reg[k][1]
                            key = (c, d, k)
                            if key not in sim_cache:
                                sim_cache[key] = {mode: simulate(reg, k, stop, c, d, mode) for mode in EXITS + ["반반15:19"]}
                                if random.random() < 0.02:   # 쌓아 계산한 특징 = live.features 확인
                                    checked += 1
                                    bb = [dict(ts=datetime.combine(d, x[0]), open=x[1], high=x[2], low=x[3], close=x[4], volume=x[5]) for x in reg[:k]]
                                    f = features(bb, pcs[c])
                                    if abs(f["eff"] - A[i, 0]) > 1e-9 or f["new_highs"] != A[i, 4] or abs(f["pull"] - A[i, 5]) > 1e-9 \
                                            or (A[i, 3] >= 0 and abs(f["vwap_share"] - A[i, 3]) > 1e-9):
                                        mism += 1
                            sims = sim_cache[key]
                            trades.append(dict(v=(wname(w), n_h, fmin, cap), d=d, c=c, t=reg[k][0], up=regime_u and both,
                                               fo=buy / reg[0][1] - 1, risk=max(1 - stop / buy, 0.005), sims=sims))
        # 메모리: 지난 날 1분봉 버림
        for key in [k for k in E._bars_cache if k[1] < p]:
            del E._bars_cache[key]
        if di % 20 == 0:
            print(f"[{d}] 누적 {len(trades)} 행", flush=True)

    rep = E.Report.__new__(E.Report)
    rep.f = open(os.path.join(OUT_DIR, "early.txt"), "w", encoding="utf-8")
    rep.say(f"🎯 주도주 모양 이른 판정 1년 시험 {days[0]}~{days[-1]} — 전날 대금 상위 {TOP} 보통주, 그 시점 대금 100위는 이 표본 안 순위")
    rep.say(f"특징값 확인: {checked}건 중 live.features 와 다른 것 {mism}건. 다음 날 가격 맞춤 {dict(E.BASIS_FIX)}")
    rep.say("열: 건수·일수·건당·합계(100만/건, 만)·최고5일 빼면·앞/뒤 반·승률·낙폭 | 하루 평균 건수·기대값 R·손익비·매수 때 시가 대비·손절까지")
    rep.say("")

    def line(xs, mode, title):
        tr = [(x["d"], x["sims"][mode]) for x in xs if x["sims"][mode] is not None]
        st = rep.stats(tr, title, width=46)
        if not st:
            return None
        ok = [x for x in xs if x["sims"][mode] is not None]
        rr = np.array([x["sims"][mode] / x["risk"] for x in ok])
        v = np.array([x["sims"][mode] for x in ok])
        win, loss = v[v > 0], v[v <= 0]
        pf = (win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else float("nan")
        nd = len({x["d"] for x in ok})
        rep.say(f"   {'':46s} 하루 {len(ok) / 249:.2f}건(있는 날 {len(ok) / nd:.1f}) 기대값 {rr.mean():+.2f}R 손익비 {pf:.2f} "
                f"매수 때 시가 대비 {np.mean([x['fo'] for x in ok]):+.1%} 손절까지 {np.mean([x['risk'] for x in ok]):.1%}")
        st.update(title=title, mode=mode, R=rr.mean(), pf=pf)
        return st

    byv = defaultdict(list)
    for x in trades:
        byv[x["v"]].append(x)
    summary = []
    for part, flt in (("전체 날", lambda x: True), ("강한 상승장 + 전날 외인·기관 둘 다 순매수", lambda x: x["up"])):
        rep.say(f"===== {part} =====")
        for w in WINDOWS:
            for n_h in NEW_HIGHS:
                for fmin in FROM_OPEN:
                    for cap in CAPS:
                        v = (wname(w), n_h, fmin, cap)
                        xs = [x for x in byv.get(v, []) if flt(x)]
                        lab = f"{v[0]} 신고가≥{n_h} 시가≥+{fmin:.0%}{' ≤+5%' if cap else ''}"
                        rep.say(f"-- {lab}")
                        modes = EXITS + (["반반15:19"] if w == WINDOWS[-1] and n_h == 5 and fmin == 0.02 and cap is None else [])
                        for mode in modes:
                            st = line(xs, mode, f"{mode}")
                            if st:
                                st.update(part=part, var=lab)
                                summary.append(st)
            rep.say("")
    rep.say("===== 요약: 기대값(건당) 높은 순 상위 15 (30건 이상) =====")
    for st in sorted([s for s in summary if s["n"] >= 30], key=lambda s: -s["mean"])[:15]:
        rep.say(f" {'★' if st['star'] else ' '} [{st['part'][:4]}] {st['var']:32s} {st['mode']:12s} {st['n']:4d}건 건당 {st['mean']:+.2%} "
                f"{st['R']:+.2f}R 손익비 {st['pf']:.2f} 앞 {st['a']:+.2%} 뒤 {st['b']:+.2%}")
    rep.say(f"★ 개수: {sum(s['star'] for s in summary)} / 비교 {len(summary)}개 (15건 이상)")


if __name__ == "__main__":
    main()
