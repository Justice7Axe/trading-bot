"""book_trades.pkl 요약 — 기법·대상마다 한 줄: 건수, 책 기본 매도(+1%/−2%), 책 매도 가운데 가장 나은 것, 비교용(−3/+10).
각각 [다음 날 시가] / [15:00 정리(책)] 두 끝 처리, 앞·뒤 절반, 최고 5일 뺀 합계, 책 시장(상승·횡보·하락)별 건당.
    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_book_summary.py > data/yoonta/book_summary.txt
"""
import os
import pickle
from collections import defaultdict

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TR = pickle.load(open(os.path.join(ROOT, "data", "yoonta", "book_trades.pkl"), "rb"))


def st(tr):
    if len(tr) < 15:
        return None
    v = np.array([t[1] for t in tr])
    half = sorted(t[0] for t in tr)[len(tr) // 2]
    a = np.mean([t[1] for t in tr if t[0] < half]); b = np.mean([t[1] for t in tr if t[0] >= half])
    bd = defaultdict(float)
    for t in tr:
        bd[t[0]] += t[1]
    s = sorted(bd.values(), reverse=True)
    rg = defaultdict(list)
    for t in tr:
        rg[t[5]].append(t[1])
    return dict(n=len(v), days=len(bd), m=v.mean(), sum=v.sum(), ex5=sum(s[5:]), a=a, b=b,
                star=a > 0 and b > 0 and sum(s[5:]) > 0, reg={k: (np.mean(x), len(x)) for k, x in rg.items()})


def fmt(x):
    if not x:
        return "—"
    return f"{'★' if x['star'] else ''}{x['m']:+.2%} (앞 {x['a']:+.2%} 뒤 {x['b']:+.2%}, 최고5일 빼면 {x['ex5'] * 100:+.0f}만)"


groups = defaultdict(dict)
for (name, univ, ex, end), tr in TR.items():
    groups[(name, univ)][(ex, end)] = st(tr)

print("윤타 책 전체 규칙 v2 요약 — 건당 수익(비용 0.25% 뒤). ★ = 앞·뒤 모두 + · 최고 5일 빼도 +.")
print("열: 책 기본(+1%/−2%) | 책 매도 중 최고 | 비교용 −3/+10 — 각각 [다음 날 시가] 와 [15:00 정리(책)]")
cur = None
best_rows = []
for (name, univ) in sorted(groups):
    g = groups[(name, univ)]
    if name != cur:
        print(f"\n## {name}")
        cur = name
    base_n = max((x["n"] for x in g.values() if x), default=0)
    if not base_n:
        print(f"   · {univ}: 15건 미만")
        continue
    line = [f"   · {univ}: {base_n}건"]
    for end in ("다음 날 시가", "15:00 정리(책)"):
        b1 = g.get(("[R26] 익절 +1% · 손절 −2% (자동 주문)", end)) or g.get(("다음 날 시가", end))
        book = [(ex, x) for (ex, e), x in g.items() if e == end and x and not ex.startswith("(책에 없음")]
        bb = max(book, key=lambda t: t[1]["m"]) if book else None
        cmp_ = g.get(("(책에 없음·비교) 손절 −3% · 익절 +10%", end))
        line.append(f"\n       [{end}] 책 기본 {fmt(b1)} | 책 최고 {fmt(bb[1]) if bb else '—'} ← {bb[0][:40] if bb else ''} | 비교 −3/+10 {fmt(cmp_)}")
        if bb:
            best_rows.append((bb[1]["m"], name, univ, end, bb[0], bb[1]))
    rg = (g.get(("[R26] 익절 +1% · 손절 −2% (자동 주문)", "다음 날 시가")) or {}).get("reg", {})
    if rg:
        line.append("\n       책 시장별(+1%/−2%, 다음 날 시가): " + " ".join(f"{k} {m:+.2%}({n})" for k, (m, n) in sorted(rg.items())))
    print("".join(line))

print("\n\n### 책 매도로 ★ 가 나온 조합 (건수 30↑, 건당 순)")
for m, name, univ, end, ex, x in sorted(best_rows, reverse=True):
    if x["star"] and x["n"] >= 30:
        print(f"  {m:+.2%} | {x['n']}건 {x['days']}일 | {name} — {univ} | {ex} [{end}] | 앞 {x['a']:+.2%} 뒤 {x['b']:+.2%} 최고5일 빼면 {x['ex5'] * 100:+.0f}만")
