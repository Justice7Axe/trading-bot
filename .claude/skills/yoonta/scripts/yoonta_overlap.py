"""윤타 후보 3가지가 지금 매매표(①~⑦·🧭·🌙)와 겹치는지 — 같은 날 같은 종목 기준.

매매표 매매 목록은 세션 d9b9b62e 의 full_bt.py / compound.py 와 같은 조건으로 다시 만든다 (종목코드를 함께 남기려고 ①~⑤ 는 조건을 그대로 옮김).
윤타 후보 (book_trades.pkl, v2):
  A. 저돌 · 장전 3~5종목(책 대상 ∩ 같은 업종 주도 테마) · 20일/60일 최고가/전고점 09:00~10:00 (같은 날 같은 종목은 먼저 온 것)
  B. 저돌 · 책 대상 (같은 방식)
  C. 종가배팅 김보선 (14:30~15:00, 다음 날 시가)
    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_overlap.py > data/yoonta/overlap.txt
"""
import glob
import io
import os
import pickle
import sys
import tempfile
from collections import defaultdict
from datetime import date, time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TMP = os.path.join(tempfile.gettempdir(), "claude", "D--Ellie-trading")
S_FULL = glob.glob(os.path.join(TMP, "d9b9b62e*", "scratchpad"))[0]
P0, P1 = date(2025, 10, 16), date(2026, 10, 22)


import shutil  # noqa: E402
_copy0 = shutil.copy


def _safe_copy(src, dst, *a, **k):
    """원본이 백필·수집 중이라 잠기면 이미 있는 사본(같은 이름 또는 오늘 만든 다른 사본)을 쓴다."""
    try:
        return _copy0(src, dst, *a, **k)
    except PermissionError:
        if os.path.exists(dst):
            return dst
        base = os.path.basename(src); tmp = tempfile.gettempdir()
        c = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(base) and os.path.getsize(os.path.join(tmp, f)) > 0]
        if not c:
            raise
        best = max(c, key=os.path.getmtime)
        print(f"⚠️ {base} 잠김 — {best} 사본 사용", file=sys.__stderr__)
        return _copy0(best, dst)


shutil.copy = _safe_copy


def quiet(fn):
    so, se = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        return fn()
    finally:
        sys.stdout, sys.stderr = so, se


# ---- 매매표 (①~⑤ 는 compound.py 조건 그대로 + 코드)
cwd = os.getcwd()
csrc = open(os.path.join(S_FULL, "compound.py"), encoding="utf-8").read().split("T = []")[0]
cns = {"__file__": os.path.join(S_FULL, "compound.py"), "__name__": "x"}
quiet(lambda: exec(csrc, cns))
cls, OLD, BAD = cns["cls"], cns["OLD"], cns["BAD"]
PB = []   # (date, kind, code, ret)
rows, _ = pickle.load(open("u_cands.pkl", "rb"))
for r in rows:
    if not all(abs(v) < 0.4 for v in r["ex"].values()):
        continue
    if r["T"] == time(9, 10) and cls(r["date"]) == "U" and r["vrank"] <= 40 and r["from_open"] > 0 \
            and r["fr"] is not None and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0):
        PB.append((r["date"], "① 상승장 장 초", r["code"], r["ex"][(None, 0.04)]))
for r in pickle.load(open(OLD + "resbo2.pkl", "rb")):
    c = cls(r["date"])
    if (r["code"], r["date"]) in BAD or c not in ("U", "N+"):
        continue
    if r["N"] == 5 and r["entry"] == "E1" and r["sig_t"] < time(9, 30) and r["vr"] >= 0.10 and not r["gap_over"]:
        PB.append((r["date"], "③ 막힌 고점 돌파", r["code"], r[(0.07, "sl5" if c == "U" else "sl3")]))
import duckdb  # noqa: E402
dm = duckdb.connect(os.path.join(tempfile.gettempdir(), "inv_daily_ohlcv.duckdb"), read_only=True)
sh = dict(dm.execute("SELECT code, listed_shares FROM stocks").fetchall())
for r in pickle.load(open(OLD + "g2g_filter.pkl", "rb")):
    if "m7" not in r or (r["code"], r["date"]) in BAD or not cls(r["date"]):
        continue
    if (sh.get(r["code"]) or 0) * r["e"] >= 2e11 and r["bo_cum"] >= 1 and r["bo_t"] >= time(9, 10):
        PB.append((r["date"], "② 저항 돌파", r["code"], r["m7"][0.05]))
CB = glob.glob(os.path.join(TMP, "ea0dc09b*", "scratchpad", "closebet.pkl"))[0]
for r in pickle.load(open(CB, "rb")):
    if r["chg"] >= 0.295 or cls(r["date"]) != "D" or "open" not in r["ex"] or abs(r["ex"]["open"]) >= 0.3:
        continue
    if r["rk"] <= 30 and r["chg"] - r["mkt"] >= 0.03:
        PB.append((r["date"], "④ 역행 강세 종가", r["code"], r["ex"]["open"]))
