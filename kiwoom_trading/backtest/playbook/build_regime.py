"""시장 상황 특징값 regime_feat.pkl · 가격 안 맞는 목록 mismatch.pkl 을 원본 자료에서 다시 만든다 (2026-10-27).

원래 만든 곳 (세션 93a48a29 스크래치, 대화 기록에서 찾아 옮김):
  mismatch.pkl   대화 중 바로 실행한 짧은 코드 (스크립트 파일 없음)
  daybuy2.pkl    daybuy.py → daybuy2.py (M0·B1 의 바탕, 09:10 매수 후보)
  regime_feat.pkl regime_cmp.py (data/research_archive/93a48a29/regime_cmp.py) 끝에서 저장

만드는 값
  mismatch  (code, date) 집합 — 그날 14:00~15:19 마지막 1분봉 종가(통합 AL)와 일봉 종가가 3% 넘게 다른 종목·일.
            1분봉은 받은 날 가격, 일봉은 수정주가라 분할·배당 조정 종목에서 어긋난다. 이런 종목·일은 백테스트에서 뺀다.
  feat[d]   M0   전날 대금 상위 200 주식(그날 1분봉 60개 이상·09:01 전 시작)의 09:09 봉 종가 전일 대비 중앙값
            B1   같은 표본 중 전일 대비 오른 비율 (가격 안 맞는 종목·일과 다음 날 시가 없는 종목 뺌, 판정엔 안 씀)
            K1 / Q1   코스피(001)·코스닥(101) 09:00~09:09 마지막 값의 전일 대비
            K1z / Q1z 위 값 ÷ 최근 20거래일 일간 등락 표준편차, KQz = 둘 평균
            above200  전날 코스피 종가가 200일 평균 위인지, dd52 전날 종가 ÷ 직전 250일 고가 − 1, sd20 코스피 20일 변동성
  판정(U/N+/N-/D)은 regime.py 의 cls 가 이 값으로 한다.

입력 (읽기만): 일봉 data/backtest/playbook/daily_ohlcv_20261025.duckdb (PLAYBOOK_DAILY_DB 로 바꿀 수 있음),
             1분봉 data/minute_history.duckdb, 지수 data/index.duckdb
출력: data/backtest/playbook_rebuilt/regime_feat.pkl · mismatch.pkl
실행: python -m kiwoom_trading.backtest.playbook.build_regime          (만들고 보존본과 비교)
      python -m kiwoom_trading.backtest.playbook.build_regime --compare (비교만)
      python -m kiwoom_trading.backtest.playbook.build_regime --latest  (보존본 기준 끄고 지금 있는 1분봉 전부 — 비교 결과는 달라진다)
"""
import os
import pickle
import shutil
import sys
import tempfile
import time as _clock
from collections import defaultdict
from datetime import date, datetime, time

import duckdb
import numpy as np

from kiwoom_trading.backtest.playbook.paths import DATA, PB

OUT = os.path.join(DATA, "backtest", "playbook_rebuilt")
SNAP_DAILY = os.environ.get("PLAYBOOK_DAILY_DB") or os.path.join(PB, "daily_ohlcv_20261025.duckdb")
MINUTE_DB = os.path.join(DATA, "minute_history.duckdb")
INDEX_DB = os.path.join(DATA, "index.duckdb")
# 보존본과 같은 자료로 맞추는 기준 (--latest 로 끔).
#  LAST_DAY  보존본 마지막 날 (일봉 스냅샷 마지막 날). 그 뒤 1분봉은 안 쓴다.
#  DONE_BY   보존본 mismatch 를 만든 때(2026-10-25 01:29) 까지 백필이 끝난 (종목, 날짜) 1분봉만 쓴다.
#            그 뒤 1분봉 백필이 대금 상위 500 으로 넓어져 종목·일이 늘었다 (minute_backfill_done.done_at 으로 가림).
LAST_DAY = date(2026, 10, 23)
DONE_BY = datetime(2026, 10, 25, 1, 29)
if "--latest" in sys.argv:
    LAST_DAY, DONE_BY = date(2100, 1, 1), datetime(2100, 1, 1)


def done_filter(alias: str = "") -> str:
    """minute_ohlcv 에 붙이는 조건: DONE_BY 까지 백필이 끝난 (종목, 날짜) 만."""
    a = alias + "." if alias else ""
    return (f"EXISTS (SELECT 1 FROM minute_backfill_done b WHERE b.code = {a}code AND b.date = {a}ts::date "
            f"AND b.done_at <= TIMESTAMP '{DONE_BY:%Y-%m-%d %H:%M:%S}')")


def connect_ro(path: str) -> duckdb.DuckDBPyConnection:
    """읽기 전용으로 연다. 다른 프로그램이 잠가 두었으면 임시 폴더에 복사해서 연다."""
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.IOException:
        dst = os.path.join(tempfile.gettempdir(), "rebuild_" + os.path.basename(path))
        if not os.path.exists(dst):
            shutil.copy(path, dst)
        print(f"[잠김] {path} → 복사본 {dst}", file=sys.stderr)
        return duckdb.connect(dst, read_only=True)


