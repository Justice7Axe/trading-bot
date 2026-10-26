"""🇺🇸 간밤 미국 지수 ↔ 국내 시장·트레이딩 전략 1년 분석 (2026-10-27).

    python -m kiwoom_trading.analysis.us_overnight_bt          # 지수 5년 + 트레이딩 전략 매매별 (full_bt 불러오느라 몇 분)
    python -m kiwoom_trading.analysis.us_overnight_bt --index  # 지수만

자료: index.duckdb idx_daily(코스피 001·코스닥 101), us_daily(us_market --backfill), 매매 목록 = backtest.playbook.full_bt.EV.
결과(2021-11~2026-10): 세 지수 모두 상승 → 코스피 상승 출발 84%(갭 +0.67%), 모두 하락 → 26%(−0.56%), 상관(나스닥↔갭) 0.54·코스닥 0.65,
시가→종가와는 0.01 (무관). 매매별은 SKILL us-overnight 참고.
"""
import sys
from collections import defaultdict
from datetime import date

import duckdb
import numpy as np

from kiwoom_trading.common import us_market as u
from kiwoom_trading.ingestion.collectors.index_collector import INDEX_DB

SPLIT = date(2026, 4, 20)

def index_part(ix):
    for code, nm in (("001", "코스피"), ("101", "코스닥")):
        rows = ix.execute("select date, open, high, low, close from idx_daily where code=? order by date", [code]).fetchall()
        om = u.overnight_map(ix, [r[0] for r in rows])
        res = {}
        for i in range(1, len(rows)):
            d, o, h, l, c = rows[i]; pc = rows[i - 1][4]; ov = om.get(d)
            if not ov or len(ov.changes) < 3: continue
            res.setdefault(ov.direction, []).append((o / pc - 1, c / o - 1, c / pc - 1, ov.nasdaq, d))
        print(f"\n■ {nm} ({rows[0][0]} ~ {rows[-1][0]})")
        for k in ("상승", "혼조", "하락"):
            x = np.array([r[:4] for r in res[k]])
            print(f"  간밤 {k}: {len(x)}일 | 시가 갭 평균 {x[:,0].mean()*100:+.2f}% 상승 출발 {np.mean(x[:,0]>0)*100:.0f}% | 시가→종가 {x[:,1].mean()*100:+.2f}% (오른 날 {np.mean(x[:,1]>0)*100:.0f}%) | 종가 {x[:,2].mean()*100:+.2f}% 오른 날 {np.mean(x[:,2]>0)*100:.0f}%")
        allr = [r for k in res for r in res[k]]
        nq = np.array([r[3] for r in allr]); g = np.array([r[0] for r in allr]); oc = np.array([r[1] for r in allr])
        print(f"  상관: 나스닥 등락 ↔ 시가 갭 {np.corrcoef(nq, g)[0,1]:.2f}, ↔ 시가→종가 {np.corrcoef(nq, oc)[0,1]:.2f}")
        for lo, hi in ((-9, -0.015), (-0.015, -0.005), (-0.005, 0.005), (0.005, 0.015), (0.015, 9)):
            s = [r for r in allr if lo <= r[3] < hi]
            x = np.array([r[:3] for r in s])
            print(f"   나스닥 {lo*100:+.1f}~{hi*100:+.1f}%: {len(s)}일 갭 {x[:,0].mean()*100:+.2f}% (상승 출발 {np.mean(x[:,0]>0)*100:.0f}%) 시가→종가 {x[:,1].mean()*100:+.2f}% 종가 {x[:,2].mean()*100:+.2f}%")
        recent = [r for r in allr if r[4] >= date(2025, 10, 15)]
        x = np.array([r[:2] for r in recent]); nq = np.array([r[3] for r in recent])
        print(f"  최근 1년 상관: 갭 {np.corrcoef(nq, x[:,0])[0,1]:.2f}, 시가→종가 {np.corrcoef(nq, x[:,1])[0,1]:.2f}")


def strategies(ix):
    from kiwoom_trading.backtest.playbook import full_bt as FB
    EV = FB.EV
    kd = [r[0] for r in ix.execute("select date from idx_daily where code='001' and date>='2025-10-01' order by date").fetchall()]
    nx = {kd[i]: kd[i + 1] for i in range(len(kd) - 1)}
    om = u.overnight_map(ix, kd)
    by = defaultdict(list)
    for e in EV: by[e[2]].append(e)
    for k in sorted(by):
        print(f"\n■ {k} 전체 {len(by[k])}건 {np.mean([e[4] for e in by[k]])*100:+.2f}%")
        for lab, f in (("매수 전 간밤", lambda d: om.get(d)), ("들고 넘어간 밤", lambda d: om.get(nx.get(d)))):
            parts = []
            for dn in ("상승", "혼조", "하락"):
                v = [e[4] for e in by[k] if f(e[0]) and f(e[0]).direction == dn]
                if v: parts.append(f"{dn} {len(v)}건 {np.mean(v)*100:+.2f}%")
            print(f"   {lab}: " + " | ".join(parts))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ix = duckdb.connect(INDEX_DB, read_only=True)
    index_part(ix)
    if "--index" not in sys.argv:
        strategies(ix)
