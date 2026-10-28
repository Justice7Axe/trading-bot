"""디앤서 종목 선정법(『실전 시황 트레이딩』 3장)을 🌙 종가 재돌파에 붙인 1년 백테스트.

바탕: closing-bet 의 dans_bars.pkl (D일 대금 상위 30 · 상승 마감, D일 09:00~19:59 / D+1 08:00~15:19 통합 1분봉).
매수: 17:00~19:45 첫 1분봉 종가 > 정규장 종가 (종가 재돌파) — 비교로 정규장 종가 매수도 본다.
매도: D+1 09:00 시가. 비용 0.25%, 건당 100만. 앞/뒤 = 날짜 중앙.
선정 조건 (스킬 danswer 7장 가안):
  연속성 = 전날도 대금 10위(30위) 안 / 신고가 = 정규장 종가 ≥ 250거래일 고가 × 0.95 (또는 넘음)
  같은 섹터 = 그날 대금 30위·+5%↑ 안에 같은 업종(stocks.sector) 다른 종목이 있음
  0순위 = 대금 10위·상승 중 가장 많이 모인 업종(2종목↑)에서 등락률 1위 + 삼성전자·SK하이닉스(+3%↑)
  양매수 = 그날 외국인·기관 순매수 둘 다 + (investor_daily, ~2026-10-13) / 외인 순매수 / 며칠(3일 중 2일↑) 양매수
  15분봉 120선 = 정규장 종가 ≥ 통합 15분봉 종가 120개 평균
  ⚠️ 그날 외인·기관 확정치는 18시 이후 나온다 (책: [0784] 18시~). 17~18시 매수엔 장 마감 잠정치를 써야 한다.
"""
import os, pickle, shutil, sys, tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta
import duckdb
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
S = os.path.join(ROOT, "data", "closing_bet")
TMP = tempfile.gettempdir(); COST = 0.0025
BIG = {"005930", "000660"}


def _copy(name):
    dst = os.path.join(TMP, "dsel_" + name)
    shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


