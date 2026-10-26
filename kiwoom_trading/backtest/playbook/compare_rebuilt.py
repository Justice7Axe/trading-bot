"""보존본(data/backtest/playbook) 과 다시 만든 입력(data/backtest/playbook_rebuilt) 비교 — 매매표 계좌가 실제로 쓰는 행만.

  ④ closebet.pkl  : D 날 · 대금 30위 · 시장 대비 +3%p↑ (events_15 와 같은 거르기), 수익률 ex['open']
  ⑥ np_cands.pkl  : U·N+ 날 · vrank ≤ 10 · E52(11:00 전) 또는 E10(시가 > 52주 고가 & 시가 위), 수익률 ex[(None, 0.04, 'n')]
  ⑤ inv_bars.pkl  : 날짜별 봉 (다시 받은 경우만)
행 열쇠 (date, code[, kind, t]) 일치율, 같은 열쇠의 수익률 차이, 전체 행 수를 보여 준다.

실행: python -m kiwoom_trading.backtest.playbook.compare_rebuilt
"""
import os
import pickle
import sys
from datetime import time

import numpy as np

from kiwoom_trading.backtest.playbook.paths import PB, REBUILT
from kiwoom_trading.backtest.playbook.regime import cls


def _cb(r):
    return r["chg"] < 0.295 and cls(r["date"]) == "D" and "open" in r["ex"] and abs(r["ex"]["open"]) < 0.3 \
        and r["rk"] <= 30 and r["chg"] - r["mkt"] >= 0.03


def _np(r):
    if cls(r["date"]) not in ("U", "N+") or r["vrank"] > 10:
        return False
    return (r["kind"] == "E52" and r["t"] <= time(11, 0)) or (r["kind"] == "E10" and r["open_over52"] and r["from_open"] > 0)


SPECS = {
    "closebet.pkl": (_cb, lambda r: (r["date"], r["code"]), lambda r: r["ex"]["open"]),
    "np_cands.pkl": (_np, lambda r: (r["date"], r["code"], r["kind"], r["t"]), lambda r: r["ex"][(None, 0.04, "n")]),
}


def _same(a, b):
    """두 값이 같은가 (dict 는 칸마다, 숫자는 1e-9 안, NaN 끼리는 같음)."""
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if a is None or b is None:
        return a is None and b is None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return (fa != fa and fb != fb) or abs(fa - fb) <= 1e-9 * max(1.0, abs(fa))


def _load(d, name):
    p = os.path.join(d, name)
    return pickle.load(open(p, "rb")) if os.path.exists(p) else None


def compare(name, show=8):
    old, new = _load(PB, name), _load(REBUILT, name)
    if new is None:
        print(f"## {name}: 다시 만든 파일 없음"); return
    if name == "inv_bars.pkl":
        same = [d for d in old if d in new and old[d] == new[d]]
        print(f"## {name}: 보존본 {len(old)}일 · 새 {len(new)}일 · 봉까지 같은 날 {len(same)}"); return
    f, key, ret = SPECS[name]
    print(f"## {name}: 전체 행 보존본 {len(old):,} · 새 {len(new):,}")
    ka = {key(r) for r in old}; kb = {key(r) for r in new}
    print(f"  전체 열쇠 일치 {len(ka & kb):,} · 보존본에만 {len(ka - kb):,} · 새것에만 {len(kb - ka):,}")
    nb = {key(r): r for r in new}
    full = sum(1 for r in old if key(r) in nb and _same(r, nb[key(r)]))
    print(f"  모든 칸(특징·매도 수익률 전부)까지 같은 행 {full:,} / {len(old):,}")
    A = {key(r): ret(r) for r in old if f(r)}; B = {key(r): ret(r) for r in new if f(r)}
    both = sorted(set(A) & set(B))
    print(f"  필터 통과 보존본 {len(A)} · 새 {len(B)} · 일치 {len(both)} ({len(both) / max(len(A), 1) * 100:.1f}%)")
    if both:
        dif = np.array([B[k] - A[k] for k in both], dtype=float)
        ok = np.isclose(dif, 0, atol=1e-9) | (np.isnan([A[k] for k in both]) & np.isnan([B[k] for k in both]))
        print(f"  같은 열쇠 수익률: 같음 {int(ok.sum())} · 다름 {int((~ok).sum())} · 최대 차 {np.nanmax(np.abs(dif)) * 100:.4f}%p")
    sa = sum(v for v in A.values() if v == v); sb = sum(v for v in B.values() if v == v)
    print(f"  수익률 합 보존본 {sa * 100:+.2f}% · 새 {sb * 100:+.2f}% (건당 {sa / max(len(A), 1) * 100:+.3f}% / {sb / max(len(B), 1) * 100:+.3f}%)")
    for lab, ks in (("보존본에만", sorted(set(A) - set(B))), ("새것에만", sorted(set(B) - set(A)))):
        if ks:
            print(f"  {lab}: " + ", ".join(str(k) for k in ks[:show]) + (" …" if len(ks) > show else ""))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for n in ("closebet.pkl", "np_cands.pkl", "inv_bars.pkl"):
        compare(n)


if __name__ == "__main__":
    main()
