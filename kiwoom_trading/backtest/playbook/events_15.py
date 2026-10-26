"""매매표 ①~⑤ 매매 기록 (원래 d9b9b62e/compound.py — PR #60+#61 시장 상황별 매매표).

  U  : ② 저항 돌파 100만 · ③ 막힌 고점 +7/−5 100만 · ① 상승장 장 초(대금 40 시가 위, 익절 없음/−4, 전날 외인·기관 둘 다 − 제외) 25만
  N+ : ② · ③ +7/−3
  N- : ② · ⑤ 인버스 09:11 +5/−3
  D  : ② · ④ 역행 강세 종가 → 다음날 시가
build() → (T, days): T = [(date, 매매, 시드 1천만 기준 금액, 수익률, (신호 시각, 순서))].
`python -m kiwoom_trading.backtest.playbook.events_15` 는 ①~⑤ 만의 고정·복리 계좌 결과를 보여 준다 (옛 compound.py 출력).
"""
import pickle
import sys
from collections import defaultdict
from datetime import date, time

import duckdb
import numpy as np

from kiwoom_trading.backtest.playbook.paths import INV_DAILY_DB, pb
from kiwoom_trading.backtest.playbook.regime import BAD, SPLIT, cls, feat

SEED = 10_000_000
ORDER = {"② 저항 돌파": 0, "③ 막힌 고점 돌파": 1, "⑤ 약세장 인버스": 2, "① 상승장 장 초": 3, "④ 역행 강세 종가": 4}


def _inv_trade(inv, idays, d, tp=0.05, sl=0.03):
    bars = inv[d]; i = idays.index(d)
    if i + 1 >= len(idays): return None
    k = next((j for j, b in enumerate(bars) if b["ts"].time() >= time(9, 11)), None)
    if k is None: return None
    e = bars[k]["open"]; hi = e * (1 + tp); lo = e * (1 - sl)
    for b in bars[k:]:
        if b["ts"].time() >= time(15, 20): break
        if b["low"] <= lo: return min(b["open"], lo) / e - 1 - 0.0005
        if b["high"] >= hi: return max(b["open"], hi) / e - 1 - 0.0005
    return inv[idays[i + 1]][0]["open"] / e - 1 - 0.0005


def build(with_code: bool = False):
    """with_code=True 면 각 매매 끝에 종목코드를 붙인다 (⑤ 인버스는 '123310')."""
    days = sorted(d for d in feat if cls(d))
    T = []
    rows, info = pickle.load(open(pb("u_cands.pkl"), "rb"))
    rows = [r for r in rows if all(abs(v) < 0.4 for v in r["ex"].values())]
    for r in rows:   # U ①
        if r["T"] == time(9, 10) and cls(r["date"]) == "U" and r["vrank"] <= 40 and r["from_open"] > 0 \
                and r["fr"] is not None and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0):
            T.append((r["date"], "① 상승장 장 초", 250_000, r["ex"][(None, 0.04)], (time(9, 10), r["vrank"])) + ((r["code"],) if with_code else ()))
    for r in pickle.load(open(pb("resbo2.pkl"), "rb")):   # ③ (U −5%, N+ −3%)
        c = cls(r["date"])
        if (r["code"], r["date"]) in BAD or c not in ("U", "N+"): continue
        if r["N"] == 5 and r["entry"] == "E1" and r["sig_t"] < time(9, 30) and r["vr"] >= 0.10 and not r["gap_over"]:
            T.append((r["date"], "③ 막힌 고점 돌파", 1_000_000, r[(0.07, "sl5" if c == "U" else "sl3")], (r["sig_t"], 0)) + ((r["code"],) if with_code else ()))
    dm = duckdb.connect(INV_DAILY_DB, read_only=True)   # ② 모든 날
    sh = dict(dm.execute("SELECT code, listed_shares FROM stocks").fetchall())
    dm.close()
    for r in pickle.load(open(pb("g2g_filter.pkl"), "rb")):
        if "m7" not in r or (r["code"], r["date"]) in BAD or not cls(r["date"]): continue
        if (sh.get(r["code"]) or 0) * r["e"] >= 2e11 and r["bo_cum"] >= 1 and r["bo_t"] >= time(9, 10):
            T.append((r["date"], "② 저항 돌파", 1_000_000, r["m7"][0.05], (r["bo_t"], 0)) + ((r["code"],) if with_code else ()))
    for r in pickle.load(open(pb("closebet.pkl"), "rb")):   # ④ D
        if r["chg"] >= 0.295 or cls(r["date"]) != "D" or "open" not in r["ex"] or abs(r["ex"]["open"]) >= 0.3: continue
        if r["rk"] <= 30 and r["chg"] - r["mkt"] >= 0.03:
            T.append((r["date"], "④ 역행 강세 종가", 1_000_000, r["ex"]["open"], (time(15, 20), r["rk"])) + ((r["code"],) if with_code else ()))
    inv = pickle.load(open(pb("inv_bars.pkl"), "rb")); idays = sorted(d for d in inv if inv[d])   # ⑤ N- 인버스
    for d in days:
        if cls(d) == "N-" and d in inv and inv[d]:
            x = _inv_trade(inv, idays, d)
            if x is not None:
                T.append((d, "⑤ 약세장 인버스", 1_000_000, x, (time(9, 11), 0)) + (("123310",) if with_code else ()))
    return T, days


