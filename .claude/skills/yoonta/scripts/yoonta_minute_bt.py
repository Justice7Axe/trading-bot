"""윤타(윤영준) 『주식 단타 특공대』 1분봉 기법 1년 백테스트 (통합 AL 1분봉, 2025-10-16 ~ 2026-10-22).

자료: data/minute_history.duckdb (날짜별 그날·전날 대금 상위 200) + data/kang_minute.duckdb (갭 +3%↑·급등 종목, kang_fetch.py).
그날 상위가 섞이면 결과가 부풀기 때문에(메모리 leader-chart-shape) 대상은 그 시각에 아는 정보로만 고른다:
  책 대상 = 전날 대금 ≥ 100억 & 거래량 ≥ 1,000만 주 (2장 117쪽) & 전날 대금 200위 안 (자료가 늘 있는 범위)
  넓은 대상 = 전날 대금 200위 안 / 쌍쌍바 대장 = 전날 200위 안 또는 갭 +3%↑ (09:00 에 아는 정보)
우선주(코드 끝자리 ≠ 0)·스팩은 뺀다 (책: 우선주·ETF·관리종목 제외). 관리·경고 지정 이력은 자료가 없어 못 뺀다.
신호는 봉이 끝난 뒤 판단 → 다음 1분봉 시가 매수. 비용 0.25%, 건당 100만. 그날 누적 대금 ≥ 10억. 상한가 근처(+28.5%↑) 매수는 뺀다.
매도 (메모리 backtest-exit-rules): 손절가·익절가 닿으면 그 가격(같은 봉이면 손절 먼저), 이평 이탈은 봉 종가로 확인 → 다음 봉 시가,
  15:19 까지 아무것도 안 걸리면 다음 날 시가 (종가 매도 없음). 책의 '장 마감 30분 전 결론'(194쪽)은 이 규칙 때문에 넣지 않았다.

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_minute_bt.py > data/yoonta/minute_bt.txt
"""
import os
import pickle
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta

import duckdb
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "data", "yoonta")
COST = 0.0025
T_END = time(15, 19)


def _copy(name, fresh=True):
    dst = os.path.join(tempfile.gettempdir(), "yoonta_" + name)
    src = os.path.join(ROOT, "data", name)
    if fresh or not os.path.exists(dst):
        try:
            shutil.copy(src, dst)
        except PermissionError:   # 백필·수집 중이라 잠김 → 원본 수정 시각 이후에 만든 다른 사본을 쓴다
            tmp = tempfile.gettempdir()
            cands = [os.path.join(tmp, f) for f in os.listdir(tmp)
                     if (f.endswith(name) or (name == "minute_history.duckdb" and f in ("dt_mh.duckdb", "mh2.duckdb")))
                     and (name != "minute_history.duckdb" or os.path.getsize(os.path.join(tmp, f)) >= 0.9 * os.path.getsize(src))]
            fresh_c = [f for f in cands if os.path.getmtime(f) >= os.path.getmtime(src)
                       and os.path.getsize(f) == os.path.getsize(src)]
            if not cands:
                raise
            if not fresh_c:
                print(f"⚠️ {name} 이 사본보다 새로 바뀌는 중 — 최근 사본으로 돌림 (새로 받은 1분봉은 빠짐)", file=sys.stderr)
            cands = fresh_c or cands
            dst = max(cands, key=os.path.getmtime)
            print(f"⚠️ {name} 잠김 — 사본 {dst} 사용", file=sys.stderr)
    return dst


dm = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
mh = duckdb.connect(_copy("minute_history.duckdb", fresh="--fresh" in sys.argv), read_only=True)
try:
    km = duckdb.connect(_copy("kang_minute.duckdb", fresh=True), read_only=True)
except (OSError, duckdb.Error):
    km = None
    print("⚠️ kang_minute.duckdb 를 못 읽음 — 갭·급등 종목 없이 돌림", file=sys.stderr)