D = pickle.load(open(os.path.join(S, "dans_bars.pkl"), "rb"))
R = D["rows"]
dm = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
ib = duckdb.connect(_copy("daily_ohlcv.duckdb")  # investor_daily 매일 쌓임, read_only=True)
mh = duckdb.connect(_copy("minute_history.duckdb"), read_only=True)
sector = dict(dm.execute("SELECT code, sector FROM stocks").fetchall())
DAYS = sorted({r["date"] for r in R}); HALF = DAYS[len(DAYS) // 2]

# ---- 특징 붙이기
by_day = defaultdict(list)
for r in R:
    by_day[r["date"]].append(r)
for k, d in enumerate(DAYS):
    rows = by_day[d]; codes = [r["code"] for r in rows]; ph = ",".join("?" * len(codes))
    hi = dict(dm.execute(f"""SELECT code, max(high) FROM (SELECT code, high, row_number() OVER (PARTITION BY code ORDER BY date DESC) n
                             FROM daily_ohlcv WHERE date < ? AND code IN ({ph})) WHERE n <= 250 GROUP BY code""", [d, *codes]).fetchall())
    inv = defaultdict(list)
    for c, dt, f, i in ib.execute(f"""SELECT code, date, foreign_, institution FROM investor_daily WHERE code IN ({ph})
                                     AND date <= ? AND date > ? - INTERVAL 10 DAY ORDER BY date DESC""", [*codes, d, d]).fetchall():
        inv[c].append((dt, f, i))
    # 통합 15분봉 종가 120개 평균 (D일 15:30 까지, 08:00~20:00 봉)
    ma = dict(mh.execute(f"""WITH b AS (SELECT code, time_bucket(INTERVAL 15 MINUTE, ts) t, arg_max(close, ts) c FROM minute_ohlcv
                               WHERE exchange='AL' AND code IN ({ph}) AND ts > ? AND ts <= ? GROUP BY 1, 2),
                             n AS (SELECT code, c, row_number() OVER (PARTITION BY code ORDER BY t DESC) k FROM b)
                             SELECT code, avg(c) FROM n WHERE k <= 120 GROUP BY code HAVING count(*) >= 100""",
                         [*codes, datetime.combine(d - timedelta(days=10), time(0)), datetime.combine(d, time(15, 30))]).fetchall())
    strong = [r for r in rows if r["chg"] >= 0.05]
    top10 = [r for r in rows if r["rk"] <= 10 and r["chg"] < 0.295]
    cnt = defaultdict(int)
    for r in top10:
        cnt[sector.get(r["code"])] += 1
    lead_sec = max((s for s in cnt if s and cnt[s] >= 2), key=lambda s: (cnt[s], max(x["chg"] for x in top10 if sector.get(x["code"]) == s)), default=None)
    zero = {max((x for x in top10 if sector.get(x["code"]) == lead_sec), key=lambda x: x["chg"])["code"]} if lead_sec else set()
    zero |= {r["code"] for r in top10 if r["code"] in BIG and r["chg"] >= 0.03}
    for r in rows:
        c = r["code"]
        r["hi250"] = r["close"] / hi[c] if hi.get(c) else None
        r["sector_n"] = sum(1 for x in strong if x["code"] != c and sector.get(x["code"]) == sector.get(c) and sector.get(c))
        r["zero"] = c in zero
        fl = inv.get(c, [])
        r["inv_ok"] = bool(fl) and fl[0][0] == d
        r["f"], r["i"] = (fl[0][1], fl[0][2]) if r["inv_ok"] else (None, None)
        r["both3"] = sum(1 for _, f, i in fl[:3] if f > 0 and i > 0) if r["inv_ok"] else None
        r["ma120"] = r["close"] / ma[c] - 1 if ma.get(c) else None
    print(d, file=sys.stderr, flush=True)


def at_open(r):
    reg = [b for b in r["n_bars"] if b[0] >= time(9, 0)]
    return reg[0][1] if reg and reg[0][0] <= time(9, 5) else None


def rebreak(r):
    for b in r["d_bars"]:
        if time(17, 0) <= b[0] < time(19, 45) and b[4] > r["close"]:
            return b[4]
    return None


def stats(tr, title):
    if len(tr) < 15:
        print(f"  {title:52s} {len(tr)}건 (적음)"); return
    v = np.array([t[1] for t in tr]); a = [x for d, x in tr if d < HALF]; b = [x for d, x in tr if d >= HALF]
    bd = defaultdict(float)
    for d, x in tr: bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    ok = "★" if a and b and np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
    print(f"  {ok}{title:52s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만 "
          f"| 앞 {np.mean(a) if a else 0:+.2%} 뒤 {np.mean(b) if b else 0:+.2%} | 낙폭 {mdd * 100:.0f}만")


def run(label, base, conds):
    print(f"\n=== {label}")
    for buy in ("재돌파", "정규장 종가"):
        print(f" -- 매수: {buy}")
        for name, f in conds:
            tr = []
            for r in base:
                if not f(r):
                    continue
                o = at_open(r); px = rebreak(r) if buy == "재돌파" else r["close"]
                if o and px:
                    tr.append((r["date"], o / px - 1 - COST))
            stats(tr, name)


INV = lambda r: r["inv_ok"]
CONDS = [
    ("조건 없음 (지금 규칙)", lambda r: True),
    ("연속성: 전날도 대금 10위", lambda r: r["prk"] is not None and r["prk"] <= 10),
    ("연속성: 전날도 대금 30위", lambda r: r["prk"] is not None),
    ("신고가: 종가 ≥ 250일 고가 × 0.95", lambda r: r["hi250"] is not None and r["hi250"] >= 0.95),
    ("신고가: 250일 고가 넘음", lambda r: r["hi250"] is not None and r["hi250"] >= 1.0),
    ("같은 업종 +5%↑ 종목 함께 (1개↑)", lambda r: r["sector_n"] >= 1),
    ("같은 업종 +5%↑ 종목 함께 (2개↑)", lambda r: r["sector_n"] >= 2),
    ("0순위 (최다 업종 1위 + 삼전·하닉 +3%)", lambda r: r["zero"]),
    ("15분봉 120선 위", lambda r: r["ma120"] is not None and r["ma120"] >= 0),
    ("15분봉 120선 아래 (책: 제외 대상)", lambda r: r["ma120"] is not None and r["ma120"] < 0),
    ("[수급 자료 있는 날] 전체", INV),
    ("[수급] 외국인 순매수", lambda r: INV(r) and r["f"] > 0),
    ("[수급] 외국인 순매도", lambda r: INV(r) and r["f"] <= 0),
    ("[수급] 양매수 (외인·기관 둘 다 +)", lambda r: INV(r) and r["f"] > 0 and r["i"] > 0),
    ("[수급] 둘 다 순매도", lambda r: INV(r) and r["f"] <= 0 and r["i"] <= 0),
    ("[수급] 3일 중 2일↑ 양매수", lambda r: INV(r) and r["both3"] >= 2),
    ("신고가 0.95 + 양매수 (책: 가장 신뢰하는 자리)", lambda r: INV(r) and r["hi250"] and r["hi250"] >= 0.95 and r["f"] > 0 and r["i"] > 0),
    ("연속성 30위 + 같은 업종 1↑ + 120선 위", lambda r: r["prk"] is not None and r["sector_n"] >= 1 and r["ma120"] is not None and r["ma120"] >= 0),
    ("책 체크리스트 전부 (연속·업종·신고가0.95·양매수·120선)", lambda r: INV(r) and r["prk"] is not None and r["sector_n"] >= 1 and r["hi250"] and r["hi250"] >= 0.95
     and r["f"] > 0 and r["i"] > 0 and r["ma120"] is not None and r["ma120"] >= 0),
]

if __name__ == "__main__":
    run("대금 10위 · 상승 마감 (지금 🌙 종가 재돌파 대상)", [r for r in R if r["rk"] <= 10 and r["chg"] < 0.295], CONDS)
    run("대금 10위 · +8%↑ (삼전·하닉 +3%↑, 영상 편입 기준)",
        [r for r in R if r["rk"] <= 10 and r["chg"] < 0.295 and r["chg"] >= (0.03 if r["code"] in BIG else 0.08)], CONDS)
    run("대금 30위 · 상승 마감 (넓힘)", [r for r in R if r["chg"] < 0.295], CONDS)