def run(T, days, compound: bool, seed=SEED, cap_ratio=1.0):
    byd = defaultdict(list)
    for d, k, a, r, tk, *_ in T: byd[d].append((tk, k, a, r))   # 신호 시각 순서대로 돈을 채움 (실제 모의투자와 같음)
    s = seed; curve = []; kinds = defaultdict(float); used = []
    for d in days:
        scale = s / SEED if compound else 1.0
        left = (s if compound else SEED) * cap_ratio; pnl = 0.0; u = 0.0
        for _, k, a, r in sorted(byd.get(d, []), key=lambda x: x[0]):
            take = min(a * scale, left)
            if take <= 0: break
            left -= take; u += take; pnl += take * r; kinds[k] += take * r
        s += pnl; curve.append((d, s)); used.append(u)
    return s, curve, kinds, used


def mdd(curve):
    v = np.array([x for _, x in curve]); peak = np.maximum.accumulate(np.r_[SEED, v])[1:]
    i = int(np.argmax((peak - v) / peak)); return (peak[i] - v[i]) / peak[i], peak[i] - v[i], curve[i][0]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T, days = build()
    print(f"기간 {days[0]} ~ {days[-1]} ({len(days)}거래일), 시작 시드 1,000만 원, 비용 포함(주식 0.25%, 인버스 0.05%)")
    print(f"매매 {len(T):,}건: " + ", ".join(f"{k} {sum(1 for t in T if t[1] == k)}" for k in ORDER))
    print()
    for lab, comp in (("고정 시드 (수익은 따로 빼 둠)", False), ("복리 (수익을 시드에 계속 더함)", True)):
        fin, curve, kinds, used = run(T, days, comp)
        dd, ddw, ddd = mdd(curve)
        print(f"## {lab}")
        print(f"  최종 {fin/1e4:,.0f}만 원  (수익 {(fin-SEED)/1e4:+,.0f}만, {fin/SEED*100-100:+.0f}%)  최대 낙폭 {dd*100:.1f}% ({ddw/1e4:,.0f}만, {ddd})")
        print("  매매별 손익: " + " · ".join(f"{k} {v/1e4:+,.0f}만" for k, v in sorted(kinds.items(), key=lambda x: ORDER[x[0]])))
        bym = {}
        for d, v in curve: bym[d.strftime("%y-%m")] = v
        prev = SEED; parts = []
        for m, v in bym.items(): parts.append(f"{m} {v/1e4:,.0f}만({(v/prev-1)*100:+.1f}%)"); prev = v
        print("  월말 시드: " + " · ".join(parts))
        half = [v for d, v in curve if d < SPLIT][-1]
        print(f"  앞 반기 끝 {half/1e4:,.0f}만 → 뒤 반기 {(fin/half-1)*100:+.1f}%")
        print()


if __name__ == "__main__":
    main()
