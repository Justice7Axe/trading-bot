"""차트 패턴으로 상승 초입 잡기 — 컵앤핸들·평평한 박스·신고가 돌파 (2026-11-01 사용자 '보조 지표로 상승 초입을 잡을 수 없나? 예로 컵앤핸들').

일봉(engine.daily_day, 수정주가, 9-14 뒤는 1분봉 있는 종목만 정규장 값) 2024-10-11~ 전 종목(우선주 제외). D 장 마감에 패턴 확인 → D+1 시가 매수.
대상: 20일 평균 대금 30억↑, 종가 1,000원↑, 상한가 마감 제외. 신호는 2025-04-01 부터 (앞 기간은 패턴 계산용).
매도 (손절 먼저·같은 날이면 손절, 못 닿으면 기간 끝 다음 날 시가, 종가 매도 안 함, 비용 0.25%):
  · 오닐 +20/−7 (최대 40일) · +10/−5 (5일) · 다음 날 시가 · 20일선 이탈 다음 날 시가 (−8% 손절, 최대 60일)
D+1 시가 갭 +29.5%↑(상한가 시작)은 못 산 것으로 뺌 (고른 뒤 처리, 다른 종목으로 채우지 않음).
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/chart_patterns/patterns.py
"""
import os, sys
from collections import defaultdict
from datetime import date
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "chart_patterns"); os.makedirs(OUT, exist_ok=True)
SIG0 = date.fromisoformat(os.environ.get("PAT_SIG0", "2025-04-01"))     # 4년: PAT_SIG0=2022-07-01 (2026-11-01)
EXITS = {"오닐 +20/−7·40일": (0.20, 0.07, 40, False), "+10/−5·5일": (0.10, 0.05, 5, False),
         "다음 날 시가": (None, None, 1, False), "20일선 이탈 (−8%)": (None, 0.08, 60, True)}


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep("report" + os.environ.get("PAT_SUFFIX", "") + ".txt")


def panel():
    rows = []
    for d in E.CAL:
        for c, r in E.daily_day(d).items():
            if E.is_common(c): rows.append((d, c, *r))
    return pd.DataFrame(rows, columns=["date", "code", "o", "h", "l", "c", "v", "val"]).sort_values(["code", "date"]).reset_index(drop=True)


def exit_ret(o, h, l, c, ma20, i, tp, sl, H, trail):
    n = len(o)
    if i + 1 >= n: return np.nan
    buy = o[i + 1]; sp = buy * (1 - sl) if sl else None; tpp = buy * (1 + tp) if tp else None
    last = min(n - 1, i + H)
    for k in range(i + 1, last + 1):
        if sp and l[k] <= sp:
            return (min(o[k], sp) if k > i + 1 else sp) / buy - 1 - E.COST
        if tpp and h[k] >= tpp:
            return (max(o[k], tpp) if k > i + 1 else tpp) / buy - 1 - E.COST
        if trail and c[k] < ma20[k]:
            return (o[k + 1] / buy - 1 - E.COST) if k + 1 < n else np.nan
    if i + H + 1 >= n: return np.nan
    return o[i + H + 1] / buy - 1 - E.COST


def detect(g):
    """한 종목 일봉 → 신호 목록 [(i, 패턴, 정보)]."""
    o, h, l, c, v, val = (g[k].astype(float).values for k in ("o", "h", "l", "c", "v", "val"))
    dates = g.date.values; n = len(c)
    av50 = pd.Series(v).rolling(50, min_periods=30).mean().shift(1).values
    val20 = pd.Series(val).rolling(20).mean().values
    ma20 = pd.Series(c).rolling(20).mean().values
    out = []
    for i in range(60, n):
        if dates[i] < SIG0: continue
        if not (val20[i] >= 3e9 and c[i] >= 1000 and c[i] / c[i - 1] - 1 < 0.295 and c[i] > c[i - 1]): continue
        vr = v[i] / av50[i] if av50[i] and av50[i] > 0 else 0
        # 신고가 돌파 (전날까지 N일 고가 위 마감)
        for N, nm in ((250, "250일 신고가 돌파"), (120, "120일 신고가 돌파")):
            if i - N >= 0 or (N == 250 and i >= 120):
                lo = max(0, i - N)
                if c[i] > h[lo:i].max() and vr >= 1.5:
                    out.append((i, nm, vr))
        # 평평한 박스: 직전 25~60일 폭 15% 안, 마감이 박스 고가 위, 거래량 1.4배
        for L in (25, 40, 60):
            hi, lw = h[i - L:i].max(), l[i - L:i].min()
            if hi / lw - 1 <= 0.15 and c[i] > hi and vr >= 1.4:
                out.append((i, "평평한 박스 돌파", vr)); break
        # 컵앤핸들
        if vr < 1.4: continue
        hs = i - 25 + int(np.argmax(h[i - 25:i - 4]))          # 손잡이 시작 = 오른쪽 테두리
        hh = h[hs]; hl = l[hs:i].min(); hlen = i - hs
        if not (5 <= hlen <= 25 and 0.03 <= 1 - hl / hh <= 0.15 and c[i] > hh): continue
        a, b = max(0, hs - 250), hs - 30
        if b - a < 10: continue
        L = a + int(np.argmax(h[a:b])); lh = h[L]
        if not (0.90 * lh <= hh <= 1.05 * lh): continue
        bi = L + int(np.argmin(l[L:hs])); bottom = l[bi]
        depth = 1 - bottom / lh; cl = hs - L
        if not (0.12 <= depth <= 0.40 and 30 <= cl <= 250): continue
        if not (L + 0.2 * cl <= bi <= L + 0.8 * cl): continue                  # U 자 (바닥이 가운데쯤)
        if hl < bottom + 0.5 * (lh - bottom): continue                          # 손잡이는 컵 위쪽 절반
        pre = l[max(0, L - 120):L + 1].min() if L > 20 else np.nan
        if not (pre == pre and lh >= 1.25 * pre): continue                     # 앞선 상승 25%↑
        if not (v[hs:i].mean() < av50[i]): continue                             # 손잡이 거래량 줄어듦
        out.append((i, "컵앤핸들", vr))
    return out, (o, h, l, c, ma20, dates)


