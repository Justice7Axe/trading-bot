"""장중 재판정(14:00·14:30·15:00·15:15) → 강한 하락장이면 그날 4️⃣ 역행 강세 종가를 켜는 규칙 1년 검증 — 1단계: 날마다 자료 만들기 (2026-11-06, 복기 노트 후보 A).

날마다 (1분봉·지수 1분봉 있는 2025-10-16 ~ 2026-11-05):
  판정 시각 T ∈ 09:10·09:20·14:00·14:30·15:00·15:15 마다 (T 전에 끝난 봉만 씀)
    z   = 코스피(idx_min, T 전 마지막 봉 종가) ÷ 전날 코스피 종가 − 1, ÷ 전날까지 20거래일 일간 등락 표준편차 (운영 market_regime 과 같음)
    med = 그 시각 누적 대금(09:00~T 정규장 1분봉 종가×거래량) 상위 200 주식(stocks 표에 있는 것)의 전일 대비 등락 중앙값
    강한 하락장 = z ≤ −1 또는 med ≤ −1.5%
  4️⃣ 후보 (15:15 스냅샷 재현, 운영 contra_close/live.py 와 같은 규칙): 15:15 누적 대금 상위 200 주식 중 대금 30위 안,
    15:15 전일 대비 − 그 200 의 중앙값 ≥ +3%p, 상한가(+29.5%↑) 제외. 고가 부근 = (15:15 가격 − 저가)/(고가 − 저가) (15:15 까지).
    매수 = 정규장 마지막 봉 종가(15:30 종가 동시호가), 매도 = 다음 날 09:00 시가 (engine.next_day_exits, 비용 0.25%·기준 맞춤).
  전일 종가 = 일봉(daily_day, 9-14 뒤 정규장 값으로 바꾼 것) × factor (그날 1분봉 가격 기준으로 맞춤).
⚠ minute_history 는 날마다 그날 최종 대금 상위 약 500 종목만 있다 → 'T 시각 누적 대금 상위 200' 은 이 안에서 고름 (진짜 상위 200 은 거의 다 들어 있음).
결과: data/regime_recheck/days.pkl
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.regime_recheck.build
"""
import os
import pickle
import sys
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "regime_recheck")
os.makedirs(OUT, exist_ok=True)
TIMES = [time(9, 10), time(9, 20), time(14, 0), time(14, 30), time(15, 0), time(15, 15)]
START, END = date(2025, 10, 16), date(2026, 11, 5)
STOCKS = {c for (c,) in E.DM.execute("SELECT code FROM stocks").fetchall()}

IDXM = {}
for ts, cl in E.IX.execute("SELECT ts, close FROM idx_min WHERE code='001' ORDER BY ts").fetchall():
    IDXM.setdefault(ts.date(), []).append((ts.time(), cl))


def kospi_before(d, t):
    x = [cl for tt, cl in IDXM.get(d, []) if tt < t]
    return x[-1] if x else None


def sd20(d):
    i = E.CIDX[d]
    xs = [E.kospi_chg(E.CAL[j]) for j in range(i - 20, i)]
    xs = [x for x in xs if x is not None]
    return float(np.std(xs)) if len(xs) >= 15 else None


def day_rows(d):
    p = E.prev_day(d)
    codes = [c for c in E._min_codes(d) if c in STOCKS]
    B = E.load_day(codes, d)
    dp = E.daily_day(p)
    info = {}
    for c in codes:
        reg = E.regular(B[c])
        if len(reg) < 100 or c not in dp or not dp[c][3]:
            continue
        f = E.factor(c, d)
        if not f:
            continue
        info[c] = (reg, dp[c][3] * f)        # 정규장 봉, 전일 종가(그날 1분봉 가격 기준)
    return info


def snap(info, t):
    """t 전에 끝난 봉까지: [(code, 누적 대금, 등락, 가격, 고가, 저가)] 누적 대금 순."""
    out = []
    for c, (reg, pc) in info.items():
        b = [x for x in reg if x[0] < t]
        if not b:
            continue
        val = sum(x[4] * x[5] for x in b)
        px = b[-1][4]
        out.append((c, val, px / pc - 1, px, max(x[2] for x in b), min(x[3] for x in b)))
    out.sort(key=lambda r: -r[1])
    return out[:200]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    days = [d for d in E.CAL if START <= d <= END and E._min_codes(d)]
    res = []
    for k, d in enumerate(days):
        p = E.prev_day(d)
        s = sd20(d)
        info = day_rows(d)
        reg = {}
        for t in TIMES:
            top = snap(info, t)
            med = float(np.median([r[2] for r in top])) if len(top) >= 50 else None
            kx = kospi_before(d, t)
            z = (kx / E.KOSPI[p] - 1) / s if kx and p in E.KOSPI and s else None
            kchg = kx / E.KOSPI[p] - 1 if kx and p in E.KOSPI else None
            reg[t] = dict(med=med, z=z, kchg=kchg, n=len(top),
                          down=(z is not None and z <= -1) or (med is not None and med <= -0.015))
        top = snap(info, time(15, 15))
        med = float(np.median([r[2] for r in top])) if top else None
        picks = []
        for rk, (c, val, ch, px, hi, lo) in enumerate(top[:30], 1):
            if ch - med < 0.03 or ch >= E.LIMIT:
                continue
            buy = info[c][0][-1][4]
            ex = E.next_day_exits(c, d, buy) if E.next_day(d) else {}
            picks.append(dict(date=d, code=c, name=E.NAME.get(c, c), rk=rk, chg=ch, rel=ch - med,
                              pos=(px - lo) / (hi - lo) if hi > lo else 1.0, px=float(buy), ret=ex.get("09:00 시가")))
        allm = [r[2] for r in snap(info, time(15, 31))]
        res.append(dict(date=d, reg=reg, picks=picks, kchg_close=E.kospi_chg(d),
                        med_close=float(np.median(allm)) if allm else None, n_codes=len(info)))
        if k % 20 == 0:
            print(d, len(info), {t.strftime('%H%M'): reg[t]['down'] for t in TIMES}, len(picks), flush=True)
    pickle.dump(res, open(os.path.join(OUT, "days.pkl"), "wb"))
    print(f"{len(res)}일 → {OUT}\\days.pkl, 기준 맞춤 {dict(E.BASIS_FIX)}")


if __name__ == "__main__":
    main()
