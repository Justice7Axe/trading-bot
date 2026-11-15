"""점검: 지금 data/cafe_universe.json 과 재현한 전 규칙 목록 비교 · 종목 0개 글 · 하승훈 글 없는 평일 · 트레이더 카페 생기기 전·후 나눠 본 카페 안/밖.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.cafe_universe.checks > data/cafe_history/checks.txt"""
import json, sys
from datetime import date
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
from kiwoom_trading.research.cafe_universe import analyze as A
posts = A.load_posts()
U = A.universes(posts, [date(2026,11,15), date(2026,11,16)])
j = json.load(open("data/cafe_universe.json", encoding="utf-8"))
cur = set(j["codes"]); print("json date", j["date"], len(cur), [a["subject"] for a in j["articles"]][:12])
for d,(u60,old) in U.items():
    print(d, "U60", len(u60), "OLD", len(old), "OLD∩json", len(old & cur), "json-OLD", len(cur-old), "OLD-json", len(old-cur))
print(posts[posts.n_codes==0][["cafe","kind","posted_ts"]])
h = posts[posts.cafe=="하승훈"]
d = pd.to_datetime(h.posted_ts).dt.date
gaps = sorted(set(pd.bdate_range("2025-09-01","2026-11-13").date) - set(d))
print("하승훈 글 없는 평일", len(gaps), gaps[:40])
T = pd.read_csv("data/cafe_history/trades_flagged.csv", dtype={"code":str}, encoding="utf-8-sig"); T["date"]=pd.to_datetime(T.date).dt.date
for k in ["📕","4️⃣","1️⃣","6️⃣","🌙","🔁","3️⃣"]:
    x=T[T.kind==k]
    for lab,m in (("~03-08", x.date<date(2026,3,9)), ("03-09~", x.date>=date(2026,3,9))):
        y=x[m]; i=y[y.in60]; o=y[~y.in60]
        print(k, lab, f"안 {len(i)} {i.ret.mean()*100:+.2f}% / 밖 {len(o)} {o.ret.mean()*100:+.2f}%")
# 📕 detail: in-cafe by source
