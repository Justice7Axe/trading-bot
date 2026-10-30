"""단타 매매별 '더 엄격한 종목 선정' 조건 비교 (2026-10-30 사용자 '데이 트레이딩은 더 줄여줘 — 더 엄격한 종목 선정으로').

입력: data/strict_select/trades_feat.pkl (features.py). 출력: data/strict_select/filters.txt
매매별로: 지금 규칙(기준) / 조건 하나씩 / 조건 둘 묶음 상위.
  건수·건당·합계(100만/건)·고정 반기(2026-04-20 전/후) 건당·★(engine Report.stats: 앞·뒤 반 + & 최고 5일 빼도 +)
  '↑↑' = 앞 반·뒤 반 건당이 둘 다 기준보다 높음 (한쪽 기간에서만 좋은 조건 거르기)
여러 조건을 나눠 본 것이라 우연히 좋아 보이는 조건이 섞인다 → 이웃 문턱값도 좋은지, 앞·뒤 반 모두 좋은지로 고른다.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.strict_select.filters
"""
import itertools
import os
import pickle
import sys
from datetime import date

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "strict_select")
SPLIT = date(2026, 4, 20)
KINDS = ["1️⃣", "2️⃣", "6️⃣", "📕", "☕", "🔁", "5️⃣", "3️⃣"]
NAME = {"1️⃣": "1️⃣ 상승장 장 초", "2️⃣": "2️⃣ 저항 돌파", "3️⃣": "3️⃣ 막힌 고점(참고, 모의에서 뺌)", "5️⃣": "5️⃣ 약세장 인버스(ETF)",
        "6️⃣": "6️⃣ 주도주 신고가", "📕": "📕 상한가 풀림", "🔁": "🔁 시가 탈환(모의만)", "☕": "☕ 카페 대장(박스 없음)"}
HAS_RK = {"1️⃣", "6️⃣"}

# 이름 → (묶음, 조건). 같은 묶음끼리는 둘 묶음에 같이 안 씀.
F = {
    "신호 순간 대금 ≤5위": ("rk", lambda t: 0 < t.get("rk", 0) <= 5),
    "신호 순간 대금 ≤10위": ("rk", lambda t: 0 < t.get("rk", 0) <= 10),
    "신호 순간 대금 ≤20위": ("rk", lambda t: 0 < t.get("rk", 0) <= 20),
    "전날 대금 ≤10위": ("pvr", lambda t: t["pvr"] <= 10),
    "전날 대금 ≤20위": ("pvr", lambda t: t["pvr"] <= 20),
    "전날 대금 ≤50위": ("pvr", lambda t: t["pvr"] <= 50),
    "전날 대금 ≤100위": ("pvr", lambda t: t["pvr"] <= 100),
    "전날 외인·기관 둘 다 +": ("inv", lambda t: bool(t["fb"]) and bool(t["ib"])),
    "전날 외인·기관 하나↑ +": ("inv", lambda t: bool(t["fb"]) or bool(t["ib"])),
    "전날 외인 +": ("inv", lambda t: bool(t["fb"])),
    "전날 기관 +": ("inv", lambda t: bool(t["ib"])),
    "전날 외인·기관 둘 다 − 아님": ("inv", lambda t: not (t["fb"] is False and t["ib"] is False)),
    "시총 ≥3천억": ("mc", lambda t: t["mc"] >= 3e11),
    "시총 ≥1조": ("mc", lambda t: t["mc"] >= 1e12),
    "시총 ≥5천억": ("mc", lambda t: t["mc"] >= 5e11),
    "전날 종가 20일선 위": ("up20", lambda t: t["up20"] is True),
    "전날 종가 52주 고가 −10% 안": ("n52", lambda t: t["n52"] is True),
    "시장 강한 상승장(U)": ("reg", lambda t: t["reg"] == "U"),
    "시장 U·N+": ("reg", lambda t: t["reg"] in ("U", "N+")),
    "시장 약세장(N-) 아님": ("reg", lambda t: t["reg"] not in ("N-",)),
    "가격 ≥1,000원": ("px", lambda t: t["px"] == t["px"] and t["px"] >= 1000),
    "가격 ≥5,000원": ("px", lambda t: t["px"] == t["px"] and t["px"] >= 5000),
    "보통주": ("common", lambda t: t["common"]),
    "테마 대장(6️⃣ lead)": ("lead", lambda t: bool(t.get("lead"))),
}


