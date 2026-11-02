"""장 초 고점 눌림 뒤 재돌파 매수 · 1분봉 이동평균 역배열 매도 — 1년 백테스트
(2026-11-02 사용자: SK하이닉스 11-02 차트 — 시가 뒤 눌렸다 장 초 고점 돌파에 매수, 120선 역배열 될 때 매도가 맞지 않나?)

대상: 전날 대금 30위 안(우선주·ETF 제외, 전날 정보만) — 그날 1분봉이 있는 종목.
매수: 09:00~09:10 고가 H0 → 그 뒤 H0 대비 −1.5%↓ 눌림 → 09:15~11:00 사이 종가가 H0 위로 처음 마감한 봉 → 다음 봉 시가.
      (비교: 장 초 구간 5분/15분, 눌림 −1%/−2.5%)
매도 (손절 = 눌림 저가, 같은 봉이면 손절 먼저, 종가 매도 없음, 비용 0.25%):
  A 역배열: 1분봉 이동평균 5 < 20 < 60 < 120 이 처음 될 때 그 봉 종가 → 15:19 까지 안 되면 다음 날 09:00
  B 20·120 데드크로스: 20선이 120선 아래로 내려갈 때 → 15:19 까지 없으면 다음 날 09:00
  C 비교: 손절만, 다음 날 09:00
  D 비교: 손절만, 15:19 (당일 정리)
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.open_pullback_break.bt
  → data/open_pullback_break/report.txt
"""
import os
import sys
from datetime import time

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.hong_styles.backtest import MKT

OUT = os.path.join(E.DATA, "open_pullback_break")
os.makedirs(OUT, exist_ok=True)
TOPN = 30


def ma(a, n):
    s = pd.Series(a)
    return s.rolling(n, min_periods=n).mean().values


def run_one(c, d, reg, f_prev_close, win=10, dip=0.015):
    t_end = time(9, win)
    first = [x for x in reg if x[0] < t_end]
    if len(first) < 3:
        return None
    h0 = max(x[2] for x in first)
    k0 = len(first)
    low_after = None; dipped = False; kb = None
    for k in range(k0, len(reg)):
        x = reg[k]
        if x[0] > time(11, 0):
            break
        low_after = x[3] if low_after is None else min(low_after, x[3])
        if low_after <= h0 * (1 - dip):
            dipped = True
        if dipped and x[0] >= time(9, 15) and x[4] > h0:
            kb = k; break
    if kb is None or kb + 1 >= len(reg):
        return None
    buy = reg[kb + 1][1]; sp = low_after
    if buy / f_prev_close - 1 > 0.25:
        return None
    # 1분봉 이동평균: 전날 봉 없이 그날 정규장 봉으로 (120선은 11:00 이후에야 생김 → 전날 마지막 120봉을 앞에 붙임)
    closes = np.array([x[4] for x in reg], float)
    m5, m20, m60, m120 = (ma(closes, n) for n in (5, 20, 60, 120))
    res = {}
    nx = E.next_day_exits(c, d, buy).get("09:00 시가")
    for nm in ("A", "B", "C", "D"):
        r = None
        for k in range(kb + 1, len(reg)):
            x = reg[k]
            if x[0] > time(15, 19):
                break
            if x[3] <= sp:
                r = min(x[1], sp) / buy - 1 - E.COST; break
            if k == kb + 1:
                continue
            if nm == "A" and not np.isnan(m120[k]) and m5[k] < m20[k] < m60[k] < m120[k]:
                r = x[4] / buy - 1 - E.COST; break
            if nm == "B" and not np.isnan(m120[k]) and not np.isnan(m120[k - 1]) and m20[k - 1] >= m120[k - 1] and m20[k] < m120[k]:
                r = x[4] / buy - 1 - E.COST; break
        if r is None:
            if nm == "D":
                r = E.at(reg, time(15, 19)) / buy - 1 - E.COST
            else:
                r = nx
        res[nm] = r
    return dict(date=d, code=c, name=E.NAME.get(c, c), t=reg[kb + 1][0], buy=buy, h0=h0, stop=sp, **res)


