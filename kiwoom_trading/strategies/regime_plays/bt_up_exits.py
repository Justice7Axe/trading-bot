"""1️⃣ 상승장 장 초 매도법 비교 — 지금(익절 없음 · −4% · 다음 날 시가) vs 절반 익절 + 절반 트레일링 스탑 (2026-10-27 사용자).

사용자 (텔레그램 10-27): "모의 매매에서 매수 뿐만 아니라 절반 익절, 절반 트레일링 스탑 방식으로 매도를 했어야 했잖아."
대상: build_up.py 의 u_cands.pkl 중 1️⃣ 규칙 그대로 (강한 상승장 날 09:10, 누적 대금 40위 안, 시가 위, 전날 외인·기관 둘 다 − 제외).
매수: 09:10 봉 시가. 1분봉(minute_history, 원가격) 으로 09:10~15:19 를 한 봉씩 보고, 손절·익절이 같은 봉이면 손절 먼저.
매도법:
  기준  = 익절 없음, −4% 손절, 아니면 다음 날 시가
  분할  = 처음엔 전체 −4% 손절. +a% 닿으면 절반 익절 → 남은 절반은 '매수 뒤 가장 높은 값 × (1 − t)' 와 본전 중 높은 값을 스탑으로 따라 올림
          (15:19 까지 안 닿으면 다음 날 시가)
  전체 트레일 = 절반 익절 없이 전체를 t% 트레일링 (처음 −4%)
비용 0.25% (한 번 사고 판 기준, 절반씩 팔아도 같음).
다음 날 시가는 build_up 과 같이 일봉 스냅샷 시가 — 1분봉과 가격 기준이 다르면(mismatch) 이미 빠져 있다.
실행: python -m kiwoom_trading.strategies.regime_plays.bt_up_exits   → data/backtest/playbook_rebuilt/up_exits.txt
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime, time

import numpy as np

from kiwoom_trading.backtest.playbook.build_regime import DATA, MINUTE_DB, SNAP_DAILY, cls_of, connect_ro, done_filter, out
from kiwoom_trading.strategies.regime_plays.build_up import _load

COST = 0.0025
STOP0 = 0.04


def sim(bars, nopen, a=None, t=None):
    """bars = [(o,h,l)] 09:10 봉부터 15:19 까지. a = 절반 익절 비율(None = 없음), t = 트레일링 폭(None = 없음). → 수익률."""
    e = bars[0][0]
    stop = e * (1 - STOP0)
    hi = e
    half_done, got = False, 0.0
    for o, h, l in bars:
        # 스탑 먼저 (같은 봉이면 손절 먼저)
        if l <= stop:
            px = min(o, stop)
            rest = 0.5 if half_done else 1.0
            return got + rest * (px / e - 1) - COST
        if a is not None and not half_done and h >= e * (1 + a):
            got += 0.5 * a          # 절반 익절 (시가가 이미 위면 시가에 판 것보다 보수적으로 a 로 셈)
            half_done = True
        hi = max(hi, h)
        if t is not None and (half_done or a is None):
            stop = max(stop, hi * (1 - t), e if half_done else stop)
    rest = 0.5 if half_done else 1.0
    return got + rest * (nopen / e - 1) - COST


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    m = connect_ro(MINUTE_DB)
    dm = connect_ro(SNAP_DAILY)
    days = sorted({r["date"] for r in sel})
    all_days = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    nxt = {d: all_days[i + 1] for i, d in enumerate(all_days[:-1])}
    by_day = defaultdict(list)
    for r in sel:
        by_day[r["date"]].append(r["code"])
    trades = []
    for d in days:
        codes = by_day[d]
        ph = ",".join("?" * len(codes))
        nopen = dict(dm.execute(f"SELECT code, open FROM daily_ohlcv WHERE date=? AND code IN ({ph})", [nxt[d], *codes]).fetchall())
        bars = defaultdict(list)
        for c, ts, o, h, l in m.execute(f"""SELECT code, ts, open, high, low FROM minute_ohlcv WHERE exchange='AL'
                AND ts >= ? AND ts < ? AND code IN ({ph}) AND {done_filter('minute_ohlcv')} ORDER BY code, ts""",
                [datetime.combine(d, time(9, 10)), datetime.combine(d, time(15, 20)), *codes]).fetchall():
            bars[c].append((o, h, l))
        for c in codes:
            if bars.get(c) and nopen.get(c):
                trades.append((d, c, bars[c], nopen[c]))

    R = open(os.path.join(DATA, "backtest", "playbook_rebuilt", "up_exits.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); R.write(s + "\n")

    say(f"1️⃣ 상승장 장 초 {len(trades)}건 {len(days)}일 ({days[0]} ~ {days[-1]}), 건당 25만 원으로 합계")
    half = sorted(days)[len(days) // 2]

    def report(name, fn):
        v = [(d, fn(b, n)) for d, c, b, n in trades]
        x = np.array([r for _, r in v])
        a = np.mean([r for d, r in v if d < half]); b = np.mean([r for d, r in v if d >= half])
        bd = defaultdict(float)
        for d, r in v: bd[d] += r
        s = sorted(bd.values(), reverse=True)
        eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
        say(f"  {name:34s} 건당 {x.mean():+.2%} 합계 {x.sum() * 25:+6.0f}만 | 앞 {a:+.2%} 뒤 {b:+.2%} | 최고 5일 빼면 {sum(s[5:]) * 25:+5.0f}만 "
            f"| 승률 {np.mean(x > 0):.0%} 낙폭 {mdd * 25:.0f}만")
        return x.mean()

    say("\n[기준]")
    report("익절 없음 · −4% · 다음 날 시가", lambda b, n: sim(b, n))
    say("\n[절반 익절 + 절반 트레일링 (처음 −4%, 익절 뒤 남은 절반 스탑 = max(고점×(1−t), 본전))]")
    best = []
    for a in (0.03, 0.05, 0.07, 0.10):
        for t in (0.02, 0.03, 0.04, 0.05):
            best.append((report(f"절반 +{a:.0%} 익절 · 트레일 {t:.0%}", lambda b, n, a=a, t=t: sim(b, n, a, t)), a, t))
    say("\n[절반 익절만 (남은 절반은 −4%·다음 날 시가)]")
    for a in (0.03, 0.05, 0.07):
        report(f"절반 +{a:.0%} 익절", lambda b, n, a=a: sim(b, n, a, None))
    say("\n[전체 트레일링 (절반 익절 없음, 처음 −4%)]")
    for t in (0.03, 0.04, 0.05, 0.07):
        report(f"전체 트레일 {t:.0%}", lambda b, n, t=t: sim(b, n, None, t))
    b = max(best)
    say(f"\n분할 중 가장 좋은 것: 절반 +{b[1]:.0%} · 트레일 {b[2]:.0%} 건당 {b[0]:+.2%}")
    R.close()


if __name__ == "__main__":
    main()
