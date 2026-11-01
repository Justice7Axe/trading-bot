"""🔺 홍인기 D+ 매매 1년 백테스트 (2026-11-02 사용자: 홍인기 파이널 3·4·5강 영상 분석 → 코드·스킬·백테스트).

규칙은 rules.py (강의 슬라이드 그대로). 자료·체결은 공통 엔진(engine.py), 비용 0.25%, 같은 봉이면 손절 먼저, 종가 매도 안 함.
[D+0] 09:30~10:30 매분, 그 시각 누적 대금(1분봉 거래량×(고+저+종)/3) 상위 20위 안에서 +5%↑ 가 3개↑ 인 네이버 테마 = 주도 섹터,
      그 안 등락률 1위 = 대장 → 처음 대장이 된 다음 봉 시가 매수 (+28%↑ 상한가 근처면 못 삼).
      매도 3가지: ① −3% 손절, 아니면 다음 날 09:00  ② −3% 손절, 15:19 에 아직 대장이면 다음 날 09:00 · 아니면 15:19 (강의 '종가에 대장
      아니면 다음 날로 가져가지 않음')  ③ −3% 손절, 목표 = 전날까지 250일 고가(신고가, 이미 넘었으면 +5% 라운드피겨 근사), 아니면 다음 날 09:00.
      강의 걸러내기를 하나씩 켜고 끄며 본다 (최근 강세 섹터 · 과거 대장 · 장대양봉 뒤 2주 · 시총 5천억 · 지수 상승 · 갭 +5% 미만 · 신고가 근처 · 끼).
[D+1·D+2] D 일 종가 기준 주도 섹터 대장 & 그날 +10%↑ 장대양봉 & 앞 10거래일에 장대양봉 없음 → D+1·D+2 에 갭상승 출발(+1%↑)만,
      전일 종가 +1% 지정가(09:01~11:00), 같은 섹터 D+ 종목 중 시가 갭이 가장 큰 것만. 손절 = 전일 종가 −2%, 목표 = 그날 시가(+2% 못 되면 +3%),
      아니면 다음 날 09:00.
⚠️ 테마 소속은 지금(2026-10) 네이버 목록 (과거에 없던 테마가 섞일 수 있음, 근사). 1분봉 대상은 minute_history(전날 상위 + 그날 상위) —
   그 시각 대금 20위 안 종목은 거의 다 그날 대금 상위라 빠짐은 적음.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.strategies.hong_dplus.backtest
  → data/hong_dplus/backtest.txt · trades.pkl
"""
from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict
from datetime import time
from functools import lru_cache

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.common.leader import load_themes
from kiwoom_trading.strategies.hong_dplus import rules as R
from kiwoom_trading.strategies.hong_styles.backtest import MKT, ctx, kospi_min

OUT = os.path.join(E.DATA, "hong_dplus")
os.makedirs(OUT, exist_ok=True)
THEME = {c: {t for t in ts if not R.NON_SECTOR.search(t)} for c, ts in load_themes(os.path.join(E.DATA, "naver_groups.duckdb")).items()}
N_MIN = 391                                   # 09:00 ~ 15:30
T1519 = 379


def tidx(t):
    return t.hour * 60 + t.minute - 540


