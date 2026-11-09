"""3단계: 보고서 — data/search_sell/report.txt

본 표 = 장중(09:00~15:19 사건, KRX 다음 봉 시가 매도). 장 밖(NXT 08:00~08:50·15:30~20:00) 사건은 따로.
'개장 스냅샷'(그날 08:00~08:02 첫 스냅샷부터 상위) 은 '새로 듦'이 아니라 빼고 따로 셈.
차이 = 규칙 수익률 − 실제 수익률 (건당 %p, 합계 %p = 1건 같은 금액 가정).
"""
import os
from datetime import time, date

import numpy as np
import pandas as pd

OUT = r"D:\Ellie\trading\data\search_sell"
R = pd.read_parquet(os.path.join(OUT, "sim.parquet"))
P = pd.read_parquet(os.path.join(OUT, "positions.parquet"))
R["evt"] = pd.to_datetime(R.ev_hm).dt.time
R["sess"] = np.where((R.evt >= time(9, 0)) & (R.evt < time(15, 19)), "장중", np.where(R.evt <= time(8, 2), "개장스냅샷", "장밖"))
R["grp"] = np.where(R.src == "paper", np.where(R.virtual, "모의(가상 시간끝)", "모의"), np.where(R.src == "bt", "1년목록(10-13~22)", "실전"))
P["grp"] = np.where(P.src == "paper", np.where(P.virtual, "모의(가상 시간끝)", "모의"), np.where(P.src == "bt", "1년목록(10-13~22)", "실전"))
L = []
pr = lambda s="": L.append(s)


