"""강창권 『주식투자 단기 트레이딩의 정석』 1분봉 기법 1년 백테스트 (통합 AL 1분봉, 2025-10-16 ~ 2026-10-23).

자료: data/minute_history.duckdb (날짜별 그날·전날 대금 상위 200) + data/kang_minute.duckdb (빠진 갭·급등 종목, kang_fetch.py).
이동평균선: 정규장(09:00~15:29) 1분봉 종가를 전전날·전날·그날 이어 붙여 계산 (240분선 ≈ 하루, 480분선 ≈ 이틀, 책 5장).
신호는 1분봉이 끝난 뒤 판단 → 다음 봉 시가 매수. 비용 0.25%, 건당 100만. 매수 시점까지 그날 누적 대금 ≥ 10억.
상한가 근처(전날 종가 +28.5%↑)에서 사는 신호는 체결이 어려워 뺀다.
대상 종목은 그 시각에 아는 정보로만 고른다:
  전날 상위 = 전날 대금 상위 200 / 갭 = 그날 시가 ÷ 전날 종가 / 전날 급등 = 전날 +15%↑ / 장중 급등 = 그 시각까지 고가 +15%↑
매도 (memory backtest-exit-rules): 손절가 닿으면 그 가격(같은 봉이면 손절 먼저), 익절가 닿으면 그 가격,
  이동평균선 이탈은 봉 종가로 확인 → 다음 봉 시가. 15:19 까지 아무것도 안 걸리면 다음 날 시가 매도 (종가 매도 없음).

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/kang/scripts/kang_minute_bt.py > data/kang/minute_bt.txt
"""
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta

import duckdb
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
COST = 0.0025
T0, T_END = time(9, 0), time(15, 19)


def _copy(name, fresh=True):
    dst = os.path.join(tempfile.gettempdir(), "kangm_" + name)
    if fresh or not os.path.exists(dst):
        shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


dm = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
mh = duckdb.connect(_copy("minute_history.duckdb", fresh="--fresh" in sys.argv), read_only=True)
try:   # 수집(kang_fetch.py) 중에는 파일이 잠겨 있다 → 없이 돌리면 갭·급등 종목이 빠져 결과가 부풂
    km = duckdb.connect(_copy("kang_minute.duckdb", fresh="--kang-cached" not in sys.argv), read_only=True)
except (OSError, duckdb.Error):
    km = None
    print("⚠️ kang_minute.duckdb 를 못 읽음 — 추가 수집분 없이 돌림", file=sys.stderr)