def out(name: str) -> str:
    os.makedirs(OUT, exist_ok=True)
    return os.path.join(OUT, name)


# ---------------------------------------------------------------- mismatch
def build_mismatch(m: duckdb.DuckDBPyConnection) -> set:
    m.execute(f"ATTACH '{SNAP_DAILY}' AS dd (READ_ONLY)")
    q = m.execute(f"""WITH mc AS (SELECT code, ts::date AS date, arg_max(close, ts) AS mclose FROM minute_ohlcv
                     WHERE exchange='AL' AND ts::time BETWEEN TIME '14:00' AND TIME '15:19' AND ts::date <= ?
                     AND {done_filter('minute_ohlcv')} GROUP BY 1, 2)
                     SELECT mc.code, mc.date, mc.mclose, d.close FROM mc JOIN dd.daily_ohlcv d USING(code, date)""",
                  [LAST_DAY]).fetchall()
    m.execute("DETACH dd")
    bad = {(c, d) for c, d, mcl, dc in q if dc and abs(mcl / dc - 1) > 0.03}
    print(f"mismatch: 비교 {len(q):,} 종목·일, 어긋남 {len(bad):,}")
    return bad


# ---------------------------------------------------------------- M0·B1 (원래 daybuy2.py 의 09:10 날 정보)
def build_m0_b1(m, dm, bad: set):
    """날마다 (M0, B1). daybuy2.py 와 같은 표본·같은 계산."""
    T = time(9, 10)
    days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done WHERE date <= ? AND done_at <= ? ORDER BY 1",
                                    [LAST_DAY, DONE_BY]).fetchall()]
    all_days = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    pos = {d: i for i, d in enumerate(all_days)}
    M0, B1 = {}, {}
    for d in days:
        k = pos.get(d)
        if k is None or k < 21:
            continue
        prev = all_days[k - 1]
        uni = dm.execute("""SELECT d.code, d.close FROM daily_ohlcv d JOIN stocks s USING(code)
                            WHERE d.date=? AND d.value IS NOT NULL QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200""", [prev]).fetchall()
        pc = dict(uni)
        codes = list(pc)
        ph = ",".join("?" * len(codes))
        nopen = set(c for (c,) in dm.execute(f"SELECT code FROM daily_ohlcv WHERE date=? AND code IN ({ph})",
                                               [all_days[k + 1], *codes]).fetchall()) if k + 1 < len(all_days) else set()
        by = defaultdict(list)
        for c, ts, cl in m.execute(f"""SELECT code, ts, close FROM minute_ohlcv WHERE exchange='AL'
                AND ts >= ? AND ts < ? AND code IN ({ph}) AND {done_filter('minute_ohlcv')} ORDER BY code, ts""",
                [datetime.combine(d, time(9, 0)), datetime.combine(d, time(15, 20)), *codes]).fetchall():
            by[c].append((ts.time(), cl))
        by = {c: b for c, b in by.items() if len(b) >= 60 and b[0][0] <= time(9, 1)}
        if len(by) < 100:
            continue
        chg = {}
        for c, bars in by.items():
            idx = next((i for i, b in enumerate(bars) if b[0] >= T), None)
            if idx is None or idx == 0:
                continue
            chg[c] = bars[idx - 1][1] / pc[c] - 1
        M0[d] = float(np.median(list(chg.values())))
        ups = [v > 0 for c, v in chg.items() if c in nopen and (c, d) not in bad]
        if ups:
            B1[d] = float(np.mean(ups))
    return M0, B1


# ---------------------------------------------------------------- 지수 (regime_cmp.py 그대로)
def index_parts(ix):
    daily = defaultdict(list)
    for c, d, cl, hi in ix.execute("SELECT code, date, close, high FROM idx_daily WHERE date <= ? ORDER BY code, date", [LAST_DAY]).fetchall():
        daily[c].append((d, cl, hi))
    ctx = defaultdict(dict)
    for c, xs in daily.items():
        if c not in ("001", "101"):
            continue
        for i in range(1, len(xs)):
            d = xs[i][0]
            prev = [x[1] for x in xs[:i]]
            rets = [prev[j] / prev[j - 1] - 1 for j in range(max(1, len(prev) - 20), len(prev))]
            ma200 = np.mean(prev[-200:]) if len(prev) >= 200 else None
            hi52 = max(x[2] for x in xs[max(0, i - 250):i])
            ctx[c][d] = dict(prev=prev[-1], sd20=float(np.std(rets)) if len(rets) >= 10 else None,
                             above200=(prev[-1] > ma200) if ma200 else None, dd52=prev[-1] / hi52 - 1)
    snap = defaultdict(dict)
    for c, ts, cl in ix.execute("""SELECT code, ts, close FROM idx_min WHERE code IN ('001', '101')
            AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '09:09' ORDER BY code, ts""").fetchall():
        snap[c][ts.date()] = cl
    return ctx, snap


