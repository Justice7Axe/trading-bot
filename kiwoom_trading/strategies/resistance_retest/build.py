"""② 저항 돌파 백테스트 입력 g2g_filter.pkl 을 원본 자료(일봉·1분봉 DB)에서 다시 만든다.

원래 코드: 스크래치 세션 93a48a29 의 g2g_filter.py (2026-10-25 02:37 작성, 파일은 지워졌고 세션 대화 기록에 원문이 남아 있었다).
규칙은 한 줄도 바꾸지 않고 옮겼다. 바꾼 것은 DB 경로(고정 경로·환경 변수)와 1분봉 '언제까지 받은 것만' 옵션뿐이다.

1단계 일봉(2024-07-01~): 🧱 저항 재시험 후보 (live.find_retest 와 같은 규칙)
   전날 대금 50억↑, D일·다음 날 시가 있음, 61일 동안 종가·고가·저가·대금 빈칸 없음
   H = D-60 ~ D-4 고가 최고, R = max(H, 최근 3일 고가)
   핵심: 최근 5일 +15%↑ 장대양봉 1개↑(b1) · 최근 3일 평균 대금 ≥ 그 전 20일 평균 × 2(V) · 전날 종가 H −15~0% · 최근 3일 고가 ≥ H −3%
   avg20  = 그 전 20일 평균 하루 대금 (최근 3일 뺀 평소 대금)
   fade   = 전날 대금 ÷ 최근 3일 대금 최고, pk_age = 최근 10일 대금 최고일이 며칠 전인가 (0 = 전날, 같으면 앞날)
   rise   = 최근 5일 대금 합 ÷ max(1, 앞 5일 대금 합), nopen = 다음 날 시가
   D일 고가 > R · |갭| < 30% → e = 시가 > R 이면 시가 아니면 R, d7 = 일봉 +7% 익절 / 못 닿으면 다음 날 시가 (손절 없음, 비용 0.25%)
2단계 1분봉 (시가가 R 아래인 돌파만, 1분봉이 있는 날, 통합 'AL' 08:00~15:19 봉)
   09:00~ 봉이 30개 넘고 마지막 종가가 일봉 종가와 3% 안 (가격 단위 맞는 종목·일만)
   pre_val = 08:00~08:59 (NXT 장 전) 대금 ÷ avg20 · 처음 고가 > R 인 봉 = 돌파 봉: bo_t 그 시각, bo_cum = 그 전까지 누적 대금 ÷ avg20
   m7[sl] (sl = 3·5·7%): 매수가 = max(R, 돌파 봉 시가). 돌파 봉: 저가 ≤ 손절가면 손절가, 종가 ≥ +7% 면 익절가.
          그 뒤 봉: 손절 먼저(시가가 이미 아래면 시가), 그다음 익절(시가가 이미 위면 시가). 15:19 까지 못 닿으면 다음 날 일봉 시가. 비용 0.25%.
   봉 대금 = 거래량 × (고+저+종)/3.

`python -m kiwoom_trading.strategies.resistance_retest.build` → data/backtest/playbook_rebuilt/g2g_filter.pkl
  환경 변수: G2G_DAILY_DB  일봉 (기본 data/backtest/playbook/daily_ohlcv_20261025.duckdb — 보존본이 쓴 10-24 스냅샷과 내용 같음)
            G2G_MINUTE_DB 1분봉 (기본 data/minute_history.duckdb, 잠겨 있으면 임시 폴더 복사본)
            G2G_MINUTE_LAST 이 날짜까지 1분봉만 (기본 2026-10-23 = 보존본 만든 때 받아 둔 마지막 날. 'none' 이면 전부)
  ⚠️ 1분봉 DB 는 계속 늘어난다 (2026-10-26 부터 상위 500 백필). 같은 날짜라도 나중에 받은 종목이 생기면 1분봉 행이 늘 수 있다 →
     보존본과 똑같이 보려면 2026-10-25 무렵 복사본(임시 폴더 *_minute_history.duckdb)을 G2G_MINUTE_DB 로 준다.
보존본(data/backtest/playbook/g2g_filter.pkl)이 있으면 비교 결과도 찍는다.
"""
import os
import pickle
import shutil
import sys
import tempfile
import time as _time
from collections import defaultdict
from datetime import date, datetime, time

import duckdb

from kiwoom_trading.backtest.playbook.paths import DATA, PB

