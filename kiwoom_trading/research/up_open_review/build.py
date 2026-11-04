"""1️⃣ 상승장 장 초 1년 후보 전체 + 09:10 이전 특징값 (2026-11-04 사용자 '광전자는 왜 손실 났는지 … 매매 전략에 업데이트').

후보 = build_up.py 와 같은 정의 (전날 외인·기관 둘 다 순매도 제외는 **하지 않고** 칸으로만 남김 — 실전 비교용):
  강한 상승장(U) 날, 전날 대금 상위 200 주식 중 그날 1분봉(통합 AL) 60개 이상·09:01 전 시작, 가격 안 맞는 목록(mismatch) 아님,
  09:10 직전까지 누적 대금 순위(그 표본 안) ≤ 40, 09:09 봉 종가 > 09:00 시가.
U 날 = regime_feat 판정(~10-23) + 장중 로그의 09:10 판정(10-27, 10-28 — 1분봉이 다음 날까지 있는 날).
매수 = 09:11 봉 시가 (원가격), 상한가 근처(+29%↑) 못 삼, 전일 대비 +15% 넘으면 안 삼(live.UP_MAX_PREV_GAIN) 칸 표시.
매도 = 1️⃣ 실제 규칙: 익절 없음 · 매수가 −6% 닿으면 즉시(시가가 이미 아래면 시가) · 15:19 봉까지 안 닿으면 다음 날 09:00 시가. 비용 0.25%.
  (backtest-rules 3장, bt_up_chase2 / account_alloc.build_trades.up_trades 와 같은 계산)
특징값 (모두 09:10 이전에 앎):
  vrank 09:10 누적 대금 순위 · from_open 09:09 종가/시가 · gap 시가/전일 정규장 종가 · chg 09:09 종가/전일 종가
  off_hi 09:09 종가/09:00~09:09 고가 − 1 · pos (종가−저가)/(고가−저가) · cval 09:10 누적 대금 · cval_r 누적 대금 ÷ 20일 평균 하루 대금
  d1 전날 등락 · d5 전날까지 5일 등락 · d10max 전날까지 10일 중 하루 최대 대금 ÷ 그 전 20일 평균 · spike_ago 그 날이 며칠 전
  hi250 전날 종가 ÷ 250일 고가 − 1 · fr/ins 전날 외인·기관 순매수 · mcap 전날 시총 · age 상장 뒤 거래일 수(오늘 포함, 일봉 첫날 = 상장일,
  2022-01-03 첫날 종목은 기존 상장) · 날 특징 K1z·M0·dd52·전날 시장 상황.
출력: data/up_open_review/cands.pkl
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.up_open_review.build
"""
import os
import pickle
import sys
from collections import Counter
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import BAD, cls, feat

OUT = os.path.join(E.DATA, "up_open_review")
os.makedirs(OUT, exist_ok=True)
STOP = 0.06
# 10-24 이후 강한 상승장 (장중 로그 09:10 판정): K1z, M0, dd52(로그의 '52주 고점 대비')
EXTRA = {date(2026, 10, 27): dict(K1z=1.42, M0=0.039, dd52=-0.40), date(2026, 10, 28): dict(K1z=1.00, M0=0.034, dd52=-0.40)}
FIRST_DAY = dict(E.DM.execute("SELECT code, min(date) FROM daily_ohlcv GROUP BY code").fetchall())
OLDEST = min(FIRST_DAY.values())


def prev_regular(c, d):
    p = E.prev_day(d)
    if not p:
        return None
    r = E.regular(E.bars(c, p))
    if len(r) < 30:
        return None
    k = 1.0
    fd, fp = E.factor(c, d), E.factor(c, p)
    if fd and fp and abs(fd / fp - 1) > 0.003:
        k = fd / fp
    return r[-1][4] * k


def age_of(c, d):
    f = FIRST_DAY.get(c)
    if f is None or f == OLDEST or f not in E.CIDX:
        return 9999
    return E.CIDX[d] - E.CIDX[f] + 1


def u_days():
    out = {}
    for d, x in feat.items():
        if cls(d) == "U":
            out[d] = dict(K1z=x["K1z"], M0=x["M0"], dd52=x["dd52"])
    out.update(EXTRA)
    return {d: v for d, v in sorted(out.items()) if d in E.CIDX and E.next_day(d)}


