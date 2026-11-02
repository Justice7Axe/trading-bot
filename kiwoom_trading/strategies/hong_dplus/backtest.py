"""🔺 홍인기 D+ 매매 1년 백테스트 (2026-11-02 사용자: 홍인기 파이널 3·4·5강 영상 분석 → 코드·스킬·백테스트, 같은 날 규칙 점검 뒤 다시).

규칙은 rules.py, 섹터는 sectors.py (네이버 테마를 큰 섹터로 묶고 그룹주 더함). 자료·체결은 공통 엔진, 비용 0.25%, 같은 봉이면 손절 먼저, 종가 매도 안 함.
[D+0] 09:00 부터 매분, 그 시각 누적 대금(1분봉 거래량×(고+저+종)/3) 상위 20위(앞서 20위였다 상한가로 밀린 종목 포함) 안에서
      +5%↑ 가 3개↑ 인 섹터 = 주도 섹터, 그 안 등락률 1위 = 대장. 09:30~14:30 에 처음 대장이 되면:
      · 시총 2조↑ → 다음 봉 시가 장중 매수 (+28%↑ 면 못 삼)
      · 시총 2조 미만 → 상따: 그 뒤 상한가(전일 종가 +29.5%) 닿는 봉에서 상한가 매수 (체결된 것으로 가정 — 실제론 줄 서야 함), 다음 날 09:00 매도
      장중 매수 매도 4가지 (−3% 손절 먼저): ① 다음 날 09:00  ② 15:19 에 아직 대장이면 다음 날 09:00 · 아니면 15:19
        ③ ② + 10분마다 같은 섹터 대장이 바뀌면 그 봉 종가에 정리 (강의 '장중 대장 교체 시 손절')  ④ 신고가 목표(이미 넘었으면 +5%)
      강의 걸러내기: 최근 강세 섹터(20일) · 같은 섹터 과거 대장(60일) · 장대양봉 뒤 2주 · 시총 5천억↑ · 코스피 −2% 위 ·
        KRX 갭·NXT 프리장 +5% 미만 · 신고가 근처 · 끼.
[D+1·D+2] D 일 종가 기준 주도 섹터 대장 & +10%↑ → D+1·D+2 에 갭상승 출발만(시가 > 전일 종가), 같은 섹터 D+ 종목 중 시가 갭 1위.
      전일 종가 +1% 지정가 (시가가 그보다 낮으면 09:00 시가), 손절 전일 종가 −2%, 목표 시가(+2% 못 되면 +3%), 아니면 다음 날 09:00.
      비교: 갭하락 출발이어도 09:10 안에 전일 종가를 넘으면 그 다음 봉 시가 (강의 예외).
⚠️ 섹터 소속은 지금(2026-10) 네이버 목록 기준 (근사). 1분봉 대상은 minute_history(전날 상위 + 그날 상위).
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.strategies.hong_dplus.backtest
  → data/hong_dplus/backtest.txt · trades.pkl   (--report-only, --examples: 강의 예시 확인만)
"""
from __future__ import annotations

import os
import pickle
import sys
from datetime import date, time
from functools import lru_cache

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.common.leader import load_themes
from kiwoom_trading.strategies.hong_dplus import rules as R
from kiwoom_trading.strategies.hong_dplus import sectors as SX
from kiwoom_trading.strategies.hong_styles.backtest import MKT, ctx, kospi_min

OUT = os.path.join(E.DATA, "hong_dplus")
os.makedirs(OUT, exist_ok=True)
THEME = SX.build(load_themes(os.path.join(E.DATA, "naver_groups.duckdb")), E.NAME)     # {code: {섹터}}
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


def past_leader(c, d, th=None, n=R.PAST_LEAD):
    """지난 n 거래일 안에 (th 가 있으면 같은 섹터의) 대장이었나."""
    return any(day_lead(E.prev_day(d, k))[1].get(c) == th if th else c in day_lead(E.prev_day(d, k))[1] for k in range(1, n + 1))