def line(lab, x, tot=None):
    if not len(x):
        pr(f"  {lab:<34} 0건"); return
    d_full = x.full - x.act; d_half = x.half - x.act
    days = sorted(x.date.unique()); mid = days[len(days) // 2] if len(days) > 1 else days[0]
    a, b = x[x.date < mid], x[x.date >= mid]
    h = lambda y: f"{(y.full - y.act).mean()*100:+.2f}" if len(y) else "  -  "
    pr(f"  {lab:<34} {len(x):3d}건{'' if tot is None else f'/{tot}'} {len(days):2d}일 | 실제 {x.act.mean()*100:+.2f}% → 전부 {x.full.mean()*100:+.2f}% · 절반 {x.half.mean()*100:+.2f}%"
       f" | 차이 전부 {d_full.mean()*100:+.2f}%p(합 {d_full.sum()*100:+.1f}) 절반 {d_half.mean()*100:+.2f}%p(합 {d_half.sum()*100:+.1f})"
       f" | 규칙이 나은 건 {int((d_full>0).sum())}/{len(x)} | 앞 {h(a)} 뒤 {h(b)}")


pr("# 조회 상위 첫 진입 → 익절 규칙 검증 (보유 종목) — 2026-10-30, 연구 전용")
pr("# 사건 다음 1분봉 시가에 전부/절반 매도 vs 실제(또는 규칙) 매도. 비용 같은 몫(0.25%, ETF 0.05%) 양쪽 적용.")
pr("# A = 그날 08:00~매수 사이 조회 상위 N 에 한 번도 없다가 보유 중 처음 듦 (말 그대로 '처음 들면')")
pr("# B = 보유 중, 직전 30분 상위 N 에 없다가 새로 듦 (매수 전에 이미 떴다 빠진 종목·밤샘 뒤 아침 포함)")
pr()
pr("## 0. 보유 구간 수와 사건 수")
for g, x in P.groupby("grp"):
    pr(f"  {g:<20} 보유 {len(x)}건, 날짜 {x.date.min()}~{x.date.max()}")
pr()
st = R.groupby(["grp", "N", "var", "sess", "status"]).size().unstack("status").fillna(0).astype(int)
pr(st.to_string()); pr()
pr("  '봉 없음'(장밖) = 그 종목이 NXT 에서 안 거래돼 다음 날 09:00 전에 팔 수 없음 → 실제와 같음.")
pr("  '실제 매도가 먼저' = 사건 다음 봉보다 실제 매도가 먼저 → 바뀌는 것 없음.")
pr()

A = R[R.status == "적용"].copy()
for sess in ("장중", "장밖"):
    pr(f"## 1. {sess} 사건 — 묶음 × N × 정의 × 그 순간 수익 조건")
    for g in ("모의", "모의(가상 시간끝)", "실전", "1년목록(10-13~22)"):
        for N in (20, 10):
            for v in ("A", "B"):
                x = A[(A.grp == g) & (A.N == N) & (A["var"] == v) & (A.sess == sess)]
                if not len(x): continue
                for lab, m in (("아무 때나", x.pnl_at > -9), ("그 순간 +0%↑", x.pnl_at >= 0), ("그 순간 +2%↑", x.pnl_at >= 0.02)):
                    line(f"{g} 상위{N} {v} {lab}", x[m])
        pr()
    pr()

pr("## 2. 장중·모의+1년목록 합침 (두 출처는 같은 매매가 겹칠 수 있음 — 참고용)")
for N in (20, 10):
    for v in ("A", "B"):
        x = A[(A.N == N) & (A["var"] == v) & (A.sess == "장중") & A.grp.isin(["모의", "모의(가상 시간끝)", "1년목록(10-13~22)", "실전"])]
        for lab, m in (("아무 때나", x.pnl_at > -9), ("그 순간 +0%↑", x.pnl_at >= 0), ("그 순간 +2%↑", x.pnl_at >= 0.02)):
            line(f"합침 상위{N} {v} {lab}", x[m])
pr()

pr("## 3. 매매법별 (장중, 상위20, B 아무 때나 — 가장 많은 묶음)")
x = A[(A.N == 20) & (A["var"] == "B") & (A.sess == "장중")]
for k, y in x.groupby(["grp", "kind"]):
    line(f"{k[0][:6]} {k[1]}", y)
pr()

pr("## 4. 같은 표를 '실제 매도 이유'별 (장중, 상위20, B)")
x = A[(A.N == 20) & (A["var"] == "B") & (A.sess == "장중")].copy()
x["why"] = np.where(x.reason.str.contains("손절", na=False), "실제 손절", np.where(x.reason.str.contains("다음 날|09:00", na=False), "실제 다음 날 09:00",
            np.where(x.reason.str.contains("장 마감|시간 끝", na=False), "실제 장 마감/시간 끝", "실제 그 밖(익절·큰 음봉·장중)")))
for k, y in x.groupby("why"):
    line(k, y)
pr()

pr("## 5. 사건 목록 (장중, 상위20, A·B 합집합 — 첫 사건)")
x = A[(A.N == 20) & (A.sess == "장중")].sort_values(["var"]).drop_duplicates("id").sort_values("ev_hm")
for r in x.itertuples():
    pr(f"  {r.grp[:4]} {str(r.date)} {r.code} {str(r.name)[:8]:<8} {r.kind[:10]:<10} 매수 {pd.Timestamp(r.buy_ts):%H:%M} {r.buy:>9,.0f} | 사건({r.var}) {pd.Timestamp(r.ev_hm):%m-%d %H:%M} {r.ev_rank:2d}위 그때 {r.pnl_at*100:+5.1f}% → 매도 {r.sell_px:>9,.0f} 전부 {r.full*100:+5.1f}% | 실제 {r.act*100:+5.1f}% ({str(r.reason)[:16]}) {pd.Timestamp(r.exit_ts):%m-%d %H:%M}")
pr()
pr("## 6. 장밖 사건 (NXT) 목록")
x = A[(A.sess == "장밖") & (A.N == 20)].drop_duplicates("id")
for r in x.itertuples():
    pr(f"  {r.grp[:4]} {str(r.date)} {r.code} {str(r.name)[:8]:<8} {r.kind[:10]:<10} 사건({r.var}) {pd.Timestamp(r.ev_hm):%m-%d %H:%M} NXT 매도 전부 {r.full*100:+5.1f}% | 실제 {r.act*100:+5.1f}%")
pr()
pr(f"## 7. 개장 스냅샷(08:00 첫 스냅샷부터 상위) — 본 표에서 뺌: {int((R.sess=='개장스냅샷').sum())}건 (대형주·전날 화제주가 08:00 부터 늘 상위)")
open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
