"""Position sizing for Korean stocks (long only), Nada-style fixed-risk rules.

Usage:
  python position_size.py --account 30000000 --risk 0.5 --entry 10000 --stop 9700 --target 10600
Options:
  --fee   one-way commission %, default 0.015
  --tax   sell-side transaction tax %, default 0.20 (assumption; check current law)
  --slip  slippage % per side, default 0.05
"""
import argparse
import math


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account", type=float, required=True, help="account size (KRW)")
    p.add_argument("--risk", type=float, default=0.5, help="risk per trade, %% of account (0.5 default, max 1)")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--target", type=float)
    p.add_argument("--fee", type=float, default=0.015)
    p.add_argument("--tax", type=float, default=0.20)
    p.add_argument("--slip", type=float, default=0.05)
    a = p.parse_args()

    if a.stop >= a.entry:
        raise SystemExit("long only: stop must be below entry")
    warnings = []
    if a.risk > 1:
        warnings.append(f"risk {a.risk}% exceeds 1% rule")

    fee, tax, slip = a.fee / 100, a.tax / 100, a.slip / 100
    # cost per share at the stop: buy fee+slip on entry, sell fee+tax+slip on exit
    cost_at_stop = a.entry * (fee + slip) + a.stop * (fee + tax + slip)
    loss_per_share = (a.entry - a.stop) + cost_at_stop
    risk_krw = a.account * a.risk / 100
    qty = math.floor(risk_krw / loss_per_share)
    notional = qty * a.entry

    print(f"risk budget      : {risk_krw:,.0f} KRW ({a.risk}% of {a.account:,.0f})")
    print(f"loss/share (net) : {loss_per_share:,.1f} KRW (stop distance {(a.entry - a.stop) / a.entry * 100:.2f}%)")
    print(f"quantity         : {qty:,} shares")
    print(f"position size    : {notional:,.0f} KRW ({notional / a.account * 100:.1f}% of account)")
    print(f"actual max loss  : {qty * loss_per_share:,.0f} KRW")

    if notional > a.account:
        warnings.append("position exceeds account size (would need margin) -> widen nothing, reduce qty or skip")

    if a.target:
        cost_at_target = a.entry * (fee + slip) + a.target * (fee + tax + slip)
        gain_per_share = (a.target - a.entry) - cost_at_target
        rr = gain_per_share / loss_per_share
        print(f"gain/share (net) : {gain_per_share:,.1f} KRW")
        print(f"net R:R          : 1:{rr:.2f}")
        if rr < 2:
            warnings.append(f"net R:R {rr:.2f} < 2 -> skip or improve entry/target")
        min_target = a.entry + 2 * loss_per_share + cost_at_target
        print(f"min target for 1:2 (approx): {min_target:,.0f} KRW")

    for w in warnings:
        print("WARNING:", w)
    print("note: round prices to your broker's tick size.")


if __name__ == "__main__":
    main()