def first_big(c, d):
    """d 이전 10거래일에 +10%↑ 날이 없음 (장대양봉 뒤 2주 지난 자리)."""
    h = E.hist(c, d, R.QUIET + 1)
    return not any(h[i + 1][4] and h[i][4] / h[i + 1][4] - 1 >= R.BIG for i in range(len(h) - 1))


def kki(c, d):
    h = E.hist(c, d, R.KKI_DAYS + 3)
    return any(h[i + 3][4] and h[i][4] / h[i + 3][4] - 1 >= R.KKI_UP for i in range(len(h) - 3))


# ---------------------------------------------------------------- 매도
def exit_path(reg, k, buy, tp=None, sp=None, until=time(15, 19), skip_tp_first=False, swap_at=None):
    """swap_at = {시각: True} — 그 시각 봉 종가에 정리 (장중 대장 교체)."""
    for i, x in enumerate(reg[k:]):
        if x[0] > until:
            break
        if sp and x[3] <= sp:
            return min(x[1], sp) / buy - 1 - E.COST, "손절", x[0]
        if skip_tp_first and i == 0:
            continue
        if tp and x[2] >= tp:
            return max(x[1], tp) / buy - 1 - E.COST, "목표", x[0]
        if swap_at and x[0] in swap_at:
            return x[4] / buy - 1 - E.COST, "대장 교체", x[0]
    return None, None, None


def limit_released(reg, k, lim):
    """상한가 닿은 뒤 그날 상한가 아래 체결이 있었나 — 없으면(끝까지 잠김) 줄 선 매수는 체결 안 됐을 가능성이 큼."""
    return any(x[3] < lim * 0.995 for x in reg[k + 1:])


def next_open(c, d, buy):
    return E.next_day_exits(c, d, buy).get("09:00 시가")


# ---------------------------------------------------------------- D+0
def arrays(codes, d):
    """codes 의 그날 정규장 분별 종가(앞 값 채움)·누적 대금·1분봉·환산 계수·프리장 마지막 가격."""
    B = E.load_day(codes, d)
    keep, CL, CV, REG, F, PRE = [], [], [], {}, {}, {}
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
        pre = [x for x in B[c] if x[0] < time(9, 0)]
        keep.append(c); CL.append(cl); CV.append(np.cumsum(v)); REG[c] = reg; F[c] = f; PRE[c] = pre[-1][4] if pre else None
    return keep, np.array(CL), np.array(CV), REG, F, PRE


class Day:
    """하루치 매분 대장 계산 (20위 + 상한가로 밀린 종목)."""

    def __init__(self, d):
        p = E.prev_day(d); pdd = E.daily_day(p)
        codes = [c for c in E._min_codes(d) if E.is_common(c) and c in pdd]
        self.keep, self.CL, self.CV, self.REG, self.F, self.PRE = arrays(codes, d)
        self.d = d
        if not self.keep:
            return
        self.PC = np.array([pdd[c][3] * self.F[c] for c in self.keep])
        self.idx = {c: j for j, c in enumerate(self.keep)}
        self.CH = self.CL / self.PC[:, None] - 1
        self.held = set(); self.lead = {}
        for i in range(0, N_MIN):
            cv = self.CV[:, i]
            top = np.argpartition(-cv, R.TOP)[:R.TOP] if len(cv) > R.TOP else np.arange(len(cv))
            self.held |= {self.keep[j] for j in top if cv[j] > 0}
            mem = set(top) | {self.idx[c] for c in self.held if self.CH[self.idx[c], i] >= R.LIMIT_HELD}
            rows = [(self.keep[j], None if np.isnan(self.CH[j, i]) else self.CH[j, i], cv[j]) for j in mem]
            self.lead[i] = R.lead_themes(rows, THEME, top=len(rows), held=())

    def rank(self, c, i):
        j = self.idx[c]
        return int((self.CV[:, i] > self.CV[j, i]).sum()) + 1


