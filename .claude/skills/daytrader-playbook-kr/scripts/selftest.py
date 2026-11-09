"""스모크 테스트: 합성 데이터로 5개 전략을 모두 돌리고 엔진 불변조건을 검사한다.

  python scripts/selftest.py
코드 수정 후 반드시 다시 실행할 것. (수익률이 아니라 '룩어헤드/비용/체결 규칙'이 지켜지는지 확인)
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import make_sample_data  # noqa: E402
from data import Bar, build_days, load_bars  # noqa: E402
from engine import metrics, run_portfolio, simulate_exit  # noqa: E402
from krx import krx_stock_tick, load_instrument, load_portfolio_defaults  # noqa: E402
from strategies import REGISTRY  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def unit_tests():
    kr = load_instrument("KRX_STOCK")
    check(krx_stock_tick(1999) == 1 and krx_stock_tick(2000) == 5 and krx_stock_tick(49950) == 50, "tick table")
    check(kr.round_tick(10003, "up") == 10010, "round up")
    # 비용: 1만원 * 100주 매수 수수료 150원, 매도 수수료 150 + 거래세 2000
    check(abs(kr.cost(10000, 100, False, False) - 150) < 1e-6, "buy cost")
    check(abs(kr.cost(10000, 100, True, True) - 2150) < 1e-6, "sell cost")
    # 같은 바에서 손절/목표 동시 -> 손절 우선
    t = dt.datetime(2025, 1, 2, 9, 30)
    bars = [Bar(t, 10000, 10000, 10000, 10000, 1), Bar(t + dt.timedelta(minutes=1), 10000, 10500, 9800, 10000, 1)]
    legs, _ = simulate_exit(bars, 1, "long", 10000, 9900, kr, targets=[(10200, 1.0)])
    check(legs[0].reason == "stop" and legs[0].price < 9900, "stop-first & slippage")
    # 갭 하락 손절 -> 시가 체결
    bars2 = [Bar(t, 10000, 10000, 10000, 10000, 1), Bar(t + dt.timedelta(minutes=1), 9700, 9750, 9650, 9700, 1)]
    legs, _ = simulate_exit(bars2, 1, "long", 10000, 9900, kr)
    check(legs[0].price <= 9700, "gap stop fills at open")
    print("unit tests OK")


def strategy_tests(tmp):
    make_sample_data.make_kr(os.path.join(tmp, "kr_1m.csv"))
    make_sample_data.make_nq(os.path.join(tmp, "nq_1m.csv"))
    cases = [(n, "KRX_STOCK", "kr_1m.csv") for n in REGISTRY if n.startswith("kr_")]
    cases += [(n, "MNQ", "nq_1m.csv") for n in REGISTRY if n.startswith("fut_")]
    for name, iname, fn in cases:
        inst = load_instrument(iname)
        days = build_days(load_bars(os.path.join(tmp, fn)), inst)
        strat = REGISTRY[name](inst)
        plans = [p for d in days for p in strat.plans_for_day(d)]
        for p in plans:
            check(p.entry_t > p.signal_t, f"{name}: entry must be after signal bar")
            check(abs(sum(l.frac for l in p.legs) - 1) < 1e-6, f"{name}: legs must sum to 1")
            check(all(l.t >= p.entry_t for l in p.legs), f"{name}: exit before entry")
            if p.side == "long":
                check(p.stop < p.entry, f"{name}: long stop below entry")
            else:
                check(p.stop > p.entry, f"{name}: short stop above entry")
            flat = inst.flat_time
            check(p.exit_t.strftime("%H:%M") <= max(flat, inst.session_end), f"{name}: overnight hold")
        pf = load_portfolio_defaults(inst.currency)
        res, skipped = run_portfolio(plans, inst, **pf)
        m = metrics(res, pf["initial_equity"])
        if res:
            check(all(r["costs"] > 0 for r in res), f"{name}: costs missing")
        print(f"{name:32s} plans={len(plans):4d} trades={m.get('trades', 0):4d} "
              f"expR={m.get('expectancy_R')} skipped={skipped}")


if __name__ == "__main__":
    # 사용법: python scripts/selftest.py [작업폴더]  (임시폴더 권한이 막힌 환경이면 폴더를 지정)
    unit_tests()
    if len(sys.argv) > 1:
        os.makedirs(sys.argv[1], exist_ok=True)
        strategy_tests(sys.argv[1])
    else:
        with tempfile.TemporaryDirectory() as tmp:
            strategy_tests(tmp)
    print("SELFTEST PASSED (합성 데이터 결과의 수익성은 의미 없음)")
