"""백테스트 실행 CLI (표준 라이브러리만).

예)
  python scripts/run_backtest.py --strategy kr_s1_inplay_vwap_pullback --instrument KRX_STOCK \
      --data "data/kr_1m/*.csv" --out results/s1 --split 2025-06-30
  python scripts/run_backtest.py --strategy fut_f2_trullas_divergence --instrument MNQ \
      --data "data/mnq_1m.csv" --out results/f2 --set tf=3 --set sizing=risk
  # 파라미터 민감도 (in-sample 구간에서만 돌린다)
  python scripts/run_backtest.py ... --split 2025-06-30 --grid pullback_atr=0.3,0.5,0.8 --grid min_rvol=2,3,5
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glob  # noqa: E402

from data import build_days, load_bars, load_daily, load_universe  # noqa: E402
from engine import (DEFAULT_CRITERIA, acceptance, metrics, run_portfolio, write_report,  # noqa: E402
                    write_trades_csv)
from krx import load_instrument, load_portfolio_defaults  # noqa: E402
from strategies import REGISTRY  # noqa: E402


def _parse_val(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def generate_plans(strategy_cls, inst, params, days):
    strat = strategy_cls(inst, params)
    plans = []
    for d in days:
        plans.extend(strat.plans_for_day(d))
    return plans


def file_chunks(a):
    """--per-file 이면 CSV 를 한 개씩(메모리 절약), 아니면 전부 한 번에 읽는다. 각 파일은 날짜 단위로 완결돼야 한다."""
    if not a.per_file:
        yield a.data
        return
    files = []
    for p in a.data:
        files.extend(sorted(glob.glob(p)) or [p])
    for f in files:
        yield [f]


def collect(a, cls, inst, param_sets, daily, universe, split, include_oos=True):
    """param_sets 각각에 대해 (IS 계획, OOS 계획, 종목 수, 일수) 를 만든다. 파일을 한 번만 읽는다."""
    out = [([], []) for _ in param_sets]
    syms, dates = set(), set()
    for chunk in file_chunks(a):
        days = build_days(load_bars(chunk, a.label, a.bar_minutes), inst, daily=daily, universe=universe)
        syms.update(d.symbol for d in days)
        dates.update(d.date for d in days)
        is_days = [d for d in days if not split or d.date <= split]
        oos_days = [d for d in days if split and d.date > split] if include_oos else []
        for k, pp in enumerate(param_sets):
            out[k][0].extend(generate_plans(cls, inst, pp, is_days))
            out[k][1].extend(generate_plans(cls, inst, pp, oos_days))
        if a.per_file:
            print("loaded", chunk[0], len(days), "days", flush=True)
    return out, syms, dates


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=sorted(REGISTRY))
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--data", required=True, nargs="+", help="CSV 경로 또는 글롭 패턴")
    ap.add_argument("--out", required=True)
    ap.add_argument("--params", help="파라미터 JSON 파일")
    ap.add_argument("--set", action="append", default=[], help="key=value (값은 JSON 해석)")
    ap.add_argument("--label", default="start", choices=["start", "end"], help="바 타임스탬프가 시작/종료 시각인지")
    ap.add_argument("--bar-minutes", type=int, default=1)
    ap.add_argument("--split", help="YYYY-MM-DD. 이 날짜까지 in-sample, 이후 out-of-sample")
    ap.add_argument("--grid", action="append", default=[], help="key=v1,v2,... (in-sample 에서만 실행)")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--risk", type=float, help="트레이드당 리스크 %% (등급 A 기준)")
    ap.add_argument("--criteria", help="합격 기준 JSON 파일 (기본: engine.DEFAULT_CRITERIA)")
    ap.add_argument("--slippage", type=float, help="편도 슬리피지 틱 수 덮어쓰기 (비용 민감도 테스트)")
    ap.add_argument("--fee-rate", type=float, help="편도 수수료율 덮어쓰기 (예: 0.00015)")
    ap.add_argument("--daily", help="일봉 CSV (date,symbol,OHLCV). 주면 일봉 이력·전일 종가를 여기서 만든다")
    ap.add_argument("--universe", help="매매 대상 CSV (date,symbol). 그 날짜 장 전에 알 수 있는 목록만")
    ap.add_argument("--per-file", action="store_true", help="CSV 를 파일별로 읽어 메모리 절약 (파일은 날짜 단위로 완결)")
    a = ap.parse_args(argv)

    inst = load_instrument(a.instrument)
    if a.slippage is not None:
        inst.slippage_ticks = a.slippage
    if a.fee_rate is not None:
        inst.fee_rate = a.fee_rate
    pf = load_portfolio_defaults(inst.currency)
    if a.equity:
        pf["initial_equity"] = a.equity
    if a.risk:
        pf["risk_pct"] = a.risk
    params = {}
    if a.params:
        with open(a.params, encoding="utf-8") as f:
            params.update(json.load(f))
    for kv in a.set:
        k, v = kv.split("=", 1)
        params[k] = _parse_val(v)
    crit = DEFAULT_CRITERIA
    if a.criteria:
        with open(a.criteria, encoding="utf-8") as f:
            crit = {**crit, **json.load(f)}

    os.makedirs(a.out, exist_ok=True)
    daily = load_daily(a.daily) if a.daily else None
    universe = load_universe(a.universe) if a.universe else None
    split = dt.date.fromisoformat(a.split) if a.split else None
    cls = REGISTRY[a.strategy]

    if a.grid:
        keys, vals = [], []
        for g in a.grid:
            k, v = g.split("=", 1)
            keys.append(k)
            vals.append([_parse_val(x) for x in v.split(",")])
        combos = list(itertools.product(*vals))
        sets, _, _ = collect(a, cls, inst, [{**params, **dict(zip(keys, c))} for c in combos], daily, universe, split,
                           include_oos=False)
        rows = []
        for combo, (is_plans, _) in zip(combos, sets):
            res, _ = run_portfolio(is_plans, inst, **pf)
            m = metrics(res, pf["initial_equity"])
            rows.append({**dict(zip(keys, combo)), **{k: m.get(k) for k in
                         ("trades", "expectancy_R", "profit_factor", "max_drawdown_pct", "return_pct")}})
        with open(os.path.join(a.out, "grid_in_sample.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        for r in rows:
            print(r)
        print("주의: 그리드 결과로 고른 파라미터는 반드시 OOS 에서 '한 번만' 확인할 것")
        return

    [(is_plans, oos_plans)], syms, dates = collect(a, cls, inst, [params], daily, universe, split)
    if not dates:
        sys.exit("데이터 없음: 세션 시간/CSV 형식을 확인하세요")
    ds_dates = {"In-sample": sorted(x for x in dates if not split or x <= split),
                "Out-of-sample": sorted(x for x in dates if split and x > split)}
    sections, all_res = [], []
    for label, plans in (("In-sample", is_plans), ("Out-of-sample", oos_plans)):
        ds = ds_dates[label]
        if not ds:
            continue
        res, skipped = run_portfolio(plans, inst, **pf)
        m = metrics(res, pf["initial_equity"])
        m["skipped"] = skipped
        sections.append((f"{label} ({ds[0]} ~ {ds[-1]})", m, acceptance(m, crit)))
        for r in res:
            r["sample"] = label
        all_res.extend(res)
        with open(os.path.join(a.out, f"summary_{label.lower().replace('-', '_')}.json"), "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1, default=str)
    write_trades_csv(all_res, os.path.join(a.out, "trades.csv"))
    meta = {
        "strategy": a.strategy, "instrument": a.instrument, "params": json.dumps({**cls.DEFAULTS, **params}, ensure_ascii=False),
        "portfolio": json.dumps(pf), "costs": f"fee_rate={inst.fee_rate}, fee/contract={inst.fee_per_contract}, sell_tax={inst.sell_tax_rate}, slippage_ticks={inst.slippage_ticks}",
        "symbols": len(syms), "days": len(dates), "daily": a.daily or "-", "universe": a.universe or "-",
        "criteria": json.dumps(crit), "generated": dt.datetime.now().isoformat(timespec="seconds"),
    }
    write_report(os.path.join(a.out, "report.md"), f"Backtest: {a.strategy}", meta, sections)
    for name, m, acc in sections:
        print(name, {k: m.get(k) for k in ("trades", "win_rate", "expectancy_R", "profit_factor",
                                           "max_drawdown_pct", "return_pct")}, "PASS" if acc["pass"] else "FAIL")
    print("saved:", a.out)


if __name__ == "__main__":
    main()