def d0_day(d, dy=None):
    dy = dy or Day(d)
    if not dy.keep:
        return []
    p = E.prev_day(d)
    km = kospi_min(d); kpc = E.KOSPI.get(p)
    kmap = {tidx(x[0]): x[4] for x in km}
    kidx = sorted(kmap)
    seen, out = set(), []
    lead1519 = dy.lead[T1519][1]
    for i in range(tidx(time(*R.FIRST_BUY)), tidx(time(*R.LAST_BUY)) + 1):
        lead, leaders = dy.lead[i]
        for c, th in leaders.items():
            if c in seen:
                continue
            seen.add(c)
            j = dy.idx[c]; ch = dy.CH[j, i]; reg = dy.REG[c]; f = dy.F[c]; pc = dy.PC[j]
            mc = E.mcap(c, p); big = mc >= R.BIG_CAP
            hi = E.hi_n(c, d, 250)
            kx = [kmap[n] for n in kidx if n <= i]
            pre = dy.PRE.get(c)
            rec = dict(date=d, code=c, theme=th, n=len(lead[th]), chg=ch, rank=dy.rank(c, i), sig=ttime(i), big=big,
                       mode="장중" if big else "상따",
                       f_recent=recent_theme(th, d), f_past=past_leader(c, d, th), f_quiet=first_big(c, d),
                       f_mcap=mc >= R.MCAP_MIN, f_index=bool(kx and kpc and kx[-1] / kpc - 1 > R.INDEX_DROP),
                       f_gap=reg[0][1] / pc - 1 < R.GAP_MAX and (pre is None or pre / pc - 1 < R.PRE_MAX),
                       f_high=bool(hi and dy.CL[j, i] / f >= R.NEAR_HIGH * hi), f_kki=kki(c, d), mkt=MKT.get(d))
            none = (None, None)
            if big:
                k = next((n for n, x in enumerate(reg) if tidx(x[0]) > i), None)
                if k is None or ch >= 0.28:
                    continue
                buy = reg[k][1]; sp = buy * 0.97; nx = next_open(c, d, buy)
                rec.update(t=reg[k][0], px=buy)
                r, _, xt = exit_path(reg, k, buy, sp=sp, until=time(15, 30))      # 다음 날로 넘기는 매도는 장 끝까지 손절 확인
                rec["x_next"] = (r, xt) if r is not None else ((nx, None) if nx is not None else none)
                if r is None:
                    if c in lead1519:
                        r, xt = (nx, None) if nx is not None else none
                    else:
                        r, xt = E.at(reg, time(15, 19)) / buy - 1 - E.COST, time(15, 19)
                rec["x_lead"] = (r, xt)
                # 10분마다: 그 섹터가 더는 주도 섹터가 아니거나 다른 종목이 대장이면 정리
                swap = {ttime(n) for n in range(i + R.SWAP_EVERY, T1519, R.SWAP_EVERY) if dy.lead[n][1].get(c) != th}
                r, _, xt = exit_path(reg, k, buy, sp=sp, swap_at=swap)
                if r is None:
                    r, xt = rec["x_lead"]
                rec["x_swap"] = (r, xt)
                hraw = hi * f if hi else None
                tp = min(hraw if hraw and hraw > buy * 1.02 else buy * 1.05, buy * 1.15)
                r, _, xt = exit_path(reg, k, buy, tp=tp, sp=sp, until=time(15, 30))
                rec["x_high"] = (r, xt) if r is not None else ((nx, None) if nx is not None else none)
            else:
                lim = pc * 1.295
                k = next((n for n, x in enumerate(reg) if tidx(x[0]) > i and x[2] >= lim), None)
                if k is None:
                    rec.update(t=None, px=None, x_next=none, x_lead=none, x_swap=none, x_high=none)
                else:
                    buy = lim; nx = next_open(c, d, buy)
                    rec.update(t=reg[k][0], px=buy, released=limit_released(reg, k, lim))
                    v = (nx, None) if nx is not None else none
                    rec.update(x_next=v, x_lead=v, x_swap=v, x_high=v)
            out.append(rec)
    return out


