"""종가배팅 1년 백테스트 — D일 종가에 사서 D+1 에 판다.

종목 고르기 (D일 장 마감 때 아는 것만): D일 대금 상위 200(주식만, daily_ohlcv), D일 통합 AL 1분봉으로 종가·고가·등락 계산.
  매수가 = D일 마지막 정규장 봉(≤15:30) 종가. 상한가(+29.5%↑)는 살 수 없다고 보고 뺀다.
특징: 등락, 종가/고가, 대금 순위, 시장(대금 상위 200 중앙) 등락, 52주 고점 대비, 종가 직전 30분 흐름(15:00→종가)
매도 (D+1 통합 1분봉):
  시가 / 09:30 / 10:00 / 15:19 종가 / 익절 +2·3·5% (손절 −3·−5%, 시가가 손절 아래면 시가) 안 닿으면 15:19
비용 0.25%. 같은 봉 손절 먼저.
"""
import os, pickle, sys, tempfile
from collections import defaultdict
from datetime import datetime, time
import duckdb

import shutil
TMP = tempfile.gettempdir(); COST = 0.0025
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
S = os.path.join(ROOT, "data", "closing_bet"); os.makedirs(S, exist_ok=True)


def _copy(name):   # 원본 DB 는 20:00 업데이트·백필이 잠글 수 있어 임시 복사본을 읽는다
    dst = os.path.join(TMP, "cb_" + name)
    shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


m = duckdb.connect(_copy("minute_history.duckdb"), read_only=True)
dm = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done ORDER BY 1").fetchall()]
TPS = [(tp, sl) for tp in (0.02, 0.03, 0.05) for sl in (0.03, 0.05)]


def load(codes, d, t0, t1):
    by = defaultdict(list)
    for c, ts, o, h, l, cl, v in m.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL'
            AND ts >= ? AND ts <= ? AND code IN ({','.join('?' * len(codes))}) ORDER BY code, ts""",
            [datetime.combine(d, t0), datetime.combine(d, t1), *codes]).fetchall():
        by[c].append((ts.time(), o, h, l, cl, v))
    return by


rows = []
for k in range(1, len(days) - 1):
    d, n = days[k], days[k + 1]
    prev = dm.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [d]).fetchone()[0]
    top = dm.execute("""SELECT d.code, rank() OVER (ORDER BY d.value DESC) rk FROM daily_ohlcv d JOIN stocks s USING(code)
                        WHERE d.date=? AND d.value IS NOT NULL QUALIFY rk <= 200""", [d]).fetchall()
    rk = dict(top); codes = list(rk)
    pc = dict(dm.execute(f"SELECT code, close FROM daily_ohlcv WHERE date=? AND code IN ({','.join('?'*len(codes))})", [prev, *codes]).fetchall())
    hi52 = dict(dm.execute(f"""SELECT code, max(high) FROM daily_ohlcv WHERE date < ? AND date >= ? - INTERVAL 365 DAY
                               AND code IN ({','.join('?'*len(codes))}) GROUP BY code""", [d, d, *codes]).fetchall())
    today = load(codes, d, time(9, 0), time(15, 30))
    nxt = load(codes, n, time(9, 0), time(15, 19))
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
    print(d, len(rows), file=sys.stderr, flush=True)
pickle.dump(rows, open(os.path.join(S, "closebet.pkl"), "wb"))
