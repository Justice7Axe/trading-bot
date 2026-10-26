"""③ 막힌 고점 돌파 백테스트 입력 resbo2.pkl 을 원본 자료(일봉·1분봉 DB)에서 다시 만든다 (2026-10-27).

원래 코드: 세션 93a48a29 스크래치 resbo.py → resbo2.py (2026-10-25, 대화 기록에서 되살림). 규칙은 그대로 옮겼다.
매매표 계좌 백테스트(kiwoom_trading/backtest/playbook/events_15.py)는 이 중
N == 5, entry == "E1", sig_t < 09:30, vr >= 0.10, gap_over 아님 인 행만 쓴다.

표본: 날짜 D 의 전 거래일 대금 상위 200 (stocks 에 있는 주식만, 순위는 일봉 대금), 통합(AL) 1분봉 09:00~15:19.
저항 R  = 전 거래일까지 N 거래일(3·5·10·20) 일봉 고가 최고값.
신호    = 09:00 부터 1분봉 종가가 처음 R 을 넘은 봉. vr = 그 봉까지 누적 대금(거래량 × (고+저+종)/3) ÷ 20일 평균 하루 대금.
gap_over = 첫 봉 시가 > R (갭으로 이미 넘음 — 계좌 백테스트에선 뺌).
매수    E1 = 신호 다음 봉 시가 (R +3% 넘으면 안 삼)
        E2 = 신호 뒤 60봉 안에 R +1% 안까지 되밀렸다가 양봉이 R 위 마감 → 다음 봉 시가 (R −1.5% 아래 마감·14:30 넘으면 실패)
매도    (익절 tp, 손절 이름): 익절가 닿으면 그 값, 손절가 닿으면 즉시(같은 봉이면 손절 먼저), 15:20 까지 둘 다 아니면 다음 날 일봉 시가.
        tp = 2·5·7%, 손절 sl2·sl3·sl5 = 매수가 −2·3·5%, 'R' = R × 0.98 (매수가 −0.1% 보다 위면 그 값으로 낮춤). 비용 0.25%.
regime  = 09:09 봉 종가 기준 표본 종목 전일 대비 등락 중앙값 (표본 100종목 미만인 날은 통째로 뺌).
f·inst  = 전 거래일 외인·기관 순매수(investor_daily, 없으면 0).

주의 (원래 코드 그대로 둔 것):
- 일봉은 수정주가, 1분봉은 받은 날 가격이라 R 과 1분봉을 바로 비교한다 → 어긋난 (종목, 날짜)는 mismatch.pkl(BAD)로 계좌 백테스트에서 뺀다.
- 다음 날 시가는 일봉 값이다.

실행: python -m kiwoom_trading.strategies.regime_plays.build_block            # 만들기 → data/backtest/playbook_rebuilt/resbo2.pkl
      python -m kiwoom_trading.strategies.regime_plays.build_block --compare  # 보존본과 비교만
환경 변수: BLOCK_DAILY_DB (기본 data/backtest/playbook/daily_ohlcv_20261025.duckdb), BLOCK_MINUTE_DB (기본 data/minute_history.duckdb)
"""
import os
import pickle
import shutil
import sys
import tempfile
import time as _time
from collections import defaultdict
from datetime import datetime, time

import duckdb
import numpy as np

from kiwoom_trading.backtest.playbook.paths import DATA, PB

DAILY_DB = os.environ.get("BLOCK_DAILY_DB") or os.path.join(PB, "daily_ohlcv_20261025.duckdb")
MINUTE_DB = os.environ.get("BLOCK_MINUTE_DB") or os.path.join(DATA, "minute_history.duckdb")
OUT_DIR = os.path.join(DATA, "backtest", "playbook_rebuilt")
OUT = os.path.join(OUT_DIR, "resbo2.pkl")
ORIG = os.path.join(PB, "resbo2.pkl")

COST = 0.0025
NS = (3, 5, 10, 20)
TPS = (0.02, 0.05, 0.07)
SLS = (0.02, 0.03, 0.05)


def _open_ro(path):
    """읽기 전용으로 연다. 다른 프로그램이 쓰고 있어 잠겼으면 임시 폴더에 복사해서 연다."""
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.Error:
        dst = os.path.join(tempfile.gettempdir(), "block_" + os.path.basename(path))
        print(f"[build_block] {path} 잠김 → {dst} 로 복사", file=sys.stderr, flush=True)
        shutil.copy(path, dst)
        return duckdb.connect(dst, read_only=True)


def new_exit(bars, k, e, tp, stop, nopen):
    """k 봉 시가에 e 로 산 뒤: 손절가 먼저, 익절가 다음, 15:20 까지 못 닿으면 다음 날 시가."""
    T = e * (1 + tp)
    for j in range(k, len(bars)):
        b = bars[j]
        if b[0] >= time(15, 20):
            break
        if b[3] <= stop:
            return min(b[1], stop) / e - 1 - COST
        if b[2] >= T:
            return max(b[1], T) / e - 1 - COST
    return nopen / e - 1 - COST