# ---------------------------------------------------------------- D+1·D+2
def d12_day(d):
    out = []
    for kk in (1, 2):
        d0 = E.prev_day(d, kk)
        lead, leaders = day_lead(d0)
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
            rec = dict(date=d, code=c, k=kk, theme=th, gap=gap, f_strong=bool(peers) and max(peers)[1] == c, f_quiet=first_big(c, d0),
                       f_mcap=E.mcap(c, E.prev_day(d)) >= R.MCAP_MIN, f_kki=kki(c, d), mkt=MKT.get(d), recover=False)
            for nm in ("x_101",):
                rec[nm] = (None, None); rec[nm + "_px"] = None; rec[nm + "_t"] = None
                k = buy = None
                if gap > 0:
                    lim = pc * 1.01
                    if reg[0][1] <= lim:
                        k, buy = 0, reg[0][1]
                    else:
                        k = next((n for n, b in enumerate(reg[1:], 1) if b[0] <= time(11, 0) and b[3] <= lim), None)
                        buy = min(reg[k][1], lim) if k is not None else None
                else:
                    kr = next((n for n, b in enumerate(reg) if b[0] <= time(9, 10) and b[4] > pc), None)
                    if kr is not None and kr + 1 < len(reg):
                        k, buy = kr + 1, reg[kr + 1][1]; rec["recover"] = True
                if k is None:
                    continue
                op = reg[0][1]
                tp = op if op >= buy * 1.02 else buy * 1.03
                r, _, xt = exit_path(reg, k, buy, tp=tp, sp=pc * 0.98, skip_tp_first=True)
                if r is None:
                    nx = next_open(c, d, buy)
                    r, xt = (nx, None) if nx is not None else (None, None)
                rec[nm] = (r, xt); rec[nm + "_px"] = buy; rec[nm + "_t"] = reg[k][0]
            out.append(rec)
    return out


# ---------------------------------------------------------------- 강의 예시 확인
EXAMPLES = [("제주반도체", date(2026, 5, 14), "반도체 D+0 (3·5강)"), ("LG이노텍", date(2026, 5, 26), "신고가 돌파 D+0 (5강)"),
            ("삼화콘덴서", date(2026, 5, 26), "상따 (5강)"), ("대한광통신", date(2026, 4, 1), "상따·끼 (5강)"),
            ("현대건설", date(2026, 1, 12), "주봉 목표 D+0 (5강)"), ("LG씨엔에스", date(2026, 5, 29), "강한 뉴스 대장 (5강)"),
            ("고영", date(2026, 4, 24), "과거 끼 넘어섬 (5강)"), ("두산로보틱스", date(2026, 5, 15), "처음 대장 X (4강, 걸러져야 함)"),
            ("레인보우로보틱스", date(2026, 5, 7), "아침 대장 → 교체 (4강)")]


def examples(say=print):
    say("## 강의 예시가 규칙대로 잡히나")
    for nm, d, why in EXAMPLES:
        c = E.code_by_name(nm)
        lead, leaders = day_lead(d)
        dy = Day(d)
        first = next(((ttime(i), dy.lead[i][1][c], len(dy.lead[i][0][dy.lead[i][1][c]])) for i in range(tidx(time(9, 20)), tidx(time(14, 31)))
                      if c in dy.lead[i][1]), None) if c in dy.idx else None
        rec = [r for r in d0_day(d, dy) if r["code"] == c]
        fl = {k[2:]: v for k, v in rec[0].items() if k.startswith("f_")} if rec else {}
        say(f"  {d} {nm} [{why}] 종가 {E.chg(c, d):+.1%} · 섹터 {sorted(THEME.get(c, ()))}")
        say(f"     종가 기준 대장: {leaders.get(c)} | 장중 처음 대장: {first} | 걸러내기 {fl}")


