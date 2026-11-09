"""book_trades.pkl → 스킬 문서용 규칙별 표 (마크다운). 대상마다 한 표.
    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_book_table.py > data/yoonta/book_table.md
"""
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TR = pickle.load(open(os.path.join(ROOT, "data", "yoonta", "book_trades.pkl"), "rb"))
B1 = "[R26] 익절 +1% · 손절 −2% (자동 주문)"
CMP = "(책에 없음·비교) 손절 −3% · 익절 +10%"


def st(tr):
    if not tr or len(tr) < 15:
        return None
    v = np.array([t[1] for t in tr])
    half = sorted(t[0] for t in tr)[len(tr) // 2]
    a = np.mean([t[1] for t in tr if t[0] < half]); b = np.mean([t[1] for t in tr if t[0] >= half])
    bd = defaultdict(float)
    for t in tr:
        bd[t[0]] += t[1]
    s = sorted(bd.values(), reverse=True)
    return dict(n=len(v), m=v.mean(), a=a, b=b, ex5=sum(s[5:]), star=a > 0 and b > 0 and sum(s[5:]) > 0)


def f(x):
    return "—" if not x else f"{'★' if x['star'] else ''}{x['m']:+.2%}"


univs = sys.argv[1:] or ["책 대상", "장전 3~5종목 (책 대상 ∩ 주도 테마·평소 함께)", "09:10 주도 테마 대장주(평소 함께)", "평소 함께 묶음"]
for univ in univs:
    names = sorted({k[0] for k in TR if k[1] == univ})
    print(f"\n#### 대상: {univ}")
    print("| 기법 | 건수 | 책 기본 +1%/−2% (다음 날 시가 / 15:00 정리) | 책 매도 중 최고 (다음 날 시가) | 그 매도 앞·뒤 | 비교 −3/+10 |")
    print("|---|---|---|---|---|---|")
    for nm in names:
        g = {(k[2], k[3]): st(v) for k, v in TR.items() if k[0] == nm and k[1] == univ}
        n = max((x["n"] for x in g.values() if x), default=0)
        if not n:
            continue
        b1n = g.get((B1, "다음 날 시가")) or g.get(("다음 날 시가", "다음 날 시가")); b1e = g.get((B1, "15:00 정리(책)"))
        book = [(ex, x) for (ex, e), x in g.items() if e == "다음 날 시가" and x and not ex.startswith("(책에 없음")]
        ex, bx = max(book, key=lambda t: t[1]["m"]) if book else ("", None)
        cm = g.get((CMP, "다음 날 시가"))
        print(f"| {nm} | {n} | {f(b1n)} / {f(b1e)} | {f(bx)} {ex.split(']')[0] + ']' if ex.startswith('[') else ex} {ex.split('] ', 1)[-1][:28] if ex.startswith('[') else ''} | "
              f"{'' if not bx else f'{bx[chr(97)]:+.2%} / {bx[chr(98)]:+.2%}'} | {f(cm)} |")
