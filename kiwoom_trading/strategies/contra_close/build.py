"""④ 역행 강세 종가 백테스트 입력 closebet.pkl 다시 만들기 (원래 .claude/skills/closing-bet/scripts/closebet.py, 2026-10-25).

매매표 계좌(`backtest/playbook/events_15.py`)는 이 파일에서 강한 하락장(D) 날 · 대금 30위 · 시장 대비 +3%p↑ 를 골라
그날 종가에 사서 다음 날 시가(`ex["open"]`)에 판다.

한 행 = D일 대금 상위 200 종목 하나 (D일 장 마감 때 아는 것만으로 계산):
  close     D일 마지막 정규장 1분봉(≤15:30) 종가 = 매수가 (통합 AL 1분봉)
  chg       close ÷ 전 거래일 일봉 종가 − 1
  near_high close ÷ D일 정규장 고가,  late = close ÷ 15:00 봉 종가 − 1,  hi52 = close ÷ 지난 365일 일봉 최고가 − 1
  rk        D일 일봉 대금 순위 (stocks 에 있는 종목, 상위 200),  mkt = 그날 대상 종목 chg 의 중앙값
  ex        D+1 매도: 시가 / 09:30 / 10:00 / 15:19 봉 종가, 익절 +2·3·5% × 손절 −3·−5% (같은 봉 손절 먼저, 안 닿으면 15:19). 비용 0.25%
  gap       D+1 시가 ÷ close − 1  (⚠ 다음 날 정보 — 거르기 조건으로 쓰면 안 된다)
빼는 것: D일 1분봉 100개 미만, 상한가(+29.5%↑), D+1 첫 봉이 09:05 뒤.

⚠ 원래 스크립트를 그대로 옮겼다. 일봉 종가는 2026-09-14 부터 20:00 애프터 종가라서
  그 뒤 날짜의 chg(전날 일봉 종가 기준)·rk(통합 대금 기준)·hi52 는 정규장 값과 조금 다르다 (보존본도 같은 방식).

실행: python -m kiwoom_trading.strategies.contra_close.build [--daily-db 경로] [--start 2025-10-15] [--end 2026-10-23]
결과: data/backtest/playbook_rebuilt/closebet.pkl
"""
import argparse
import os
import pickle
import sys
import time as _time
from collections import defaultdict
from datetime import date, datetime, time

from kiwoom_trading.backtest.playbook.paths import MINUTE_DB, SNAPSHOT_DB, open_ro, rebuilt

COST = 0.0025
TPS = [(tp, sl) for tp in (0.02, 0.03, 0.05) for sl in (0.03, 0.05)]


def _load(m, codes, d, t0, t1):
    by = defaultdict(list)
    for c, ts, o, h, l, cl, v in m.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL'
            AND ts >= ? AND ts <= ? AND code IN ({','.join('?' * len(codes))}) ORDER BY code, ts""",
                                             [datetime.combine(d, t0), datetime.combine(d, t1), *codes]).fetchall():
        by[c].append((ts.time(), o, h, l, cl, v))
    return by


def build(daily_db=SNAPSHOT_DB, minute_db=MINUTE_DB, start=date(2025, 10, 15), end=date(2026, 10, 23)):
    m = open_ro(minute_db)
    dm = open_ro(daily_db)
    days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done WHERE date BETWEEN ? AND ? ORDER BY 1",
                                    [start, end]).fetchall()]
    rows = []
    for k in range(1, len(days) - 1):
        d, n = days[k], days[k + 1]
        prev = dm.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [d]).fetchone()[0]
        top = dm.execute("""SELECT d.code, rank() OVER (ORDER BY d.value DESC) rk FROM daily_ohlcv d JOIN stocks s USING(code)
                            WHERE d.date=? AND d.value IS NOT NULL QUALIFY rk <= 200""", [d]).fetchall()
        rk = dict(top); codes = list(rk)
        if not codes:
            continue
        q = ','.join('?' * len(codes))
        pc = dict(dm.execute(f"SELECT code, close FROM daily_ohlcv WHERE date=? AND code IN ({q})", [prev, *codes]).fetchall())
        hi52 = dict(dm.execute(f"""SELECT code, max(high) FROM daily_ohlcv WHERE date < ? AND date >= ? - INTERVAL 365 DAY
                                   AND code IN ({q}) GROUP BY code""", [d, d, *codes]).fetchall())
        today = _load(m, codes, d, time(9, 0), time(15, 30))
        nxt = _load(m, codes, n, time(9, 0), time(15, 19))
        chg_all = []
        feats = {}
        for c, bs in today.items():
            if c not in pc or not pc[c] or len(bs) < 100:
                continue
            reg = [b for b in bs if b[0] <= time(15, 30)]
            close = reg[-1][4]; high = max(b[2] for b in reg)
            c1500 = next((b[4] for b in reg if b[0] >= time(15, 0)), close)
            chg = close / pc[c] - 1
            chg_all.append(chg)
            feats[c] = dict(close=close, chg=chg, near_high=close / high, rk=rk[c], late=close / c1500 - 1,
                            hi52=close / hi52[c] - 1 if hi52.get(c) else None)
        if not chg_all:
            continue
        med = sorted(chg_all)[len(chg_all) // 2]
        for c, f in feats.items():
            nb = nxt.get(c)
            if not nb or f["chg"] >= 0.295 or nb[0][0] > time(9, 5):
                continue
            buy = f["close"]
            at = lambda t: next((b[4] for b in nb if b[0] >= t), nb[-1][4])
            ex = {"open": nb[0][1] / buy - 1 - COST, "0930": at(time(9, 30)) / buy - 1 - COST, "1000": at(time(10, 0)) / buy - 1 - COST,
                  "close": nb[-1][4] / buy - 1 - COST}
            for tp, sl in TPS:
                r = None
                for b in nb:
                    if b[3] <= buy * (1 - sl):
                        r = min(b[1], buy * (1 - sl)) / buy - 1; break
                    if b[2] >= buy * (1 + tp):
                        r = max(b[1], buy * (1 + tp)) / buy - 1; break
                ex[(tp, sl)] = (nb[-1][4] / buy - 1 if r is None else r) - COST
            rows.append(dict(date=d, code=c, mkt=med, **f, ex=ex, gap=nb[0][1] / buy - 1))
        if k % 20 == 0:
            print(d, len(rows), file=sys.stderr, flush=True)
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="④ 역행 강세 종가 closebet.pkl 다시 만들기")
    ap.add_argument("--daily-db", default=SNAPSHOT_DB)
    ap.add_argument("--minute-db", default=MINUTE_DB)
    ap.add_argument("--start", default="2025-10-15")
    ap.add_argument("--end", default="2026-10-23", help="1분봉 날짜 끝 (마지막 매수일은 그 전 거래일)")
    ap.add_argument("--out", default=rebuilt("closebet.pkl"))
    a = ap.parse_args()
    t0 = _time.time()
    rows = build(a.daily_db, a.minute_db, date.fromisoformat(a.start), date.fromisoformat(a.end))
    pickle.dump(rows, open(a.out, "wb"))
    print(f"closebet {len(rows):,}행 {len({r['date'] for r in rows})}일 → {a.out} ({_time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