def ttime(i):
    return time(9 + i // 60, i % 60)


# ---------------------------------------------------------------- 일봉 기준 (D 일 마감에 아는 것)
@lru_cache(maxsize=None)
def day_lead(d):
    dd = E.daily_day(d)
    rows = [(c, E.chg(c, d), r[5] or 0) for c, r in dd.items() if E.is_common(c)]
    return R.lead_themes(rows, THEME)


def recent_theme(th, d, n=R.RECENT):
    return any(th in day_lead(E.prev_day(d, k))[0] for k in range(1, n + 1))


def past_leader(c, d, n=R.PAST_LEAD):
    return any(c in day_lead(E.prev_day(d, k))[1] for k in range(1, n + 1))


def first_big(c, d):
    """d 이전 10거래일에 +10%↑ 날이 없음 (장대양봉 뒤 2주 지난 자리)."""
    h = E.hist(c, d, R.QUIET + 1)
    return not any(h[i + 1][4] and h[i][4] / h[i + 1][4] - 1 >= R.BIG for i in range(len(h) - 1))


def kki(c, d):
    h = E.hist(c, d, R.KKI_DAYS + 3)
    return any(h[i + 3][4] and h[i][4] / h[i + 3][4] - 1 >= R.KKI_UP for i in range(len(h) - 3))


# ---------------------------------------------------------------- 매도
def exit_path(reg, k, buy, tp=None, sp=None, until=time(15, 19), skip_tp_first=False):
    for i, x in enumerate(reg[k:]):
        if x[0] > until:
            break
        if sp and x[3] <= sp:
            return min(x[1], sp) / buy - 1 - E.COST, "손절", x[0]
        if skip_tp_first and i == 0:
            continue
        if tp and x[2] >= tp:
            return max(x[1], tp) / buy - 1 - E.COST, "목표", x[0]
    return None, None, None


def next_open(c, d, buy):
    return E.next_day_exits(c, d, buy).get("09:00 시가")


# ---------------------------------------------------------------- D+0
def arrays(codes, d):
    """codes 의 그날 정규장 분별 종가(앞 값 채움)·누적 대금·1분봉 목록·환산 계수."""
    B = E.load_day(codes, d)
    keep, CL, CV, REG, F = [], [], [], {}, {}
    for c in codes:
        reg = E.regular(B[c])
        if len(reg) < 60:
            continue
        f = E.factor(c, d)
        if not f:
            continue
        cl = np.full(N_MIN, np.nan); v = np.zeros(N_MIN)
        for x in reg:
            i = tidx(x[0])
            if 0 <= i < N_MIN:
                cl[i] = x[4]; v[i] += x[5] * (x[2] + x[3] + x[4]) / 3
        for i in range(1, N_MIN):
            if np.isnan(cl[i]): cl[i] = cl[i - 1]
        keep.append(c); CL.append(cl); CV.append(np.cumsum(v)); REG[c] = reg; F[c] = f
    return keep, np.array(CL), np.array(CV), REG, F


def leaders_at(keep, CL, CV, PC, i):
    rows = [(c, CL[j, i] / PC[j] - 1 if CL[j, i] == CL[j, i] else None, CV[j, i]) for j, c in enumerate(keep)]
    return R.lead_themes(rows, THEME)


def d0_day(d):
    p = E.prev_day(d); pdd = E.daily_day(p)
    codes = [c for c in E._min_codes(d) if E.is_common(c) and c in pdd]
    keep, CL, CV, REG, F = arrays(codes, d)
    if not keep:
        return []
    PC = np.array([pdd[c][3] * F[c] for c in keep])
    km = kospi_min(d); kpc = E.KOSPI.get(p)
    kmap = {tidx(x[0]): x[4] for x in km}
    seen, out = set(), []
    lead1519 = leaders_at(keep, CL, CV, PC, T1519)[1]
    for i in range(tidx(time(*R.FIRST_BUY)), tidx(time(*R.LAST_BUY)) + 1):
        lead, leaders = leaders_at(keep, CL, CV, PC, i)
        for c, th in leaders.items():
            if c in seen:
                continue
            seen.add(c)
            j = keep.index(c); ch = CL[j, i] / PC[j] - 1
            reg = REG[c]; k = next((n for n, x in enumerate(reg) if tidx(x[0]) > i), None)
            if k is None:
                continue
            if ch >= 0.28:
                continue                                    # 상한가 근처 — 못 삼
            buy = reg[k][1]; f = F[c]
            hi = E.hi_n(c, d, 250)
            kx = [kmap[n] for n in sorted(kmap) if n <= i]
            rec = dict(date=d, code=c, t=reg[k][0], px=buy, theme=th, n=len(lead[th]), chg=ch,
                       rank=int((CV[:, i] > CV[j, i]).sum()) + 1,
                       f_recent=recent_theme(th, d), f_past=past_leader(c, d), f_quiet=first_big(c, d),
                       f_mcap=E.mcap(c, p) >= R.MCAP_MIN, big=E.mcap(c, p) >= R.BIG_CAP,
                       f_index=bool(kx and kpc and kx[-1] >= kpc), f_gap=reg[0][1] / PC[j] - 1 < R.GAP_MAX,
                       f_high=bool(hi and CL[j, i] / f >= R.NEAR_HIGH * hi), f_kki=kki(c, d), mkt=MKT.get(d))
            sp = buy * 0.97
            nx = next_open(c, d, buy)
            r, why, xt = exit_path(reg, k, buy, sp=sp)
            rec["x_next"] = (r, xt) if r is not None else ((nx, None) if nx is not None else (None, None))
            if r is not None:
                rec["x_lead"] = (r, xt)
            elif c in lead1519:
                rec["x_lead"] = (nx, None) if nx is not None else (None, None)
            else:
                rec["x_lead"] = (E.at(reg, time(15, 19)) / buy - 1 - E.COST, time(15, 19))
            hraw = hi * f if hi else None
            tp = min(hraw if hraw and hraw > buy * 1.02 else buy * 1.05, buy * 1.15)
            r, why, xt = exit_path(reg, k, buy, tp=tp, sp=sp)
            rec["x_high"] = (r, xt) if r is not None else ((nx, None) if nx is not None else (None, None))
            out.append(rec)
    return out


# ---------------------------------------------------------------- D+1·D+2
def d12_day(d):
    out = []
    for kk in (1, 2):
        d0 = E.prev_day(d, kk)
        lead, leaders = day_lead(d0)
        cand = []
        for c, th in leaders.items():
            ch0 = E.chg(c, d0)
            if ch0 is None or ch0 < R.BIG:
                continue
            reg, pc = ctx(c, d)
            if reg is None:
                continue
            peers = []
            for pcode, _ in lead[th]:
                preg, ppc = ctx(pcode, d)
                if preg is not None:
                    peers.append((preg[0][1] / ppc - 1, pcode))
            gap = reg[0][1] / pc - 1
            cand.append(dict(c=c, th=th, reg=reg, pc=pc, gap=gap, strongest=bool(peers) and max(peers)[1] == c,
                             quiet=first_big(c, d0)))
        for x in cand:
            c, reg, pc = x["c"], x["reg"], x["pc"]
            rec = dict(date=d, code=c, k=kk, theme=x["th"], gap=x["gap"], f_strong=x["strongest"], f_quiet=x["quiet"],
                       f_mcap=E.mcap(c, E.prev_day(d)) >= R.MCAP_MIN, f_kki=kki(c, d), mkt=MKT.get(d))
            for nm, lim_k in (("x_101", 1.01), ("x_100", 1.00)):
                rec[nm] = (None, None); rec[nm + "_px"] = None; rec[nm + "_t"] = None
                if x["gap"] < 0.01:
                    continue
                lim = pc * lim_k
                if reg[0][1] <= lim:
                    continue
                k = next((n for n, b in enumerate(reg[1:], 1) if b[0] <= time(11, 0) and b[3] <= lim), None)
                if k is None:
                    continue
                buy = min(reg[k][1], lim)
                op = reg[0][1]
                tp = op if op >= buy * 1.02 else buy * 1.03
                r, why, xt = exit_path(reg, k, buy, tp=tp, sp=pc * 0.98, skip_tp_first=True)
                if r is None:
                    nx = next_open(c, d, buy)
                    r, xt = (nx, None) if nx is not None else (None, None)
                rec[nm] = (r, xt); rec[nm + "_px"] = buy; rec[nm + "_t"] = reg[k][0]
            out.append(rec)
    return out


# ---------------------------------------------------------------- 집계
D0_F = [("최근 강세 섹터", "f_recent"), ("과거 대장", "f_past"), ("장대양봉 뒤 2주", "f_quiet"), ("시총 5천억↑", "f_mcap"),
        ("지수 상승 중", "f_index"), ("KRX 갭 +5% 미만", "f_gap"), ("신고가 근처", "f_high"), ("끼", "f_kki")]
D0_X = [("다음 날 09:00", "x_next"), ("15:19 대장 유지면 다음 날", "x_lead"), ("신고가 목표", "x_high")]


def tr_of(rows, x):
    return [(r["date"], r[x][0]) for r in rows if r[x][0] is not None]


def report(d0, d12):
    rp = E.Report.__new__(E.Report); rp.f = open(os.path.join(OUT, "backtest.txt"), "w", encoding="utf-8")
    ds = E.days()
    rp.say(f"🔺 홍인기 D+ 매매 1년 ({ds[0]} ~ {ds[-1]}, {len(ds)}일) — 비용 0.25%, ★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +")
    rp.say(f"\n## D+0 (09:30~10:30 그 시각 주도 섹터 대장 → 다음 봉 시가) 신호 {len(d0)}건")
    allf = [r for r in d0 if all(r[k] for _, k in D0_F)]
    for xn, x in D0_X:
        rp.say(f"\n### 매도: {xn} (−3% 손절)")
        rp.stats(tr_of(d0, x), "걸러내기 없음 (대장 전부)")
        rp.stats(tr_of(allf, x), "강의 걸러내기 전부")
        for fn, k in D0_F:
            rp.stats(tr_of([r for r in d0 if r[k]], x), f"  + {fn} 만")
        for fn, k in D0_F:
            rp.stats(tr_of([r for r in d0 if all(r[kk] for _, kk in D0_F if kk != k)], x), f"  전부 − {fn}")
    rp.say("\n### 강의 걸러내기 전부 · 15:19 대장 유지 매도 — 나눠 보기")
    for nm, sel in (("시총 2조↑ (장중 매매)", lambda r: r["big"]), ("시총 2조 미만", lambda r: not r["big"]),
                    ("주도 섹터 5개↑ (초강세)", lambda r: r["n"] >= 5), ("주도 섹터 3~4개", lambda r: r["n"] < 5)):
        rp.stats(tr_of([r for r in allf if sel(r)], "x_lead"), nm)
    for tag in sorted({r["mkt"] for r in d0 if r["mkt"]}):
        rp.stats(tr_of([r for r in d0 if r["mkt"] == tag], "x_lead"), f"걸러내기 없음 · {tag}")
        rp.stats(tr_of([r for r in allf if r["mkt"] == tag], "x_lead"), f"걸러내기 전부 · {tag}")
    rp.say("\n  강의 걸러내기 전부 신호 (최근 15건)")
    for r in sorted(allf, key=lambda r: (r["date"], r["t"]))[-15:]:
        rp.say(f"   {r['date']} {r['t']:%H:%M} {E.NAME.get(r['code'], r['code'])} [{r['theme']}] {r['n']}개 {r['chg']:+.1%} "
               f"→ 다음 날 {r['x_next'][0] if r['x_next'][0] is None else format(r['x_next'][0], '+.1%')} · 대장 유지 {r['x_lead'][0] if r['x_lead'][0] is None else format(r['x_lead'][0], '+.1%')}")

    rp.say(f"\n## D+1·D+2 (D 일 대장 +10%↑ → 갭상승 출발 · 전일 종가 지지 눌림) 후보 {len(d12)}건")
    for xn, x in (("전일 종가 +1% 지정가", "x_101"), ("전일 종가 지정가", "x_100")):
        rp.say(f"\n### {xn} · 손절 전일 종가 −2% · 목표 시가")
        for kk in (1, 2, None):
            base = [r for r in d12 if kk is None or r["k"] == kk]
            lab = f"D+{kk}" if kk else "D+1·D+2"
            rp.stats(tr_of(base, x), f"{lab} 갭상승 전부")
            rp.stats(tr_of([r for r in base if r["f_strong"]], x), f"{lab} + 같은 섹터 가장 강함")
            rp.stats(tr_of([r for r in base if r["f_strong"] and r["f_quiet"]], x), f"{lab} + 가장 강함 + 첫 장대양봉")
            rp.stats(tr_of([r for r in base if r["f_strong"] and r["f_quiet"] and r["f_mcap"]], x), f"{lab} + 가장 강함 + 첫 장대양봉 + 시총 5천억↑")
            rp.stats(tr_of([r for r in base if r["f_strong"] and r["f_kki"]], x), f"{lab} + 가장 강함 + 끼")
    return rp


def account(d0, d12, rp):
    """10만 계좌 (종목당 3만, 정수 주) — 지금 실전 구성과 함께 (스킬 backtest-rules, memory account-sim-before-drop)."""
    from kiwoom_trading.research.strict_select import choose as C
    S = C.S
    if "🔺" not in S.KINDS:
        S.KINDS.append("🔺")
    base = [t for t in C.apply(pickle.load(open(os.path.join(C.OUT, "trades_feat.pkl"), "rb")), C.ALT) if t["kind"] != "7️⃣"]
    REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}
    allf = [r for r in d0 if all(r[k] for _, k in D0_F)]
    mk = lambda r, x, px, t: dict(date=r["date"], t=t, kind="🔺", code=r["code"], px=px, ret=r[x][0], xt=r[x][1], rk=r.get("rank", 0))
    sets = {
        "D+0 강의 전부 (15:19 대장 유지)": [mk(r, "x_lead", r["px"], r["t"]) for r in allf if r["x_lead"][0] is not None],
        "D+0 강의 전부 (다음 날 09:00)": [mk(r, "x_next", r["px"], r["t"]) for r in allf if r["x_next"][0] is not None],
        "D+1·2 가장 강함+첫 장대양봉": [mk(r, "x_101", r["x_101_px"], r["x_101_t"]) for r in d12
                                  if r["f_strong"] and r["f_quiet"] and r["x_101"][0] is not None],
    }
    sets["D+0(대장 유지)+D+1·2"] = sets["D+0 강의 전부 (15:19 대장 유지)"] + sets["D+1·2 가장 강함+첫 장대양봉"]
    days1 = list(S.DAYS)
    rp.say("\n## 10만 계좌 (종목당 3만 원, 정수 주) — 지금 실전(6️⃣ 주도주 신고가·2️⃣ 저항 돌파·5️⃣ 약세장 인버스·📕 상한가 풀림·1️⃣ 상승장 장 초·🌙 종가 재돌파·4️⃣ 역행 강세 종가)과 함께")
    for lab, d_from in (("1년", days1[0]), ("최근 3달", days1[max(0, len(days1) - 63)])):
        dd = [d for d in days1 if d >= d_from]
        S.DAYS = dd; S.SPLIT = dd[len(dd) // 2]
        b = [t for t in base if t["date"] >= d_from]
        r0 = C.real_sim(b, kinds=REAL)
        rp.say(f"  [{lab}] 지금 실전            10만 → {r0['final']:>12,.0f}원 낙폭 {r0['mdd']:.0%}")
        for nm, T in sets.items():
            T = [t for t in T if t["date"] >= d_from]
            r1 = C.real_sim(b + T, kinds=REAL | {"🔺"})
            r2 = C.real_sim(T, kinds={"🔺"})
            rp.say(f"  [{lab}] + 🔺 {nm:28s} 10만 → {r1['final']:>12,.0f}원 낙폭 {r1['mdd']:.0%} (🔺 {r1['n'].get('🔺', 0)}건 {r1['pnl'].get('🔺', 0) / 1e4:+.1f}만)"
                   f" | 🔺만 {r2['final']:>10,.0f}원 낙폭 {r2['mdd']:.0%}")
    S.DAYS = days1; S.SPLIT = days1[len(days1) // 2]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pk = os.path.join(OUT, "trades.pkl")
    if "--report-only" in sys.argv and os.path.exists(pk):
        d0, d12 = pickle.load(open(pk, "rb"))
    else:
        d0, d12 = [], []
        for n, d in enumerate(E.days()):
            if not E.next_day(d):
                continue
            d0 += d0_day(d); d12 += d12_day(d)
            if n % 20 == 0:
                print(f"  {d} D+0 {len(d0)} D+1·2 {len(d12)}", flush=True)
        pickle.dump((d0, d12), open(pk, "wb"))
    rp = report(d0, d12)
    account(d0, d12, rp)


if __name__ == "__main__":
    main()