CAL = [r[0] for r in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
DAYS = [d for d in CAL if d >= datetime(2025, 10, 16).date()]
names = dict(dm.execute("SELECT code, name FROM stocks").fetchall())
shares = dict(dm.execute("SELECT code, listed_shares FROM stocks").fetchall())
BAD = {c for c, n in names.items() if c[-1] != "0" or "스팩" in (n or "")}


def market_days():
    """시장 분위기 (메모리 regime-redefine, PR #54 와 같은 뜻 — 중앙값 조건은 뺌, 스킬 kang 7장과 같음)."""
    ix = duckdb.connect(_copy("index.duckdb"), read_only=True)
    daily = ix.execute("SELECT date, close FROM idx_daily WHERE code='001' ORDER BY date").fetchall()
    m910 = dict(ix.execute("""SELECT ts::date, arg_max(close, ts) FROM idx_min WHERE code='001' AND ts::time <= TIME '09:10'
                              GROUP BY 1""").fetchall())
    dates = [d for d, _ in daily]; cl = np.array([c for _, c in daily], dtype=float)
    out = {}
    for i, d in enumerate(dates):
        if i < 250 or d not in m910:
            continue
        r = np.diff(cl[i - 21:i]) / cl[i - 21:i - 1]
        z = (m910[d] / cl[i - 1] - 1) / r.std()
        out[d] = "U" if z >= 1 else "D" if z <= -1 else ("N+" if cl[i - 1] >= 0.9 * cl[i - 250:i].max() else "N-")
    return out


REG = market_days()


def build_peer_graph(before, threshold=0.25, window=120, min_avg_value=3e8):
    """평소 함께 오르내리는 종목 (kiwoom_trading/screener/theme_track.py 와 같은 계산): 과거 120일 수익률에서
    시장 평균 × 베타를 뺀 나머지의 상관 ≥ 0.25 인 쌍. before 이전 자료만 쓴다. 상관값도 함께 돌려준다."""
    df = dm.execute("""SELECT date, code, close / lag(close) OVER (PARTITION BY code ORDER BY date) - 1 r, value
                       FROM daily_ohlcv WHERE date < ? AND date >= ?::DATE - 200""", [before, before]).df()
    R = df.pivot(index="date", columns="code", values="r").sort_index().astype(float).iloc[-window:]
    V = df.pivot(index="date", columns="code", values="value").sort_index().astype(float).iloc[-20:]
    ok = (R.notna().sum() >= window * 0.8) & (V.mean() >= min_avg_value)
    R = R.loc[:, ok].fillna(0).clip(-0.3, 0.3)
    mkt = R.mean(axis=1)
    beta = (R.apply(lambda s: np.cov(s, mkt)[0, 1]) / mkt.var()).values
    E = R.values - np.outer(mkt.values, beta)
    E = (E - E.mean(0)) / (E.std(0) + 1e-12)
    C = (E.T @ E) / len(E)
    np.fill_diagonal(C, 0)
    cols = R.columns.values
    g = defaultdict(dict)
    for i, j in zip(*np.where(C >= threshold)):
        g[cols[i]][cols[j]] = float(C[i, j])
    return g


def day_info(d):
    i = CAL.index(d)
    p1, p2 = CAL[i - 1], CAL[i - 2]
    rows = dm.execute("""
        WITH a AS (SELECT code, close pc, high ph, value pv, volume pvol, rank() OVER (ORDER BY value DESC) rk FROM daily_ohlcv WHERE date = ?),
             b AS (SELECT code, close ppc FROM daily_ohlcv WHERE date = ?),
             c AS (SELECT code, open, high, close FROM daily_ohlcv WHERE date = ?),
             n AS (SELECT code, open nopen FROM daily_ohlcv WHERE date = ?),
             r AS (SELECT code, max(high) FILTER (WHERE rn <= 20) r20, max(high) FILTER (WHERE rn <= 60) r60,
                          max(high) FILTER (WHERE rn <= 120) r120, count(*) nd
                   FROM (SELECT code, high, row_number() OVER (PARTITION BY code ORDER BY date DESC) rn FROM daily_ohlcv
                         WHERE date <= ? AND date > ?::DATE - 200) WHERE rn <= 120 GROUP BY code)
        SELECT c.code, a.pc, a.ph, a.pv, a.pvol, a.rk, b.ppc, c.open, c.high, c.close, n.nopen, r.r20, r.r60, r.r120, r.nd
        FROM c JOIN a USING (code) JOIN b USING (code) LEFT JOIN n USING (code) LEFT JOIN r USING (code)
        WHERE a.pc > 0 AND b.ppc > 0""", [p1, p2, d, CAL[i + 1] if i + 1 < len(CAL) else d, p1, p1]).fetchall()
    info = {}
    for code, pc, ph, pv, pvol, rk, ppc, op, hi, cl, nopen, r20, r60, r120, nd in rows:
        if code in BAD:
            continue
        info[code] = dict(pc=pc, ph=ph, rk=rk, pchg=pc / ppc - 1, gap=op / pc - 1, hi=hi / pc - 1, close=cl, nopen=nopen,
                          book=pv >= 1e10 and pvol >= 1e7 and rk <= 200, r20=r20, r60=r60, r120=r120 if (nd or 0) >= 120 else None)
    return info, p1, p2


def load_bars(d, p1, p2, codes):
    ph = ",".join("?" * len(codes))
    q = f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange = 'AL' AND code IN ({ph})
            AND ts >= ? AND ts < ? AND ts::time >= TIME '09:00' AND ts::time < TIME '15:30'"""
    args = [*codes, datetime.combine(p2, time(0)), datetime.combine(d + timedelta(days=1), time(0))]
    rows = mh.execute(q, args).fetchall()
    have = {(r[0], r[1].date()) for r in rows}
    if km is not None:
        rows += [r for r in km.execute(q, args).fetchall() if (r[0], r[1].date()) not in have]
    # 15:30 종가 단일가 봉 = 그날 원가격 종가 (수정주가 이벤트가 없으면 일봉 종가와 정확히 같음 — 확인 92.3% 일치, 나머지는 배당·증자·분할)
    q30 = q.replace("ts::time >= TIME '09:00' AND ts::time < TIME '15:30'", "ts::time = TIME '15:30'")
    c30 = {(r[0], r[1].date()): r[5] for r in mh.execute(q30, args).fetchall()}
    if km is not None:
        for r in km.execute(q30, args).fetchall():
            c30.setdefault((r[0], r[1].date()), r[5])
    by = defaultdict(dict)
    for r in rows:
        by[r[0]][r[1]] = r
    dclose = {(c, dt): cl for c, dt, cl in dm.execute(
        f"SELECT code, date, close FROM daily_ohlcv WHERE code IN ({ph}) AND date BETWEEN ? AND ?", [*codes, p2, d]).fetchall()}
    out = {}
    for code, m in by.items():
        ts = sorted(m)
        if not ts or ts[-1].date() != d:
            continue
        a = np.array([m[t][2:7] for t in ts], dtype=float)
        dates = np.array([t.date() for t in ts])
        for dt in set(dates):     # 1분봉 원가격 → 일봉 수정주가 기준 환산 (메모리 backtest-rigor: 둘을 섞지 않는다)
            idx = np.where(dates == dt)[0]
            dc = dclose.get((code, dt)); x30 = c30.get((code, dt))
            if dc and x30:
                f = x30 / dc                        # 정확한 환산 비율 (작은 배당락 차이도 맞춤)
                if abs(f - 1) > 1e-9:
                    a[idx, :4] /= f; a[idx, 4] *= f
            else:
                f = a[idx[-1], 3] / dc if dc else 1.0   # 15:30 봉이 없으면 예전 방식 (5% 넘을 때만)
                if abs(f - 1) > 0.05:
                    a[idx, :4] /= f; a[idx, 4] *= f
        k0 = next(i for i, t in enumerate(ts) if t.date() == d)
        pv = a[:k0][dates[:k0] == p1, 4]
        out[code] = dict(ts=ts, o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3], v=a[:, 4], k0=k0, dates=dates,
                         pvm=float(pv.mean()) if len(pv) else 0.0, tm=[t.time() for t in ts])
    return out


def ma(c, n):
    cs = np.cumsum(np.insert(c, 0, 0.0))
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def agg(b, n):
    """n분봉 (날짜별 09:00 부터 n분 단위). last = 그 봉의 마지막 1분봉 번호 (그 1분봉이 끝나야 n분봉도 끝난 것으로 본다)."""
    mins = np.array([(t.hour * 60 + t.minute - 540) // n for t in b["tm"]])
    key = np.array([dt.toordinal() for dt in b["dates"]]) * 1000 + mins
    starts = np.r_[0, np.where(np.diff(key) != 0)[0] + 1]
    ends = np.r_[starts[1:], len(key)] - 1
    o = b["o"][starts]; c = b["c"][ends]
    h = np.maximum.reduceat(b["h"], starts); l = np.minimum.reduceat(b["l"], starts)
    v = np.add.reduceat(b["v"], starts)
    today = b["dates"][starts] == b["dates"][-1]
    return dict(o=o, h=h, l=l, c=c, v=v, last=ends, first=starts, today=today, tm=[b["tm"][s] for s in starts])


def on_grid(b, g, arr):
    """n분봉 값 → 1분봉 번호(그 n분봉의 마지막 1분봉)에 올림. 나머지는 nan."""
    out = np.full(len(b["c"]), np.nan)
    out[g["last"]] = arr
    return out


def demark_ok(g):
    """막시무스(디마크, 4장 216~218쪽): 5분봉 X = (양봉 2H+L+C, 음봉 H+2L+C, 보합 H+L+2C), 다음 봉 High 선 = X/2 − L.
    그 5분봉이 끝날 때 종가 ≥ (앞 5분봉으로 계산한) High 선이면 True."""
    o, h, l, c = g["o"], g["h"], g["l"], g["c"]
    x = np.where(c > o, 2 * h + l + c, np.where(c < o, h + 2 * l + c, h + l + 2 * c))
    line = np.r_[np.nan, (x / 2 - l)[:-1]]
    return c >= line


def simulate(b, e, nopen, stop=None, tps=(), trail=None, under=None):
    """e 번째 1분봉 시가 매수. stop = 손절가, tps = [(비율, 익절가)] 분할 익절,
    trail = 1분봉 배열 (값 < 0 이면 그 봉 종가로 이탈 확인 → 다음 봉 시가에 남은 물량 매도), under = 이 가격 아래 종가면 이탈과 같음.
    돌려줌: (수익률, 매도 봉 번호 또는 None=다음 날 시가)."""
    o, h, l, c, tm = b["o"], b["h"], b["l"], b["c"], b["tm"]
    buy = o[e]; rem = 1.0; pnl = 0.0; done = [False] * len(tps)
    n = len(c)
    for j in range(e, n):
        if tm[j] > T_END:
            break
        if stop and l[j] <= stop:
            return pnl + rem * (min(o[j], stop) / buy - 1) - COST, j
        for i, (f, p) in enumerate(tps):
            if not done[i] and h[j] >= p:
                pnl += f * (max(o[j], p) / buy - 1); rem -= f; done[i] = True
        if rem <= 1e-9:
            return pnl - COST, j
        brk = (trail is not None and trail[j] < 0) or (under is not None and c[j] < under)
        if brk and j + 1 < n and tm[j + 1] <= T_END:
            return pnl + rem * (o[j + 1] / buy - 1) - COST, j + 1
    if not nopen:
        return None, None
    return pnl + rem * (nopen / buy - 1) - COST, None


def value_until(b, j):
    s = slice(b["k0"], j + 1)
    return float((b["c"][s] * b["v"][s]).sum())


def first_from(b, t):
    return next((j for j in range(b["k0"], len(b["tm"])) if b["tm"][j] >= t), None)


# ------------------------------------------------------------------ 신호 (진입할 1분봉 번호를 돌려줌)
def sig_jeodol(b, inf, R, start=time(9, 0), end=time(9, 59), filt=None):
    """저돌(4장 197~199쪽): 일봉 저항선(최근 N일 최고가)을 분봉 종가가 뚫는 순간 + 거래량(그 1분봉 거래량 ≥ 전날 1분 평균 × 3) → 다음 봉.
    시가가 이미 저항 위면 신호 없음 (갭으로 넘은 것은 저돌이 아님)."""
    k0 = b["k0"]
    if R is None or b["o"][k0] >= R or R > inf["pc"] * 1.25:
        return None
    for j in range(k0, len(b["tm"])):
        t = b["tm"][j]
        if t > end:
            return None
        if b["c"][j] > R:
            if t < start or b["v"][j] < 3 * max(b["pvm"], 1):
                return None
            if filt is not None and not filt[j]:
                return None
            return j + 1
    return None


def sig_bundol(b, inf, start=time(9, 10), end=time(9, 59), min_chg=0.05, gap_bars=10, dip=0.02):
    """분돌(4장 222쪽): 당일 고점을 다시 뚫음. 고점이 gap_bars 봉 전 이상에 만들어졌고 그 뒤 dip 이상 눌렸던 것,
    그 시각 +5%↑ (재료가 센 날). 저돌의 하위 개념."""
    k0 = b["k0"]; pc = inf["pc"]
    hi, hi_j, lo_after = -1, None, 1e18
    for j in range(k0, len(b["tm"])):
        t = b["tm"][j]
        if t > end:
            return None
        if hi_j is not None and b["c"][j] > hi and t >= start and j - hi_j >= gap_bars and lo_after <= hi * (1 - dip) \
                and b["c"][j] / pc - 1 >= min_chg:
            return j + 1
        if b["h"][j] > hi:
            hi, hi_j, lo_after = b["h"][j], j, 1e18
        else:
            lo_after = min(lo_after, b["l"][j])
    return None


def sig_open_reclaim(b, inf, start=time(9, 5), end=time(9, 59), below=5):
    """시가 돌파(4장 219~220쪽): 시가 아래에서 움직이던 종목(직전 below 봉 종가가 모두 시가 아래)이 시가를 종가로 회복 → 다음 봉."""
    k0 = b["k0"]; op = b["o"][k0]; run = 0
    for j in range(k0, len(b["tm"])):
        t = b["tm"][j]
        if t > end:
            return None
        if b["c"][j] < op:
            run += 1
        else:
            if run >= below and t >= start:
                return j + 1
            run = 0
    return None


def sig_byeonbi(g, inf, m15, m20, start=time(9, 0), end=time(9, 59), mode="touch", need=0.05):
    """변비타점(4장 173~177쪽): 상승하던(그 시각까지 고가 +5%↑, 15선 ≥ 20선) 분봉이 15~20선 사이에 뭉치고 20선이 받쳐 줌.
    mode='touch' : 저가가 20선 +0.3% 안까지 내려오고 종가 ≥ 20선 → 그 봉이 끝나면 매수 (책: 20일선 지지 보이면 분할매수)
    mode='squeeze': 3봉 연속 저가 ≥ 20선 × 0.995 · 종가 ≤ 15선 × 1.01 (뭉침) → 다음 봉 종가가 뭉침 고점 돌파 → 매수.
    돌려줌: n분봉 번호 (그 봉이 끝난 뒤 다음 1분봉에서 매수)."""
    pc = inf["pc"]; hi = 0.0
    idx = np.where(g["today"])[0]
    for k in idx:
        t = g["tm"][k]
        hi = max(hi, g["h"][k] / pc - 1)
        if t > end:
            return None
        if t < start or np.isnan(m20[k]) or hi < need or m15[k] < m20[k]:
            continue
        if mode == "touch":
            if g["l"][k] <= m20[k] * 1.003 and g["c"][k] >= m20[k] and g["c"][k] <= m15[k] * 1.01:
                return k
        elif k >= 3 and g["today"][k - 3]:
            s = slice(k - 3, k)
            if (g["l"][s] >= m20[s] * 0.995).all() and (g["c"][s] <= m15[s] * 1.01).all() and (g["c"][s] >= m20[s]).all() \
                    and g["c"][k] > g["h"][s].max():
                return k
    return None


def sig_volume_pullback(g, inf, start=time(9, 0), end=time(10, 29), vx=3.0, body=0.02, support="open"):
    """거래량 터진 양봉 → 거래량 줄며 눌림 → 지지 확인 → 매수 (1장 87쪽 '반드시 외워두세요'):
    3분봉 거래량 ≥ 직전 20봉 평균 × vx 이고 몸통 +2%↑ 양봉 → 다음 봉들 거래량 < 그 양봉 × 0.5, 저가 ≥ 지지(양봉 시가 또는 중간)
    → 눌린 봉(2봉↑) 뒤 종가가 직전 봉 고가 위 = 반등 확인 → 매수. 지지 가격도 돌려줌."""
    idx = [k for k in np.where(g["today"])[0]]
    for k in idx:
        t = g["tm"][k]
        if t > end:
            return None, None
        if t < start or k < 20 or g["o"][k] <= 0:
            continue
        if not (g["v"][k] >= vx * g["v"][k - 20:k].mean() and g["c"][k] / g["o"][k] - 1 >= body):
            continue
        sup = g["o"][k] if support == "open" else (g["o"][k] + g["c"][k]) / 2
        pulls = 0
        for m in range(k + 1, min(k + 15, len(g["c"]))):
            if not g["today"][m] or g["tm"][m] > end:
                break
            if g["l"][m] < sup or g["v"][m] >= 0.5 * g["v"][k]:
                break
            if pulls >= 2 and g["c"][m] > g["h"][m - 1]:
                return m, sup
            pulls += 1
        # 이 양봉에서 신호가 안 나면 다음 양봉을 찾는다
    return None, None


def sig_second_wave(b, inf, m20, start=time(10, 10), end=time(11, 30), need=0.10, look=30):
    """10시 이후 2차 상승(3장 160~161쪽): 09~10시 고가 +10%↑ 종목, 10시 이후 저점(L)을 깨지 않고
    종가가 직전 30분 고가 위 + 20분선 위 + 그 시각 +5%↑ → 다음 봉. L 도 돌려줌 (손절 기준)."""
    pc = inf["pc"]; k0 = b["k0"]
    j10 = first_from(b, time(10, 0))
    if j10 is None:
        return None, None
    if b["h"][k0:j10].max() / pc - 1 < need:
        return None, None
    for j in range(j10 + look + 1, len(b["tm"])):
        t = b["tm"][j]
        if t > end:
            return None, None
        L = b["l"][j10:j - look].min()          # 10시 이후 앞쪽 저점 — 최근 30분이 이 저점을 깨지 않아야 함
        if t >= start and b["c"][j] > b["h"][j - look:j].max() and b["c"][j] > m20[j]                 and b["l"][j - look:j + 1].min() >= L and b["c"][j] / pc - 1 >= 0.05:
            return j + 1, L
    return None, None


# ------------------------------------------------------------------ 실행
TR = defaultdict(list)          # (기법, 매도) → [(날짜, 수익, 코드, 진입시각, 매도봉시각 또는 None)]
FACT = defaultdict(list)
GRAPH = {}


def add(key, d, code, r, t_in, t_out):
    if r is not None:
        TR[key].append((d, r, code, t_in, t_out))


def exits_std(b, m4_1, d4_3, extra=()):
    X = [("익절 +1% · 손절 −2% (책 자동 주문)", dict(stop=lambda p: p * 0.98, tps=lambda p: [(1, p * 1.01)])),
         ("123 분할(+1·+2·+3%) · 손절 −2%", dict(stop=lambda p: p * 0.98, tps=lambda p: [(1 / 3, p * 1.01), (1 / 3, p * 1.02), (1 / 3, p * 1.03)])),
         ("기계 손절: 익절 +2% · 손절 −1%", dict(stop=lambda p: p * 0.99, tps=lambda p: [(1, p * 1.02)])),
         ("4턴4꺾 1분봉 4선 이탈 · 손절 −2%", dict(stop=lambda p: p * 0.98, trail=m4_1)),
         ("4턴4꺾 3분봉 4선 이탈 · 손절 −2%", dict(stop=lambda p: p * 0.98, trail=d4_3)),
         ("반반이: +5% 절반 · 나머지 3분봉 4선 이탈 · 손절 −2%", dict(stop=lambda p: p * 0.98, tps=lambda p: [(0.5, p * 1.05)], trail=d4_3)),
         ("손절 −3% · 익절 +5% (비교용)", dict(stop=lambda p: p * 0.97, tps=lambda p: [(1, p * 1.05)]))]
    return X + list(extra)


def run_day(d):
    info, p1, p2 = day_info(d)
    want = [c for c, x in info.items() if x["rk"] <= 200 or x["gap"] >= 0.03 or x["pchg"] >= 0.15 or x["hi"] >= 0.15]
    bars = load_bars(d, p1, p2, want)
    reg = REG.get(d, "?")
    g_peer = GRAPH.get(d) or {}
    cache = {}

    def prep(code):
        if code in cache:
            return cache[code]
        b = bars[code]
        c = b["c"]
        g3 = agg(b, 3)
        m4_3 = ma(g3["c"], 4)
        d4_3 = on_grid(b, g3, g3["c"] - m4_3)
        g5 = agg(b, 5)
        dm5 = on_grid(b, g5, demark_ok(g5).astype(float))
        ok5 = np.zeros(len(c), bool); cur = False
        for j in range(len(c)):
            if not np.isnan(dm5[j]):
                cur = dm5[j] > 0
            ok5[j] = cur
        x = dict(m4=c - ma(c, 4), m20=ma(c, 20), g3=g3, d4_3=d4_3, m15_3=ma(g3["c"], 15), m20_3=ma(g3["c"], 20),
                 m120_3=ma(g3["c"], 120), ok5=ok5)
        cache[code] = x
        return x

    def go(name, code, e, exits, minval=1e9, univ=None):
        b = bars[code]; inf = info[code]
        if e is None or e >= len(b["tm"]) or b["tm"][e] > T_END or b["ts"][e].date() != d or value_until(b, e - 1) < minval:
            return
        buy = b["o"][e]
        if buy >= inf["pc"] * 1.285:
            return
        for xn, kw in exits:
            kw = {k: (v(buy) if callable(v) else v) for k, v in kw.items()}
            r, jx = simulate(b, e, inf["nopen"], **kw)
            add((name, xn), d, code, r, b["tm"][e], b["tm"][jx] if jx is not None else None)

    leaders = []
    for code, b in bars.items():
        inf = info[code]; k0 = b["k0"]
        if b["tm"][k0] > time(9, 5):
            continue
        c = b["c"]; pc = inf["pc"]
        reg_bars = range(k0, len(b["tm"]))
        # ---- 책 주장 확인 (전날 200위 안 종목)
        if inf["rk"] <= 200:
            j10 = first_from(b, time(10, 0))
            if j10:
                val = c[k0:] * b["v"][k0:]
                FACT["val"].append((val[:j10 - k0].sum(), val.sum()))
        if inf["close"] / pc - 1 >= 0.29:
            j_hit = next((j for j in reg_bars if b["h"][j] / pc - 1 >= 0.10), None)
            if j_hit is not None:
                FACT["limit"].append(b["tm"][j_hit])
        # 쌍쌍바 대장 후보: 09:00~10:00 처음 +5% 를 넘은 봉 (누적 대금 20억↑)
        if inf["rk"] <= 200 or inf["gap"] >= 0.03:
            for j in reg_bars:
                if b["tm"][j] > time(9, 59):
                    break
                r = c[j] / pc - 1
                if r >= 0.05:
                    if r < 0.29 and value_until(b, j) >= 2e9:
                        leaders.append((b["tm"][j], code, r))
                    break
        if inf["rk"] > 200:
            continue
        P = prep(code)
        univs = [("책 대상", inf["book"]), ("전날 200위", True)]
        for un, ok in univs:
            if not ok:
                continue
            X = exits_std(b, P["m4"], P["d4_3"])
            tag = f"({un})"
            # 저돌 — 20·60일 최고가, 갭 +10%↑ 종목은 책에서 후순위
            for rn in ("r20", "r60"):
                R = inf[rn]
                lab = "20일" if rn == "r20" else "60일"
                e = sig_jeodol(b, inf, R)
                xx = X + [("속임수 돌파(종가가 저항 아래) 매도 · 손절 −2%", dict(stop=lambda p: p * 0.98, under=R))]
                go(f"[저돌] {lab} 최고가 돌파 09:00~10:00 {tag}", code, e, xx, univ=un)
                if e is not None:
                    nxt = inf["r120"]
                    if nxt is None or nxt >= b["o"][min(e, len(c) - 1)] * 1.03 or nxt <= R:
                        go(f"[저돌] {lab} 최고가 돌파 + 다음 저항(120일 고가)까지 3%↑ 여유 {tag}", code, e, X)
                    go(f"[저돌+막시무스] {lab} 최고가 돌파 + 5분봉 디마크 High 위 {tag}", code,
                       sig_jeodol(b, inf, R, filt=P["ok5"]), X)
                    if reg in ("U", "N+"):
                        go(f"[저돌] {lab} 최고가 돌파 — 상승장(U·N+)만 {tag}", code, e, X)
                if un == "책 대상":
                    go(f"[비교] {lab} 최고가 돌파 10:00~15:00 (알람형, 책은 9~10시 집중) {tag}", code,
                       sig_jeodol(b, inf, R, start=time(10, 0), end=time(15, 0)), X)
            go(f"[분돌] 당일 고점 재돌파 09:10~10:00 (+5%↑) {tag}", code, sig_bundol(b, inf), X)
            op = b["o"][k0]
            go(f"[시가] 시가 아래 5봉 → 시가 회복 09:05~10:00 {tag}", code, sig_open_reclaim(b, inf),
               X + [("시가 −0.5% 손절 · 익절 +2%", dict(stop=lambda p, op=op: op * 0.995, tps=lambda p: [(1, p * 1.02)])),
                    ("시가 −0.5% 손절 · 3분봉 4선 이탈", dict(stop=lambda p, op=op: op * 0.995, trail=P["d4_3"]))])
            g3 = P["g3"]
            m20_3g = on_grid(b, g3, g3["c"] - P["m20_3"])
            for mode, lab in (("touch", "20선 터치 지지"), ("squeeze", "15~20선 뭉침 뒤 돌파")):
                k = sig_byeonbi(g3, inf, P["m15_3"], P["m20_3"], mode=mode)
                e = g3["last"][k] + 1 if k is not None else None
                go(f"[변비] 3분봉 {lab} 09:00~10:00 {tag}", code, e,
                   X + [("3분봉 20선 이탈 · 손절 −2%", dict(stop=lambda p: p * 0.98, trail=m20_3g))])
            k, sup = sig_volume_pullback(g3, inf)
            e = g3["last"][k] + 1 if k is not None else None
            go(f"[눌림] 3분봉 거래량 양봉 → 거래량 줄며 눌림 → 반등 09:00~10:30 {tag}", code, e,
               X + [("양봉 시가(지지) −0.5% 손절 · 익절 +2%", dict(stop=lambda p, s=sup: s * 0.995 if s else None, tps=lambda p: [(1, p * 1.02)]))])
            e, L = sig_second_wave(b, inf, P["m20"])
            go(f"[10시 이후] 2차 상승 10:10~11:30 (09~10시 +10%↑, 저점 유지) {tag}", code, e,
               X + [("저점 이탈 손절 · 익절 +1% (책)", dict(stop=lambda p, L=L: L if L and L < p else p * 0.98, tps=lambda p: [(1, p * 1.01)]))])
            # 종가배팅 (김보선: 3분봉 120선 지지 + 거래량 감소) — 종가 매수 → 다음 날 시가
            if un == "전날 200위":
                kk = [k for k in np.where(g3["today"])[0] if g3["tm"][k] <= time(15, 18)]
                if kk and inf["nopen"] and 0.03 <= inf["close"] / pc - 1 < 0.29:
                    k = kk[-1]; m = P["m120_3"][k]
                    if not np.isnan(m) and m <= g3["c"][k] <= m * 1.02 and k >= 30 and \
                            g3["v"][k - 9:k + 1].mean() < 0.7 * g3["v"][k - 30:k - 9].mean():
                        r = inf["nopen"] / inf["close"] - 1 - COST
                        add(("[종가배팅] +3%↑ · 15:18 3분봉 120선(김보선) 0~2% 위 · 거래량 감소", "종가 매수 → 다음 날 시가"),
                            d, code, r, time(15, 30), None)

    # ---- 쌍쌍바 (2장 127~136쪽): 대장(그 묶음에서 가장 먼저·가장 강하게 +5%↑) → 2등주(같은 묶음, 아직 −1~+3%) 즉시 매수
    used = set()
    for t, lead, r in sorted(leaders):
        peers = g_peer.get(lead, {})
        if not peers:
            continue
        cand = []
        lead_top = True
        for p, corr in peers.items():
            if p not in bars or p == lead:
                continue
            b = bars[p]
            j = max((i for i in range(b["k0"], len(b["tm"])) if b["tm"][i] <= t), default=None)
            if j is None:
                continue
            rp = b["c"][j] / info[p]["pc"] - 1
            if rp >= r:
                lead_top = False
                break
            if info[p]["rk"] <= 200 and -0.01 <= rp <= 0.03:
                cand.append((rp, corr, p, j))
        if not lead_top or not cand:
            continue
        cand.sort(reverse=True)
        rp, corr, p, j = cand[0]
        if p in used:
            continue
        used.add(p)
        b = bars[p]; P = prep(p)
        X = exits_std(b, P["m4"], P["d4_3"], [("익절 +7% · 손절 −2% (책 고려·삼표시멘트 사례)", dict(stop=lambda q: q * 0.98, tps=lambda q: [(1, q * 1.07)]))])
        go("[쌍쌍바] 대장 +5% 돌파 순간 2등주(평소 함께 오르내림, −1~+3%) 매수 09:00~10:00", p, j + 1, X, minval=5e8)
        if r >= 0.0 and REG.get(d) in ("U", "N+"):
            go("[쌍쌍바] 위 — 상승장(U·N+)만", p, j + 1, X, minval=5e8)


def stats(tr, title):
    if len(tr) < 10:
        print(f"   {title:52s} {len(tr):4d}건 (적음)")
        return None
    v = np.array([t[1] for t in tr])
    half = sorted(t[0] for t in tr)[len(tr) // 2]
    a = [t[1] for t in tr if t[0] < half]; bb = [t[1] for t in tr if t[0] >= half]
    bd = defaultdict(float)
    for t in tr:
        bd[t[0]] += t[1]
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    w = v[v > 0]; ls = v[v <= 0]
    pf = (w.mean() / -ls.mean()) if len(w) and len(ls) and ls.mean() < 0 else float("nan")
    ok = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    rg = defaultdict(list)
    for t in tr:
        rg[REG.get(t[0], "?")].append(t[1])
    rs = " ".join(f"{k} {np.mean(rg[k]):+.2%}({len(rg[k])})" for k in ("U", "N+", "N-", "D") if rg[k])
    print(f"  {ok}{title:52s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} (비용 전 {v.mean() + COST:+.2%}) 합계 {v.sum() * 100:+5.0f}만 "
          f"최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만 손익비 {pf:.2f} 승률 {len(w) / len(v):.0%} | 앞 {np.mean(a):+.2%} 뒤 {np.mean(bb):+.2%} | 낙폭 {mdd * 100:.0f}만"
          f" | 분위기 {rs}")
    return v.mean()


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    NDAYS = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else None
    for i, d in enumerate(DAYS[:-1][:NDAYS]):
        if i % 20 == 0:
            GRAPH_D = build_peer_graph(d)
        GRAPH[d] = GRAPH_D
        run_day(d)
        GRAPH.pop(d, None)
        if i % 20 == 0:
            print(d, file=sys.stderr, flush=True)
    with open(os.path.join(OUT, "minute_trades.pkl"), "wb") as f:
        pickle.dump(dict(TR), f)
    print(f"윤타 『주식 단타 특공대』 1분봉 기법 백테스트 — {DAYS[0]} ~ {DAYS[-2]}, 다음 봉 시가 매수, 비용 0.25%, 건당 100만.")
    print("★ = 앞·뒤 반 모두 + 이고 최고 5일 빼도 +. 손익비 = 평균 이익 ÷ 평균 손실. 분위기 U 강한 상승 / N+ 보통·상승 추세 / N− 보통·약세 / D 강한 하락")
    print("\n### 책 주장 확인")
    fv = FACT["val"]
    print(f"  09:00~10:00 거래대금 비중 (전날 200위 종목 {len(fv)}종목·일): {sum(a for a, _ in fv) / sum(b for _, b in fv):.0%} (책: 1시간에 거래가 가장 많이 몰림)")
    lt = FACT["limit"]
    if lt:
        print(f"  상한가 마감 {len(lt)}건 중 처음 +10% 닿은 시각이 10:00 전: {np.mean([t < time(10, 0) for t in lt]):.0%}, 09:30 전: "
              f"{np.mean([t < time(9, 30) for t in lt]):.0%} (책 33쪽 '상한가 대부분이 9~10시에 급등 시작')")
    last = None
    for (name, xn) in sorted(TR, key=lambda k: k[0]):
        if name != last:
            print(f"\n=== {name}")
            last = name
        stats(TR[(name, xn)], xn)