os.chdir(cwd)
# ⑥·🧭·🌙·⑦ 는 full_bt.py 그대로 (EV 에 코드가 있음)
fsrc = open(os.path.join(S_FULL, "full_bt.py"), encoding="utf-8").read().split("KINDS = [")[0]
fns = {"__file__": os.path.join(S_FULL, "full_bt.py"), "__name__": "x"}
quiet(lambda: exec(fsrc, fns))
os.chdir(cwd)
for d, tk, k, a, r, code in fns["EV"]:
    if code is not None and k in ("⑥ 주도주 신고가", "🧭 디앤서 종가", "🌙 종가 재돌파"):
        PB.append((d, k, code, r))
for t in fns["T7c"]:
    PB.append((t["buy_d"], "⑦ 주도주 추세", t["code"], t["r"]))
PB = [x for x in PB if P0 <= x[0] <= P1]
pb_by = defaultdict(list)
for d, k, code, r in PB:
    pb_by[(d, code)].append((k, r))

# ---- 윤타 후보
TR = pickle.load(open(os.path.join(ROOT, "data", "yoonta", "book_trades.pkl"), "rb"))
JD = ("[R36] 저돌 20일 최고가 09:00~10:00", "[R36] 저돌 60일 최고가 09:00~10:00", "[R36] 저돌 전고점(가장 최근 고점) 09:00~10:00")


def cand(univ, exit_, names=JD, end="다음 날 시가"):
    first = {}
    for nm in names:
        for t in TR.get((nm, univ, exit_, end), []):
            d, r, code, t_in = t[:4]
            k = (d, code)
            if k not in first or t_in < first[k][1]:
                first[k] = (r, t_in)
    return {k: v[0] for k, v in first.items() if P0 <= k[0] <= P1}


CANDS = [
    ("A. 저돌 · 장전 3~5종목(같은 업종) · 반반이", cand("장전 3~5종목 (책 대상 ∩ 주도 테마·같은 업종)", "[R47] 반반이: 다음 일봉 저항에서 절반 · 나머지 4턴4꺾 · 손절 −2%")),
    ("A'. 위 · 비교 −3/+10", cand("장전 3~5종목 (책 대상 ∩ 주도 테마·같은 업종)", "(책에 없음·비교) 손절 −3% · 익절 +10%")),
    ("B. 저돌 · 책 대상 · 비교 −3/+10", cand("책 대상", "(책에 없음·비교) 손절 −3% · 익절 +10%")),
    ("C. 종가배팅 김보선 → 다음 날 시가", cand("책 대상", "다음 날 시가", names=("[R44] 종가배팅: 14:30~15:00 김보선 지지·거래량 감소·+3%↑",))),
]
KINDS = ["① 상승장 장 초", "② 저항 돌파", "③ 막힌 고점 돌파", "④ 역행 강세 종가", "⑥ 주도주 신고가", "🧭 디앤서 종가", "🌙 종가 재돌파", "⑦ 주도주 추세"]
print(f"윤타 후보 × 지금 매매표 겹침 — {P0} ~ {P1}, 같은 날 같은 종목 기준 (⑤ 인버스는 종목이 달라 뺌)")
cnt = defaultdict(int)
for d, k, code, r in PB:
    cnt[k] += 1
print("매매표 건수: " + " · ".join(f"{k} {cnt[k]}" for k in KINDS))
pb_days = defaultdict(set)
for d, k, code, r in PB:
    pb_days[k].add(d)
for name, C in CANDS:
    if not C:
        print(f"\n=== {name}: 0건"); continue
    v = np.array(list(C.values()))
    print(f"\n=== {name}: {len(C)}건 {len({d for d, _ in C})}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+.0f}만")
    over = {k: x for k, x in C.items() if k in pb_by}
    only = {k: x for k, x in C.items() if k not in pb_by}
    o = np.array(list(over.values())) if over else np.array([0.0])
    n = np.array(list(only.values())) if only else np.array([0.0])
    print(f"  같은 날 같은 종목이 매매표에도 있음: {len(over)}건 ({len(over) / len(C):.0%}) 윤타 건당 {o.mean():+.2%} | "
          f"윤타에만 있음: {len(only)}건 건당 {n.mean():+.2%} 합계 {n.sum() * 100:+.0f}만")
    for k in KINDS:
        hit = [(key, C[key], next(r for kk, r in pb_by[key] if kk == k)) for key in C if any(kk == k for kk, _ in pb_by.get(key, []))]
        if hit:
            print(f"    {k}: {len(hit)}건 — 윤타 건당 {np.mean([h[1] for h in hit]):+.2%} / 매매표 건당 {np.mean([h[2] for h in hit]):+.2%}")
    days = {d for d, _ in C}
    for k in KINDS:
        share = len(days & pb_days[k]) / len(days)
        if share:
            print(f"    같은 날(종목 무관) {k} 도 매매한 날 비율 {share:.0%}", end="")
    print()
    # 윤타에만 있는 매매의 앞·뒤 반
    if only:
        ds = sorted(d for d, _ in only); half = ds[len(ds) // 2]
        a = [x for (d, _), x in only.items() if d < half]; b = [x for (d, _), x in only.items() if d >= half]
        bd = defaultdict(float)
        for (d, _), x in only.items():
            bd[d] += x
        s = sorted(bd.values(), reverse=True)
        print(f"  윤타에만 있는 매매: 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} · 최고 5일 빼면 {sum(s[5:]) * 100:+.0f}만")
