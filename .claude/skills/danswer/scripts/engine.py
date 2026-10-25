"""디앤서 백테스트 공통 엔진 (2026-10-25 다시 만듦) — 모든 기법이 같은 자료 처리·체결·매도·집계를 쓴다.

자료 점검(audit.py) 결과에 따른 규칙:
- 일봉 daily_ohlcv 는 **수정주가**(지금 기준), 1분봉은 **받은 날 기준 가격** → 같은 날 종가가 14.6% 종목·일에서 0.3% 넘게 다르다
  (예 010120 2025-10-15 일봉 61,100 / 1분봉 305,500). 그래서
  · 등락률·대금 순위·시총·이동평균·250일 고가 판단은 **일봉끼리만** 계산한다.
  · 일봉에서 나온 **가격 레벨**(전일 종가·고가, 250일 고가 등)을 1분봉과 비교할 땐 환산 비율 f = 1분봉 D일 정규장 종가 ÷ 일봉 D일 종가 를
    곱한다 (D일 장중 판단에 D일 종가를 쓰지만 이는 '가격 기준 맞추기'일 뿐이라 미래 정보가 아니다 — 같은 날 기준이 같으면 비율이 같다).
    f 를 못 구하면(1분봉 없음) 그 종목·일은 뺀다.
- daily_ohlcv.market_cap 은 100% 빈칸 → 시총 = stocks.listed_shares(지금) × 일봉 종가(지금 기준 수정주가) — 둘 다 지금 기준이라 맞다.
- investor_daily(외인·기관 확정치)는 2026-10-13 까지. 그날 확정치는 장 마감 뒤에 나온다 → 장중 판단에 쓰면 미래 정보 (상한선 표시에만).
- 1분봉: minute_history(전날·그날 대금 상위 약 200~260) + kang_minute(장중 +15%↑ 날·전날 +15%↑ 다음 날, 강창권 세션) 중 봉이 많은 쪽.
체결: 신호 봉 **다음 봉 시가**. 손절가·익절가 닿으면 그 가격(시가가 이미 넘었으면 시가), 같은 봉이면 손절 먼저. 비용 0.25% (메모리 backtest-exit-rules).
"""
import os, shutil, sys, tempfile
from collections import defaultdict
from datetime import date, datetime, time
from functools import lru_cache
import duckdb
import numpy as np

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "danswer"); os.makedirs(OUT, exist_ok=True)
TMP = tempfile.gettempdir()
COST = 0.0025
P0, P1 = date(2025, 10, 16), date(2026, 10, 22)      # 1분봉 기간 (D+1 이 있어야 하므로 10-22 까지)
LIMIT = 0.295


def _cp(name):
    dst = os.path.join(TMP, "eng_" + name)
    try:
        shutil.copy(os.path.join(DATA, name), dst)
    except (PermissionError, OSError):
        if not os.path.exists(dst):
            alt = os.path.join(TMP, "dbk_" + name)
            if os.path.exists(alt): return alt
            raise
        print(f"[engine] {name} 잠김 → 전에 복사한 것 사용", file=sys.stderr)
    return dst


DM = duckdb.connect(_cp("daily_ohlcv.duckdb"), read_only=True)
IB = duckdb.connect(_cp("investor_backfill.duckdb"), read_only=True)
IX = duckdb.connect(_cp("index.duckdb"), read_only=True)
MIN_SRC = [duckdb.connect(_cp("minute_history.duckdb"), read_only=True)]
try:
    MIN_SRC.append(duckdb.connect(_cp("kang_minute.duckdb"), read_only=True))
except Exception as e:
    if os.environ.get("NEED_KANG"):
        raise SystemExit(f"[engine] kang_minute 를 열 수 없음 — 상따·테마 결과가 대금 큰 종목으로 쏠리므로 멈춤: {e}")
    print(f"[engine] kang_minute 없음 (minute_history 만): {e}", file=sys.stderr)