CAL = [r[0] for r in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
DAYS = [d for d in CAL if d >= datetime(2025, 10, 16).date()]
names = dict(dm.execute("SELECT code, name FROM stocks").fetchall())


def market_days():
    """시장 분위기 (메모리 regime-redefine, PR #54 와 같은 뜻 — 중앙값 조건은 뺌):
    코스피 09:10 등락 ÷ 전날까지 20일 변동성 ≥ +1 → 강한 상승(U), ≤ −1 → 강한 하락(D),
    나머지는 전날 종가가 52주(250일) 최고 종가 −10% 안이면 보통·상승 추세(N+), 밖이면 보통·약세(N−)."""
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
shares = dict(dm.execute("SELECT code, listed_shares FROM stocks").fetchall())


def day_info(d):
    """그날 판단에 쓰는 일봉 정보 (전날까지 + 그날 시가). 그날 고가는 1분봉을 불러올 종목을 고르는 데만 쓴다."""
    i = CAL.index(d)
    p1, p2 = CAL[i - 1], CAL[i - 2]
    rows = dm.execute("""
        WITH a AS (SELECT code, close pc, high ph, value pv, rank() OVER (ORDER BY value DESC) rk FROM daily_ohlcv WHERE date = ?),
             b AS (SELECT code, close ppc FROM daily_ohlcv WHERE date = ?),
             c AS (SELECT code, open, high, close FROM daily_ohlcv WHERE date = ?),
             n AS (SELECT code, open nopen FROM daily_ohlcv WHERE date = ?)
        SELECT c.code, a.pc, a.ph, a.rk, b.ppc, c.open, c.high, n.nopen FROM c JOIN a USING (code) JOIN b USING (code) LEFT JOIN n USING (code)
        WHERE a.pc > 0 AND b.ppc > 0""", [p1, p2, d, CAL[i + 1] if i + 1 < len(CAL) else d]).fetchall()
    info = {}
    for code, pc, ph, rk, ppc, op, hi, nopen in rows:
        info[code] = dict(pc=pc, ph=ph, rk=rk, pchg=pc / ppc - 1, gap=op / pc - 1, hi=hi / pc - 1, nopen=nopen,
                          cap=pc * (shares.get(code) or 0))
    return info, p2


def load_bars(d, p2, codes):
    ph = ",".join("?" * len(codes))
    q = f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange = 'AL' AND code IN ({ph})
            AND ts >= ? AND ts < ? AND ts::time >= TIME '09:00' AND ts::time < TIME '15:30'"""
    args = [*codes, datetime.combine(p2, time(0)), datetime.combine(d + timedelta(days=1), time(0))]
    rows = mh.execute(q, args).fetchall()
    have = {(r[0], r[1].date()) for r in rows}
    if km is not None:
        rows += [r for r in km.execute(q, args).fetchall() if (r[0], r[1].date()) not in have]
    by = defaultdict(dict)
    for r in rows:
        by[r[0]][r[1]] = r
    # 1분봉은 원래 가격, 일봉은 수정주가 (액면분할·유상증자 뒤 어긋남, 예: LS ELECTRIC 2026-04 5:1)
    # → 날마다 '1분봉 마지막 종가 ÷ 일봉 종가' 가 5% 넘게 다르면 그날 1분봉을 일봉 기준으로 환산
    dclose = {(c, dt): cl for c, dt, cl in dm.execute(
        f"SELECT code, date, close FROM daily_ohlcv WHERE code IN ({ph}) AND date BETWEEN ? AND ?", [*codes, p2, d]).fetchall()}
    out = {}
    for code, m in by.items():
        ts = sorted(m)
        if not ts or ts[-1].date() != d:
            continue
        a = np.array([m[t][2:7] for t in ts], dtype=float)
        dates = np.array([t.date() for t in ts])
        for dt in set(dates):
            idx = np.where(dates == dt)[0]
            dc = dclose.get((code, dt))
            f = a[idx[-1], 3] / dc if dc else 1.0
            if abs(f - 1) > 0.05:
                a[idx, :4] /= f
        k0 = next(i for i, t in enumerate(ts) if t.date() == d)
        out[code] = dict(ts=ts, o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3], v=a[:, 4], k0=k0)
    return out


def ma(c, n):
    cs = np.cumsum(np.insert(c, 0, 0.0))
    out = np.full(len(c), np.nan)
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def simulate(b, e, nopen, stop=None, tp=None, ma_exit=None, res=None):
    """b 의 e 번째 봉 시가 매수. stop·tp = 가격, ma_exit = 이평 배열 (종가 < 선 → 다음 봉 시가), res = 저항 이평 배열 (고가가 닿으면 그 가격)."""
    buy = b["o"][e]
    for j in range(e, len(b["ts"])):
        if b["ts"][j].time() > T_END:
            break
        if stop and b["l"][j] <= stop:
            return min(b["o"][j], stop) / buy - 1 - COST, "손절"
        if tp and b["h"][j] >= tp:
            return max(b["o"][j], tp) / buy - 1 - COST, "익절"
        if res is not None and not np.isnan(res[j]) and res[j] > buy * 1.003 and b["h"][j] >= res[j]:
            return max(b["o"][j], res[j]) / buy - 1 - COST, "저항"
        if ma_exit is not None and b["c"][j] < ma_exit[j] and j + 1 < len(b["ts"]) and b["ts"][j + 1].time() <= T_END:
            return b["o"][j + 1] / buy - 1 - COST, "이평 이탈"
    if not nopen:
        return None, "자료 없음"
    return nopen / buy - 1 - COST, "다음 날 시가"


def value_until(b, j):
    s = slice(b["k0"], j + 1)
    return float((b["c"][s] * b["v"][s]).sum())


# ------------------------------------------------------------------ 기법별 신호 (진입 봉 번호 e 를 돌려줌)
def sig_gap_open(b, inf):
    return b["k0"] if b["ts"][b["k0"]].time() <= time(9, 5) else None


def sig_gap_two_red(b, inf, last=time(9, 10)):
    """[8-3] 시초가 뒤 1분봉 음봉 2개↑ 연속 → 첫 양봉 끝난 뒤 다음 봉 시가 매수 (09:10 까지)."""
    red = 0
    for j in range(b["k0"], len(b["ts"])):
        if b["ts"][j].time() > last:
            return None
        if b["c"][j] < b["o"][j]:
            red += 1
        elif b["c"][j] > b["o"][j]:
            if red >= 2:
                return j + 1
            red = 0
    return None


def sig_gap_ma10_touch(b, inf, m10, start=time(9, 5), end=time(9, 15)):
    """[8-3] start~end 첫 10분선 터치(저가 ≤ 선, 종가 ≥ 선) → 다음 봉."""
    for j in range(b["k0"], len(b["ts"])):
        t = b["ts"][j].time()
        if t > end:
            return None
        if t >= start and b["l"][j] <= m10[j] <= b["c"][j]:
            return j + 1
    return None


def sig_ma20_reclaim(b, inf, m20, lo=5, hi=20, min_chg=0.03, start=time(9, 30), end=time(14, 30)):
    """[5-2/14-4 골드존] 20분선 위에 20봉↑ 있다가 종가로 깨고, lo~hi 봉 안에 종가로 다시 올라서면 → 다음 봉.
    그 시각 등락률 ≥ min_chg (강한 날)."""
    above, below_at = 0, None
    for j in range(b["k0"], len(b["ts"])):
        t = b["ts"][j].time()
        if t > end or np.isnan(m20[j]):
            if t > end:
                return None
            continue
        if b["c"][j] >= m20[j]:
            if below_at is not None:
                n = j - below_at
                if lo <= n <= hi and t >= start and b["c"][j] / inf["pc"] - 1 >= min_chg:
                    return j + 1
                below_at = None; above = 0
            above += 1
        else:
            if below_at is None:
                below_at = j if above >= 20 else None
                above = 0
    return None


def sig_ck480(b, inf, m480, hold=10, need_hi=0.15, band=0.03, end=time(14, 30)):
    """[15-1 CK480] 전날 +15%↑ 이거나 그 시각까지 고가 +15%↑ 인 종목이 480분선까지 내려와
    hold 봉 동안 종가가 480분선 ~ 480분선 × (1+band) 사이에서 버팀 (첫 봉 저가는 선 × 1.005 아래) → 다음 봉."""
    pc = inf["pc"]; hi_so_far = 0.0; run = 0
    for j in range(b["k0"], len(b["ts"])):
        t = b["ts"][j].time()
        if t >= end:
            return None
        hi_so_far = max(hi_so_far, b["h"][j] / pc - 1)
        if np.isnan(m480[j]) or not (inf["pchg"] >= need_hi or hi_so_far >= need_hi):
            run = 0; continue
        x = m480[j]
        if x <= b["c"][j] <= x * (1 + band):
            if run == 0 and b["l"][j] > x * 1.005:
                continue
            run += 1
            if run >= hold:
                return j + 1
        else:
            run = 0
    return None


def sig_480_240(b, inf, m480, m240, hold=30, need_hi=0.10, end=time(14, 30)):
    """[15-4] 오전 급등(그 시각까지 고가 +10%↑) → 480분선 위 3% 안에서 hold 봉 버팀 → 종가가 240분선 위로 → 다음 봉."""
    pc = inf["pc"]; hi_so_far = 0.0; run = 0
    for j in range(b["k0"], len(b["ts"])):
        t = b["ts"][j].time()
        if t >= end:
            return None
        hi_so_far = max(hi_so_far, b["h"][j] / pc - 1)
        if np.isnan(m480[j]) or np.isnan(m240[j]) or hi_so_far < need_hi:
            run = 0; continue
        if run >= hold and b["c"][j] > m240[j] >= b["c"][j - 1] and m240[j] > m480[j]:
            return j + 1
        run = run + 1 if m480[j] <= b["c"][j] <= m480[j] * 1.03 else 0
    return None


def sig_prevhigh_box(b, inf, box=10, width=0.04, start=time(9, 10), end=time(14, 30)):
    """[13-2] +3%↑ 양봉이 전일 고가를 종가로 돌파 → 다음 box 봉이 전일 고가 위에서 폭 width 안 옆걸음 → 박스 고점 종가 돌파 → 다음 봉."""
    ph = inf["ph"]
    for j in range(b["k0"] + 1, len(b["ts"]) - box - 1):
        t = b["ts"][j].time()
        if t > end:
            return None
        if t < time(9, 1) or not (b["c"][j] > ph >= b["c"][j - 1] and b["c"][j] / b["o"][j] - 1 >= 0.03):
            continue
        s = slice(j + 1, j + 1 + box)
        hi, lo = b["h"][s].max(), b["l"][s].min()
        if lo < ph or hi / lo - 1 > width:
            continue
        for k in range(j + 1 + box, len(b["ts"]) - 1):
            if b["ts"][k].time() > end:
                break
            if b["c"][k] > hi:
                return k + 1 if b["ts"][k].time() >= start else None
            if b["l"][k] < lo:
                break
        return None
    return None


def sig_limit_next(b, inf, m10):
    """[8-4] 전날 상한가 → 오늘 갭 +5%↑ → 09:03~09:05 시초가 아래로 눌렸다가 09:05 봉 종가가 시초가 위 → 다음 봉."""
    op = b["o"][b["k0"]]
    dip = False
    for j in range(b["k0"], len(b["ts"])):
        t = b["ts"][j].time()
        if time(9, 3) <= t <= time(9, 5) and b["l"][j] < op:
            dip = True
        if t >= time(9, 5):
            return j + 1 if dip and b["c"][j] >= op else None
    return None


def sig_limit_weak(b, inf, m20):
    """[8-4(3)] 전날 상한가 → 오늘 갭 +3% 미만 → 장 초 밀린 뒤 09:20~10:30 첫 20분선 종가 돌파 → 다음 봉."""
    was_below = False
    for j in range(b["k0"], len(b["ts"])):
        t = b["ts"][j].time()
        if t > time(10, 30):
            return None
        if np.isnan(m20[j]):
            continue
        if b["c"][j] < m20[j]:
            was_below = True
        elif was_below and t >= time(9, 20):
            return j + 1
    return None


# ------------------------------------------------------------------ 실행
TR = defaultdict(list)          # (기법, 매도) → [(날짜, 수익, 코드)]
FACT = defaultdict(list)        # 책 주장 확인용


def add(key, d, code, r):
    if r[0] is not None:
        TR[key].append((d, r[0], code))


def run_day(d):
    info, p2 = day_info(d)
    want = [c for c, x in info.items() if x["rk"] <= 200 or x["gap"] >= 0.03 or x["pchg"] >= 0.15 or x["hi"] >= 0.15]
    bars = load_bars(d, p2, want)
    for code, b in bars.items():
        inf = info[code]; k0 = b["k0"]
        if b["ts"][k0].time() > time(9, 5):
            continue
        c = b["c"]
        m5, m10, m20, m240, m480 = ma(c, 5), ma(c, 10), ma(c, 20), ma(c, 240), ma(c, 480)
        nopen = inf["nopen"]
        op = b["o"][k0]

        def go(name, e, exits, minval=1e9):
            if e is None or e >= len(b["ts"]) or b["ts"][e].time() > T_END or value_until(b, e - 1) < minval:
                return
            buy = b["o"][e]
            if buy >= inf["pc"] * 1.285:   # 상한가 근처 매수는 잔량이 줄 서 있어 거의 체결 안 됨 → 뺀다
                return
            for xn, kw in exits:
                kw = {k: (v(buy) if callable(v) else v) for k, v in kw.items()}
                add((name, xn), d, code, simulate(b, e, nopen, **kw))

        X_GAP = [("10분선 이탈 (책)", dict(ma_exit=m10)), ("5분선 이탈", dict(ma_exit=m5)),
                 ("손절 −3% · 익절 +5%", dict(stop=lambda p: p * 0.97, tp=lambda p: p * 1.05)),
                 ("10분선 이탈 + 손절 −3%", dict(ma_exit=m10, stop=lambda p: p * 0.97))]
        g = inf["gap"]
        # 8장 시초가: 갭 크기별 (그날 시가로 판단)
        if 0.10 <= g < 0.29:
            tag = "갭 +10~15%" if g < 0.15 else "갭 +15%↑"
            # 책 주장 확인
            reg = [j for j in range(k0, len(b["ts"])) if b["ts"][j].time() <= time(15, 29)]
            hi_j = max(reg, key=lambda j: b["h"][j])
            early = [j for j in reg if b["ts"][j].time() <= time(9, 10)]
            FACT[tag].append(dict(dip=min(b["l"][j] for j in early) < op, top3=b["ts"][hi_j].time() <= time(9, 3),
                                  below_close=c[reg[-1]] < op,
                                  t904=next((c[j] < op for j in reg if b["ts"][j].time() == time(9, 4)), None),
                                  hi_after_939=b["ts"][hi_j].time() > time(9, 40)))
            go(f"[8-3] {tag} 시초가 매수 (책: 하지 말 것)", sig_gap_open(b, inf), X_GAP, 0)
            go(f"[8-3] {tag} 음봉 2개↑ 뒤 첫 양봉", sig_gap_two_red(b, inf), X_GAP, 5e8)
            go(f"[8-3] {tag} 09:05~15 10분선 터치", sig_gap_ma10_touch(b, inf, m10), X_GAP, 5e8)
            if REG.get(d) == "U":   # 09:10 에 강한 상승장 판정이 난 뒤에만 사는 실전형
                go(f"[8-3 실전형] {tag} 강한 상승장 판정 뒤 09:10~20 10분선 터치", sig_gap_ma10_touch(b, inf, m10, time(9, 10), time(9, 20)),
                   X_GAP + [("손절 −3% · 익절 +7%", dict(stop=lambda p: p * 0.97, tp=lambda p: p * 1.07)),
                            ("손절 −2% · 익절 +5%", dict(stop=lambda p: p * 0.98, tp=lambda p: p * 1.05)),
                            ("손절 −4% · 익절 없음", dict(stop=lambda p: p * 0.96))], 5e8)
        if 0.03 <= g <= 0.05 and inf["rk"] <= 200:
            go("[8-2] 갭 +3~5% 시초가 매수 (전날 대금 200위)", sig_gap_open(b, inf), X_GAP, 0)
        # 8-4 상한가 다음 날
        if inf["pchg"] >= 0.29:
            if g >= 0.05:
                go("[8-4] 상한가 다음 날 갭 +5%↑ 09:03~05 눌림 후 시초가 위", sig_limit_next(b, inf, m10),
                   [("시초가 이탈 손절 + 10분선 이탈", dict(stop=lambda p, op=op: op * 0.995, ma_exit=m10)),
                    ("시초가 이탈 손절 + 20분선 이탈", dict(stop=lambda p, op=op: op * 0.995, ma_exit=m20))], 5e8)
            elif g < 0.03:
                e = sig_limit_weak(b, inf, m20)
                lowpx = float(b["l"][k0:e].min()) if e else None
                go("[8-4] 상한가 다음 날 갭 +3% 미만 → 20분선 돌파", e,
                   [("그날 저가 손절 + 20분선 이탈", dict(stop=lambda p, lp=lowpx: lp, ma_exit=m20)),
                    ("손절 −3% + 20분선 이탈", dict(stop=lambda p: p * 0.97, ma_exit=m20))], 5e8)
        # 5-2 / 14-4 골드존 (전날 대금 200위 안)
        if inf["rk"] <= 200:
            X20 = [("20분선 다시 이탈 (책)", dict(ma_exit=m20)), ("20분선 이탈 + 손절 −2%", dict(ma_exit=m20, stop=lambda p: p * 0.98))]
            go("[5-2] 20분선 이탈 뒤 5~20분 안 회복 (그 시각 +3%↑)", sig_ma20_reclaim(b, inf, m20), X20)
            go("[5-2] 위 + 그 시각 +5%↑", sig_ma20_reclaim(b, inf, m20, min_chg=0.05), X20)
            if inf["cap"] >= 1e13:
                go("[14-4 골드존] 시총 10조↑ · 그 시각 +1%↑ · 20분선 회복 (프로그램 조건 없음)",
                   sig_ma20_reclaim(b, inf, m20, min_chg=0.01, start=time(9, 20)), X20)
            go("[13-2] 전일 고가 돌파 양봉 → 10분 옆걸음 → 박스 고점 돌파", sig_prevhigh_box(b, inf),
               [("10분선 이탈 (책)", dict(ma_exit=m10)), ("20분선 이탈", dict(ma_exit=m20)),
                ("10분선 이탈 + 손절 −2%", dict(ma_exit=m10, stop=lambda p: p * 0.98))])
        # 15장 CK480
        X480 = [("손절 −2% · 익절 +3% (책)", dict(stop=lambda p: p * 0.98, tp=lambda p: p * 1.03)),
                ("손절 −2% · 익절 +1%", dict(stop=lambda p: p * 0.98, tp=lambda p: p * 1.01)),
                ("손절 −2% · 240분선 저항 매도", dict(stop=lambda p: p * 0.98, res=m240)),
                ("손절 −2% · 익절 +5%", dict(stop=lambda p: p * 0.98, tp=lambda p: p * 1.05))]
        for hold in (5, 10, 20, 30):
            go(f"[15-1 CK480] 15%↑ 종목 480분선 지지 {hold}분 옆걸음", sig_ck480(b, inf, m480, hold=hold), X480)
        go("[15-4] 오전 +10%↑ → 480분선 30분 지지 → 240분선 돌파", sig_480_240(b, inf, m480, m240),
           [("손절 −2% · 익절 +3% (책 1~3%)", dict(stop=lambda p: p * 0.98, tp=lambda p: p * 1.03)),
            ("손절 −2% · 익절 +1%", dict(stop=lambda p: p * 0.98, tp=lambda p: p * 1.01))])
        # 13-3 9:40 고점 (테마주: 09:30 에 +10%↑)
        j930 = next((j for j in range(k0, len(b["ts"])) if b["ts"][j].time() >= time(9, 30)), None)
        if j930 is not None and c[j930] / inf["pc"] - 1 >= 0.10 and c[j930] / inf["pc"] - 1 < 0.29:
            reg = [j for j in range(k0, len(b["ts"]))]
            hi_j = max(reg, key=lambda j: b["h"][j])
            FACT["09:30 +10%↑ 종목"].append(dict(hi_by_945=b["ts"][hi_j].time() <= time(9, 45), hi_by_1000=b["ts"][hi_j].time() <= time(10, 0),
                                               r940_close=c[reg[-1]] / c[min(j930 + 10, reg[-1])] - 1))


def stats(tr, title):
    if len(tr) < 10:
        print(f"   {title:44s} {len(tr):4d}건 (적음)")
        return
    v = np.array([t[1] for t in tr])
    half = sorted(d for d, _, _ in tr)[len(tr) // 2]
    a = [x for d, x, _ in tr if d < half]; bb = [x for d, x, _ in tr if d >= half]
    bd = defaultdict(float)
    for d, x, _ in tr:
        bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    w = v[v > 0]; ls = v[v <= 0]
    pf = (w.mean() / -ls.mean()) if len(w) and len(ls) and ls.mean() < 0 else float("nan")
    ok = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    reg = defaultdict(list)
    for d, x, _ in tr:
        reg[REG.get(d, "?")].append(x)
    rs = " ".join(f"{k} {np.mean(reg[k]):+.2%}({len(reg[k])})" for k in ("U", "N+", "N-", "D") if reg[k])
    print(f"  {ok}{title:44s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} (비용 전 {v.mean() + COST:+.2%}) 합계 {v.sum() * 100:+5.0f}만 "
          f"최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만 승률 {len(w) / len(v):.0%} 손익비 {pf:.2f} | 앞 {np.mean(a):+.2%} 뒤 {np.mean(bb):+.2%} | 낙폭 {mdd * 100:.0f}만"
          f" | 분위기 {rs}")


if __name__ == "__main__":
    for i, d in enumerate(DAYS[:-1]):
        run_day(d)
        if i % 20 == 0:
            print(d, file=sys.stderr, flush=True)
    print(f"강창권 1분봉 기법 백테스트 — {DAYS[0]} ~ {DAYS[-2]}, 다음 봉 시가 매수, 비용 0.25%, 건당 100만. ★ = 앞·뒤 반 모두 + 이고 최고 5일 빼도 +")
    print("\n### 책 주장 확인")
    for tag, rows in FACT.items():
        n = len(rows)
        if tag.startswith("갭"):
            t4 = [r["t904"] for r in rows if r["t904"] is not None]
            print(f"  {tag}: {n}건 | 09:10 안에 시초가 아래로 눌림 {np.mean([r['dip'] for r in rows]):.0%} (책 90%)"
                  f" | 그날 고가가 09:03 안 {np.mean([r['top3'] for r in rows]):.0%} (책 '열에 아홉은 시초가가 고점')"
                  f" | 15:29 종가 < 시초가 {np.mean([r['below_close'] for r in rows]):.0%}"
                  f" | 09:04 봉 종가 < 시초가일 때 종가도 시초가 아래 "
                  f"{np.mean([r['below_close'] for r in rows if r['t904']]) if any(t4) else 0:.0%} (책 99%, {sum(t4)}건)")
        else:
            print(f"  {tag}: {n}건 | 그날 고가가 09:45 안 {np.mean([r['hi_by_945'] for r in rows]):.0%}, 10:00 안 {np.mean([r['hi_by_1000'] for r in rows]):.0%}"
                  f" | 09:40 에 사서 15:29 종가까지 평균 {np.mean([r['r940_close'] for r in rows]):+.2%} (책: 09:40 이후 추격 금지)")
    last = None
    for (name, xn) in sorted(TR, key=lambda k: k[0]):
        if name != last:
            print(f"\n=== {name}")
            last = name
        stats(TR[(name, xn)], xn)
