"""☕ 카페 테마 대장 — 11-17 손실(가온칩스·RFHIC) 뒤 매수·매도 자리 개선 후보 1년 검증 (2026-11-18).

backtest.py 와 같은 매수 자리(①+③, 1분봉 고점 돌파+햄버거 → 돌파 고점 눌림 지정가, 대상 = 전날 대금 200위 안)에서
매도 규칙·진입 거르기만 바꿔 같은 매매 목록으로 비교한다.
  손절 −2%(지금)·−3%·−4% / 절반 익절 뒤 남은 절반 손절을 산 값(본전)으로 올림 / 매수 때 등락률 상한(+15%·+20%) / 테마 +4%↑ 종목 3개↑
매도 공통: 절반 +2.5%, 나머지 상한가 / 손절 즉시(같은 봉이면 손절 먼저) / 아니면 다음 날 09:00. 지정가 체결 봉에선 익절 안 함. 비용 0.25%.
계좌 시뮬: 10만·100만 원, 하루 3종목, 종목당 (그때 잔고 ÷ 3), 매수 시각 순서, 복리 (1주 가격이 몫보다 비싸면 못 삼).

실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.cafe_leader.exit_study [--report-only]
  → data/cafe/exit_study.txt, exit_study.pkl
"""
from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.cafe_leader import backtest as B

OUT = B.OUT
STOPS = (0.02, 0.03, 0.04)


def exit_var(c, d, reg, k, buy, pc, stop, be):
    """reg[k] 봉에서 buy 에 지정가 체결 → (수익률, 매도 시각 문자열). be = 절반 익절 뒤 손절선을 산 값으로."""
    sp, tp, lim = buy * (1 - stop), buy * (1 + B.HALF_TP), pc * 1.295
    left, r, half = 1.0, 0.0, False
    for x in reg[k:]:
        if x[3] <= sp:
            return r + left * (min(x[1], sp) / buy - 1) - E.COST, x[0]
        if x is reg[k]:
            continue
        if not half and x[2] >= tp:
            r += 0.5 * (max(x[1], tp) / buy - 1)
            left, half = 0.5, True
            if be:
                sp = buy
        if x[2] >= lim:
            return r + left * (lim / buy - 1) - E.COST, x[0]
    nx = E.next_day_exits(c, d, buy)
    if "09:00 시가" not in nx:
        return None, None
    return r + left * (nx["09:00 시가"] + E.COST) - E.COST, "다음날"


def day_trades(d):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    pd_ = E.daily_day(p)
    U = [c for c, r in vr.items() if r <= 200 and E.is_common(c) and c in pd_]
    Bd = E.load_day(U, d)
    info = {}
    for c in U:
        b = Bd[c]
        reg = E.regular(b)
        f = E.factor(c, d)
        if len(reg) < 60 or not f:
            continue
        pre = [x for x in b if x[0] < time(9, 0)]
        info[c] = dict(reg=reg, pre=pre, pc=pd_[c][3] * f, prev=sum(B.val(x) for x in pre))
    out = []
    for c, v in info.items():
        reg, pc = v["reg"], v["pc"]
        if v["prev"] < B.PRE_VALUE:      # ③ 프리장 50억↑ 만 (지금 규칙 ①③⑥ 중 ③)
            continue
        hi = None
        for j, x in enumerate(reg):
            t = x[0]
            if t > B.LAST_BUY:
                break
            if hi is not None and j >= 3 and x[4] > hi and x[4] > x[1]:
                prev5 = [B.val(y) for y in reg[max(0, j - 5):j]]
                bv = B.val(x)
                if bv >= B.BAR_VALUE and bv >= B.BAR_MULT * (np.mean(prev5) if prev5 else 0) and j + 1 < len(reg):
                    lead, n = B.leader_at(c, d, t, info, by="value")
                    if lead:
                        fill = None
                        for k in range(j + 1, min(j + 11, len(reg))):
                            if reg[k][3] <= hi:
                                fill = (k, min(reg[k][1], hi))
                                break
                        if fill:
                            tr = dict(code=c, date=d, t=t, fill_t=reg[fill[0]][0], buy=fill[1], chg=fill[1] / pc - 1, n_up=n,
                                      open_gap=reg[0][1] / pc - 1)
                            for s in STOPS:
                                for be in (False, True):
                                    tr[(s, be)], tr[("t", s, be)] = exit_var(c, d, reg, fill[0], fill[1], pc, s, be)
                            out.append(tr)
                    break      # 종목당 하루 첫 돌파만 (backtest.py 와 같음)
            hi = x[2] if hi is None else max(hi, x[2])
    return out


