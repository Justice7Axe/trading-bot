"""거감음봉 + 다른 정보(외인·기관 수급, 시장 분위기, 대금·시총, 고점 위치) 조합 찾기 — 2026-10-28.

거감음봉 기본 조건(책 그대로)은 고정하고, 다른 정보 필터를 1~2개 더한다.
미래 정보 막기:
  · D1(거래량 급감일) 종가 매수 → D0(폭증일)까지의 수급만 쓴다 (D1 확정 수급은 장 마감 뒤에 나옴).
  · D1 수급 필터를 쓰면 D2 09:00 시가 매수로 바꾼다.
과최적화 막기: 앞 기간(~2025-12)에서 고르고 뒤 기간(2026-01~)에서 확인. 고른 조합 수를 함께 적는다.
수급 자료는 일봉 DB investor_daily (매일 쌓임).
"""
import itertools, os
from collections import defaultdict
from datetime import date
import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.geogam import backtest as B

SPLIT = date(2026, 1, 1)
INV_END = date(2026, 10, 28)
KOSPI = E.KOSPI
KD = sorted(KOSPI)


from functools import lru_cache


@lru_cache(maxsize=None)
def _inv_rows(d):
    cols = ["individual", "pension", "trust"]
    return {c: dict(zip(cols, r)) for c, *r in E.IB.execute(
        "SELECT code, individual, pension, trust FROM investor_daily WHERE date=?", [d]).fetchall()}


def inv_full(c, d):
    return _inv_rows(d).get(c) or {"individual": 0, "pension": 0, "trust": 0}


def kospi_ma20(d):
    i = KD.index(d)
    return np.mean([KOSPI[x] for x in KD[i - 19:i + 1]]) if i >= 19 else None


def add_features(S, sig):
    out = []
    for s in sig:
        rows = S[s["code"]]; i = s["i"]
        d1, d0 = rows[i][0], rows[i - 1][0]
        if d1 > INV_END: continue
        f0, f1 = E.inv(s["code"], d0), E.inv(s["code"], d1)
        if f0 is None or f1 is None: continue
        r0 = inv_full(s["code"], d0); r1 = inv_full(s["code"], d1)
        prev5 = [E.inv(s["code"], rows[k][0]) for k in range(i - 5, i)]
        val0 = s["val0"] or 1
        k1 = KOSPI.get(d1); kp = KOSPI.get(E.prev_day(d1)); ma = kospi_ma20(d1) if d1 in KOSPI else None
        o0, h0, l0, c0 = rows[i - 1][1:5]
        hi120 = max(r[2] for r in rows[i - 120:i])
        s = dict(s)
        s.update(
            F_d0_frn=f0[0] > 0, F_d0_ins=f0[1] > 0, F_d0_both=f0[0] > 0 and f0[1] > 0,
            F_d0_strong=(f0[0] + f0[1]) / val0 >= 0.05,
            F_d0_ind_sell=r0["individual"] < 0,
            F_5d_flow=sum((x[0] + x[1]) for x in prev5 if x) > 0,
            F_d0_pension_trust=(r0["pension"] or 0) + (r0["trust"] or 0) > 0,
            G_d1_flow=f1[0] + f1[1] > 0, G_d1_both=f1[0] > 0 and f1[1] > 0, G_d1_ind_sell=r1["individual"] < 0,
            G_d1_frn=f1[0] > 0,
            M_up=bool(ma and k1 > ma), M_kospi_up=bool(kp and k1 > kp), M_kospi_dn=bool(kp and k1 < kp),
            R_rank100=E.value_rank(d0).get(s["code"], 9999) <= 100,
            R_cap2000=E.mcap(s["code"], d1) >= 2e11,
            R_near_hi=s["buy"] >= 0.9 * hi120,
            R_short_wick=(h0 - l0) > 0 and (c0 - l0) / (h0 - l0) >= 0.7,
        )
        out.append(s)
    return out


FEATS = ["F_d0_frn", "F_d0_ins", "F_d0_both", "F_d0_strong", "F_d0_ind_sell", "F_5d_flow", "F_d0_pension_trust",
         "G_d1_flow", "G_d1_both", "G_d1_ind_sell", "G_d1_frn",
         "M_up", "M_kospi_up", "M_kospi_dn", "R_rank100", "R_cap2000", "R_near_hi", "R_short_wick"]
LABEL = {"F_d0_frn": "폭증일 외인 매수", "F_d0_ins": "폭증일 기관 매수", "F_d0_both": "폭증일 외인·기관 둘 다 매수",
         "F_d0_strong": "폭증일 외인+기관 ≥ 대금 5%", "F_d0_ind_sell": "폭증일 개인 매도", "F_5d_flow": "폭증일까지 5일 외인+기관 +",
         "F_d0_pension_trust": "폭증일 연기금+투신 매수", "G_d1_flow": "급감일 외인+기관 +", "G_d1_both": "급감일 외인·기관 둘 다 매수",
         "G_d1_ind_sell": "급감일 개인 매도", "G_d1_frn": "급감일 외인 매수",
         "M_up": "코스피 20일선 위", "M_kospi_up": "급감일 코스피 상승", "M_kospi_dn": "급감일 코스피 하락",
         "R_rank100": "폭증일 대금 100위 안", "R_cap2000": "시총 2천억↑", "R_near_hi": "120일 고가 −10% 안", "R_short_wick": "폭증일 윗꼬리 짧음(종가 위쪽 30%)"}