COST = 0.0025
OUT_DIR = os.path.join(DATA, "backtest", "playbook_rebuilt")
DAILY_DB = os.environ.get("G2G_DAILY_DB") or os.path.join(PB, "daily_ohlcv_20261025.duckdb")
MINUTE_DB = os.environ.get("G2G_MINUTE_DB") or os.path.join(DATA, "minute_history.duckdb")
_last = os.environ.get("G2G_MINUTE_LAST", "2026-10-23")
MINUTE_LAST = None if _last.lower() == "none" else date.fromisoformat(_last)


def _open_ro(path: str) -> duckdb.DuckDBPyConnection:
    """읽기 전용으로 연다. 운영 프로세스가 잡고 있으면 임시 폴더로 복사해서 연다 (이미 복사본이 있으면 그것)."""
    try:
        return duckdb.connect(path, read_only=True)
    except duckdb.IOException:
        dst = os.path.join(tempfile.gettempdir(), "g2g_" + os.path.basename(path))
        if not os.path.exists(dst):
            shutil.copy(path, dst)
        print(f"[build] {os.path.basename(path)} 잠김 → 복사본 {dst} 사용", file=sys.stderr)
        return duckdb.connect(dst, read_only=True)


def build(dm, m) -> list[dict]:
    """원래 g2g_filter.py 본문 그대로 (dm = 일봉, m = 1분봉 연결)."""
    q = dm.execute("""SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.value FROM daily_ohlcv d JOIN stocks s USING(code)
                      WHERE d.date >= '2024-07-01' ORDER BY d.code, d.date""").fetchall()
    by = defaultdict(list)
    for r in q:
        by[r[0]].append(r[1:])
    mdays = {d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done").fetchall()
             if MINUTE_LAST is None or d <= MINUTE_LAST}
    rows = []
    for code, xs in by.items():
        for k in range(65, len(xs) - 1):
            p, d, n = xs[k - 1], xs[k], xs[k + 1]
            if not p[5] or p[5] < 5e9 or not d[1] or not n[1] or not p[4]:
                continue
            if any(x[4] is None or x[2] is None or x[3] is None or x[5] is None for x in xs[k - 61:k]):
                continue
            H = max(x[2] for x in xs[k - 60:k - 3])
            b1 = sum(1 for j in range(k - 5, k) if xs[j][4] / xs[j - 1][4] - 1 >= 0.15)
            v3 = sum(x[5] for x in xs[k - 3:k]) / 3
            v20 = sum(x[5] for x in xs[k - 23:k - 3]) / 20
            C = p[4] / H - 1
            T = max(x[2] for x in xs[k - 3:k]) / H - 1
            if not (b1 >= 1 and v20 and v3 / v20 >= 2 and -0.15 <= C <= 0 and T >= -0.03):
                continue
            R = max(H, max(x[2] for x in xs[k - 3:k]))
            last10 = [x[5] for x in xs[k - 10:k]]
            pk_age = 9 - max(range(10), key=lambda j: last10[j])
            o, h, l, c = d[1], d[2], d[3], d[4]
            r = dict(code=code, date=d[0], R=R, b1=b1, V=v3 / v20, avg20=v20, fade=p[5] / max(x[5] for x in xs[k - 3:k]),
                     pk_age=pk_age, rise=sum(x[5] for x in xs[k - 5:k]) / max(1, sum(x[5] for x in xs[k - 10:k - 5])),
                     gap=o / p[4] - 1, gap_over=o > R, broke=h > R, nopen=n[1])
            if h > R and abs(o / p[4] - 1) < 0.3:
                e = o if o > R else R
                r["e"] = e
                r["d7"] = (0.07 - COST) if h >= e * 1.07 else n[1] / e - 1 - COST     # 일봉: 손절 없음
            # 2단계: 1분봉
            if r.get("e") and not r["gap_over"] and d[0] in mdays:
                bars = m.execute("""SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL' AND code=?
                                    AND ts >= ? AND ts < ? ORDER BY ts""",
                                 [code, datetime.combine(d[0], time(8, 0)), datetime.combine(d[0], time(15, 20))]).fetchall()
                reg = [b for b in bars if b[0].time() >= time(9, 0)]
                if len(reg) > 30 and abs(reg[-1][4] / c - 1) < 0.03:       # 1분봉·일봉 가격 단위 맞는 경우만
                    val = lambda b: b[5] * (b[2] + b[3] + b[4]) / 3
                    r["pre_val"] = sum(val(b) for b in bars if b[0].time() < time(9, 0)) / v20
                    i = next((j for j, b in enumerate(reg) if b[2] > R), None)
                    if i is not None:
                        r["bo_t"] = reg[i][0].time()
                        r["bo_cum"] = sum(val(b) for b in reg[:i]) / v20
                        e = max(R, reg[i][1])
                        out = {}
                        for sl in (0.03, 0.05, 0.07):
                            px = None
                            for j in range(i, len(reg)):
                                b = reg[j]
                                if b[3] <= e * (1 - sl):
                                    px = min(b[1], e * (1 - sl)) if j > i else e * (1 - sl); break
                                if (j > i and b[2] >= e * 1.07) or (j == i and b[4] >= e * 1.07):
                                    px = max(b[1], e * 1.07) if j > i else e * 1.07; break
                            out[sl] = (px if px else n[1]) / e - 1 - COST
                        r["m7"] = out
            rows.append(r)
    return rows