def prepend_prev(c, d, reg):
    """이동평균이 장 초부터 있도록 전날 정규장 마지막 120봉을 앞에 붙임 (가격 기준 다르면 안 붙임)."""
    p = E.prev_day(d)
    prev = E.regular(E.bars(c, p))
    fd, fp = E.factor(c, d), E.factor(c, p)
    if not prev or not fd or not fp or abs(fd / fp - 1) > 0.003:
        return reg, 0
    return prev[-120:] + reg, len(prev[-120:])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); f.write(s + "\n"); f.flush()

    rows = {k: [] for k in ("기본 10분·−1.5%", "5분·−1.5%", "15분·−1.5%", "10분·−1%", "10분·−2.5%")}
    params = {"기본 10분·−1.5%": (10, 0.015), "5분·−1.5%": (5, 0.015), "15분·−1.5%": (15, 0.015), "10분·−1%": (10, 0.01), "10분·−2.5%": (10, 0.025)}
    for n, d in enumerate(E.days()):
        if not E.next_day(d):
            continue
        p = E.prev_day(d)
        vr = E.value_rank(p)
        codes = [c for c, r in sorted(vr.items(), key=lambda x: x[1]) if E.is_common(c)][:TOPN]
        pdd = E.daily_day(p)
        for c in codes:
            reg = E.regular(E.bars(c, d))
            fct = E.factor(c, d)
            if len(reg) < 100 or not fct or c not in pdd:
                continue
            full, off = prepend_prev(c, d, reg)
            for lab, (w, dp) in params.items():
                r = run_one_off(c, d, full, off, pdd[c][3] * fct, w, dp)
                if r:
                    r["mkt"] = MKT.get(d); rows[lab].append(r)
        if n % 25 == 0:
            print(f"  {d} {len(rows['기본 10분·−1.5%'])}건", flush=True)
    say(f"장 초 고점 눌림 뒤 재돌파 매수 — 1년 ({E.days()[0]} ~ {E.days()[-1]}), 전날 대금 {TOPN}위, 비용 0.25%, 손절 = 눌림 저가")
    say("매도: A 1분 이평 5<20<60<120 역배열 / B 20·120 데드크로스 / C 다음 날 09:00 / D 당일 15:19 (A·B 는 15:19 까지 안 오면 다음 날 09:00)")
    rp = E.Report.__new__(E.Report); rp.f = f
    for lab, rs in rows.items():
        df = pd.DataFrame(rs)
        say(f"\n## {lab} — {len(df)}건")
        if df.empty:
            continue
        for x, nm in (("A", "A 역배열 매도"), ("B", "B 20·120 데드크로스"), ("C", "C 손절만·다음 날 09:00"), ("D", "D 손절만·15:19")):
            rp.stats([(r.date, getattr(r, x)) for r in df.itertuples() if getattr(r, x) == getattr(r, x) and getattr(r, x) is not None], nm)
        if lab.startswith("기본"):
            for tag in sorted(df.mkt.dropna().unique()):
                g = df[df.mkt == tag]
                rp.stats([(r.date, r.A) for r in g.itertuples() if r.A == r.A], f"  A · {tag}")
            g = df[df.code == "000660"]
            say(f"  SK하이닉스만 {len(g)}건 A 건당 {g.A.mean():+.2%}" if len(g) else "")
            df.to_parquet(os.path.join(OUT, "trades.parquet"))


def run_one_off(c, d, full, off, prev_close, w, dp):
    """full = 전날 120봉 + 그날 봉. 매수 판단은 그날 봉만, 이동평균은 full 로."""
    reg = full[off:]
    t_end = time(9, w) if w < 60 else time(10, 0)
    first = [x for x in reg if x[0] < t_end]
    if len(first) < 3:
        return None
    h0 = max(x[2] for x in first)
    low_after = None; dipped = False; kb = None
    for k in range(len(first), len(reg)):
        x = reg[k]
        if x[0] > time(11, 0):
            break
        low_after = x[3] if low_after is None else min(low_after, x[3])
        if low_after <= h0 * (1 - dp):
            dipped = True
        if dipped and x[0] >= time(9, 15) and x[4] > h0:
            kb = k; break
    if kb is None or kb + 1 >= len(reg):
        return None
    buy = reg[kb + 1][1]; sp = low_after
    if buy / prev_close - 1 > 0.25:
        return None
    closes = np.array([x[4] for x in full], float)
    m5, m20, m60, m120 = (ma(closes, n) for n in (5, 20, 60, 120))
    nx = E.next_day_exits(c, d, buy).get("09:00 시가")
    res = {}
    for nm in ("A", "B", "C", "D"):
        r = None
        for k in range(kb + 1, len(reg)):
            x = reg[k]; j = k + off
            if x[0] > time(15, 19):
                break
            if x[3] <= sp:
                r = min(x[1], sp) / buy - 1 - E.COST; break
            if k == kb + 1 or np.isnan(m120[j]):
                continue
            if nm == "A" and m5[j] < m20[j] < m60[j] < m120[j]:
                r = x[4] / buy - 1 - E.COST; break
            if nm == "B" and m20[j - 1] >= m120[j - 1] and m20[j] < m120[j]:
                r = x[4] / buy - 1 - E.COST; break
        if r is None:
            r = (E.at(reg, time(15, 19)) / buy - 1 - E.COST) if nm == "D" else nx
        res[nm] = r
    return dict(date=d, code=c, name=E.NAME.get(c, c), t=reg[kb + 1][0], buy=buy, h0=h0, stop=sp, **res)


if __name__ == "__main__":
    main()
