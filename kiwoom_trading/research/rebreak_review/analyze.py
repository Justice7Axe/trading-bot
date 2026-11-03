r"""🌙 종가 재돌파 손실 원인·보완 (2026-11-03 사용자: SK하이닉스 11-02 🌙 신호가 다음 날 −3.9% — 원인 찾고 보완).

매매 기록: research/strict_select trades_feat.pkl 의 🌙 (17:00~18:00 NXT 애프터장 정규장 종가 위 매수 → 다음 날 09:00 매도, 손절 없음).
살펴볼 것 (매수·매도 결정 때 알 수 있는 것만):
  ① 간밤 미국 나스닥 등락 (다음 날 07:50 에 앎) ② 그날 정규장 상승률 ③ 애프터장 매수가가 정규장 종가보다 얼마나 위 ④ 매수 시각(17시 몇 분)
  ⑤ 그날 코스피 등락 ⑥ 대금 순위
보완 후보 (다음 날 아침에 할 수 있는 것):
  A 그대로 09:00 / B 항상 NXT 08:00 시가 / C 나스닥 −1%↓ 이면 08:00, 아니면 09:00 / D 08:00 시가가 매수가 아래면 08:00, 아니면 09:00
  / E 나스닥 −1.5%↓ 면 다음 날 매매 안 함(=그날 밤 신호 무시 불가 → 08:00 정리와 같음, 비교용으로 '그런 날 빼기')
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.rebreak_review.analyze
  → data/rebreak_review/report.txt
"""
import os
import pickle
import sys
from datetime import time

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.common import us_market as U
from kiwoom_trading.research.strict_select import choose as C

OUT = os.path.join(E.DATA, "rebreak_review")
os.makedirs(OUT, exist_ok=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rp = E.Report.__new__(E.Report); rp.f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")
    T = [t for t in pickle.load(open(os.path.join(C.OUT, "trades_feat.pkl"), "rb")) if t["kind"] == "🌙"]
    nds = [E.next_day(t["date"]) for t in T]
    om = U.overnight_map(E.IX, [n for n in nds if n])
    rows = []
    for t, n in zip(T, nds):
        if not n:
            continue
        c, d, buy = t["code"], t["date"], t["px"]
        dd, pdd = E.daily_day(d).get(c), E.daily_day(E.prev_day(d)).get(c)
        ex = E.next_day_exits(c, d, buy)
        ov = om.get(n)
        rows.append(dict(date=d, code=c, name=E.NAME.get(c, c), t=t["t"], rk=t.get("rk"), A=t["ret"], B=ex.get("08:00 NXT 시가"),
                         nq=ov.nasdaq if ov else np.nan, day_chg=(dd[3] / pdd[3] - 1) if dd and pdd else np.nan,
                         ah=(buy / dd[3] - 1) if dd else np.nan, kospi=E.kospi_chg(d), tmin=t["t"].hour * 60 + t["t"].minute - 17 * 60))
    df = pd.DataFrame(rows)
    df["C"] = np.where((df.nq <= -0.01) & df.B.notna(), df.B, df.A)
    df["D"] = np.where(df.B.notna() & (df.B + E.COST < 0), df.B, df.A)
    df.to_parquet(os.path.join(OUT, "trades.parquet"))
    rp.say(f"🌙 종가 재돌파 {len(df)}건 ({df.date.min()} ~ {df.date.max()}) — 지금 규칙(다음 날 09:00) 건당 {df.A.mean():+.2%}, 승률 {(df.A > 0).mean():.0%}")
    rp.say(f"  −3%↓ 손실 {int((df.A <= -0.03).sum())}건 · 최악 {df.A.min():+.1%}")
    rp.say("\n## 언제 손실이 나나 (셋으로 나눠, 건당 · 승률 · 건수)")
    for col, nm in (("nq", "간밤 나스닥"), ("day_chg", "그날 정규장 상승률"), ("ah", "애프터 매수가 − 정규장 종가"), ("tmin", "매수 시각(17시 뒤 분)"),
                    ("kospi", "그날 코스피"), ("rk", "대금 순위")):
        v = df[[col, "A"]].dropna()
        q = pd.qcut(v[col], 3, labels=False, duplicates="drop")
        rp.say(f"  {nm:22s} " + " | ".join(f"{v[col][q == k].min():.3g}~{v[col][q == k].max():.3g}: {v.A[q == k].mean():+.2%} 승률 {(v.A[q == k] > 0).mean():.0%} ({int((q == k).sum())})"
                                           for k in sorted(q.unique())))
    rp.say("  간밤 나스닥 구간: " + " | ".join(f"{lo:+.1%}~{hi:+.1%}: {df.A[(df.nq > lo) & (df.nq <= hi)].mean():+.2%} ({int(((df.nq > lo) & (df.nq <= hi)).sum())}건)"
                                          for lo, hi in ((-0.2, -0.015), (-0.015, -0.005), (-0.005, 0.005), (0.005, 0.015), (0.015, 0.2))))
    rp.say("\n## 보완 후보 — 같은 554건, 다음 날 아침 파는 방법만 바꿈")
    has = df[df.B.notna()]
    rp.say(f"  (NXT 08:00 가격이 있는 것 {len(has)}건에서 비교)")
    for col, nm in (("A", "A 그대로 다음 날 09:00"), ("B", "B 항상 NXT 08:00 시가"), ("C", "C 간밤 나스닥 −1%↓ 면 08:00, 아니면 09:00"),
                    ("D", "D 08:00 시가가 매수가 아래면 08:00, 아니면 09:00")):
        rp.stats([(r.date, getattr(r, col)) for r in has.itertuples()], nm)
    bad = df[df.nq <= -0.015]
    rp.stats([(r.date, r.A) for r in bad.itertuples()], "참고: 간밤 나스닥 −1.5%↓ 날 09:00")
    rp.stats([(r.date, r.B) for r in bad.itertuples() if r.B == r.B], "참고: 간밤 나스닥 −1.5%↓ 날 08:00")
    rp.say("\n## 11-02 SK하이닉스 같은 경우 (정규장 +3%↑ 마감 & 애프터 +0.3% 안쪽 재돌파 & 17:30 뒤)")
    sim = df[(df.day_chg >= 0.03) & (df.ah <= 0.003) & (df.tmin >= 30)]
    rp.stats([(r.date, r.A) for r in sim.itertuples()], "비슷한 매매 09:00")


if __name__ == "__main__":
    main()
