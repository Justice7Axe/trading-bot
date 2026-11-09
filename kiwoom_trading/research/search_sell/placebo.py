"""4단계: 비교 기준(플라시보) — '조회 사건 때 판 것'이 '아무 때나 장중에 판 것'보다 나은가?

장중 사건(09:00~15:19) 하나마다, 그 사건이 없던(같은 정의·N 에서 사건 없음) 다른 보유 구간 중
같은 시각(분)에 들고 있던 것들을 그 시각 다음 봉 시가에 팔았다고 보고 (실제 대비 차이) 평균을 낸다.
→ 사건 차이 − 플라시보 차이 = 조회 신호 자체의 몫.
또 보유 구간 전체를 고정 시각(10:00·11:00·13:00·14:30)에 판 경우도 본다 (밤샘 대신 장중에 판 효과).
출력: data/search_sell/placebo.txt
"""
import os
from datetime import datetime, time, timedelta

import numpy as np
import pandas as pd

from kiwoom_trading.research.search_sell.sim import bars

OUT = r"D:\Ellie\trading\data\search_sell"
P = pd.read_parquet(os.path.join(OUT, "positions.parquet"))
R = pd.read_parquet(os.path.join(OUT, "sim.parquet"))
R["evt"] = pd.to_datetime(R.ev_hm).dt.time
A = R[(R.status == "적용") & (R.evt >= time(9, 0)) & (R.evt < time(15, 19))].copy()
P["grp"] = np.where(P.src == "paper", "모의", np.where(P.src == "bt", "1년목록", "실전"))

# 보유 구간별 매수일 KRX 1분봉 (매수일 장중에 팔 수 있는 것만)
BB = {}
for p in P.itertuples():
    if p.buy_ts.time() >= time(15, 19): continue
    b = bars(p.code, p.date, "KRX")
    if len(b): BB[p.id] = b.set_index("ts").open
print("봉 있는 보유", len(BB), "/", len(P), flush=True)


def sell_at(pid, m):
    s = BB.get(pid)
    if s is None: return None
    j = s[(s.index >= m + timedelta(minutes=1)) & (s.index <= m + timedelta(minutes=5))]
    return float(j.iat[0]) if len(j) else None


Pi = P.set_index("id")
L = []
pr = L.append
pr("# 플라시보: 같은 시각에 사건 없던 다른 보유를 판 경우 vs 사건 때 판 경우 (실제 대비 차이, 전부 매도 기준)")
for src_set, lab in ((("bt",), "1년목록"), (("paper", "real"), "모의+실전"), (("bt", "paper", "real"), "합침")):
    for N in (20, 10):
        for v in ("A", "B"):
            ev = A[(A.N == N) & (A["var"] == v) & A.src.isin(src_set)]
            if not len(ev): continue
            had = set(R[(R.N == N) & (R["var"] == v)].id)
            pool = P[P.src.isin(src_set) & ~P.id.isin(had)]
            ed, pd_ = [], []
            for e in ev.itertuples():
                m = pd.Timestamp(e.ev_hm)
                ed.append(e.full - e.act)
                # 같은 시각(날짜 무관) 보유 중이던 사건 없는 구간 — 같은 날짜 우선, 없으면 모든 날짜의 같은 시각
                sub = []
                for q in pool.itertuples():
                    mm = pd.Timestamp(datetime.combine(q.date, m.time()))
                    if not (q.buy_ts < mm and mm + timedelta(minutes=1) < q.exit_ts): continue
                    px = sell_at(q.id, mm)
                    if px is None: continue
                    sub.append(px / q.buy - 1 - q.cost - q.act)
                if sub: pd_.append(np.mean(sub))
            pr(f"  {lab:<8} 상위{N} {v}: 사건 {len(ed)}건 차이 {np.mean(ed)*100:+.2f}%p | 같은 시각 사건 없는 보유 {len(pd_)}건 평균 차이 {np.mean(pd_)*100:+.2f}%p | 신호 몫 {np.mean(ed)*100-np.mean(pd_)*100:+.2f}%p")
pr("")
pr("# 고정 시각에 전부 팔았다면 (실제 대비 차이) — 사건 여부 무관, 그 시각에 들고 있던 보유 전부")
for src_set, lab in ((("bt",), "1년목록"), (("paper",), "모의"),):
    for T in (time(9, 30), time(10, 0), time(11, 0), time(13, 0), time(14, 30)):
        for night in (True, False):
            d = []
            for q in P[P.src.isin(src_set)].itertuples():
                mm = pd.Timestamp(datetime.combine(q.date, T))
                if not (q.buy_ts < mm and mm + timedelta(minutes=1) < q.exit_ts): continue
                if (q.exit_ts.date() > q.date) != night: continue
                px = sell_at(q.id, mm)
                if px is None: continue
                d.append(px / q.buy - 1 - q.cost - q.act)
            if d:
                pr(f"  {lab:<8} {T:%H:%M} {'밤샘 보유' if night else '당일 청산'}: {len(d):3d}건 차이 {np.mean(d)*100:+.2f}%p (합 {np.sum(d)*100:+.1f}) 나은 건 {sum(x>0 for x in d)}/{len(d)}")
open(os.path.join(OUT, "placebo.txt"), "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