# ---------------------------------------------------------------- 집계
D0_F = [("최근 강세 섹터", "f_recent"), ("같은 섹터 과거 대장", "f_past"), ("장대양봉 뒤 2주", "f_quiet"), ("시총 5천억↑", "f_mcap"),
        ("코스피 −2% 위", "f_index"), ("갭·프리장 +5% 미만", "f_gap"), ("신고가 근처", "f_high"), ("끼", "f_kki")]
D0_X = [("다음 날 09:00", "x_next"), ("15:19 대장 유지면 다음 날", "x_lead"), ("+ 장중 대장 교체 정리", "x_swap"), ("신고가 목표", "x_high")]


def tr_of(rows, x):
    return [(r["date"], r[x][0]) for r in rows if r[x][0] is not None]


def report(d0, d12):
    rp = E.Report.__new__(E.Report); rp.f = open(os.path.join(OUT, "backtest.txt"), "w", encoding="utf-8")
    ds = E.days()
    rp.say(f"🔺 홍인기 D+ 매매 1년 ({ds[0]} ~ {ds[-1]}, {len(ds)}일) — 섹터 지도(sectors.py), 비용 0.25%, ★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +")
    examples(rp.say)
    for mode, sel in (("시총 2조↑ 장중 매수", lambda r: r["big"]), ("시총 2조 미만 상따 (상한가 체결 가정)", lambda r: not r["big"])):
        rows = [r for r in d0 if sel(r)]
        allf = [r for r in rows if all(r[k] for _, k in D0_F)]
        rp.say(f"\n## D+0 · {mode} — 대장 신호 {len(rows)}건 (매수된 것 {sum(r['px'] is not None for r in rows)})")
        xs = D0_X if mode.startswith("시총 2조↑") else D0_X[:1]
        for xn, x in xs:
            rp.say(f"\n### 매도: {xn}" + (" (−3% 손절)" if mode.startswith("시총 2조↑") else ""))
            rp.stats(tr_of(rows, x), "걸러내기 없음 (대장 전부)")
            rp.stats(tr_of(allf, x), "강의 걸러내기 전부")
            for fn, k in D0_F:
                rp.stats(tr_of([r for r in rows if r[k]], x), f"  + {fn} 만")
            for fn, k in D0_F:
                rp.stats(tr_of([r for r in rows if all(r[kk] for _, kk in D0_F if kk != k)], x), f"  전부 − {fn}")
        if not mode.startswith("시총 2조↑"):
            rp.say("\n### 체결 엄격하게: 상한가 닿은 뒤 그날 풀린 적 있는 것만 체결 (끝까지 잠기면 줄 서도 못 삼)")
            rel = [r for r in rows if r.get("released")]
            rp.stats(tr_of(rel, "x_next"), "걸러내기 없음 · 풀린 것만 체결")
            rp.stats(tr_of([r for r in rows if r["px"] is not None and not r.get("released")], "x_next"), "참고: 끝까지 잠김 (실제론 거의 못 삼)")
            rp.stats(tr_of([r for r in rel if all(r[k] for _, k in D0_F)], "x_next"), "강의 걸러내기 전부 · 풀린 것만")
            for fn, k in D0_F:
                rp.stats(tr_of([r for r in rel if r[k]], "x_next"), f"  + {fn} 만 · 풀린 것만")
        rp.say("\n  강의 걸러내기 전부 신호")
        for r in sorted(allf, key=lambda r: (r["date"], r["sig"])):
            v = r["x_swap"][0] if r["big"] else r["x_next"][0]
            rp.say(f"   {r['date']} {r['sig']:%H:%M} {E.NAME.get(r['code'], r['code'])} [{r['theme']}] {r['n']}개 {r['chg']:+.1%} "
                   f"{'매수 ' + format(r['t'], '%H:%M') if r['t'] else '상한가 안 닿음'} → {'' if v is None else format(v, '+.1%')}")

    rp.say(f"\n## D+1·D+2 (D 일 대장 +10%↑ → 갭상승 출발 · 전일 종가 지지 눌림) 후보 {len(d12)}건")
    x = "x_101"
    for kk in (1, 2, None):
        base = [r for r in d12 if (kk is None or r["k"] == kk) and not r["recover"]]
        lab = f"D+{kk}" if kk else "D+1·D+2"
        rp.stats(tr_of(base, x), f"{lab} 갭상승 전부")
        rp.stats(tr_of([r for r in base if r["f_strong"]], x), f"{lab} + 같은 섹터 가장 강함")
        rp.stats(tr_of([r for r in base if r["f_strong"] and r["f_quiet"]], x), f"{lab} + 가장 강함 + 첫 장대양봉")
        rp.stats(tr_of([r for r in base if r["f_strong"] and r["f_quiet"] and r["f_mcap"]], x), f"{lab} + 가장 강함 + 첫 장대양봉 + 시총 5천억↑")
        rp.stats(tr_of([r for r in base if r["f_strong"] and r["f_kki"]], x), f"{lab} + 가장 강함 + 끼")
    rp.stats(tr_of([r for r in d12 if r["recover"] and r["k"] == 1], x), "D+1 갭하락 → 09:10 안에 전일 종가 회복 (예외)")
    return rp