CAL = [d for (d,) in DM.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
CIDX = {d: i for i, d in enumerate(CAL)}
NAME = dict(DM.execute("SELECT code, name FROM stocks").fetchall())
SECTOR = dict(DM.execute("SELECT code, sector FROM stocks").fetchall())
SHARES = dict(DM.execute("SELECT code, listed_shares FROM stocks").fetchall())
KOSPI = dict(IX.execute("SELECT date, close FROM idx_daily WHERE code='001'").fetchall())


def prev_day(d, n=1):
    return CAL[CIDX[d] - n]


def next_day(d):
    i = CIDX[d] + 1
    return CAL[i] if i < len(CAL) else None


NXT_SWITCH = date(2026, 9, 14)   # 이날부터 키움 일봉(ka10081)·일별(ka10086)·1분봉 모두 통합(정규장+애프터) 기준 → 일봉 종가 = 20:00 애프터 종가
UNSURE = set()                   # (code, date): 9-14 이후인데 1분봉이 없어 정규장 값으로 못 바꾼 종목·일


def is_common(c):
    """우선주(끝자리 5·7·9·K) 제외용."""
    return c[-1] not in "579K"


@lru_cache(maxsize=None)
def _min_codes(d):
    out = set()
    for src in MIN_SRC:
        try:
            out |= {c for (c,) in src.execute("SELECT code FROM minute_backfill_done WHERE date=?", [d]).fetchall()}
        except Exception:
            pass
    return out


@lru_cache(maxsize=None)
def daily_day(d):
    """그날 주식(stocks 에 있는 것)의 일봉 {code: (o,h,l,c,v,value)} — 수정주가.
    2026-09-14 부터는 일봉 시·고·저·종이 통합(애프터 포함) 값이라, 1분봉이 있는 종목은 정규장(09:00~15:30) 1분봉으로 다시 만든다
    (가격 기준은 g = 일봉 종가 ÷ 그날 1분봉 마지막 종가 로 맞춤). 거래대금·거래량은 통합 값 그대로 (정규장만 따로 못 구함)."""
    rows = {c: list(r) for c, *r in DM.execute("""SELECT d.code, d.open, d.high, d.low, d.close, d.volume, d.value
                                          FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date=?""", [d]).fetchall()}
    if d >= NXT_SWITCH:
        mc = [c for c in _min_codes(d) if c in rows]
        B = load_day(mc, d)
        for c in rows:
            b = B.get(c) if c in B else None
            if not b:
                UNSURE.add((c, d)); continue
            reg = [x for x in b if time(9, 0) <= x[0] <= time(15, 30)]
            if len(reg) < 30: UNSURE.add((c, d)); continue
            g = rows[c][3] / b[-1][4] if b[-1][4] else 1.0
            rows[c][0:4] = [reg[0][1] * g, max(x[2] for x in reg) * g, min(x[3] for x in reg) * g, reg[-1][4] * g]
    return {c: tuple(r) for c, r in rows.items()}


def chg(c, d):
    a, b = daily_day(d).get(c), daily_day(prev_day(d)).get(c)
    return a[3] / b[3] - 1 if a and b and b[3] else None


@lru_cache(maxsize=None)
def value_rank(d):
    rows = sorted(((c, r[5] or 0) for c, r in daily_day(d).items()), key=lambda x: -x[1])
    return {c: i + 1 for i, (c, _) in enumerate(rows)}


@lru_cache(maxsize=None)
def mcap_rank(d):
    rows = sorted(((c, (SHARES.get(c) or 0) * r[3]) for c, r in daily_day(d).items()), key=lambda x: -x[1])
    return {c: i + 1 for i, (c, _) in enumerate(rows)}


def mcap(c, d):
    r = daily_day(d).get(c)
    return (SHARES.get(c) or 0) * r[3] if r else 0


@lru_cache(maxsize=200000)
def hist(c, d, n):
    """d 이전(d 제외) 그 종목이 거래된 n 거래일 일봉 [(date,o,h,l,c,v,value)] 최신 순 — daily_day(바로잡은 값)에서 만든다."""
    out, i = [], CIDX[d] - 1
    while len(out) < n and i >= 0 and CIDX[d] - i <= n + 60:
        r = daily_day(CAL[i]).get(c)
        if r: out.append((CAL[i], *r))
        i -= 1
    return out


def hi_n(c, d, n):
    """전날까지 n 일 고가. 250일은 상장 60일 이상일 때만 (신규 상장주의 '신고가'는 상장 뒤 최고가일 뿐)."""
    h = hist(c, d, n)
    return max(x[2] for x in h) if len(h) >= min(n, 60 if n >= 120 else 20) else None


def nxt_known(c, d):
    """애프터(NXT) 거래 종목인지 — 판단 시점에 아는 정보로: 전날 19:30 이후 1분봉이 있었나."""
    p = prev_day(d)
    return any(x[0] >= time(19, 30) for x in load_day([c], p)[c])


def ma_n(c, d, n, include_today=False):
    h = hist(c, d, n) if not include_today else [(d, *daily_day(d)[c][:4], 0, 0)] + list(hist(c, d, n - 1))
    return sum(x[4] for x in h) / len(h) if len(h) == n else None


def streak_limitup(c, d):
    """d 이전 연속 상한가 수 (d 제외)."""
    h = hist(c, d, 7); n = 0
    for i in range(len(h) - 1):
        if h[i + 1][4] and h[i][4] / h[i + 1][4] - 1 >= LIMIT: n += 1
        else: break
    return n


@lru_cache(maxsize=None)
def _inv_day(d):
    return {c: (f, i) for c, f, i in IB.execute("SELECT code, foreign_, institution FROM investor_daily WHERE date=?", [d]).fetchall()}


def inv(c, d):
    return _inv_day(d).get(c)


def both_buy(c, d):
    x = inv(c, d)
    return x is not None and x[0] > 0 and x[1] > 0


def kospi_chg(d):
    p = prev_day(d)
    return KOSPI[d] / KOSPI[p] - 1 if d in KOSPI and p in KOSPI else None


# ---------------------------------------------------------------- 1분봉
_bars_cache = {}


def load_day(codes, d):
    """codes 의 d일 08:00~20:00 통합 1분봉 {code: [(time,o,h,l,c,v)]} — 두 출처 중 봉이 많은 쪽."""
    need = [c for c in codes if (c, d) not in _bars_cache]
    if need:
        got = defaultdict(dict)
        for si, src in enumerate(MIN_SRC):
            for i in range(0, len(need), 400):
                part = need[i:i + 400]
                for c, ts, o, h, l, cl, v in src.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL'
                        AND ts >= ? AND ts <= ? AND code IN ({','.join('?' * len(part))}) ORDER BY code, ts""",
                        [datetime.combine(d, time(8, 0)), datetime.combine(d, time(20, 0)), *part]).fetchall():
                    got[(c, si)][ts.time()] = (ts.time(), o, h, l, cl, v)
        for c in need:
            best = max((sorted(got[(c, si)].values()) for si in range(len(MIN_SRC))), key=len)
            _bars_cache[(c, d)] = best
    return {c: _bars_cache[(c, d)] for c in codes}


def bars(c, d):
    return load_day([c], d)[c]


def regular(b):
    return [x for x in b if time(9, 0) <= x[0] <= time(15, 30)]


def factor(c, d):
    """1분봉 가격 = 일봉 가격 × f. 그날 정규장 마지막 봉 ÷ 일봉 종가."""
    r = regular(bars(c, d)); dd = daily_day(d).get(c)
    if len(r) < 30 or not dd or not dd[3]:
        return None
    return r[-1][4] / dd[3]


def at(b, t):
    """t 시각까지 마지막 봉 종가."""
    x = [y for y in b if y[0] <= t]
    return x[-1][4] if x else None


def open_at(b, t0, t1):
    x = next((y for y in b if t0 <= y[0] <= t1), None)
    return x[1] if x else None


BASIS_FIX = defaultdict(int)


def next_day_exits(c, d, buy):
    """다음 날 매도 가격들 → {이름: 수익률}. 08:00 NXT 시가 / 프리 3분할(08:00·08:30·08:49) / 09:00 시가.
    두 날 1분봉의 가격 기준이 다르면(받은 날 사이에 액면분할 등) f(D)/f(D+1) 를 곱해 D일 기준으로 맞춘다.
    맞출 수 없는데 |수익률| > 35% 면 가짜로 보고 뺀다."""
    n = next_day(d)
    if not n: return {}
    b = bars(c, n); out = {}
    fd, fn = factor(c, d), factor(c, n)
    if fd and fn and abs(fn / fd - 1) > 0.003:
        k = fd / fn; BASIS_FIX["맞춤"] += 1
        b = [(x[0], x[1] * k, x[2] * k, x[3] * k, x[4] * k, x[5]) for x in b]
    o9 = open_at(b, time(9, 0), time(9, 5))
    if o9: out["09:00 시가"] = o9 / buy - 1 - COST
    pre = [y for y in b if y[0] < time(9, 0)]
    if pre and pre[0][0] <= time(8, 5):
        out["08:00 NXT 시가"] = pre[0][1] / buy - 1 - COST
        out["프리 3분할"] = np.mean([pre[0][1], at(pre, time(8, 30)), pre[-1][4]]) / buy - 1 - COST
    bad = [k for k, v in out.items() if abs(v) > 0.35]
    if bad:
        BASIS_FIX["35% 넘어 뺌"] += 1
        return {}
    return out


def intraday_exit(b, j, buy, stop=0.02, tp=None, until=time(15, 19), hold=None, c=None, d=None):
    """b[j] 봉 시가에 매수. 손절(stop 비율)·익절(tp) 먼저 닿는 쪽, 아니면 until 종가.
    hold(last_price) 가 참이면 until 에 팔지 않고 다음 날 09:00 시가 (없으면 until 종가)."""
    sp = buy * (1 - stop) if stop else None
    tpp = buy * (1 + tp) if tp else None
    for x in b[j:]:
        if x[0] > until: break
        if sp and x[3] <= sp: return min(x[1], sp) / buy - 1 - COST, "손절"
        if tpp and x[2] >= tpp: return max(x[1], tpp) / buy - 1 - COST, "익절"
    last = at(b, until)
    if hold and hold(last):
        ex = next_day_exits(c, d, buy)
        if "09:00 시가" in ex: return ex["09:00 시가"], "다음 날"
    return last / buy - 1 - COST, "시간"


# ---------------------------------------------------------------- 집계
class Report:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()

    def stats(self, tr, title, width=64):
        """tr = [(date, ret)]. ★ = 앞·뒤 반 모두 + & 가장 좋은 5일을 빼도 +."""
        if len(tr) < 15:
            self.say(f"  {title:{width}s} {len(tr)}건 (적음)"); return None
        ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
        v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; b = [x for d, x in tr if d >= h]
        bd = defaultdict(float)
        for d, x in tr: bd[d] += x
        s = sorted(bd.values(), reverse=True)
        eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
        ok = "★" if np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
        self.say(f" {ok}{title:{width}s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만 "
                 f"| 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} | 승률 {np.mean(v > 0):.0%} 낙폭 {mdd * 100:.0f}만")
        return dict(n=len(v), mean=v.mean(), a=np.mean(a), b=np.mean(b), star=ok == "★")


def days():
    return [d for d in CAL if P0 <= d <= P1]


def code_by_name(name):
    r = DM.execute("SELECT code FROM stocks WHERE name=?", [name]).fetchone()
    return r[0] if r else None