def day_rows(d, dx):
    prev = E.prev_day(d)
    pdaily = E.daily_day(prev)
    uni = [c for c, _ in sorted(((c, r[5] or 0) for c, r in pdaily.items()), key=lambda x: -x[1])[:200]]
    B = E.load_day(uni, d)
    by = {}
    for c in uni:
        b = E.regular(B[c])
        if len(b) >= 60 and b[0][0] <= time(9, 1) and (c, d) not in BAD:
            by[c] = b
    cut, cv = {}, {}
    for c, b in by.items():
        i = next((i for i, x in enumerate(b) if x[0] >= time(9, 10)), None)
        if i:
            cut[c] = i
            cv[c] = sum(x[5] * (x[2] + x[3] + x[4]) / 3 for x in b[:i])
    rk = {c: r + 1 for r, c in enumerate(sorted(cv, key=lambda c: -cv[c]))}
    pc_prev = {}
    prev_cls = cls(prev) if prev in feat else ("U" if prev in EXTRA else None)
    rows, miss = [], Counter()
    for c, i in cut.items():
        if rk[c] > 40:
            continue
        b = by[c]
        last, opn = b[i - 1][4], b[0][1]
        if not last > opn:
            continue
        idx = {x[0]: j for j, x in enumerate(b)}
        if time(9, 11) not in idx:
            miss["09:11 봉 없음"] += 1; continue
        pc = prev_regular(c, d)
        if pc is None:
            miss["전날 1분봉 없음"] += 1
            dpc = pdaily.get(c)
            f = E.factor(c, d)
            pc = dpc[3] * f if dpc and f else None
        if not pc:
            miss["전일 종가 모름"] += 1; continue
        j = idx[time(9, 11)]
        buy = b[j][1]
        if buy / pc - 1 >= 0.29:
            miss["상한가 근처"] += 1; continue
        nx = E.next_day_exits(c, d, buy).get("09:00 시가")
        if nx is None:
            miss["다음 날 09:00 없음"] += 1; continue
        sp = buy * (1 - STOP); ret, xt = nx, None
        for x in b[j:]:
            if x[0] > time(15, 19):
                break
            if x[3] <= sp:
                ret, xt = min(x[1], sp) / buy - 1 - E.COST, x[0]; break
        if abs(ret) > 0.4:
            miss["수익률 이상(>40%)"] += 1; continue
        hi9 = max(x[2] for x in b[:i]); lo9 = min(x[3] for x in b[:i])
        h = E.hist(c, d, 31)                     # 최신 순 (date,o,h,l,c,v,value)
        vals = [x[6] or 0 for x in h]
        avg20 = np.mean(vals[:20]) if len(vals) >= 5 else None
        k10 = int(np.argmax(vals[:10])) if vals else None
        base = np.mean(vals[10:30]) if len(vals) >= 15 else None
        h250 = E.hi_n(c, d, 250)
        fr_ins = E.inv(c, prev) or (None, None)
        mc = E.mcap(c, prev)
        rows.append(dict(
            date=d, code=c, name=E.NAME.get(c, c), vrank=rk[c], buy=float(buy), ret=float(ret), xt=xt, stopped=xt is not None,
            nx=float(nx), over15=buy / pc - 1 > 0.15, from_open=last / opn - 1, gap=opn / pc - 1, chg=last / pc - 1, buy_chg=buy / pc - 1,
            off_hi=last / hi9 - 1, pos=(last - lo9) / (hi9 - lo9) if hi9 > lo9 else 1.0, cval=cv[c],
            cval_r=cv[c] / avg20 if avg20 else None,
            d1=h[0][4] / h[1][4] - 1 if len(h) > 1 and h[1][4] else None,
            d5=h[0][4] / h[5][4] - 1 if len(h) > 5 and h[5][4] else None,
            d10max=vals[k10] / base if k10 is not None and base else None, spike_ago=(k10 + 1) if k10 is not None else None,
            hi250=h[0][4] / h250 - 1 if h250 and h else None,
            fr=fr_ins[0], ins=fr_ins[1], mcap=mc, age=age_of(c, d),
            K1z=dx["K1z"], M0=dx["M0"], dd52=dx["dd52"], prev_cls=prev_cls))
    return rows, miss


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    U = u_days()
    print(f"강한 상승장 {len(U)}일 ({min(U)} ~ {max(U)})", flush=True)
    allr, miss = [], Counter()
    for n, (d, dx) in enumerate(U.items(), 1):
        r, m = day_rows(d, dx)
        allr += r; miss.update(m)
        print(f"  {n:2d} {d} 후보 {len(r)}건 건당 {np.mean([x['ret'] for x in r]) if r else 0:+.2%}", flush=True)
    pickle.dump(allr, open(os.path.join(OUT, "cands.pkl"), "wb"))
    print(f"합계 {len(allr)}건 · 빠짐 {dict(miss)}")


if __name__ == "__main__":
    main()