def account(d0, d12, rp):
    """10만 계좌 (종목당 3만, 정수 주) — 지금 실전 구성과 함께 (스킬 backtest-rules, 메모리 account-sim-before-drop)."""
    from kiwoom_trading.research.strict_select import choose as C
    S = C.S
    if "🔺" not in S.KINDS:
        S.KINDS.append("🔺")
    base = [t for t in C.apply(pickle.load(open(os.path.join(C.OUT, "trades_feat.pkl"), "rb")), C.ALT) if t["kind"] != "7️⃣"]
    REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}
    allf = [r for r in d0 if all(r[k] for _, k in D0_F) and r["px"] is not None and (r["big"] or r.get("released"))]
    rel = [r for r in d0 if not r["big"] and r.get("released")]                      # 상따 · 체결 엄격 (풀린 것만)
    mk = lambda r, x, px, t: dict(date=r["date"], t=t, kind="🔺", code=r["code"], px=px, ret=r[x][0], xt=r[x][1], rk=r.get("rank", 0))
    sets = {
        "D+0 강의 전부 (장중 교체 정리·상따)": [mk(r, "x_swap", r["px"], r["t"]) for r in allf if r["x_swap"][0] is not None],
        "D+1 가장 강함+첫 장대양봉": [mk(r, "x_101", r["x_101_px"], r["x_101_t"]) for r in d12
                                if r["k"] == 1 and not r["recover"] and r["f_strong"] and r["f_quiet"] and r["x_101"][0] is not None],
    }
    sets["D+0 상따 대장 전부 (풀린 것만)"] = [mk(r, "x_next", r["px"], r["t"]) for r in rel if r["x_next"][0] is not None]
    sets["D+0 상따 + 신고가 근처 (풀린 것만)"] = [mk(r, "x_next", r["px"], r["t"]) for r in rel if r["f_high"] and r["x_next"][0] is not None]
    sets["둘 다"] = sets["D+0 강의 전부 (장중 교체 정리·상따)"] + sets["D+1 가장 강함+첫 장대양봉"]
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
            rp.say(f"  [{lab}] + 🔺 {nm:26s} 10만 → {r1['final']:>12,.0f}원 낙폭 {r1['mdd']:.0%} (🔺 {r1['n'].get('🔺', 0)}건 {r1['pnl'].get('🔺', 0) / 1e4:+.1f}만)"
                   f" | 🔺만 {r2['final']:>10,.0f}원 ({r2['n'].get('🔺', 0)}/{len(T)}건, 예수금 부족 {r2['skip'].get('예수금 부족', 0)})")
    S.DAYS = days1; S.SPLIT = days1[len(days1) // 2]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--examples" in sys.argv:
        examples(); return
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
