"""bt.py 가 만든 trades.csv 를 조건별로 집계 → bt_out.txt"""
import sys
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd

OUT = r"D:\Ellie\trading\data\lectures\yt\msQZetf7_UI"
T = pd.read_csv(OUT + r"\trades.csv", dtype={"code": str})
T["date"] = pd.to_datetime(T["date"]).dt.date
f = open(OUT + r"\bt_out.txt", "w", encoding="utf-8")


def say(s=""):
    print(s); f.write(s + "\n")


ds_all = sorted(T.date.unique()); H = ds_all[len(ds_all) // 2]
R3 = date(2026, 8, 1)


def st(sub, col, title):
    v = sub[col].dropna()
    s = sub.loc[v.index]
    if len(v) < 5:
        say(f"  {title:46s} {len(v):4d}건 (적음)"); return
    a = v[s.date < H]; b = v[s.date >= H]; r3 = v[s.date >= R3]
    top = v.sort_values(ascending=False)
    ex10 = top.iloc[10:].mean() if len(v) > 10 else np.nan
    star = "★" if (len(a) and a.mean() > 0 and len(b) and b.mean() > 0 and ex10 > 0) else " "
    say(f" {star}{title:46s} {len(v):4d}건 건당 {v.mean():+.2%} 합계 {v.sum()*100:+6.0f}%p 승률 {np.mean(v>0):.0%} | "
        f"앞 {a.mean() if len(a) else np.nan:+.2%}({len(a)}) 뒤 {b.mean() if len(b) else np.nan:+.2%}({len(b)}) "
        f"최근3달 {r3.mean() if len(r3) else np.nan:+.2%}({len(r3)}) | 최고10건 빼면 {ex10:+.2%}")


say(f"기간 {ds_all[0]} ~ {ds_all[-1]}, 앞/뒤 나눔 {H}, 최근 3달 = {R3}~ / 비용 0.25% 포함")
say("★ = 앞·뒤 반 모두 + 이고 최고 10건 빼도 +")
COLS = [("r_s2_tp0", "하루: 선−2% 손절·익절 없음·다음날 09:00"), ("r_s4_tp0", "하루: 선−4% 손절·익절 없음"),
        ("r_s2_tp5", "하루: 선−2%·+5% 익절"), ("r_s2_tp10", "하루: 선−2%·+10% 익절"), ("r_s4_tp10", "하루: 선−4%·+10% 익절"),
        ("sw_tp0", "보유: 종가<VWMA→다음날 시가(최대20일)"), ("sw_tp10", "보유: +10% 익절 또는 종가<VWMA"), ("sw_tp15", "보유: +15% 익절 또는 종가<VWMA")]


def block(sub, name):
    say(f"\n[{name}]")
    for col, t in COLS:
        st(sub, col, t)


for kind, kn in (("A", "A 장중 돌파 매수"), ("B", "B 종가 확인 → 다음날 09:00 매수")):
    K = T[T.kind == kind]
    say("\n" + "=" * 100 + f"\n{kn}")
    base = K[(K.run >= 20) & (K.slope < 0) & (K.gap >= -0.05)]
    block(base, "기본: 20일↑ 아래·VWMA 내려옴·전날 −5% 안")
    block(K, "조건 없음 (전날 VWMA 아래인 대금 상위 100 전부)")
    say("\n-- 기본에서 숫자 하나씩 바꿈 (매도 = 하루 선−2%·다음날 / 보유 종가<VWMA)")
    for nm, sub in [("아래 머문 기간 5일↑", K[(K.run >= 5) & (K.slope < 0) & (K.gap >= -0.05)]),
                    ("아래 머문 기간 60일↑", K[(K.run >= 60) & (K.slope < 0) & (K.gap >= -0.05)]),
                    ("기울기 조건 없음", K[(K.run >= 20) & (K.gap >= -0.05)]),
                    ("VWMA 20일에 −5%↓ (빠르게 내려옴)", K[(K.run >= 20) & (K.slope < -0.05) & (K.gap >= -0.05)]),
                    ("가까움 조건 없음", K[(K.run >= 20) & (K.slope < 0)]),
                    ("전날 −3% 안 (더 가까움)", K[(K.run >= 20) & (K.slope < 0) & (K.gap >= -0.03)])]:
        st(sub, "r_s2_tp0", nm + " | 하루")
        st(sub, "sw_tp0", nm + " | 보유")
    if kind == "A":
        say("\n-- 시가에 이미 선 위로 뜬 날(갭) vs 장중에 뚫은 날 (기본 조건)")
        st(base[base.gapopen == True], "r_s2_tp0", "시가부터 선 위 | 하루")
        st(base[base.gapopen == False], "r_s2_tp0", "장중 돌파 | 하루")
        st(base[base.gapopen == True], "sw_tp0", "시가부터 선 위 | 보유")
        st(base[base.gapopen == False], "sw_tp0", "장중 돌파 | 보유")
    say("\n-- 시장 분위기 (전날 코스피 vs 코스피 대금 가중 100일선) — 기본 조건")
    for v, nm in ((True, "코스피 VWMA100 위"), (False, "코스피 VWMA100 아래(영상: 이때 뚫는 종목 = 상대 강도 좋음)")):
        st(base[base.mkt == v], "r_s2_tp0", nm + " | 하루")
        st(base[base.mkt == v], "sw_tp0", nm + " | 보유")
f.close()
