"""일봉만으로 되는 매매 4년 백테스트 (2026-11-01 사용자 '일봉만으로 되는 매매는 2~4년으로 늘려서 백필·백테스트').

자료: daily_ohlcv 2022-01-03~ (engine.daily_day), investor_daily·program_daily 2022-01~. 코스피 idx_daily.
⚠️ 상장폐지 종목은 종목 마스터에 없어 빠짐(생존 편향 → 결과가 실제보다 좋게 나올 수 있음).
1) 7️⃣ 주도주 추세 (trend7.f7: 52주 신고가 & 대금 5위 & 외인·기관 둘 다 순매수 → 20일선 이탈 다음 날 시가)
2) 종가배팅 근사 (대금 10위·상승 마감, 상한가 제외 → 다음 날 시가) — 🌙 종가 재돌파·종가배팅 계열의 바탕
3) 4️⃣ 역행 강세 종가 근사 — 09:10 판정 대신 '그날 대금 상위 200 종가 중앙값 ≤ −2%' 날, 대금 30위 & 중앙 대비 +3%p → 다음 날 시가
4) 연도별·월별 장세(코스피 월 등락·월중 폭·52주 고점 대비)와 위 매매 성적
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading TREND7_START=2022-01-01 .venv\\Scripts\\python.exe kiwoom_trading/research/long_daily/run4y.py
"""
import os, sys
from collections import defaultdict
from datetime import date
import numpy as np
import pandas as pd

os.environ.setdefault("TREND7_START", "2022-01-01")
from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook import trend7 as T7

OUT = os.path.join(E.DATA, "long_daily"); os.makedirs(OUT, exist_ok=True)
f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); f.write(str(s) + "\n"); f.flush()


def stat(rows, title):
    """rows = [(date, ret)]"""
    if len(rows) < 10:
        say(f"  {title}: {len(rows)}건 (적음)"); return
    df = pd.DataFrame(rows, columns=["d", "r"]); ds = sorted(df.d.unique()); h = ds[len(ds) // 2]
    bd = df.groupby("d").r.sum().sort_values(ascending=False)
    star = "★" if df[df.d < h].r.mean() > 0 and df[df.d >= h].r.mean() > 0 and bd.iloc[5:].sum() > 0 else " "
    yr = " · ".join(f"{y}:{g.r.mean():+.2%}({len(g)})" for y, g in df.groupby(pd.to_datetime(df.d).dt.year))
    say(f" {star}{title}: {len(df)}건 건당 {df.r.mean():+.2%} (앞 {df[df.d < h].r.mean():+.2%} 뒤 {df[df.d >= h].r.mean():+.2%}) 승률 {(df.r > 0).mean():.0%} | 연도별 {yr}")
    return df


def main():
    days = [d for d in E.CAL if d >= date(2022, 2, 1)]
    say(f"일봉 {E.CAL[0]} ~ {E.CAL[-1]} ({len(E.CAL)}일), 신호 2022-02 ~")

    # 1) 7️⃣
    say("\n## 1) 7️⃣ 주도주 추세 (52주 신고가 & 대금 5위 & 외인·기관 둘 다 + → 20일선 이탈 매도)")
    t7 = T7.trades(T7.f7)
    r7 = stat([(t["sig"], t["r"]) for t in t7 if not t["open"]], "7️⃣ 주도주 추세")
    if t7:
        say(f"   평균 보유 {np.mean([t['days'] for t in t7]):.0f}일 · 중앙 수익 {np.median([t['r'] for t in t7]):+.1%} · +50%↑ {np.mean([t['r'] >= 0.5 for t in t7]):.0%}")

    # 2) 3) 종가배팅·4️⃣ 근사
    cb, c4 = [], []
    mk_med = {}
    for d in days:
        n = E.next_day(d)
        if not n: continue
        dd, pd_, nd = E.daily_day(d), E.daily_day(E.prev_day(d)), E.daily_day(n)
        rows = []
        for c, r in dd.items():
            if not E.is_common(c) or c not in pd_ or c not in nd or not pd_[c][3]: continue
            ch = r[3] / pd_[c][3] - 1
            rows.append((r[5] or 0, c, ch, r[3], nd[c][0]))
        rows.sort(reverse=True)
        top = rows[:200]
        if len(top) < 100: continue
        med = float(np.median([x[2] for x in top])); mk_med[d] = med
        for v, c, ch, cl, no in rows[:10]:
            if 0 < ch < 0.295 and cl and no:
                r_ = no / cl - 1 - E.COST
                if abs(r_) < 0.35: cb.append((d, r_))
        if med <= -0.02:
            for v, c, ch, cl, no in rows[:30]:
                if ch - med >= 0.03 and ch < 0.295 and cl and no:
                    r_ = no / cl - 1 - E.COST
                    if abs(r_) < 0.35: c4.append((d, r_))
    say("\n## 2) 종가배팅 근사 (대금 10위·상승 마감 → 다음 날 시가)")
    rcb = stat(cb, "종가배팅 근사")
    say("\n## 3) 4️⃣ 역행 강세 종가 근사 (대금 상위 200 종가 중앙 ≤ −2% 날)")
    r4 = stat(c4, "4️⃣ 역행 강세 종가 근사")
    say(f"   해당 날 {sum(1 for v in mk_med.values() if v <= -0.02)}일 / {len(mk_med)}일")

    # 4) 월별 장세
    say("\n## 4) 월별 장세와 매매 (코스피 월 등락 · 월중 고저 폭 · 월말 52주 고점 대비)")
    ix = pd.DataFrame(E.IX.execute("SELECT date, high, low, close FROM idx_daily WHERE code='001' ORDER BY date").fetchall(), columns=["d", "h", "l", "c"])
    ix["hi250"] = ix.c.rolling(250, min_periods=120).max()
    ix["m"] = pd.to_datetime(ix.d).dt.strftime("%Y-%m")
    prev = None
    month_rows = {"7️⃣ 주도주 추세": r7, "종가배팅 근사": rcb, "4️⃣ 역행 강세 종가 근사": r4}
    lab_cnt = defaultdict(lambda: defaultdict(list))
    for m, g in ix.groupby("m"):
        if prev is None or m < "2022-02":
            prev = g.c.iloc[-1]; continue
        ret = g.c.iloc[-1] / prev - 1; rng = g.h.max() / g.l.min() - 1; dd52 = g.c.iloc[-1] / g.hi250.iloc[-1] - 1; prev = g.c.iloc[-1]
        lab = ("🟢 강한 상승장" if ret >= 0.05 else "🔵 상승장" if ret >= 0.02 else ("🟡 출렁이는 횡보" if rng >= 0.10 else "⚪ 박스권") if ret > -0.02
               else "🟠 하락장" if ret > -0.05 else "🔴 강한 하락장")
        parts = []
        for nm, df in month_rows.items():
            if df is None: continue
            x = df[pd.to_datetime(df.d).dt.strftime("%Y-%m") == m]
            if len(x): parts.append(f"{nm} {len(x)}건 {x.r.mean():+.1%}"); lab_cnt[lab][nm].extend(x.r.tolist())
        say(f"  {m} {lab}{' · 약세 국면' if dd52 <= -0.10 else ''} | 월 {ret:+.1%} 폭 {rng:.0%} 고점 {dd52:+.0%} | " + " · ".join(parts))
    say("\n## 5) 장세별 합계 (4년)")
    for lab, d in lab_cnt.items():
        say(f"  {lab}: " + " · ".join(f"{nm} {len(v)}건 {np.mean(v):+.2%}" for nm, v in d.items()))


if __name__ == "__main__":
    main()
