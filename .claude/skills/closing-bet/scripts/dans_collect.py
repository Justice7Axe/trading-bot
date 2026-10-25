"""디앤서 종가배팅(영상 2026-10-18) 백테스트용 자료 모으기.

D일 대금 상위 30(주식만) · 상승 마감 종목마다 D일 09:00~19:59, D+1 08:00~15:19 통합(AL) 1분봉을 저장한다.
애프터마켓(15:40~20:00)·프리마켓(08:00~08:50) 봉이 있어 '17시 이후 정규장 종가 재돌파' 를 그대로 재현할 수 있다.
결과: data/closing_bet/dans_bars.pkl  (분석은 dans_an.py)
"""
import os, pickle, shutil, sys, tempfile
from collections import defaultdict
from datetime import datetime, time
import duckdb

TMP = tempfile.gettempdir()
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
S = os.path.join(ROOT, "data", "closing_bet"); os.makedirs(S, exist_ok=True)


def _copy(name):   # 원본 DB 는 20:00 업데이트·백필이 잠글 수 있어 임시 복사본을 읽는다
    dst = os.path.join(TMP, "cbd_" + name)
    shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


m = duckdb.connect(_copy("minute_history.duckdb"), read_only=True)
dm = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
ix = duckdb.connect(_copy("index.duckdb"), read_only=True)
days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done ORDER BY 1").fetchall()]
kospi = dict(ix.execute("SELECT date, close FROM idx_daily WHERE code='001' ORDER BY date").fetchall())
kd = sorted(kospi)


def load(codes, d, t0, t1):
    by = defaultdict(list)
    for c, ts, o, h, l, cl, v in m.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL'
            AND ts >= ? AND ts <= ? AND code IN ({','.join('?' * len(codes))}) ORDER BY code, ts""",
            [datetime.combine(d, t0), datetime.combine(d, t1), *codes]).fetchall():
        by[c].append((ts.time(), o, h, l, cl, v))
    return by


def ranks(d, n):
    return dict(dm.execute("""SELECT d.code, rank() OVER (ORDER BY d.value DESC) rk FROM daily_ohlcv d JOIN stocks s USING(code)
                              WHERE d.date=? AND d.value IS NOT NULL QUALIFY rk <= ?""", [d, n]).fetchall())


def closes(d, codes):
    return dict(dm.execute(f"SELECT code, close FROM daily_ohlcv WHERE date=? AND code IN ({','.join('?' * len(codes))})", [d, *codes]).fetchall())


def prevday(d):
    return dm.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [d]).fetchone()[0]


out = []
for k in range(1, len(days) - 1):
    d, n = days[k], days[k + 1]
    p = prevday(d); pp = prevday(p)
    rk = ranks(d, 30); codes = list(rk)
    pc = closes(p, codes); ppc = closes(pp, codes); prk = ranks(p, 30)
    pcl = closes(p, codes)
    today = load(codes, d, time(9, 0), time(19, 59))
    nxt = load(codes, n, time(8, 0), time(15, 19))
    ki = kd.index(d) if d in kospi else None
    kchg = kospi[d] / kospi[kd[ki - 1]] - 1 if ki else None
    for c, bs in today.items():
        if not pc.get(c):
            continue
        reg = [b for b in bs if b[0] <= time(15, 30)]
        if len(reg) < 100:
            continue
        close = reg[-1][4]; chg = close / pc[c] - 1
        if chg <= 0:
            continue
        out.append(dict(date=d, nxt=n, code=c, rk=rk[c], chg=chg, close=close, high=max(b[2] for b in reg), kchg=kchg,
                        pchg=pc[c] / ppc[c] - 1 if ppc.get(c) else None, prk=prk.get(c), d_bars=bs, n_bars=nxt.get(c, [])))
    print(d, len(out), file=sys.stderr, flush=True)
pickle.dump(dict(rows=out, kospi=kospi), open(os.path.join(S, "dans_bars.pkl"), "wb"))