def build_feat(M0, B1, ctx, snap) -> dict:
    days = sorted(d for d in M0 if d in snap["001"] and d in snap["101"] and d in ctx["001"] and ctx["001"][d]["sd20"])
    feat = {}
    for d in days:
        k = snap["001"][d] / ctx["001"][d]["prev"] - 1
        q = snap["101"][d] / ctx["101"][d]["prev"] - 1
        kz, qz = k / ctx["001"][d]["sd20"], q / ctx["101"][d]["sd20"]
        feat[d] = dict(M0=M0[d], B1=B1.get(d, np.nan), K1=k, Q1=q, K1z=kz, Q1z=qz, KQz=(kz + qz) / 2,
                       above200=ctx["001"][d]["above200"], dd52=ctx["001"][d]["dd52"], sd20=ctx["001"][d]["sd20"])
    return feat


def cls_of(x):
    """regime.py 의 cls 와 같은 규칙 (그 모듈은 보존본을 불러오므로 여기서 따로 둔다)."""
    if x["K1z"] <= -1 or x["M0"] <= -0.015:
        return "D"
    if x["K1z"] >= 1 or x["M0"] >= 0.02:
        return "U"
    return "N+" if x["dd52"] > -0.10 else "N-"


# ---------------------------------------------------------------- 비교
def compare():
    old_f = pickle.load(open(os.path.join(PB, "regime_feat.pkl"), "rb"))
    new_f = pickle.load(open(out("regime_feat.pkl"), "rb"))
    old_b = pickle.load(open(os.path.join(PB, "mismatch.pkl"), "rb"))
    new_b = pickle.load(open(out("mismatch.pkl"), "rb"))
    both = old_b & new_b
    print(f"\n[mismatch] 보존본 {len(old_b):,} · 새로 {len(new_b):,} · 같음 {len(both):,} "
          f"({len(both) / max(len(old_b | new_b), 1) * 100:.2f}% of 합집합) · 보존본에만 {len(old_b - new_b)} · 새것에만 {len(new_b - old_b)}")
    for nm, xs in (("보존본에만", sorted(old_b - new_b)[:10]), ("새것에만", sorted(new_b - old_b)[:10])):
        if xs:
            print(f"  {nm} 예: {xs}")
    days = sorted(set(old_f) | set(new_f))
    common = [d for d in days if d in old_f and d in new_f]
    same = sum(cls_of(old_f[d]) == cls_of(new_f[d]) for d in common)
    print(f"\n[regime_feat] 보존본 {len(old_f)}일 · 새로 {len(new_f)}일 · 둘 다 {len(common)}일 · 분류 같음 {same}/{len(common)} "
          f"({same / max(len(common), 1) * 100:.1f}%)")
    for d in days:
        if d not in old_f or d not in new_f:
            print(f"  {d} 한쪽에만: {'보존본' if d in old_f else '새것'}")
        elif cls_of(old_f[d]) != cls_of(new_f[d]):
            print(f"  {d} 분류 다름 {cls_of(old_f[d])} → {cls_of(new_f[d])}  M0 {old_f[d]['M0']:+.4f}/{new_f[d]['M0']:+.4f}  K1z {old_f[d]['K1z']:+.3f}/{new_f[d]['K1z']:+.3f}")
    print("  특징값 최대 차이(둘 다 있는 날):")
    for k in ("M0", "B1", "K1", "Q1", "K1z", "Q1z", "KQz", "dd52", "sd20"):
        diff = [abs(old_f[d][k] - new_f[d][k]) for d in common if not (np.isnan(old_f[d][k]) and np.isnan(new_f[d][k]))]
        nz = sum(x > 1e-12 for x in diff)
        print(f"    {k:5s} 최대 {max(diff) if diff else 0:.3g}  다른 날 {nz}")
    a2 = sum(old_f[d]["above200"] == new_f[d]["above200"] for d in common)
    print(f"    above200 같음 {a2}/{len(common)}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--compare" in sys.argv:
        compare()
        return
    t0 = _clock.time()
    m = connect_ro(MINUTE_DB)
    dm = connect_ro(SNAP_DAILY)
    ix = connect_ro(INDEX_DB)
    bad = build_mismatch(m)
    pickle.dump(bad, open(out("mismatch.pkl"), "wb"))
    M0, B1 = build_m0_b1(m, dm, bad)
    ctx, snap = index_parts(ix)
    feat = build_feat(M0, B1, ctx, snap)
    pickle.dump(feat, open(out("regime_feat.pkl"), "wb"))
    print(f"regime_feat: {len(feat)}일 ({min(feat)} ~ {max(feat)}), 걸린 시간 {_clock.time() - t0:.0f}초")
    compare()


if __name__ == "__main__":
    main()