def all_exits(bars, k, e, nopen, extra_stops=None):
    """{(tp, 'sl2'|'sl3'|'sl5'|이름): 수익률}"""
    out = {}
    stops = {f"sl{int(s * 100)}": e * (1 - s) for s in SLS}
    for nm, px in (extra_stops or {}).items():
        stops[nm] = min(px, e * 0.999)
    for tp in TPS:
        for nm, px in stops.items():
            out[(tp, nm)] = new_exit(bars, k, e, tp, px, nopen)
    return out


def build():
    m = _open_ro(MINUTE_DB)
    dm = _open_ro(DAILY_DB)
    days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done ORDER BY 1").fetchall()]
    all_days = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    didx = {d: i for i, d in enumerate(all_days)}
    shares = dict(dm.execute("SELECT code, listed_shares FROM stocks").fetchall())
    rows = []
    for d in days:
        if d not in didx:
            continue
        k = didx[d]
        if k < 25 or k + 1 >= len(all_days):
            continue
        prev, nxt = all_days[k - 1], all_days[k + 1]
        uni = dm.execute("""SELECT d.code, d.close, d.value FROM daily_ohlcv d JOIN stocks s USING(code)
                            WHERE d.date=? AND d.value IS NOT NULL QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200""", [prev]).fetchall()
        pc = {c: cl for c, cl, v in uni}
        codes = list(pc)
        ph = ",".join("?" * len(codes))
        hist = defaultdict(list)
        for c, hi, v in dm.execute(f"""SELECT code, high, value FROM daily_ohlcv WHERE date <= ? AND date >= ? AND code IN ({ph})
                                       ORDER BY code, date""", [prev, all_days[k - 20], *codes]).fetchall():
            hist[c].append((hi, v))
        flow = {c: (f or 0, i or 0) for c, f, i in dm.execute("SELECT code, foreign_, institution FROM investor_daily WHERE date=?", [prev]).fetchall()}
        nopen = dict(dm.execute(f"SELECT code, open FROM daily_ohlcv WHERE date=? AND code IN ({ph})", [nxt, *codes]).fetchall())
        # 시장 분위기 09:10 (09:09 봉 종가 기준 표본 중앙)
        snap = dict(m.execute(f"""SELECT code, close FROM minute_ohlcv WHERE exchange='AL' AND ts=? AND code IN ({ph})""",
                              [datetime.combine(d, time(9, 9)), *codes]).fetchall())
        if len(snap) < 100:
            continue
        regime = float(np.median([snap[c] / pc[c] - 1 for c in snap]))
        by = defaultdict(list)
        for c, ts, o, h, l, cl, v in m.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL'
                AND ts >= ? AND ts < ? AND code IN ({ph}) ORDER BY code, ts""",
                [datetime.combine(d, time(9, 0)), datetime.combine(d, time(15, 20)), *codes]).fetchall():
            by[c].append((ts.time(), o, h, l, cl, v))
        for c, bars in by.items():
            if c not in nopen:
                continue
            h = hist.get(c, [])
            if len(h) < 20 or len(bars) < 60 or bars[0][0] > time(9, 1):
                continue
            avg20 = sum(x[1] for x in h[-20:]) / 20
            if not avg20:
                continue
            o0 = bars[0][1]
            mcap = (shares.get(c) or 0) * pc[c]
            for N in NS:
                R = max(x[0] for x in h[-N:])
                touch = sum(1 for x in h[-N:] if x[0] >= R * 0.98)   # 고점 근처(−2% 안)까지 간 날 수 (막힘)
                gap_over = o0 > R
                cum = 0
                sig = None
                for i, b in enumerate(bars):
                    cum += b[5] * (b[2] + b[3] + b[4]) / 3
                    if b[4] > R:
                        sig = (i, cum / avg20)
                        break
                if sig is None:
                    continue
                i, vr = sig
                if i + 1 >= len(bars):
                    continue
                base = dict(date=d, code=c, N=N, R=R, touch=touch, gap_over=gap_over, sig_t=bars[i][0], vr=vr,
                            gap=o0 / pc[c] - 1, prev_gap_R=pc[c] / R - 1, regime=regime, mcap=mcap,
                            f=flow.get(c, (0, 0))[0], inst=flow.get(c, (0, 0))[1],
                            day_ret=bars[-1][4] / pc[c] - 1)
                # E1: 신호 다음 봉 시가
                e = bars[i + 1][1]
                if e <= R * 1.03:
                    r = dict(base, entry="E1", buy_t=bars[i + 1][0], buy=e)
                    r.update(all_exits(bars, i + 1, e, nopen[c], {"R": R * 0.98}))
                    rows.append(r)
                # E2: 되밀림 확인 뒤
                dipped = False
                for j in range(i + 1, min(len(bars) - 1, i + 61)):
                    t, o, hh, l, cl, v = bars[j]
                    if t > time(14, 30) or cl < R * 0.985:
                        break
                    if l <= R * 1.01:
                        dipped = True
                    if dipped and cl > o and cl > R:
                        e = bars[j + 1][1]
                        if e <= R * 1.03:
                            r = dict(base, entry="E2", buy_t=bars[j + 1][0], buy=e)
                            r.update(all_exits(bars, j + 1, e, nopen[c], {"R": R * 0.98}))
                            rows.append(r)
                        break
        print(d, len(rows), flush=True)
    return rows


def _used(r):
    """계좌 백테스트(events_15)가 쓰는 행."""
    return r["N"] == 5 and r["entry"] == "E1" and r["sig_t"] < time(9, 30) and r["vr"] >= 0.10 and not r["gap_over"]


def compare(a_path=ORIG, b_path=OUT):
    from datetime import date
    a = pickle.load(open(a_path, "rb"))
    b = pickle.load(open(b_path, "rb"))
    BAD = pickle.load(open(os.path.join(PB, "mismatch.pkl"), "rb"))
    print(f"(a) 행 수: 보존본 {len(a):,} / 다시 만든 것 {len(b):,}")
    ka = set().union(*(r.keys() for r in a)); kb = set().union(*(r.keys() for r in b))
    print(f"    키: 같음 {ka == kb} (보존본에만 {sorted(map(str, ka - kb))}, 새것에만 {sorted(map(str, kb - ka))})")
    key = lambda r: (r["date"], r["code"], r["N"], r["entry"])
    A = {key(r): r for r in a}; B = {key(r): r for r in b}
    print(f"    전체 (날짜, 종목, N, 매수 방식) 겹침 {len(A.keys() & B.keys()):,} / 보존본에만 {len(A.keys() - B.keys()):,} / 새것에만 {len(B.keys() - A.keys()):,}")
    for lab, flt in (("필터 통과 전부", lambda r: True), ("BAD 뺀 것", lambda r: (r["code"], r["date"]) not in BAD)):
        sa = {(r["date"], r["code"], r["sig_t"]) for r in a if _used(r) and flt(r)}
        sb = {(r["date"], r["code"], r["sig_t"]) for r in b if _used(r) and flt(r)}
        both = sa & sb
        print(f"(b) {lab}: 보존본 {len(sa):,} / 새것 {len(sb):,} / 같음 {len(both):,} ({len(both) / max(len(sa | sb), 1) * 100:.2f}%) "
              f"보존본에만 {len(sa - sb)} 새것에만 {len(sb - sa)}")
        for x in sorted(sa - sb)[:10]: print("      보존본에만", x)
        for x in sorted(sb - sa)[:10]: print("      새것에만", x)
    ua = {(r["date"], r["code"]): r for r in a if _used(r)}
    ub = {(r["date"], r["code"]): r for r in b if _used(r)}
    common = ua.keys() & ub.keys()
    for k2 in ((0.07, "sl5"), (0.07, "sl3")):
        diff = [(x, ua[x][k2], ub[x][k2]) for x in sorted(common) if abs(ua[x][k2] - ub[x][k2]) >= 5e-5]
        mx = max((abs(ua[x][k2] - ub[x][k2]) for x in common), default=0)
        print(f"(c) 수익률 {k2}: 같은 행 {len(common):,} 중 소수 넷째 자리에서 다른 행 {len(diff)} (가장 큰 차이 {mx:.6f}), "
              f"합계 보존본 {sum(ua[x][k2] for x in common):+.4f} / 새것 {sum(ub[x][k2] for x in common):+.4f}")
        for x, va, vb in diff[:10]: print("      ", x, round(va, 6), round(vb, 6))
    # 나머지 칸도 같은지 (필터 통과 행)
    for f in ("R", "touch", "vr", "gap", "prev_gap_R", "regime", "mcap", "f", "inst", "day_ret", "buy_t", "buy"):
        nd = sum(1 for x in common if (ua[x][f] != ub[x][f]) if not isinstance(ua[x][f], float) or abs(ua[x][f] - ub[x][f]) > 1e-9)
        if nd: print(f"    칸 {f}: 다른 행 {nd}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--compare" in sys.argv:
        compare()
        return
    t0 = _time.time()
    print(f"일봉 {DAILY_DB}\n1분봉 {MINUTE_DB}", flush=True)
    rows = build()
    os.makedirs(OUT_DIR, exist_ok=True)
    pickle.dump(rows, open(OUT, "wb"))
    print(f"saved {len(rows):,} → {OUT} ({_time.time() - t0:.0f}초)")
    compare()


if __name__ == "__main__":
    main()
