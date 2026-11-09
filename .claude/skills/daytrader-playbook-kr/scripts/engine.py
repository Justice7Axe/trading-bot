"""백테스트 엔진: 체결 시뮬레이션, 포트폴리오(리스크 사이징/일일 손실 규칙), 성과 지표, 리포트.

체결 규칙 (보수적):
- 신호는 바 '종가'에서 확정 -> 다음 바 시가 + 슬리피지로 진입.
- 같은 바에서 손절/목표가 모두 닿으면 손절이 먼저 체결된 것으로 본다.
- 손절: 시가가 이미 손절가를 넘어 갭이면 시가로 체결(+슬리피지).
- 목표가(지정가): 목표가를 conservative_target_ticks 틱 이상 '통과'해야 체결.
- 종가 기준 청산 신호 -> 다음 바 시가 청산. VI 단일가 구간 바에서는 체결하지 않는다.
- flat_time 이후 첫 바 시가에 전량 청산 (데이트레이딩: 오버나잇 없음).
"""
from __future__ import annotations

import csv
import heapq
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field


@dataclass
class Leg:
    t: object
    price: float
    frac: float
    reason: str


@dataclass
class TradePlan:
    strategy: str
    symbol: str
    side: str  # "long" | "short"
    signal_t: object
    entry_t: object
    entry: float
    stop: float  # 최초 손절가 (R 계산 기준)
    legs: list
    risk_mult: float = 1.0
    fixed_qty: int | None = None
    grade: str = "A"
    tags: dict = field(default_factory=dict)

    @property
    def exit_t(self):
        return self.legs[-1].t


def simulate_exit(bars, entry_idx, side, entry, stop, inst, *, targets=(), be_after_first=False,
                  exit_on_close=None, trail_atr=None, atr_vals=None, flat_time=None, blocked=frozenset(),
                  conservative_target_ticks=1):
    """entry_idx 바 시가에 진입했다고 보고 청산 경로를 시뮬레이션한다. (legs, exit_idx) 반환."""
    long = side == "long"
    sgn = 1 if long else -1
    remaining, legs = 1.0, []
    cur_stop, ti, best = stop, 0, entry
    pending = None
    last_i = entry_idx
    for i in range(entry_idx, len(bars)):
        b = bars[i]
        last_i = i
        if i in blocked:
            continue
        if flat_time and b.t.time() >= flat_time and i > entry_idx:
            legs.append(Leg(b.t, inst.slip(b.o, -sgn), remaining, "time"))
            return legs, i
        if pending:
            legs.append(Leg(b.t, inst.slip(b.o, -sgn), remaining, pending))
            return legs, i
        # 1) 손절 우선
        if (long and b.l <= cur_stop) or ((not long) and b.h >= cur_stop):
            px = min(cur_stop, b.o) if long else max(cur_stop, b.o)
            reason = "stop" if cur_stop == stop else ("breakeven" if cur_stop == entry else "trail")
            legs.append(Leg(b.t, inst.slip(px, -sgn), remaining, reason))
            return legs, i
        # 2) 목표가
        while ti < len(targets):
            tp, frac = targets[ti]
            k = conservative_target_ticks * inst.tick_at(tp)
            hit = b.h >= tp + k if long else b.l <= tp - k
            if not hit:
                break
            px = max(tp, b.o) if long else min(tp, b.o)
            f = min(frac, remaining)
            if f > 1e-9:
                legs.append(Leg(b.t, px, f, f"target{ti + 1}"))
                remaining -= f
            ti += 1
            if be_after_first:
                cur_stop = max(cur_stop, entry) if long else min(cur_stop, entry)
        if remaining <= 1e-9:
            return legs, i
        # 3) 트레일링
        if trail_atr and atr_vals is not None:
            best = max(best, b.c) if long else min(best, b.c)
            trail = best - sgn * trail_atr * atr_vals[i]
            cur_stop = max(cur_stop, trail) if long else min(cur_stop, trail)
        # 4) 종가 기준 재량 청산 신호 -> 다음 바 시가
        if exit_on_close:
            r = exit_on_close(i)
            if r:
                pending = r
    b = bars[last_i]
    legs.append(Leg(b.t, inst.slip(b.c, -sgn), remaining, "eod"))
    return legs, last_i


def next_unblocked(idx, n, blocked):
    while idx < n and idx in blocked:
        idx += 1
    return idx if idx < n else None


# ---------------------------------------------------------------- 포트폴리오