def compare(new: list[dict], old: list[dict]) -> None:
    """보존본과 비교: (a) 행 수·키 (b) 계좌 백테스트(events_15) 필터 통과 행 (c) 같은 행의 m7[0.05] 차이."""
    from kiwoom_trading.backtest.playbook.paths import INV_DAILY_DB
    from kiwoom_trading.backtest.playbook.regime import BAD, cls
    nk = {(r["code"], r["date"]) for r in new}; ok = {(r["code"], r["date"]) for r in old}
    print(f"(a) 행 수 보존본 {len(old):,} / 다시 만든 것 {len(new):,} · 키 같음 {len(nk & ok):,} · 보존본에만 {len(ok - nk)} · 새것에만 {len(nk - ok)}")
    om = {(r["code"], r["date"]): r for r in old}
    diff = defaultdict(int)
    for r in new:
        o = om.get((r["code"], r["date"]))
        if not o:
            continue
        if set(map(str, r)) != set(map(str, o)):
            diff["칸 구성"] += 1
        for k, v in o.items():
            if k not in r:
                continue
            w = r[k]
            if k == "m7":
                diff["m7"] += any(abs(v[s] - w.get(s, 9)) > 1e-12 for s in v)
            elif isinstance(v, float):
                diff[k] += abs(w - v) > 1e-12 * max(1.0, abs(v))
            else:
                diff[k] += w != v
    bad = {k: v for k, v in diff.items() if v}
    print("    같은 키 행에서 값이 다른 칸: " + (", ".join(f"{k} {v}행" for k, v in bad.items()) if bad else "없음 (모든 칸 같음)"))
    dmi = duckdb.connect(INV_DAILY_DB, read_only=True)
    sh = dict(dmi.execute("SELECT code, listed_shares FROM stocks").fetchall())
    dmi.close()

    def passed(rs):
        out = {}
        for r in rs:
            if "m7" not in r or (r["code"], r["date"]) in BAD or not cls(r["date"]):
                continue
            if (sh.get(r["code"]) or 0) * r["e"] >= 2e11 and r["bo_cum"] >= 1 and r["bo_t"] >= time(9, 10):
                out[(r["date"], r["code"], r["bo_t"])] = r["m7"][0.05]
        return out
    po, pn = passed(old), passed(new)
    both = po.keys() & pn.keys()
    print(f"(b) 필터 통과 (date, code, bo_t): 보존본 {len(po)} / 새것 {len(pn)} · 같음 {len(both)} "
          f"(일치율 {len(both) / max(1, len(po.keys() | pn.keys())) * 100:.1f}%)"
          + (f" · 보존본에만 {sorted(po.keys() - pn.keys())}" if po.keys() - pn.keys() else "")
          + (f" · 새것에만 {sorted(pn.keys() - po.keys())}" if pn.keys() - po.keys() else ""))
    d = [abs(po[k] - pn[k]) for k in both]
    print(f"(c) 같은 행 m7[0.05] 차이: 최대 {max(d, default=0):.2e} · 소수 넷째 자리에서 다른 행 {sum(x >= 5e-5 for x in d)} · "
          f"합계 보존본 {sum(po.values()):+.6f} / 새것 {sum(pn.values()):+.6f}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = _time.time()
    dm, m = _open_ro(DAILY_DB), _open_ro(MINUTE_DB)
    rows = build(dm, m)
    dm.close(); m.close()
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "g2g_filter.pkl")
    pickle.dump(rows, open(out, "wb"))
    print(f"저장 {out}: {len(rows):,}행 (일봉 돌파 {sum('e' in r for r in rows)}, 1분봉 {sum('m7' in r for r in rows)}) · {_time.time() - t0:.0f}초")
    old = os.path.join(PB, "g2g_filter.pkl")
    if os.path.exists(old):
        compare(rows, pickle.load(open(old, "rb")))


if __name__ == "__main__":
    main()