def ok_for(kind, fam, rows):
    if fam == "rk" and kind not in HAS_RK: return False
    if fam == "lead" and kind != "6️⃣": return False
    if fam == "reg" and all(t["reg"] is None for t in rows): return False   # 09:10 전 신호 → 시장 판정 모름
    return True


def reg_known(fam, f):
    """시장 조건은 09:10 뒤 신호만 판정 가능 — 09:10 전 신호는 '모름'이라 그대로 둔다(거르지 않음)."""
    if fam != "reg": return f
    return lambda t: t["reg"] is None or f(t)


class Rep(E.Report):
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")


def summ(rows):
    v = np.array([t["ret"] for t in rows]) if rows else np.array([])
    a = [t["ret"] for t in rows if t["date"] < SPLIT]; b = [t["ret"] for t in rows if t["date"] >= SPLIT]
    return dict(n=len(v), mean=v.mean() if len(v) else 0, sum=v.sum() * 100 if len(v) else 0,
                a=np.mean(a) if a else np.nan, b=np.mean(b) if b else np.nan)


def star(rows):
    """Report.stats 와 같은 ★ (출력 없이)."""
    if len(rows) < 15: return False
    tr = [(t["date"], t["ret"]) for t in rows]
    ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
    a = [x for d, x in tr if d < h]; b = [x for d, x in tr if d >= h]
    bd = {}
    for d, x in tr: bd[d] = bd.get(d, 0) + x
    s = sorted(bd.values(), reverse=True)
    return np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0


def line(title, rows, base):
    s = summ(rows); st = "★" if star(rows) else " "
    up = "↑↑" if s["n"] and s["a"] > base["a"] and s["b"] > base["b"] else "  "
    return (f" {st}{up} {title:34s} {s['n']:5d}건({s['n'] / max(base['n'], 1):4.0%}) 건당 {s['mean']:+.2%} 합계 {s['sum']:+6.0f}만 "
            f"| 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%}"), s, st == "★", up == "↑↑"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = pickle.load(open(os.path.join(OUT, "trades_feat.pkl"), "rb"))
    R = Rep(os.path.join(OUT, "filters.txt"))
    R.say("단타 매매별 더 엄격한 종목 선정 — 1년 (2025-10-16 ~ 2026-10-22), 비용 포함, 합계 = 100만/건, 반기 기준 2026-04-20")
    R.say("★ = 앞·뒤 반 모두 + & 최고 5일 빼도 + (Report.stats) · ↑↑ = 앞·뒤 반 건당 모두 기준보다 높음 · (%) = 기준 대비 건수")
    best = {}
    for k in KINDS:
        rows = [t for t in T if t["kind"] == k]
        if not rows: continue
        base = summ(rows)
        R.say(f"\n## {NAME[k]}")
        R.stats([(t["date"], t["ret"]) for t in rows], "기준 (지금 규칙) — Report.stats", 34)
        s0, _, _, _ = line("기준", rows, base); R.say(s0)
        if k == "5️⃣":
            R.say("  (인버스 ETF 한 종목 → 종목 조건 해당 없음)"); continue
        singles = []
        for nm, (fam, f) in F.items():
            if not ok_for(k, fam, rows): continue
            g = reg_known(fam, f)
            sub = [t for t in rows if g(t)]
            if len(sub) == len(rows) or not sub: continue
            txt, s, st, up = line(nm, sub, base); R.say(txt)
            singles.append((nm, fam, g))
        combos = []
        for (n1, f1, g1), (n2, f2, g2) in itertools.combinations(singles, 2):
            if f1 == f2: continue
            sub = [t for t in rows if g1(t) and g2(t)]
            if len(sub) < 15: continue
            txt, s, st, up = line(f"{n1} + {n2}", sub, base)
            combos.append((s, st, up, txt, (n1, n2)))
        good = [c for c in combos if c[0]["n"] <= 0.75 * base["n"] and c[1] and c[0]["mean"] > base["mean"]]
        R.say(f"  -- 둘 묶음 (건수 ≤75%·★·건당 기준보다 높음) 합계 순 상위 8 / 전체 {len(combos)}개 중 {len(good)}개")
        for c in sorted(good, key=lambda c: -c[0]["sum"])[:8]:
            R.say("  " + c[3])
        R.say("  -- 둘 묶음 건당 순 상위 5 (건수 ≥20)")
        for c in sorted([c for c in combos if c[0]["n"] >= 20], key=lambda c: -c[0]["mean"])[:5]:
            R.say("  " + c[3])


if __name__ == "__main__":
    main()