def _split_qty(qty, legs, integer=True):
    out, used = [], 0
    for j, lg in enumerate(legs):
        if j == len(legs) - 1:
            out.append(qty - used)
        else:
            q = int(round(qty * lg.frac)) if integer else qty * lg.frac
            q = min(q, qty - used)
            out.append(q)
            used += q
    return out


def run_portfolio(plans, inst, *, initial_equity, risk_pct, max_positions, max_losses_per_day,
                  daily_loss_limit_pct, max_notional_pct):
    plans = sorted(plans, key=lambda p: (p.entry_t, p.symbol))
    equity = initial_equity
    heap, seq = [], 0
    open_count = 0
    day_start_eq, day_losses, day_pnl = {}, defaultdict(int), defaultdict(float)
    results, skipped = [], defaultdict(int)

    def realize(until):
        nonlocal equity, open_count
        while heap and (until is None or heap[0][0] <= until):
            _, _, rec = heapq.heappop(heap)
            equity += rec["net"]
            d = rec["exit_t"].date()
            day_pnl[d] += rec["net"]
            if rec["net"] < 0:
                day_losses[d] += 1
            open_count -= 1
            rec["equity_after"] = equity

    for p in plans:
        realize(p.entry_t)
        d = p.entry_t.date()
        day_start_eq.setdefault(d, equity)
        if day_losses[d] >= max_losses_per_day:
            skipped["max_losses_per_day"] += 1
            continue
        if day_pnl[d] <= -day_start_eq[d] * daily_loss_limit_pct / 100:
            skipped["daily_loss_limit"] += 1
            continue
        if open_count >= max_positions:
            skipped["max_positions"] += 1
            continue
        if p.risk_mult <= 0:
            skipped["grade_D"] += 1
            continue
        per_unit = abs(p.entry - p.stop) * inst.multiplier
        per_unit += inst.cost(p.entry, 1, p.side == "short", False) + inst.cost(p.stop, 1, p.side == "long", True)
        risk_amt = equity * risk_pct / 100 * p.risk_mult
        if p.fixed_qty:
            qty = int(p.fixed_qty)
        else:
            qty = int(math.floor(risk_amt / per_unit)) if per_unit > 0 else 0
        if inst.kind == "stock":
            qty = min(qty, int(equity * max_notional_pct / 100 // p.entry))
        if qty < 1:
            skipped["qty_lt_1"] += 1
            continue
        sgn = 1 if p.side == "long" else -1
        qtys = _split_qty(qty, p.legs)
        gross = sum(q * (lg.price - p.entry) * sgn * inst.multiplier for q, lg in zip(qtys, p.legs))
        costs = inst.cost(p.entry, qty, p.side == "short", False)
        costs += sum(inst.cost(lg.price, q, p.side == "long", p.side == "long") for q, lg in zip(qtys, p.legs))
        net = gross - costs
        init_risk = abs(p.entry - p.stop) * inst.multiplier * qty
        rec = {
            "strategy": p.strategy, "symbol": p.symbol, "side": p.side, "grade": p.grade,
            "signal_t": p.signal_t, "entry_t": p.entry_t, "exit_t": p.exit_t,
            "entry": p.entry, "stop": p.stop, "qty": qty,
            "exits": ";".join(f"{lg.t:%H:%M}@{lg.price:g}x{q}({lg.reason})" for q, lg in zip(qtys, p.legs)),
            "exit_reason": p.legs[-1].reason,
            "gross": round(gross, 2), "costs": round(costs, 2), "net": round(net, 2),
            "R": round(net / init_risk, 3) if init_risk > 0 else 0.0,
            "risk_amt": round(init_risk, 2),
            "hold_min": round((p.exit_t - p.entry_t).total_seconds() / 60, 1),
            "equity_before": round(equity, 2),
            "tags": json.dumps(p.tags, ensure_ascii=False, default=str),
        }
        seq += 1
        heapq.heappush(heap, (p.exit_t, seq, rec))
        open_count += 1
        results.append(rec)
    realize(None)
    return results, dict(skipped)


# ---------------------------------------------------------------- 지표/리포트

def metrics(results, initial_equity):
    if not results:
        return {"trades": 0}
    rs = sorted(results, key=lambda r: r["exit_t"])
    nets = [r["net"] for r in rs]
    Rs = [r["R"] for r in rs]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    eq, peak, mdd = initial_equity, initial_equity, 0.0
    for x in nets:
        eq += x
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak if peak > 0 else 0)
    streak = mx = 0
    for x in nets:
        streak = streak + 1 if x <= 0 else 0
        mx = max(mx, streak)
    daily = defaultdict(float)
    for r in rs:
        daily[r["exit_t"].date()] += r["net"]
    eq, dr = initial_equity, []
    for d in sorted(daily):
        dr.append(daily[d] / eq if eq > 0 else 0)
        eq += daily[d]
    sharpe = (statistics.mean(dr) / statistics.pstdev(dr) * math.sqrt(252)) if len(dr) > 1 and statistics.pstdev(dr) > 0 else None
    top5 = sorted(nets, reverse=True)[:5]
    by_year = defaultdict(lambda: [0, 0.0])
    for r in rs:
        y = r["exit_t"].year
        by_year[y][0] += 1
        by_year[y][1] += r["net"]
    by_grade = defaultdict(lambda: [0, 0.0])
    for r in rs:
        by_grade[r["grade"]][0] += 1
        by_grade[r["grade"]][1] += r["R"]
    reasons = defaultdict(int)
    for r in rs:
        reasons[r["exit_reason"]] += 1
    gl = -sum(losses)
    return {
        "trades": len(rs),
        "win_rate": round(len(wins) / len(rs), 4),
        "net_pnl": round(sum(nets), 2),
        "return_pct": round(sum(nets) / initial_equity * 100, 2),
        "profit_factor": round(sum(wins) / gl, 3) if gl > 0 else None,
        "expectancy_R": round(statistics.mean(Rs), 4),
        "avg_win_R": round(statistics.mean([r for r in Rs if r > 0]), 3) if any(r > 0 for r in Rs) else None,
        "avg_loss_R": round(statistics.mean([r for r in Rs if r <= 0]), 3) if any(r <= 0 for r in Rs) else None,
        "max_drawdown_pct": round(mdd * 100, 2),
        "max_consecutive_losses": mx,
        "sharpe_daily_annualized": round(sharpe, 3) if sharpe is not None else None,
        "avg_hold_min": round(statistics.mean(r["hold_min"] for r in rs), 1),
        "total_costs": round(sum(r["costs"] for r in rs), 2),
        "net_without_top5": round(sum(nets) - sum(top5), 2),
        "by_year": {str(k): {"trades": v[0], "net": round(v[1], 2)} for k, v in sorted(by_year.items())},
        "by_grade_avgR": {k: {"trades": v[0], "avg_R": round(v[1] / v[0], 3)} for k, v in sorted(by_grade.items())},
        "exit_reasons": dict(reasons),
    }


def write_trades_csv(results, path):
    if not results:
        open(path, "w").close()
        return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        for r in results:
            w.writerow(r)


def acceptance(m, crit):
    """사전 정의한 합격 기준 체크. crit 예: {"min_trades":200,"min_expectancy_R":0.1,...}"""
    if not m.get("trades"):
        return {"pass": False, "fails": ["no trades"]}
    fails = []
    if m["trades"] < crit["min_trades"]:
        fails.append(f"trades {m['trades']} < {crit['min_trades']}")
    if m["expectancy_R"] < crit["min_expectancy_R"]:
        fails.append(f"expectancy_R {m['expectancy_R']} < {crit['min_expectancy_R']}")
    if (m["profit_factor"] or 0) < crit["min_profit_factor"]:
        fails.append(f"PF {m['profit_factor']} < {crit['min_profit_factor']}")
    if m["max_drawdown_pct"] > crit["max_drawdown_pct"]:
        fails.append(f"MDD {m['max_drawdown_pct']}% > {crit['max_drawdown_pct']}%")
    if m["net_without_top5"] <= 0:
        fails.append("상위 5개 트레이드 제외 시 손실 (소수 대박 의존)")
    return {"pass": not fails, "fails": fails}


DEFAULT_CRITERIA = {"min_trades": 200, "min_expectancy_R": 0.10, "min_profit_factor": 1.2, "max_drawdown_pct": 15.0}


def write_report(path, title, meta, sections):
    lines = [f"# {title}", ""]
    for k, v in meta.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    for name, m, acc in sections:
        lines.append(f"## {name}")
        if not m.get("trades"):
            lines += ["트레이드 없음", ""]
            continue
        lines.append("| 지표 | 값 |")
        lines.append("|---|---|")
        for k, v in m.items():
            if isinstance(v, dict):
                continue
            lines.append(f"| {k} | {v} |")
        for k in ("by_year", "by_grade_avgR", "exit_reasons"):
            lines.append(f"\n**{k}**: `{json.dumps(m.get(k, {}), ensure_ascii=False)}`")
        if acc is not None:
            lines.append(f"\n**합격 기준**: {'통과' if acc['pass'] else '불합격'} {'; '.join(acc['fails'])}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
