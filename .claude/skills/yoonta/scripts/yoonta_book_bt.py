"""윤타 『주식 단타 특공대』 책 전체 규칙 1분봉 백테스트 v2 (2025-10-16 ~ 2026-10-22).

책의 매매 규칙을 쪽수별로 모두 목록(R01~R53, 스킬 yoonta 7장)으로 만들고, 자료가 있는 것은 전부 넣었다.
v1(yoonta_minute_bt.py)에서 빠졌거나 다르게 정의한 것: 지지저항 타점·분할 매수, 저돌 뒤 되돌림 지지, 전고점(가장 최근 고점)·
'오랫동안 저항' 구간, 변비 1분봉(9~10시)·변비+VI, 상승장 지수 +1% 대장주, 하락·횡보장 사이드 테마 대장주, 주도 테마(대금 상위 30 중 3종목↑)·
주도 테마 없는 날 쉼·장전 3~5종목, 책의 시장 정의(1개월 지수 추세·이전 저점·상승/하락 종목 수, 종목 시장별 지수), 반반이 '다음 저항에서 절반',
시간대별 4선(9~10시 1분봉, 10시 이후 3분봉), 기계 손절 3쌍, 김보선 손절·물타기, 책의 '15:00 당일 정리'(194쪽).

자료·체결은 v1 과 같다 (그 시각에 아는 정보로만 대상 선택, 전날 대금 200위 안, 다음 봉 시가 매수, 비용 0.25%, 건당 100만, 상한가 근처 매수 제외).
매도 끝 처리 두 가지를 나란히 보여 준다:
  · 기본 (메모리 backtest-exit-rules): 15:19 까지 아무것도 안 걸리면 다음 날 시가
  · 책 원칙 (194쪽 '장 마감 30분 전부터 손절이든 익절이든 결론', 당일 청산): 15:00 봉 시가에 정리

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_book_bt.py --kang-cached > data/yoonta/book_bt.txt
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime, time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import yoonta_minute_bt as Y  # noqa: E402

dm, COST, T_END = Y.dm, Y.COST, Y.T_END
T15 = time(15, 0)
MARKET = dict(dm.execute("SELECT code, market FROM stocks").fetchall())
SECTOR = dict(dm.execute("SELECT code, sector FROM stocks").fetchall())
# 책 154쪽 '무거운 메인 섹터'(반도체·조선·2차전지·제약/바이오·엔터·건설·방산·원자력)를 키움 업종으로 대신 (거친 근사)
MAIN_SECTORS = {"전기/전자", "운송장비/부품", "화학", "제약", "의료/정밀기기", "오락/문화", "건설", "기계/장비", "전기/가스"}


# ------------------------------------------------------------------ 시장 (책 11·31·125·151~153쪽)
def book_regimes():
    """책 정의를 숫자로: 상승장 = 1개월(20거래일) 지수 상승 + 고점을 높임 + 상승 종목 > 하락 종목,
    하락장 = 이전 저점을 깸(최근 20일 저가 < 그 앞 20~60일 저가) + 1개월 하락, 나머지 횡보. 모두 전날까지 자료 (장 전에 앎).
    시장별(코스피 001 / 코스닥 101). 상승·하락 종목 수는 그 시장 일봉으로 센다."""
    ix = duckdb_index()
    out = {}
    for mk, code in (("KOSPI", "001"), ("KOSDAQ", "101")):
        rows = ix.execute("SELECT date, high, low, close FROM idx_daily WHERE code=? ORDER BY date", [code]).fetchall()
        br = dict(dm.execute("""SELECT d.date, sum(CASE WHEN d.close > p.close THEN 1 WHEN d.close < p.close THEN -1 ELSE 0 END)
                                FROM daily_ohlcv d JOIN stocks s USING (code)
                                JOIN (SELECT code, date, lag(close) OVER (PARTITION BY code ORDER BY date) AS close FROM daily_ohlcv) p
                                  ON p.code = d.code AND p.date = d.date
                                WHERE s.market = ? AND d.date >= '2025-06-01' GROUP BY 1""", [mk]).fetchall())
        ds = [r[0] for r in rows]; h = np.array([r[1] for r in rows], float); lo = np.array([r[2] for r in rows], float)
        c = np.array([r[3] for r in rows], float)
        for i in range(61, len(ds)):
            d = ds[i]; k = i - 1                                   # 전날까지
            up = c[k] > c[k - 20] and h[k - 19:k + 1].max() > h[k - 39:k - 19].max() and \
                sum(br.get(x, 0) for x in ds[k - 19:k + 1]) > 0
            down = lo[k - 19:k + 1].min() < lo[k - 59:k - 19].min() and c[k] < c[k - 20]
            out[(mk, d)] = "상승장" if up else "하락장" if down else "횡보장"
    return out


def duckdb_index():
    import duckdb
    return duckdb.connect(Y._copy("index.duckdb"), read_only=True)


IXC = duckdb_index()
BREG = book_regimes()
IDX_MIN = defaultdict(dict)
for code, ts, cl in IXC.execute("SELECT code, ts, close FROM idx_min WHERE code IN ('001','101') AND ts::time <= TIME '15:30'").fetchall():
    IDX_MIN[(code, ts.date())][ts.time()] = cl
IDX_PC = {}
_rows = IXC.execute("SELECT code, date, close FROM idx_daily WHERE code IN ('001','101') ORDER BY code, date").fetchall()
for (c1, d1, x1), (c2, d2, x2) in zip(_rows, _rows[1:]):
    if c1 == c2:
        IDX_PC[(c2, d2)] = x1


def idx_ret(mk, d, t):
    code = "001" if mk == "KOSPI" else "101"
    m = IDX_MIN.get((code, d)); pc = IDX_PC.get((code, d))
    if not m or not pc:
        return None
    ks = [x for x in m if x <= t]
    return m[max(ks)] / pc - 1 if ks else None


# ------------------------------------------------------------------ 테마 (책 121~126쪽)
def components(codes, linked):
    par = {c: c for c in codes}

    def f(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for i, a in enumerate(codes):
        for b2 in codes[i + 1:]:
            if linked(a, b2):
                par[f(a)] = f(b2)
    g = defaultdict(list)
    for c in codes:
        g[f(c)].append(c)
    return [v for v in g.values() if len(v) >= 3]


def link_peer(graph):
    return lambda a, b: b in graph.get(a, {})


def link_sector(a, b):
    return SECTOR.get(a) is not None and SECTOR.get(a) == SECTOR.get(b)


# ------------------------------------------------------------------ 일봉 저항 (책 77·197·221·232쪽)
def daily_levels(p1, codes):
    """전날까지 120일 일봉 고가 → 20·60일 최고가, '오랫동안 저항'(60일 최고가 −2% 안에 2번↑ 닿고 그 사이 5일↑ 떨어짐),
    전고점 = 가장 최근 스윙 고점(앞뒤 2일보다 높은 고가) 중 전날 종가 위, 다음 저항 후보(스윙 고점 + 20·60·120일 최고가)."""
    ph = ",".join("?" * len(codes))
    rows = dm.execute(f"""SELECT code, date, high FROM daily_ohlcv WHERE code IN ({ph}) AND date <= ? AND date > ?::DATE - 200
                          ORDER BY code, date""", [*codes, p1, p1]).fetchall()
    by = defaultdict(list)
    for c, d, h in rows:
        by[c].append(h)
    out = {}
    for c, hs in by.items():
        h = np.array(hs[-120:], float)
        if len(h) < 60:
            continue
        h60 = h[-60:]; m60 = h60.max()
        touch = np.where(h60 >= m60 * 0.98)[0]
        zone = m60 if len(touch) >= 2 and touch[-1] - touch[0] >= 5 else None
        piv = [i for i in range(2, len(h) - 2) if h[i] > max(h[i - 2], h[i - 1], h[i + 1], h[i + 2])]
        if len(h) >= 3 and h[-1] > max(h[-3], h[-2]):
            piv.append(len(h) - 1)     # 전날 자체가 고점 (뒤 2일은 아직 모름) — 가장 최근 고점
        out[c] = dict(r20=h[-20:].max(), r60=m60, zone=zone, piv=sorted({float(h[i]) for i in piv}),
                      piv_last=[(i, float(h[i])) for i in piv], hi120=h.max() if len(h) >= 120 else None)
    return out


def prev_high_level(lv, pc):
    """가장 최근 스윙 고점 가운데 전날 종가 위인 것 (책 221쪽 '가장 최근에 주가가 고점을 찍었던 가격대')."""
    above = [(i, x) for i, x in lv["piv_last"] if x > pc]
    return max(above)[1] if above else None


def next_resistance(lv, price):
    xs = [x for x in lv["piv"] + [lv["r20"], lv["r60"]] + ([lv["hi120"]] if lv["hi120"] else []) if x >= price * 1.01]
    return min(xs) if xs else None


# ------------------------------------------------------------------ 체결·매도
def simulate(b, legs, nopen, stop=None, tps=(), trails=(), under=None, half_at=None, end15=False):
    """legs = [(비중, 진입봉)], 둘째 다리는 첫 다리가 아직 들고 있을 때 그 봉 시가에 추가 매수 (분할 매수).
    stop·tps(분할 익절 [(비중, 가격)])·half_at(반반이: 이 가격에 보유 절반 매도)은 첫 매수가 기준으로 미리 계산해 넘김.
    trails = 1분봉 배열들 (값 < 0 → 종가로 이탈 확인 → 다음 봉 시가 남은 물량 매도), under = 종가가 이 가격 아래면 이탈.
    end15 = 책 원칙: 15:00 봉 시가에 남은 물량 정리. 아니면 15:19 뒤 다음 날 시가.
    돌려줌: (전체 자금 대비 수익률, 매도 시각 또는 None=다음 날)."""
    o, h, l, c, tm = b["o"], b["h"], b["l"], b["c"], b["tm"]
    legs = [(f, e) for f, e in legs if e is not None and e < len(tm) and tm[e] <= T_END and b["ts"][e].date() == b["ts"][-1].date()]
    if not legs:
        return None, None
    e0 = legs[0][1]
    held = 0.0; cost = 0.0; pnl = 0.0; done = [False] * len(tps); half_done = False
    pending = list(legs)
    n = len(c)
    for j in range(e0, n):
        if end15 and tm[j] >= T15:
            return (pnl + held * o[j] - cost) - COST * (cost > 0), tm[j]
        if tm[j] > T_END:
            break
        while pending and pending[0][1] == j:
            f, _ = pending.pop(0)
            if j > e0 and held <= 1e-12:
                pending = []
                break
            held += f / o[j]; cost += f
        if held <= 1e-12 and not pending:
            break
        if stop and l[j] <= stop:
            px = min(o[j], stop)
            return pnl + held * px - cost - COST, tm[j]
        for i, (f, p) in enumerate(tps):
            if not done[i] and h[j] >= p:
                q = min(held, f * held / max(1e-12, 1 - sum(ff for (ff, _), dd in zip(tps, done) if dd)))
                pnl += q * max(o[j], p); held -= q; done[i] = True
        if half_at and not half_done and h[j] >= half_at:
            q = held / 2; pnl += q * max(o[j], half_at); held -= q; half_done = True
        if held <= 1e-12:
            return pnl - cost - COST, tm[j]
        brk = any(t[j] < 0 for t in trails) or (under is not None and c[j] < under)
        if brk and j + 1 < n and tm[j + 1] <= T_END:
            return pnl + held * o[j + 1] - cost - COST, tm[j + 1]
    if cost == 0:
        return None, None
    if not nopen:
        return None, None
    return pnl + held * nopen - cost - COST, None


# ------------------------------------------------------------------ 신호 (진입 1분봉 번호)
def sig_jeodol(b, inf, R, start=time(9, 0), end=time(9, 59), filt=None, vx=3.0):
    k0 = b["k0"]
    if R is None or b["o"][k0] >= R or R > inf["pc"] * 1.25:
        return None
    for j in range(k0, len(b["tm"])):
        t = b["tm"][j]
        if t > end:
            return None
        if b["c"][j] > R:
            if t < start or b["v"][j] < vx * max(b["pvm"], 1) or (filt is not None and not filt[j]):
                return None
            return j + 1
    return None


def sig_retest(b, inf, R, end=time(10, 29)):
    """[R07·R40] 저돌 뒤 되돌림: 저항을 거래량과 뚫은 뒤(sig_jeodol), 다시 저항까지 눌려(저가 ≤ R × 1.005) 종가는 R 위 = 지지로 바뀜 확인
    → 다음 봉 종가가 그 봉 고가 위면 매수. 저항 아래 종가가 나오면 속임수 돌파로 보고 신호 없음."""
    e = sig_jeodol(b, inf, R)
    if e is None:
        return None
    for j in range(e, len(b["tm"]) - 1):
        if b["tm"][j] > end:
            return None
        if b["c"][j] < R:
            return None
        if b["l"][j] <= R * 1.005:
            for k in range(j + 1, min(j + 6, len(b["tm"]))):
                if b["c"][k] < R:
                    return None
                if b["c"][k] > b["h"][k - 1]:
                    return k + 1
            return None
    return None


def sig_support_bounce(b, inf, start=time(9, 5), end=time(9, 59), tol=0.005, gap=5):
    """[R07·R29] 지지저항 타점(분봉): 당일 저가가 같은 구간(±0.5%)에서 2번 반등(사이 5봉↑)한 자리 = 지지선 →
    세 번째로 내려와 그 구간에서 버티고 종가가 직전 봉 고가 위 → 1차 매수. 지지 가격도 돌려줌."""
    k0 = b["k0"]; lows = []
    for j in range(k0 + 2, len(b["tm"]) - 1):
        t = b["tm"][j]
        if t > end:
            return None, None
        # 바로 앞 봉이 국지 저점(앞뒤 2봉보다 낮음)이면 기록
        i = j - 1
        if i - 2 >= k0 and b["l"][i] < min(b["l"][i - 2], b["l"][i - 1], b["l"][j]):
            lows.append((i, b["l"][i]))
        if len(lows) >= 3 and t >= start:
            (i1, a1), (i2, a2), (i3, a3) = lows[-3], lows[-2], lows[-1]
            sup = min(a1, a2)
            if abs(a1 - a2) <= sup * tol and i2 - i1 >= gap and i3 - i2 >= gap and sup * (1 - tol) <= a3 <= sup * (1 + tol) \
                    and i3 == j - 1 and b["c"][j] > b["h"][i3]:
                return j + 1, sup
    return None, None


def sig_open_support(b, inf, start=time(9, 5), end=time(9, 59), above=5):
    """[R39·R43 두산중공업 '시가를 지켜줌'] 시가 위에서 움직이던(직전 5봉 종가 모두 시가 위) 종목이 시가까지 눌렸다가(저가 ≤ 시가 × 1.003)
    종가가 시가 위 → 다음 봉."""
    k0 = b["k0"]; op = b["o"][k0]; run = 0
    for j in range(k0, len(b["tm"])):
        t = b["tm"][j]
        if t > end:
            return None
        if run >= above and t >= start and b["l"][j] <= op * 1.003 and b["c"][j] >= op:
            return j + 1
        run = run + 1 if b["l"][j] > op * 1.003 else 0
    return None


def sig_byeonbi(g, inf, m15, m20, start, end, mode, need=0.05):
    """[R30] 변비타점 (v1 과 같은 정의, 분봉 단위를 바꿔 씀). 돌려줌: (신호 분봉 번호, 뭉침 고점 또는 None)."""
    pc = inf["pc"]; hi = 0.0
    for k in np.where(g["today"])[0]:
        t = g["tm"][k]
        hi = max(hi, g["h"][k] / pc - 1)
        if t > end:
            return None, None
        if t < start or np.isnan(m20[k]) or hi < need or m15[k] < m20[k]:
            continue
        if mode == "touch":
            if g["l"][k] <= m20[k] * 1.003 and g["c"][k] >= m20[k] and g["c"][k] <= m15[k] * 1.01:
                return k, float(max(g["h"][max(0, k - 3):k + 1]))
        elif k >= 3 and g["today"][k - 3]:
            s = slice(k - 3, k)
            if (g["l"][s] >= m20[s] * 0.995).all() and (g["c"][s] <= m15[s] * 1.01).all() and (g["c"][s] >= m20[s]).all() \
                    and g["c"][k] > g["h"][s].max():
                return k, None
    return None, None


def second_leg_above(b, e, level, bars=10):
    """분할 매수 둘째 다리 (책 173쪽 '50주 먼저 사고 추가 확인 후 나머지'): e 뒤 bars 봉 안에 종가가 level 위 → 다음 봉."""
    if e is None or level is None:
        return None
    for j in range(e, min(e + bars, len(b["c"]) - 1)):
        if b["c"][j] > level:
            return j + 1
    return None


def leg_kimbo(b, e, kimbo_ff, bars=60):
    """물타기 둘째 다리 (256~257쪽: 현금이 남아 있으면 김보선이 마지막 물타기 자리): e 뒤 저가가 3분봉 120선에 닿으면 그 다음 봉."""
    if e is None:
        return None
    for j in range(e, min(e + bars, len(b["c"]) - 1)):
        if not np.isnan(kimbo_ff[j]) and b["l"][j] <= kimbo_ff[j]:
            return j + 1
    return None


def sig_vi_after_byeonbi(b, k_last, end=time(10, 30)):
    """[R33] 변비타점 뒤 VI(정적 VI 근사: 시가 대비 +10% 고가) → 2분 단일가 끝난 뒤(2봉 뒤) 매수."""
    if k_last is None:
        return None
    op = b["o"][b["k0"]]
    for j in range(k_last + 1, len(b["tm"]) - 3):
        if b["tm"][j] > end:
            return None
        if b["h"][j] >= op * 1.10:
            return j + 2
    return None


def sig_vol_pullback(g, start, end, vx=3.0):
    """[R09] 87쪽 문장 (v1 과 같은 정의). 돌려줌 (분봉 번호, 지지=양봉 시가)."""
    for k in np.where(g["today"])[0]:
        t = g["tm"][k]
        if t > end:
            return None, None
        if t < start or k < 20 or g["o"][k] <= 0:
            continue
        if not (g["v"][k] >= vx * g["v"][k - 20:k].mean() and g["c"][k] / g["o"][k] - 1 >= 0.02):
            continue
        sup = g["o"][k]; pulls = 0
        for m in range(k + 1, min(k + 15, len(g["c"]))):
            if not g["today"][m] or g["tm"][m] > end or g["l"][m] < sup or g["v"][m] >= 0.5 * g["v"][k]:
                break
            if pulls >= 2 and g["c"][m] > g["h"][m - 1]:
                return m, sup
            pulls += 1
    return None, None


def sig_second_wave10(b, g10, inf, theme_ok):
    """[R24] 10시 이후 2차 상승: 09~10시 고가 +10%↑, 10분봉으로 10:00 뒤 저점을 깨지 않고(각 10분봉 저가 ≥ 10:00 뒤 첫 저점),
    10~10:59 대금이 09~09:59 대금의 30%↑ 유지, 10분봉 종가가 직전 10분봉 고가 위 → 다음 1분봉 (10:20~11:30). 저점도 돌려줌."""
    pc = inf["pc"]; k0 = b["k0"]
    j10 = Y.first_from(b, time(10, 0))
    if j10 is None or b["h"][k0:j10].max() / pc - 1 < 0.10 or not theme_ok:
        return None, None
    v9 = float((b["c"][k0:j10] * b["v"][k0:j10]).sum())
    idx = [k for k in np.where(g10["today"])[0] if g10["tm"][k] >= time(10, 0)]
    if len(idx) < 2:
        return None, None
    L = g10["l"][idx[0]]
    for a, k in zip(idx, idx[1:]):
        t = g10["tm"][k]
        if t > time(11, 30):
            return None, None
        if g10["l"][k] < L:
            return None, None
        jl = g10["last"][k]
        v10 = float((b["c"][j10:jl + 1] * b["v"][j10:jl + 1]).sum())
        if t >= time(10, 10) and g10["c"][k] > g10["h"][a] and v10 >= 0.3 * v9 * (jl + 1 - j10) / 60 and g10["c"][k] / pc - 1 >= 0.05:
            return jl + 1, float(L)
    return None, None


def sig_bundol(b, inf, start=time(9, 10), end=time(9, 59)):
    return Y.sig_bundol(b, inf, start=start, end=end)


def sig_open_reclaim(b, inf, start=time(9, 5)):
    return Y.sig_open_reclaim(b, inf, start=start)


# ------------------------------------------------------------------ 실행
TR = defaultdict(list)   # (기법, 대상, 매도, 끝처리) → [(날짜, 수익, 코드, 진입시각, 매도시각, 책 시장, 당일 지수 +1%↑)]
FACT = defaultdict(list)
GRAPH = {}


def run_day(d):
    info, p1, p2 = Y.day_info(d)
    want = [c for c, x in info.items() if x["rk"] <= 200 or x["gap"] >= 0.03 or x["pchg"] >= 0.15 or x["hi"] >= 0.15]
    bars = Y.load_bars(d, p1, p2, want)
    graph = GRAPH.get(d) or {}
    lv_all = daily_levels(p1, [c for c in bars if info[c]["rk"] <= 200])
    lp = link_peer(graph)

    # ---- 장전 주도 테마 (R15): 전날 대금 상위 30 중 전날 오른 종목, 3종목↑ 묶이면 주도 테마
    top30 = [c for c, x in info.items() if x["rk"] <= 30 and x["pchg"] > 0]
    pre = {"평소 함께": components(top30, lp), "같은 업종": components(top30, link_sector)}
    pre_members = {k: {c for comp in v for c in comp} for k, v in pre.items()}
    FACT["pre_theme_days"].append({k: bool(v) for k, v in pre.items()})
    book = sorted([c for c, x in info.items() if x["book"] and c in bars], key=lambda c: info[c]["rk"])
    universes = {"책 대상": set(book), "책 대상 대금 상위 5": set(book[:5])}
    for k in pre:
        picks = [c for c in book if c in pre_members[k]][:5]
        universes[f"장전 3~5종목 (책 대상 ∩ 주도 테마·{k})"] = set(picks)
        universes[f"책 대상 · 장전 주도 테마({k}) 있는 날만"] = set(book) if pre[k] else set()

    # ---- 당일 09:10 주도 테마 (R15·R20·R22·R23): 그 시각 누적 대금 상위 30 중 오른 종목, 3종목↑ 묶음, 대장 = 상승률 1위
    def live_theme(t, link):
        st = []
        for c, b in bars.items():
            j = max((i for i in range(b["k0"], len(b["tm"])) if b["tm"][i] <= t), default=None)
            if j is None:
                continue
            st.append((Y.value_until(b, j), c, b["c"][j] / info[c]["pc"] - 1))
        st.sort(reverse=True)
        top = [c for v, c, r in st[:30] if r > 0]
        rr = {c: r for v, c, r in st}
        comps = components(top, link)
        return [(max(comp, key=lambda c: rr[c]), comp, rr) for comp in comps]

    live = {"평소 함께": live_theme(time(9, 10), lp), "같은 업종": live_theme(time(9, 10), link_sector)}
    lead_univ = {}
    for k, lst in live.items():
        leaders = {ld for ld, comp, rr in lst if info[ld]["rk"] <= 200}
        lead_univ[f"09:10 주도 테마 대장주({k})"] = leaders
        side = set()
        for ld, comp, rr in lst:
            if info[ld]["rk"] <= 200 and SECTOR.get(ld) not in MAIN_SECTORS:
                side.add(ld)
        lead_univ[f"09:10 사이드 테마 대장주({k}, 메인 섹터 제외)"] = side

    cache = {}

    def prep(code):
        if code in cache:
            return cache[code]
        b = bars[code]; c = b["c"]
        g3 = Y.agg(b, 3); g5 = Y.agg(b, 5); g10 = Y.agg(b, 10)
        m4_1 = c - Y.ma(c, 4)
        d4_3 = Y.on_grid(b, g3, g3["c"] - Y.ma(g3["c"], 4))
        tt = np.where(np.array([t < time(10, 0) for t in b["tm"]]), m4_1, d4_3)   # 9~10시 1분봉, 10시 뒤 3분봉 (174~175·188쪽)
        m120_3 = Y.ma(g3["c"], 120)
        kim = Y.on_grid(b, g3, g3["c"] - m120_3)
        kim_ff = np.full(len(c), np.nan); cur = np.nan
        for i, x in enumerate(Y.on_grid(b, g3, m120_3)):
            if not np.isnan(x):
                cur = x
            kim_ff[i] = cur
        dmk = Y.on_grid(b, g5, Y.demark_ok(g5).astype(float))
        ok5 = np.zeros(len(c), bool); cur = False
        for j in range(len(c)):
            if not np.isnan(dmk[j]):
                cur = dmk[j] > 0
            ok5[j] = cur
        m20_3 = Y.ma(g3["c"], 20)
        x = dict(g3=g3, g10=g10, m4_1=m4_1, d4_3=d4_3, tt=tt, kim=kim, kim_ff=kim_ff, ok5=ok5,
                 m15_1=Y.ma(c, 15), m20_1=Y.ma(c, 20), m15_3=Y.ma(g3["c"], 15), m20_3=m20_3,
                 d20_3=Y.on_grid(b, g3, g3["c"] - m20_3), d20_1=c - Y.ma(c, 20))
        cache[code] = x
        return x

    def exits(code, buy, extra=()):
        """책 5장·3장의 매도 전부 + 비교용 두 가지. buy = 첫 매수가."""
        P = prep(code); lv = lv_all.get(code)
        nr = next_resistance(lv, buy) if lv else None
        X = [("[R26] 익절 +1% · 손절 −2% (자동 주문)", dict(stop=buy * 0.98, tps=[(1, buy * 1.01)])),
             ("[R45] 123 분할 · 손절 −2%", dict(stop=buy * 0.98, tps=[(1 / 3, buy * 1.01), (1 / 3, buy * 1.02), (1 / 3, buy * 1.03)])),
             ("[R49] 기계 손절 +1% / −0.5%", dict(stop=buy * 0.995, tps=[(1, buy * 1.01)])),
             ("[R49] 기계 손절 +2% / −1%", dict(stop=buy * 0.99, tps=[(1, buy * 1.02)])),
             ("[R49] 기계 손절 +3% / −1.5%", dict(stop=buy * 0.985, tps=[(1, buy * 1.03)])),
             ("[R46] 4턴4꺾 (9~10시 1분봉·뒤 3분봉 4선) · 손절 −2%", dict(stop=buy * 0.98, trails=(P["tt"],))),
             ("[R46] 4턴4꺾 3분봉 4선 (초보 매뉴얼) · 손절 −2%", dict(stop=buy * 0.98, trails=(P["d4_3"],))),
             ("[R47] 반반이: 다음 일봉 저항에서 절반 · 나머지 4턴4꺾 · 손절 −2%", dict(stop=buy * 0.98, half_at=nr, trails=(P["tt"],))),
             ("[R47] 반반이: +5% 절반 · 나머지 4턴4꺾 · 손절 −2% (261쪽)", dict(stop=buy * 0.98, half_at=buy * 1.05, trails=(P["tt"],))),
             ("[R50] 김보선: 3분봉 120선 종가 이탈 손절 · 4턴4꺾 익절", dict(trails=(P["kim"], P["tt"]))),
             ("[R39] 시가 이탈(시가 −0.5%) 손절 · 4턴4꺾", dict(stop=bars[code]["o"][bars[code]["k0"]] * 0.995, trails=(P["tt"],))),
             ("(책에 없음·비교) 손절 −3% · 익절 +5%", dict(stop=buy * 0.97, tps=[(1, buy * 1.05)])),
             ("(책에 없음·비교) 손절 −3% · 익절 +10%", dict(stop=buy * 0.97, tps=[(1, buy * 1.10)]))]
        return X + list(extra)

    def go(name, univ, code, legs, extra=(), minval=1e9):
        b = bars[code]; inf = info[code]
        legs = [(f, e) for f, e in legs]
        e0 = legs[0][1]
        if e0 is None or e0 >= len(b["tm"]) or b["tm"][e0] > T_END or b["ts"][e0].date() != d or Y.value_until(b, e0 - 1) < minval:
            return
        if time(12, 0) <= b["tm"][e0] < time(13, 0):        # R27 점심 새 진입 안 함
            return
        buy = b["o"][e0]
        if buy >= inf["pc"] * 1.285:
            return
        mk = MARKET.get(code)
        breg = BREG.get((mk, d), "?")
        ir = idx_ret(mk, d, b["tm"][e0])
        for xn, kw in exits(code, buy, extra):
            for end15 in (False, True):
                r, tx = simulate(b, legs, inf["nopen"], end15=end15, **kw)
                if r is not None:
                    TR[(name, univ, xn, "15:00 정리(책)" if end15 else "다음 날 시가")].append(
                        (d, r, code, b["tm"][e0], tx, breg, ir is not None and ir >= 0.01))

    all_univ = dict(universes); all_univ.update(lead_univ)
    in_any = set().union(*all_univ.values()) if all_univ else set()
    for code in in_any:
        if code not in bars or info[code]["rk"] > 200:
            continue
        b = bars[code]; inf = info[code]; k0 = b["k0"]
        if b["tm"][k0] > time(9, 5):
            continue
        P = prep(code); lv = lv_all.get(code)
        unis = [u for u, s in all_univ.items() if code in s]
        lead_only = all(u.startswith("09:10") for u in unis)
        st0 = time(9, 10) if lead_only else time(9, 0)
        for u in unis:
            st = time(9, 10) if u.startswith("09:10") else time(9, 0)
            # ---- 저돌 (R36·R40·R37·R43·R48)
            if lv:
                pc = inf["pc"]
                levels = [("20일 최고가", lv["r20"]), ("60일 최고가", lv["r60"]), ("오랫동안 저항(60일 고점 2번↑)", lv["zone"]),
                          ("전고점(가장 최근 고점)", prev_high_level(lv, pc))]
                for ln, R in levels:
                    e = sig_jeodol(b, inf, R, start=st)
                    go(f"[R36] 저돌 {ln} 09:00~10:00", u, code, [(1, e)],
                       [("[R40] 속임수 돌파(종가 < 저항) 매도 · 손절 −2%", dict(stop=None if e is None else b["o"][min(e, len(b['o']) - 1)] * 0.98, under=R))])
                    if e is not None:
                        if inf["gap"] < 0.10:
                            go(f"[R36+R43] 저돌 {ln} · 시가 +10% 갭 제외", u, code, [(1, e)])
                        nr = next_resistance(lv, b["o"][min(e, len(b['o']) - 1)])
                        if nr is None or nr >= b["o"][min(e, len(b['o']) - 1)] * 1.03:
                            go(f"[R36] 저돌 {ln} · 다음 저항까지 3%↑ (손익비 확인)", u, code, [(1, e)])
                        go(f"[R36+R37] 저돌 {ln} · 5분봉 막시무스 High 위", u, code, [(1, sig_jeodol(b, inf, R, start=st, filt=P["ok5"]))])
                    if u == "책 대상" and ln in ("20일 최고가", "전고점(가장 최근 고점)"):
                        go(f"[비교] 저돌 {ln} 10:00~15:00 (알람형)", u, code, [(1, sig_jeodol(b, inf, R, start=time(10, 0), end=time(15, 0)))])
                    e2 = sig_retest(b, inf, R)
                    go(f"[R07·R40] 저돌 {ln} 뒤 되돌림 지지(저항→지지) 매수", u, code, [(1, e2)],
                       [("[R07] 지지(저항선) −1% 이탈 손절 · 4턴4꺾", dict(stop=None if R is None else R * 0.99, trails=(P["tt"],)))])
            # ---- 분돌 (R41)
            go("[R41] 분돌 당일 고점 재돌파 (+5%↑)", u, code, [(1, sig_bundol(b, inf, start=max(st, time(9, 10))))])
            # ---- 시가 (R39·R43)
            go("[R39] 시가 아래 5봉 → 시가 돌파", u, code, [(1, sig_open_reclaim(b, inf, start=max(st, time(9, 5))))])
            go("[R39] 시가 위 5봉 → 시가까지 눌림 후 지지", u, code, [(1, sig_open_support(b, inf, start=max(st, time(9, 5))))])
            # ---- 지지저항 타점 (R29·R07·R53): 1차 50% → 직전 고점 위 종가에 2차 50%, 지지 −1% 손절
            e, sup = sig_support_bounce(b, inf, start=max(st, time(9, 5)))
            if e is not None:
                lvl = float(b["h"][max(k0, e - 15):e].max())
                xs = [("[R07] 지지 −1% 이탈 손절 · 반반이(다음 일봉 저항)·4턴4꺾", dict(stop=sup * 0.99, half_at=next_resistance(lv, b["o"][e]) if lv else None, trails=(P["tt"],)))]
                go("[R29] 지지저항 타점: 분봉 지지 3번째 반등 · 한 번에 매수", u, code, [(1, e)], xs)
                go("[R29+R53] 지지저항 타점: 50% → 직전 고점 위에서 50% (분할)", u, code, [(0.5, e), (0.5, second_leg_above(b, e, lvl))], xs)
                if P["ok5"][e - 1]:
                    go("[R29+R37] 지지저항 타점 · 5분봉 막시무스 High 위", u, code, [(1, e)], xs)
            # ---- 변비타점 (R30·R31·R33·R50): 9~10시 1분봉(책 174쪽) / 3분봉(초보·10시 뒤)
            for unit, g, m15, m20, dd in (("1분봉", None, P["m15_1"], P["m20_1"], P["d20_1"]), ("3분봉", P["g3"], P["m15_3"], P["m20_3"], P["d20_3"])):
                if unit == "1분봉":
                    g1 = dict(o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"], last=np.arange(len(b["c"])),
                              today=b["dates"] == d, tm=b["tm"])
                    gg = g1
                else:
                    gg = g
                for mode, lab in (("touch", "20선 터치 지지"), ("squeeze", "15~20선 뭉침 뒤 돌파")):
                    k, hi = sig_byeonbi(gg, inf, m15, m20, start=st, end=time(9, 59), mode=mode)
                    e = int(gg["last"][k]) + 1 if k is not None else None
                    xs = [("[R30] 20선 이탈 손절 · 4턴4꺾", dict(trails=(dd, P["tt"])))]
                    go(f"[R30] 변비 {unit} {lab} 09:00~10:00", u, code, [(1, e)], xs)
                    if mode == "touch" and e is not None:
                        go(f"[R30+R53] 변비 {unit} {lab} · 50% → 뭉침 고점 위 50% (분할)", u, code,
                           [(0.5, e), (0.5, second_leg_above(b, e, hi, 20))], xs)
                        go(f"[R30+R50] 변비 {unit} {lab} · 50% → 김보선 닿으면 50% 물타기 (김보선 이탈 손절)", u, code,
                           [(0.5, e), (0.5, leg_kimbo(b, e, P["kim_ff"]))],
                           [("[R50] 김보선 이탈 손절 · 4턴4꺾", dict(trails=(P["kim"], P["tt"])))])
                        if P["ok5"][e - 1]:
                            go(f"[R30+R37] 변비 {unit} {lab} · 5분봉 막시무스 High 위", u, code, [(1, e)], xs)
                        go(f"[R33] 변비 {unit} {lab} 뒤 VI(시가 +10%) → 해제 후 매수", u, code, [(1, sig_vi_after_byeonbi(b, e - 1))])
                    if mode == "touch" and lv and k is not None:
                        # R31: 지지저항 + 변비 겹침 — 20선 터치 자리가 일봉 저항(20일 고가)·시가 ±1% 안
                        lvls = [lv["r20"], b["o"][k0]]
                        px = float(gg["l"][k])
                        if any(abs(px / x - 1) <= 0.01 for x in lvls if x):
                            go(f"[R31] 변비 {unit} + 지지(일봉 저항·시가) 겹침", u, code, [(1, e)], xs)
            # ---- 87쪽 거래량 눌림 (R09) 1분봉·3분봉
            for unit, g in (("1분봉", dict(o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"], last=np.arange(len(b["c"])),
                                          today=b["dates"] == d, tm=b["tm"])), ("3분봉", P["g3"])):
                k, sup = sig_vol_pullback(g, start=st, end=time(10, 29))
                e = int(g["last"][k]) + 1 if k is not None else None
                go(f"[R09] 87쪽 거래량 양봉 → 거래량 줄며 눌림 → 지지 확인 ({unit})", u, code, [(1, e)],
                   [("[R07] 양봉 시가(지지) −1% 이탈 손절 · 4턴4꺾", dict(stop=None if sup is None else sup * 0.99, trails=(P["tt"],)))])
            # ---- 10시 이후 2차 상승 (R24·R25)
            theme_ok = any(code in comp for k_ in live for ld, comp, rr in live[k_])
            e, L = sig_second_wave10(b, P["g10"], inf, theme_ok)
            go("[R24] 10시 이후 2차 상승 (10분봉 저점 유지·대금 유지·09:10 주도 테마)", u, code, [(1, e)],
               [("[R24] 저점 이탈 손절 · 익절 +1% (자동 주문)", dict(stop=L, tps=[(1, (b["o"][e] if e and e < len(b['o']) else 1) * 1.01)]))])
            # ---- 종가배팅 (R44): 14:30~15:00 김보선 0~2% 위 지지 · 거래량 감소 · 그날 +3%↑ → 다음 봉 매수 → 다음 날 시가
            if u == "책 대상" and inf["nopen"]:
                g3 = P["g3"]; m120 = Y.ma(g3["c"], 120)
                for k in np.where(g3["today"])[0]:
                    t = g3["tm"][k]
                    if t < time(14, 30) or t > time(14, 57):
                        continue
                    if np.isnan(m120[k]) or k < 30 or g3["c"][k] / inf["pc"] - 1 < 0.03:
                        continue
                    if m120[k] <= g3["l"][k] <= m120[k] * 1.02 and g3["c"][k] >= m120[k] and \
                            g3["v"][k - 9:k + 1].mean() < 0.7 * g3["v"][k - 30:k - 9].mean():
                        e = int(g3["last"][k]) + 1
                        # 다른 신호와 같은 체결 조건: 상한가 근처(+28.5%↑)는 줄 서 있어 못 삼, 그때까지 누적 대금 10억↑
                        if e < len(b["o"]) and b["o"][e] < inf["pc"] * 1.285 and Y.value_until(b, e - 1) >= 1e9:
                            r = inf["nopen"] / b["o"][e] - 1 - COST
                            TR[("[R44] 종가배팅: 14:30~15:00 김보선 지지·거래량 감소·+3%↑", u, "다음 날 시가", "다음 날 시가")].append(
                                (d, r, code, b["tm"][e], None, BREG.get((MARKET.get(code), d), "?"), False))
                        break

    # ---- 쌍쌍바 (R17): 대장 = 묶음(평소 함께) 안 상승률 1위가 +5% 를 넘는 순간 (그 1분 거래량 ≥ 전날 평균 × 3),
    #      2등 = 그 시각 묶음 안 상승률 2위 → 즉시(다음 봉) 매수. 2등이 불분명(1·2위 차 1%p 미만 또는 2등도 +5%↑)이면 안 함, 대장만 오르면(2등 ≤ 0%) 안 함.
    used = set()
    first5 = []
    for code, b in bars.items():
        inf = info[code]
        if not (inf["rk"] <= 200 or inf["gap"] >= 0.03):
            continue
        for j in range(b["k0"], len(b["tm"])):
            if b["tm"][j] > time(9, 59):
                break
            r = b["c"][j] / inf["pc"] - 1
            if r >= 0.05:
                if r < 0.29 and b["v"][j] >= 3 * max(b["pvm"], 1):
                    first5.append((b["tm"][j], code, r))
                break
    # 쌍쌍바 '미리 정해 둔 짝' (책 130~131쪽 관심종목 그룹: 천연가스 지에스이/중앙에너비스 등 테마마다 대장·2등을 미리 정리)
    # → 짝 = 평소 가장 가깝게 함께 움직인 종목 1개 (상관 0.5↑ 중 1위). 책 사례 오르비텍→우진엔텍(2025-06-23)이 상관 0.75 로 1위라 재현됨.
    used_pair = set()
    for t, lead, r in sorted(first5):
        cands = [(cv, p) for p, cv in graph.get(lead, {}).items() if cv >= 0.5 and p in bars and info[p]["rk"] <= 200]
        if not cands:
            continue
        cv, p = max(cands)
        bp = bars[p]
        j = max((i for i in range(bp["k0"], len(bp["tm"])) if bp["tm"][i] <= t), default=None)
        if j is None or (lead, p) in used_pair or p in used_pair:
            continue
        rp = bp["c"][j] / info[p]["pc"] - 1
        if not (0 <= rp < min(r, 0.05)):
            continue
        used_pair.add(p)
        e = j + 1
        if e >= len(bp["o"]):
            continue
        buy = bp["o"][e]
        ex = [("[R17] 고려→삼표 사례: 익절 +7% · 손절 −2%", dict(stop=buy * 0.98, tps=[(1, buy * 1.07)]))]
        go("[R17] 쌍쌍바 · 미리 정한 짝(가장 가깝게 함께 움직인 1종목, 상관 0.5↑)", "평소 함께 묶음", p, [(1, e)], ex, minval=5e8)
        if rp <= 0.03:
            go("[R17] 쌍쌍바 · 미리 정한 짝 · 2등이 아직 +3% 이하", "평소 함께 묶음", p, [(1, e)], ex, minval=5e8)

    for t, lead, r in sorted(first5):
        peers = graph.get(lead, {})
        rets = []
        top = True
        for p in peers:
            if p not in bars:
                continue
            bp = bars[p]
            j = max((i for i in range(bp["k0"], len(bp["tm"])) if bp["tm"][i] <= t), default=None)
            if j is None:
                continue
            rp = bp["c"][j] / info[p]["pc"] - 1
            if rp >= r:
                top = False; break
            rets.append((rp, p, j))
        if not top or not rets:
            continue
        rets.sort(reverse=True)
        rp, p, j = rets[0]
        strong = sum(1 for x in rets if x[0] >= 0.01) + 1 >= 3
        if rp <= 0 or rp >= 0.05 or (len(rets) > 1 and rp - rets[1][0] < 0.01) or info[p]["rk"] > 200 or p in used:
            continue
        used.add(p)
        cache_ok = p in bars
        if not cache_ok:
            continue
        ex = [("[R17] 고려→삼표 사례: 익절 +7% · 손절 −2%", dict(stop=None, tps=[]))]
        bp = bars[p]
        e = j + 1
        if e >= len(bp["o"]):
            continue
        buy = bp["o"][e]
        ex = [("[R17] 고려→삼표 사례: 익절 +7% · 손절 −2%", dict(stop=buy * 0.98, tps=[(1, buy * 1.07)]))]
        go("[R17] 쌍쌍바: 대장 +5%(거래량 급증) 순간 2등주 매수", "평소 함께 묶음", p, [(1, e)], ex, minval=5e8)
        if strong:
            go("[R17] 쌍쌍바 · 테마 강함(묶음 3종목↑ +1%↑)", "평소 함께 묶음", p, [(1, e)], ex, minval=5e8)
        if rp <= 0.03:
            go("[R17] 쌍쌍바 · 2등이 아직 +3% 이하 (책 '1~2%')", "평소 함께 묶음", p, [(1, e)], ex, minval=5e8)

    # ---- 상승장 지수 +1% 대장주 (R22): 종목 시장 지수가 09:00~09:59 처음 +1% 넘는 순간, 그 시각 주도 테마(평소 함께) 대장주 즉시 매수
    for mk, icode in (("KOSPI", "001"), ("KOSDAQ", "101")):
        m = IDX_MIN.get((icode, d)); pcx = IDX_PC.get((icode, d))
        if not m or not pcx:
            continue
        hit = next((t for t in sorted(m) if time(9, 1) <= t <= time(9, 59) and m[t] / pcx - 1 >= 0.01), None)
        if hit is None:
            continue
        for ld, comp, rr in live_theme(hit, lp):
            if MARKET.get(ld) != mk or info[ld]["rk"] > 200 or not (0 < rr[ld] < 0.285):
                continue
            b = bars[ld]
            j = max((i for i in range(b["k0"], len(b["tm"])) if b["tm"][i] <= hit), default=None)
            if j is not None:
                go(f"[R22] 지수 +1% 순간 주도 테마 대장주 즉시 매수 ({mk})", "평소 함께 묶음", ld, [(1, j + 1)])


def stats(tr, title):
    if len(tr) < 15:
        return None
    v = np.array([t[1] for t in tr])
    half = sorted(t[0] for t in tr)[len(tr) // 2]
    a = [t[1] for t in tr if t[0] < half]; bb = [t[1] for t in tr if t[0] >= half]
    bd = defaultdict(float)
    for t in tr:
        bd[t[0]] += t[1]
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[x] for x in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    w = v[v > 0]; ls = v[v <= 0]
    pf = (w.mean() / -ls.mean()) if len(w) and len(ls) and ls.mean() < 0 else float("nan")
    ok = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    rg = defaultdict(list)
    for t in tr:
        rg[t[5]].append(t[1])
    up1 = [t[1] for t in tr if t[6]]
    rs = " ".join(f"{k} {np.mean(rg[k]):+.2%}({len(rg[k])})" for k in ("상승장", "횡보장", "하락장") if rg[k])
    return (f"{ok}{title} {len(v)}건 {len(bd)}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+.0f}만 "
            f"손익비 {pf:.2f} 승률 {len(w) / len(v):.0%} | 앞 {np.mean(a):+.2%} 뒤 {np.mean(bb):+.2%} | 낙폭 {mdd * 100:.0f}만 | "
            f"책 시장 {rs} | 지수 +1%↑ 시각 {np.mean(up1) if up1 else float('nan'):+.2%}({len(up1)})"), v.mean()


if __name__ == "__main__":
    NDAYS = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else None
    for i, d in enumerate(Y.DAYS[:-1][:NDAYS]):
        if i % 20 == 0:
            GD = Y.build_peer_graph(d)
        GRAPH[d] = GD
        run_day(d)
        GRAPH.pop(d, None)
        if i % 20 == 0:
            print(d, file=sys.stderr, flush=True)
    pickle.dump(dict(TR), open(os.path.join(Y.OUT, "book_trades.pkl"), "wb"))
    days = Y.DAYS[:-1][:NDAYS]
    print(f"윤타 『주식 단타 특공대』 책 전체 규칙 1분봉 백테스트 v2 — {days[0]} ~ {days[-1]}, 다음 봉 시가 매수, 비용 0.25%, 건당 100만.")
    print("★ = 앞·뒤 반 모두 + · 최고 5일 빼도 +. 책 시장 = 1개월 지수 추세·이전 저점·상승/하락 종목 수(종목의 시장 지수, 장 전에 앎).")
    pt = FACT["pre_theme_days"]
    print(f"장전 주도 테마(전날 대금 상위 30 중 오른 종목 3개↑ 묶음)가 있던 날: 평소 함께 {np.mean([x['평소 함께'] for x in pt]):.0%}, "
          f"같은 업종 {np.mean([x['같은 업종'] for x in pt]):.0%} ({len(pt)}일)")
    reg_cnt = defaultdict(int)
    for (mk, d), r in BREG.items():
        if d in set(days):
            reg_cnt[(mk, r)] += 1
    print("책 시장 날 수:", ", ".join(f"{mk} {r} {n}일" for (mk, r), n in sorted(reg_cnt.items())))
    groups = defaultdict(list)
    for key in TR:
        groups[(key[0], key[1])].append(key)
    for (name, univ) in sorted(groups):
        lines = []
        for key in sorted(groups[(name, univ)], key=lambda k: (k[2], k[3])):
            res = stats(TR[key], f"{key[2]} [{key[3]}]")
            if res:
                lines.append(res)
        if lines:
            print(f"\n=== {name} — {univ}")
            for ln, _ in lines:
                print("  " + ln)
