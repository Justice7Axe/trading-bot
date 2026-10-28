"""디앤서 백테스트 전 자료 점검 (2026-10-25) — 쓰는 모든 칸의 기간·빈칸·단위·가격 기준을 먼저 확인한다.
결과: data/danswer/audit.txt
"""
import os, pickle, shutil, sys, tempfile
from collections import defaultdict
from datetime import date, datetime, time
import duckdb

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "danswer"); os.makedirs(OUT, exist_ok=True)
TMP = tempfile.gettempdir()
LOG = open(os.path.join(OUT, "audit.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); LOG.write(str(s) + "\n"); LOG.flush()


def cp(name):
    dst = os.path.join(TMP, "aud_" + name)
    try:
        shutil.copy(os.path.join(DATA, name), dst)
    except PermissionError:
        alt = os.path.join(TMP, "dbk_" + name)
        if os.path.exists(alt): return alt
        raise
    return dst


dm = duckdb.connect(cp("daily_ohlcv.duckdb"), read_only=True)
say("== 1. daily_ohlcv")
say(dm.execute("SELECT min(date), max(date), count(*), count(DISTINCT code) FROM daily_ohlcv").fetchall())
for col in ("open", "high", "low", "close", "volume", "value", "market_cap"):
    n, nn = dm.execute(f"SELECT count(*), count({col}) FROM daily_ohlcv").fetchone()
    say(f"  {col}: 빈칸 {1 - nn / n:.1%}")
say("  source: " + str(dm.execute("SELECT source, count(*) FROM daily_ohlcv GROUP BY 1").fetchall()))
say("== 2. stocks")
n, ls, sec, dl = dm.execute("SELECT count(*), count(listed_shares), count(sector), sum(CASE WHEN delisted THEN 1 ELSE 0 END) FROM stocks").fetchone()
say(f"  종목 {n}, listed_shares 있음 {ls}, sector 있음 {sec}, 상장폐지 표시 {dl}")
say("  업종 수 " + str(dm.execute("SELECT count(DISTINCT sector) FROM stocks").fetchone()[0]))
say("  daily_ohlcv 종목 중 stocks 에 없는 것(ETF 등): " + str(dm.execute("SELECT count(DISTINCT code) FROM daily_ohlcv WHERE code NOT IN (SELECT code FROM stocks)").fetchone()[0]))

mh = duckdb.connect(cp("minute_history.duckdb"), read_only=True)
say("== 3. minute_history (통합 AL 1분봉)")
say(mh.execute("SELECT exchange, min(ts), max(ts), count(DISTINCT code) FROM minute_ohlcv GROUP BY 1").fetchall())
days = [d for (d,) in mh.execute("SELECT DISTINCT date FROM minute_backfill_done ORDER BY 1").fetchall()]
say(f"  날짜 {len(days)}일 {days[0]}~{days[-1]}, 하루 종목 수: " + str(mh.execute("SELECT min(c), median(c), max(c) FROM (SELECT date, count(*) c FROM minute_backfill_done GROUP BY 1)").fetchone()))
cal = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
cov_today, cov_prev = [], []
for d in days[::10]:
    k = cal.index(d)
    have = {c for (c,) in mh.execute("SELECT code FROM minute_backfill_done WHERE date=?", [d]).fetchall()}
    t = [c for (c,) in dm.execute("SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE date=? ORDER BY value DESC LIMIT 50", [d]).fetchall()]
    p = [c for (c,) in dm.execute("SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE date=? ORDER BY value DESC LIMIT 50", [cal[k - 1]]).fetchall()]
    cov_today.append(sum(c in have for c in t) / 50); cov_prev.append(sum(c in have for c in p) / 50)
say(f"  그날 대금 상위 50 중 1분봉 있음 평균 {sum(cov_today) / len(cov_today):.0%}, 전날 대금 상위 50 중 {sum(cov_prev) / len(cov_prev):.0%}")
say("  → 그날 새로 뜬 종목(전날 대금 상위 밖)은 1분봉이 빠질 수 있음 = 그날 급등 종목 표본 편향 주의")
# 가격 기준: 일봉 종가 vs 1분봉 정규장 마지막 봉
mm, tot = 0, 0; ex = []
for d in days[::15]:
    rows = mh.execute("""SELECT code, arg_max(close, ts) FROM minute_ohlcv WHERE exchange='AL' AND ts >= ? AND ts <= ? GROUP BY code""",
                      [datetime.combine(d, time(15, 20)), datetime.combine(d, time(15, 30))]).fetchall()
    dc = dict(dm.execute("SELECT code, close FROM daily_ohlcv WHERE date=?", [d]).fetchall())
    for c, mc in rows:
        if c in dc and dc[c]:
            tot += 1
            if abs(mc / dc[c] - 1) > 0.003:
                mm += 1
                if len(ex) < 5: ex.append((d, c, mc, dc[c]))
say(f"  일봉 종가 vs 1분봉 15:30 종가 차이 0.3% 넘는 비율 {mm}/{tot} = {mm / max(tot, 1):.2%}, 예: {ex}")
say("  → 일봉은 수정주가(뒤에 액면분할 등이 있으면 과거 값이 바뀜), 1분봉은 받은 날 기준 → 한 계산에 섞지 않는다")
# 애프터마켓 봉
say("  애프터(19:30 이후) 봉이 있는 종목 비율 (월별, 1분봉 있는 종목 중):")
for ym in sorted({d.strftime('%Y-%m') for d in days}):
    sub = [d for d in days if d.strftime('%Y-%m') == ym][:3]
    a = b = 0
    for d in sub:
        have = mh.execute("SELECT count(*) FROM minute_backfill_done WHERE date=?", [d]).fetchone()[0]
        aft = mh.execute("SELECT count(DISTINCT code) FROM minute_ohlcv WHERE exchange='AL' AND ts >= ? AND ts <= ?", [datetime.combine(d, time(19, 30)), datetime.combine(d, time(20, 0))]).fetchone()[0]
        a += aft; b += have
    say(f"    {ym}: {a / max(b, 1):.0%}")
pre = mh.execute("SELECT count(DISTINCT code) FROM minute_ohlcv WHERE exchange='AL' AND hour(ts)=8").fetchone()[0]
say(f"  프리마켓(08시) 봉 있는 종목 수(전체 기간): {pre}")

ib = duckdb.connect(cp("daily_ohlcv.duckdb")  # investor_daily 매일 쌓임, read_only=True)
say("== 4. investor_daily (외인·기관 확정치, 원)")
say(ib.execute("SELECT min(date), max(date), count(*), count(DISTINCT code) FROM investor_daily").fetchall())
say("  마지막 10일 종목 수: " + str(ib.execute("SELECT date, count(*) FROM investor_daily GROUP BY 1 ORDER BY 1 DESC LIMIT 10").fetchall()))
ix = duckdb.connect(cp("index.duckdb"), read_only=True)
say("== 5. index")
say(ix.execute("SELECT code, min(date), max(date), count(*) FROM idx_daily GROUP BY 1").fetchall())
say("== 6. 프로그램 일별 (closing_bet/program_daily.pkl, ka90013)")
P = pickle.load(open(os.path.join(DATA, "closing_bet", "program_daily.pkl"), "rb"))
ds = sorted({d for _, d in P})
say(f"  {len(P)}건, 종목 {len({c for c, _ in P})}, 기간 {ds[0]}~{ds[-1]} — 종가배팅 대상(대금 30위·상승) 종목만")
say("== 7. kang_minute.duckdb (강창권 세션 추가 1분봉)")
try:
    km = duckdb.connect(cp("kang_minute.duckdb"), read_only=True)
    say(km.execute("SELECT min(ts), max(ts), count(DISTINCT code) FROM minute_ohlcv").fetchall())
    say(km.execute("SELECT count(*), min(date), max(date) FROM minute_backfill_done").fetchall())
except Exception as e:
    say(f"  열 수 없음 (수집 중): {e}")