def main():
    df = panel()
    kospi = pd.Series(E.KOSPI).sort_index(); kma = (kospi / kospi.rolling(20).mean() - 1).to_dict()
    sig, base = [], []
    rng = np.random.default_rng(0)
    for code, g in df.groupby("code", sort=False):
        if len(g) < 120: continue
        s, (o, h, l, c, ma20, dates) = detect(g)
        gap = lambda i: o[i + 1] / c[i] - 1 if i + 1 < len(o) else np.nan
        for i, nm, vr in s:
            if not (gap(i) < 0.295): continue
            rec = dict(date=dates[i], code=code, pat=nm, vr=vr, k_ma20=kma.get(dates[i], np.nan))
            for en, (tp, sl, H, tr) in EXITS.items():
                rec[en] = exit_ret(o, h, l, c, ma20, i, tp, sl, H, tr)
            sig.append(rec)
        # 비교: 같은 대상 조건(대금·가격·상승 마감)에서 무작위 표본
        val20 = pd.Series(g.val.astype(float).values).rolling(20).mean().values
        for i in range(60, len(c) - 1):
            if dates[i] < SIG0 or not (val20[i] >= 3e9 and c[i] >= 1000 and c[i] > c[i - 1] and c[i] / c[i - 1] - 1 < 0.295): continue
            if rng.random() > 0.03 or not (gap(i) < 0.295): continue
            rec = dict(date=dates[i], code=code, pat="(비교) 아무 상승 마감 종목", vr=np.nan, k_ma20=kma.get(dates[i], np.nan))
            for en, (tp, sl, H, tr) in EXITS.items():
                rec[en] = exit_ret(o, h, l, c, ma20, i, tp, sl, H, tr)
            base.append(rec)
    S = pd.DataFrame(sig + base)
    S.to_parquet(os.path.join(OUT, "signals" + os.environ.get("PAT_SUFFIX", "") + ".parquet"))
    days = sorted(S.date.unique()); hh = days[len(days) // 2]
    R.say(f"신호 기간 {min(days)} ~ {max(days)} ({len(days)}일), 반 나눔 {hh}")

    def line(x, en):
        v = x[["date", en]].dropna()
        if len(v) < 15: return f"{len(v)}건 (적음)"
        a, b = v[v.date < hh][en].mean(), v[v.date >= hh][en].mean()
        bd = v.groupby("date")[en].sum().sort_values(ascending=False)
        star = "★" if a > 0 and b > 0 and bd.iloc[5:].sum() > 0 else " "
        return f"{star} {len(v):5d}건 건당 {v[en].mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%}) 승률 {(v[en] > 0).mean():.0%} 최고5일 빼면 {bd.iloc[5:].sum() * 100:+.0f}만"

    for p, x in S.groupby("pat"):
        R.say(f"\n## {p}")
        for en in EXITS:
            R.say(f"  {en:16s} {line(x, en)}")
        for nm, mk in (("코스피 20일선 위", x.k_ma20 >= 0), ("코스피 20일선 아래", x.k_ma20 < 0)):
            R.say(f"   [{nm}] 오닐 {line(x[mk], '오닐 +20/−7·40일')} | 다음 날 {line(x[mk], '다음 날 시가')}")
    cup = S[S.pat == "컵앤핸들"]
    if len(cup):
        R.say("\n## 컵앤핸들 예시 (최근 20건)")
        for r in cup.sort_values("date").tail(20).itertuples():
            R.say(f"  {r.date} {E.NAME.get(r.code, r.code)}({r.code}) 거래량 {r.vr:.1f}배 → 오닐 {getattr(r, '_6'):+.1%}" if False else
                  f"  {r.date} {E.NAME.get(r.code, r.code)}({r.code}) 거래량 {r.vr:.1f}배 → 오닐 {r[6]:+.1%} · 다음 날 {r[8]:+.1%}")


if __name__ == "__main__":
    main()