EXITS = {"다음날09시": (0, None), "−5%·3일째09시": (2, 0.05), "−5%·5일째09시": (4, 0.05)}


def stat(v):
    v = np.array(v)
    if len(v) == 0: return dict(n=0, m=0, s=0, pf=0, wr=0)
    w, l = v[v > 0], v[v <= 0]
    pf = (w.mean() / -l.mean()) if len(w) and len(l) and l.mean() < 0 else 0
    return dict(n=len(v), m=v.mean(), s=v.sum(), pf=pf, wr=(v > 0).mean())


def main():
    rep = E.Report("flow_search.txt")
    S = B.build_series()
    base = [s for s in B.signals(S) if s["spike"] >= 5 and s["dry"] <= 0.25 and s["up0"] > 0 and -0.03 <= s["gap5"] <= 0.05]
    sig = add_features(S, base)
    rep.say(f"거감음봉(책 조건) + 다른 정보 조합 — 신호 {len(sig)}건 (수급 있는 ~{INV_END}), 고르는 기간 ~{SPLIT} / 확인 기간 {SPLIT}~")
    # 매도 방법·매수 시점별 수익을 미리 계산
    for s in sig:
        rows = S[s["code"]]
        for k, (h, st) in EXITS.items():
            s["r_" + k] = B.exit_ret(rows, s["i"], s["buy"], h, st, None)[0]
            s["n_" + k] = B.exit_ret(rows, s["i"], s["buy"], h, st, None, entry_next_open=True)[0]

    combos = [()] + [(f,) for f in FEATS] + list(itertools.combinations(FEATS, 2))
    combos = [c for c in combos if not ({"M_kospi_up", "M_kospi_dn"} <= set(c))]
    res = []
    for c in combos:
        nxt = any(f.startswith("G_") for f in c)
        sel = [s for s in sig if all(s[f] for f in c)]
        for k in EXITS:
            key = ("n_" if nxt else "r_") + k
            a = [s[key] for s in sel if s["d"] < SPLIT]; b = [s[key] for s in sel if s["d"] >= SPLIT]
            res.append((c, k, nxt, stat(a), stat(b), [(s["d"], s[key]) for s in sel]))
    rep.say(f"시험한 조합: 필터 {len(combos)}개 × 매도 {len(EXITS)}개 = {len(res)}개 (이 중 1등은 우연일 수 있음)\n")

    def name(c, nxt):
        return (" + ".join(LABEL[f] for f in c) or "추가 필터 없음") + (" [다음날 시가 매수]" if nxt else " [급감일 종가 매수]")

    rep.say("[0] 기준: 추가 필터 없음")
    for r in res:
        if r[0] == ():
            rep.say(f"  {r[1]:12s} 앞 {r[3]['n']:4d}건 {r[3]['m']:+.2%} | 뒤 {r[4]['n']:4d}건 {r[4]['m']:+.2%}")

    rep.say("\n[1] 필터 하나씩 (다음날09시 / −5%·5일째09시) — 앞 기간 | 뒤 기간")
    for r in res:
        if len(r[0]) == 1 and r[1] in ("다음날09시", "−5%·5일째09시"):
            rep.say(f"  {name(r[0], r[2]):52s} {r[1]:12s} 앞 {r[3]['n']:4d}건 {r[3]['m']:+.2%} | 뒤 {r[4]['n']:4d}건 {r[4]['m']:+.2%}")

    rep.say("\n[2] 앞 기간에서 고른 상위 15개 (앞 기간 60건↑, 건당 수익 순) → 뒤 기간 확인")
    cand = sorted([r for r in res if r[3]["n"] >= 60], key=lambda r: -r[3]["m"])[:15]
    for r in cand:
        a, b = r[3], r[4]
        rep.say(f"  {name(r[0], r[2]):60s} {r[1]:12s} 앞 {a['n']:4d}건 {a['m']:+.2%} | 뒤 {b['n']:4d}건 {b['m']:+.2%} 손익비 {b['pf']:.2f} 승률 {b['wr']:.0%}")

    rep.say("\n[3] 두 기간 모두 + 이고 각 기간 40건↑ 인 조합 (뒤 기간 건당 수익 순 상위 15) + 전체 ★ 판정")
    both = sorted([r for r in res if r[3]["n"] >= 40 and r[4]["n"] >= 40 and r[3]["m"] > 0 and r[4]["m"] > 0],
                  key=lambda r: -min(r[3]["m"], r[4]["m"]))[:15]
    rep.say(f"  (두 기간 모두 + 인 조합 수: {sum(1 for r in res if r[3]['n'] >= 40 and r[4]['n'] >= 40 and r[3]['m'] > 0 and r[4]['m'] > 0)} / {len(res)})")
    for r in both:
        rep.stats(r[5], f"{name(r[0], r[2])} {r[1]}", width=78)

    rep.say("\n[4] 분기별 (위 [3] 1등)")
    if both:
        by = defaultdict(list)
        for d, x in both[0][5]: by[(d.year, (d.month - 1) // 3 + 1)].append(x)
        for k in sorted(by):
            v = by[k]; rep.say(f"  {k[0]} {k[1]}분기 {len(v):4d}건 건당 {np.mean(v):+.2%} 합계 {sum(v) * 100:+.0f}만")


if __name__ == "__main__":
    main()