def run():
    allt = []
    for i, d in enumerate(E.days()):
        allt += day_trades(d)
        if i % 20 == 0:
            print(f"  {d} 누적 {len(allt)}", file=sys.stderr)
    with open(os.path.join(OUT, "exit_study.pkl"), "wb") as f:
        pickle.dump(allt, f)
    return allt


def account(trs, key, start, slots=3):
    """하루 slots 종목, 종목당 그때 잔고 ÷ slots. 매수가 1주보다 몫이 작으면 못 삼. 같은 날 매도는 그날 끝에 반영(보수적)."""
    cash = start
    peak, mdd = start, 0.0
    by = defaultdict(list)
    for t in trs:
        if t.get(key) is not None:
            by[t["date"]].append(t)
    n = 0
    for d in sorted(by):
        day = sorted(by[d], key=lambda t: t["fill_t"])[:slots]
        alloc = cash / slots
        pnl = 0.0
        for t in day:
            q = int(alloc // t["buy"])
            if q <= 0:
                continue
            n += 1
            pnl += q * t["buy"] * t[key]
        cash += pnl
        peak = max(peak, cash)
        mdd = max(mdd, 1 - cash / peak)
    return cash, mdd, n


def report(allt):
    R = B.Rep(os.path.join(OUT, "exit_study.txt"))
    days = E.days()
    R.say(f"☕ 카페 테마 대장 ①③⑥ 눌림 지정가 — 매도·거르기 후보 1년 ({days[0]} ~ {days[-1]}), 대상 전날 대금 200위, 1건 100만 기준 '만'")
    R.say("★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +. 계좌 = 하루 3종목·잔고÷3·복리, 매수 시각 순서\n")
    h = sorted({t["date"] for t in allt})
    rec = sorted({t["date"] for t in allt})[-1]
    def line(name, ts, key):
        st = R.stats([(t["date"], t[key]) for t in ts if t.get(key) is not None], name, 46)
        a10, m10, n10 = account(ts, key, 100_000)
        a100, m100, n100 = account(ts, key, 1_000_000)
        R.say(f"      계좌 10만 → {a10:,.0f} (낙폭 {m10:.0%}, {n10}건) · 100만 → {a100:,.0f} (낙폭 {m100:.0%}, {n100}건)")
        return st
    base = (0.02, False)
    R.say("## 1. 매도 규칙 (같은 매수 목록)")
    for s in STOPS:
        for be in (False, True):
            line(f"손절 −{s:.0%}{' · 절반 익절 뒤 본전 손절' if be else ''}{' (지금)' if (s, be) == base else ''}", allt, (s, be))
    R.say("\n## 2. 매수 거르기 (손절 −2%, 지금 매도)")
    for name, f in (("지금 그대로", lambda t: True),
                    ("매수가 어제 대비 +15% 넘으면 안 삼", lambda t: t["chg"] <= 0.15),
                    ("매수가 어제 대비 +20% 넘으면 안 삼", lambda t: t["chg"] <= 0.20),
                    ("테마 +4%↑ 종목 3개↑만", lambda t: t["n_up"] >= 3),
                    ("시가 갭 +10% 넘으면 안 삼", lambda t: t["open_gap"] <= 0.10)):
        line(name, [t for t in allt if f(t)], base)
    R.say("\n## 3. 묶음")
    for name, f, key in (("+20% 넘으면 안 삼 · 절반 뒤 본전", lambda t: t["chg"] <= 0.20, (0.02, True)),
                         ("+15% 넘으면 안 삼 · 절반 뒤 본전", lambda t: t["chg"] <= 0.15, (0.02, True))):
        line(name, [t for t in allt if f(t)], key)
    R.say("\n## 4. 최근 석 달 (2026-08 뒤)")
    import datetime as _dt
    rec = [t for t in allt if t["date"] >= _dt.date(2026, 8, 1)]
    for s, be in ((0.02, False), (0.02, True), (0.03, False)):
        line(f"[최근] 손절 −{s:.0%}{' · 본전' if be else ''}", rec, (s, be))
    for name, f in (("[최근] +20% 넘으면 안 삼", lambda t: t["chg"] <= 0.20), ("[최근] +15% 넘으면 안 삼", lambda t: t["chg"] <= 0.15)):
        line(name, [t for t in rec if f(t)], base)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--report-only" in sys.argv:
        with open(os.path.join(OUT, "exit_study.pkl"), "rb") as f:
            report(pickle.load(f))
        return
    report(run())


if __name__ == "__main__":
    main()
