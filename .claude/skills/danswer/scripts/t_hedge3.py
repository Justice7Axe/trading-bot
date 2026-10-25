"""고가 근처 마감 조건이 하락일 종가 베팅에 보탬이 되나 — 대금 30위·코스피 대비 +3%p 상승 종목을 마감 위치별로 (④ 역행 강세 종가와 같은 대상)."""
import numpy as np
from engine import *
from t_hedge2 import SIG, day_chg, exit_ret, FCODE
R = Report("t_hedge3.txt")
B = [(0, .5, "고가 근처 <0.5"), (.5, .8, "0.5~0.8"), (.8, 1.01, "≥0.8 (고가 부근 유지)")]
for dn, f in {"코스피 < 0": lambda d: (kospi_chg(d) or 0) < 0, "코스피 ≤ −1σ": lambda d: bool(SIG.get(d)) and (kospi_chg(d) or 0) <= -SIG[d]}.items():
    R.say(f"\n== {dn} ==")
    for top in (30, 100):
        rows = []
        for d in days():
            if not f(d): continue
            t = daily_day(d); ch = day_chg(d); vr = value_rank(d); k = kospi_chg(d)
            for c, r in t.items():
                x = ch.get(c)
                if x is None or x <= 0 or x >= LIMIT or not is_common(c) or vr.get(c, 9999) > top or x - k < 0.03: continue
                o, h, l, cl = r[:4]; pos = (cl - l) / (h - l) if h > l else 1.0
                ret = exit_ret(c, d, cl)
                if ret is not None: rows.append((d, ret, pos, c in FCODE))
        R.stats([(d, x) for d, x, p, hd in rows], f"대금 {top}위 · +3%p · 상승 전체")
        for a, b, nm in B:
            R.stats([(d, x) for d, x, p, hd in rows if a <= p < b], f"   {nm}")
