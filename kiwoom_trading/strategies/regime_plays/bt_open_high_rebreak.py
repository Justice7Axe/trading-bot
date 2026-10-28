"""장 초 급등 고점(저항선) 재돌파 — 엑스게이트(356680) 2026-10-28 11:20 16,765 돌파 매매 재현·1년 시험 (2026-10-28 사용자).

저항선 R (그 시각까지 아는 값만):
  R10 = 09:00~09:10 최고가 (09:10 봉 끝에 확정)  · R5 = 09:00~09:05 · R15 = 09:00~09:15
  R첫 = 09:00 뒤 처음 만든 급등 고점: 그때까지 최고가에서 저가가 −3% 이상 밀린 첫 봉에 그 최고가로 확정 (고점은 10:00 전에 만든 것만)
  급등 조건: R ≥ 그날 09:00 시가 × (1 + a), a ∈ {3%, 5%}.
돌파 봉 k (09:40~14:30): 종가 > R, 거래량 ≥ 직전 20봉 평균 × kv, R 확정 뒤 T분 이상 지남, 직전 T봉 모두 종가 ≤ R,
  저점 상승: 직전 15봉 최저 > 그 앞 15봉 최저,
  정배열(변형): 직전 봉에서 5분선 > 20분선 > 60분선, 종가 > 20분선 (이평 = 그날 09:00 부터 1분봉 종가, 봉이 모자라면 있는 만큼 평균).
  그 봉 끝 시점 누적 대금(1분봉 거래량 × (고+저+종)/3) 순위 ≤ N (1분봉이 있는 종목 안에서). → 다음 봉 시가 매수. 종목당 하루 1번.
  매수가가 전날 종가 +29% 이상이면 못 삼.
손절: S1 = R × 0.995 아래 마감 → 다음 봉 시가 / S2 = 20분선 아래 마감 → 다음 봉 시가. 둘 다 −3% 터치 안전장치(닿으면 그 가격, 시가가 이미 아래면 시가).
매도: (a) +2% 절반 · +4% 나머지 (터치). 절반 판 뒤에는 5분선 아래 마감 때 나머지(다음 봉 시가). 아니면 15:19 봉 종가.
      (b) 5분선 아래 마감 때 전부 (다음 봉 시가), 아니면 15:19 봉 종가.
      (c) 손절만, 아니면 다음 날 09:00 시가.
      15:19 당일 정리는 이 단타(10~15분 보유) 성격상 허용(종가 매도 금지 규칙의 예외로 명시). 같은 봉 손절·익절 → 손절 먼저. 비용 0.25%.
대상: 우선주·스팩 제외. 날: 전체 / 강한 상승장(U) / 그 밖. 1분봉 = engine(원가격, AL 통합) — 일봉 수정주가 안 씀(전날 종가는 일봉 비율로만).
한계: minute_history 는 전날 대금 상위 500 위주 + 그날 대금 200 안 종목 → 범위 밖 종목이 빠지고, 누적 대금 순위는 그 안에서만 매김.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.regime_plays.bt_open_high_rebreak → data/backtest/open_high_rebreak.txt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "backtest"); os.makedirs(OUT, exist_ok=True)
UNTIL = time(15, 19)
T0, T1 = time(9, 40), time(14, 30)
F = None


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


def tmin(t):
    return t.hour * 60 + t.minute


def ma(c, n):
    """expanding → rolling 평균 (그 봉까지)."""
    cs = np.cumsum(np.r_[0.0, c]); out = np.empty(len(c))
    for i in range(len(c)):
        j = max(0, i + 1 - n); out[i] = (cs[i + 1] - cs[j]) / (i + 1 - j)
    return out


class Day:
    """한 종목 하루 정규장 1분봉 + 지표."""
    def __init__(self, b):
        self.b = b
        self.t = [x[0] for x in b]
        self.o = np.array([x[1] for x in b], float); self.h = np.array([x[2] for x in b], float)
        self.l = np.array([x[3] for x in b], float); self.c = np.array([x[4] for x in b], float)
        self.v = np.array([x[5] for x in b], float)
        self.m5, self.m20, self.m60 = ma(self.c, 5), ma(self.c, 20), ma(self.c, 60)
        self.cumv = np.cumsum(self.v * (self.h + self.l + self.c) / 3)
        self._R = {}

    def R(self, kind):
        """→ (R, 확정 봉 인덱스) 또는 None."""
        if kind in self._R: return self._R[kind]
        out = None
        if kind in ("R5", "R10", "R15"):
            end = time(9, int(kind[1:]))
            ix = [i for i, t in enumerate(self.t) if t <= end]
            if ix and self.t[ix[-1]] >= time(9, int(kind[1:]) - 2):
                out = (self.h[:ix[-1] + 1].max(), ix[-1])
        else:   # R첫: 최고가에서 −3% 밀린 첫 봉
            hi, hi_t = -1, None
            for i, t in enumerate(self.t):
                # 밀림은 고점 봉 다음 봉부터 봄 (같은 봉 안 고·저 순서를 모르므로)
                if hi_t and hi_t < time(10, 0) and self.l[i] <= hi * 0.97:
                    out = (hi, i); break
                if self.h[i] > hi: hi, hi_t = self.h[i], t
                if t >= time(10, 30): break
        self._R[kind] = out
        return out


def signal(D, kind, a, T, kv, align, rank_ok):
    """→ (돌파 봉 k, R) 또는 None. rank_ok(k) = 그 봉 끝 누적 대금 순위 조건."""
    r = D.R(kind)
    if not r: return None
    R, ci = r
    if R < D.o[0] * (1 + a): return None
    for k in range(max(ci + T, 30), len(D.b) - 1):
        t = D.t[k]
        if t < T0: continue
        if t > T1: return None
        if D.c[k] <= R: continue
        if D.c[k - T:k].max() > R: continue
        if tmin(t) - tmin(D.t[ci]) < T: continue
        if k < 30 or D.l[k - 15:k].min() <= D.l[k - 30:k - 15].min(): continue
        av = D.v[k - 20:k].mean()
        if not (av > 0 and D.v[k] >= kv * av): continue
        if align and not (D.m5[k - 1] > D.m20[k - 1] > D.m60[k - 1] and D.c[k - 1] > D.m20[k - 1]): continue
        if not rank_ok(k): continue
        if D.t[k + 1] > UNTIL: return None
        return k, R
    return None


def run_exit(D, k, R, stop_kind, how, nx_px):
    """D.b[k+1] 시가 매수. → (수익률, 보유 분 or None(다음 날), R%, 매수가, 매도 이유, 매도 시각)."""
    j = k + 1; buy = D.o[j]
    safety = buy * 0.97
    lvl0 = R * 0.995 if stop_kind == "S1" else D.m20[k]
    rpct = min(max(1 - lvl0 / buy, 0.003), 0.03)
    pos, got, half, pend = 1.0, 0.0, False, None
    for i in range(j, len(D.b)):
        t = D.t[i]
        if t > UNTIL: break
        o, h, l, c = D.o[i], D.h[i], D.l[i], D.c[i]
        if pend:
            return got + pos * (o / buy - 1) - E.COST, tmin(t) - tmin(D.t[j]), rpct, buy, pend, t
        if l <= safety:
            return got + pos * (min(o, safety) / buy - 1) - E.COST, tmin(t) - tmin(D.t[j]), rpct, buy, "−3%", t
        lvl = R * 0.995 if stop_kind == "S1" else D.m20[i]
        if c < lvl:
            pend = "손절"; continue
        if how == "a":
            if not half and h >= buy * 1.02:
                got += 0.5 * (max(o, buy * 1.02) / buy - 1); pos = 0.5; half = True
            if half and h >= buy * 1.04:
                return got + pos * (max(o, buy * 1.04) / buy - 1) - E.COST, tmin(t) - tmin(D.t[j]), rpct, buy, "+4%", t
            if half and c < D.m5[i]:
                pend = "5분선"; continue
        elif how == "b":
            if c < D.m5[i]:
                pend = "5분선"; continue
    if pend:    # 15:19 봉에서 마감 신호 → 다음 봉 시가
        nxt = next((i for i in range(j, len(D.b)) if D.t[i] > UNTIL), None)
        if nxt is not None:
            return got + pos * (D.o[nxt] / buy - 1) - E.COST, tmin(D.t[nxt]) - tmin(D.t[j]), rpct, buy, pend, D.t[nxt]
    if how == "c":
        return got + pos * (nx_px / buy - 1) - E.COST, None, rpct, buy, "다음 날", None
    ix = [i for i in range(j, len(D.b)) if D.t[i] <= UNTIL]
    last = D.c[ix[-1]] if ix else D.o[j]
    return got + pos * (last / buy - 1) - E.COST, tmin(UNTIL) - tmin(D.t[j]), rpct, buy, "15:19", UNTIL


# (이름, R, a, T, kv, 정배열, 손절, 매도, N)
BASE = dict(R="R10", a=0.03, T=30, kv=2, al=True, st="S1", ex="a", N=100)
COMBOS = [("기본 R10 a3 T30 ×2 정배열 S1 (a) 상위100", {})]
for nm, ch in [
    ("R5", dict(R="R5")), ("R15", dict(R="R15")), ("R첫(−3%)", dict(R="R첫")),
    ("a5", dict(a=0.05)), ("T60", dict(T=60)), ("×3", dict(kv=3)), ("정배열 없음", dict(al=False)),
    ("손절 S2(20분선)", dict(st="S2")), ("매도 (b) 5분선", dict(ex="b")), ("매도 (c) 다음 날", dict(ex="c")),
    ("상위40", dict(N=40)),
    ("a5 ×3", dict(a=0.05, kv=3)), ("a5 T60 ×3", dict(a=0.05, T=60, kv=3)), ("R첫 a5", dict(R="R첫", a=0.05)),
    ("R15 T60", dict(R="R15", T=60)), ("R5 a5 ×3", dict(R="R5", a=0.05, kv=3)), ("R15 a5 ×3", dict(R="R15", a=0.05, kv=3)),
    ("R첫 T60 ×3", dict(R="R첫", T=60, kv=3)), ("상위40 a5 ×3", dict(N=40, a=0.05, kv=3)),
    ("상위40 (c)", dict(N=40, ex="c")), ("S2 (b)", dict(st="S2", ex="b")), ("S2 (c)", dict(st="S2", ex="c")),
    ("정배열 없음 ×3", dict(al=False, kv=3)), ("정배열 없음 (c)", dict(al=False, ex="c")),
    ("T60 (c)", dict(T=60, ex="c")), ("a5 ×3 (c)", dict(a=0.05, kv=3, ex="c")), ("a5 ×3 (b)", dict(a=0.05, kv=3, ex="b")),
    ("상위40 정배열 없음", dict(N=40, al=False)),
]:
    COMBOS.append((nm, ch))
COMBOS = [(nm, {**BASE, **ch}) for nm, ch in COMBOS]


def stats(tr):
    """tr = [dict(d, ret, hold, rpct)]."""
    if len(tr) < 5: return None
    ds = sorted({x["d"] for x in tr}); hd = ds[len(ds) // 2]
    v = np.array([x["ret"] for x in tr]); a = [x["ret"] for x in tr if x["d"] < hd]; bb = [x["ret"] for x in tr if x["d"] >= hd]
    bd = defaultdict(list)
    for x in tr: bd[x["d"]].append(x["ret"])
    dr = {d: np.mean(x) for d, x in bd.items()}
    s = sorted(dr.values(), reverse=True)
    eq = np.cumsum([dr[d] for d in sorted(dr)]) * 1000
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    hs = [x["hold"] for x in tr if x["hold"] is not None]
    return dict(n=len(v), days=len(dr), mean=v.mean(), a=np.mean(a), b=np.mean(bb), tot=sum(s) * 1000, ex5=sum(s[5:]) * 1000,
                mdd=mdd, star=star, win=np.mean(v > 0), hold=np.mean(hs) if hs else None,
                R=np.mean([x["rpct"] for x in tr]), Rm=np.mean([x["ret"] / x["rpct"] for x in tr]))


def line(name, s):
    if s is None:
        say(f"   {name:24s} 적음"); return
    hold = f"{s['hold']:5.0f}분" if s["hold"] is not None else "다음날"
    say(f" {s['star']} {name:24s} {s['n']:4d} {s['days']:3d}일 {s['mean']:+6.2%} {s['a']:+6.2%} {s['b']:+6.2%} {s['tot']:+6.0f}만 {s['ex5']:+6.0f}만 "
        f"{s['mdd']:4.0f}만 {s['win']:4.0%} {hold} {s['R']:5.2%} {s['Rm']:+5.2f}R")


def build():
    feat = _load("regime_feat.pkl")
    days = [d for d in E.days() if E.next_day(d) and d in feat]
    res = defaultdict(list)      # 이름 → trades
    inv = []                     # 역선택: (d, U, code, a3, a5, fired_base, day_ret, rank_ok_0940)
    for di, d in enumerate(days):
        p = E.prev_day(d); dd, dp = E.daily_day(d), E.daily_day(p)
        codes = [c for c in E._min_codes(d) if E.is_common(c) and c in dd and c in dp and "스팩" not in (E.NAME.get(c) or "")]
        B = {c: E.regular(b) for c, b in E.load_day(codes, d).items()}
        B = {c: Day(b) for c, b in B.items() if len(b) >= 120 and b[0][0] <= time(9, 1)}
        if not B: continue
        U = cls_of(feat[d]) == "U"
        # 분 단위 누적 대금 순위 (09:00~15:30 격자)
        grid = [time(9 + (m // 60), m % 60) for m in range(0, 391)]
        gi = {t: i for i, t in enumerate(grid)}
        cl = list(B)
        M = np.zeros((len(cl), len(grid)))
        for r, c in enumerate(cl):
            D = B[c]; last = 0.0; pos = 0
            for i, t in enumerate(grid):
                while pos < len(D.t) and D.t[pos] <= t:
                    last = D.cumv[pos]; pos += 1
                M[r, i] = last
        RK = (-M).argsort(0).argsort(0) + 1     # 순위
        rk = {c: RK[r] for r, c in enumerate(cl)}
        for c, D in B.items():
            o9 = dd[c][0]; pcl = dp[c][3]
            if not (o9 and pcl): continue
            pc0 = D.o[0] / (o9 / pcl)          # 1분봉 기준 전날 종가 (일봉은 비율만 씀)
            nxe = None
            for nm, P in COMBOS:
                f = signal(D, P["R"], P["a"], P["T"], P["kv"], P["al"], lambda k: rk[c][gi[D.t[k]]] <= P["N"])
                if not f: continue
                k, R = f
                if D.o[k + 1] / pc0 - 1 >= 0.29: continue
                nx_px = None
                if P["ex"] == "c":
                    if nxe is None:     # 다음 날 09:00 시가 (가격, 오늘 1분봉 기준으로 맞춘 값)
                        ex = E.next_day_exits(c, d, D.c[-1]).get("09:00 시가")   # 기준가 = 그날 마지막 종가 (35% 점검용)
                        nxe = (ex + E.COST + 1) * D.c[-1] if ex is not None else False
                    if nxe is False: continue
                    nx_px = nxe
                ret, hold, rp, buy, why, te = run_exit(D, k, R, P["st"], P["ex"], nx_px)
                i19 = max(i for i, t in enumerate(D.t) if t <= UNTIL)
                res[nm].append(dict(d=d, U=U, c=c, ret=ret, hold=hold, rpct=rp, t=D.t[k], why=why,
                                    raw=D.c[i19] / buy - 1, pre=buy / D.o[next(i for i, t in enumerate(D.t) if t >= time(9, 40))] - 1))
            # 역선택 바탕: R10 급등 고점이 있고 09:40 에 상위 100 안
            r10 = D.R("R10")
            if r10 and time(9, 40) in gi and rk[c][gi[time(9, 40)]] <= 100:
                i40 = next((i for i, t in enumerate(D.t) if t >= time(9, 40)), None)
                i19 = max((i for i, t in enumerate(D.t) if t <= UNTIL), default=None)
                if i40 is not None and i19 is not None and i19 > i40:
                    inv.append(dict(d=d, U=U, c=c, up=r10[0] / D.o[0] - 1, ret=D.c[i19] / D.o[i40] - 1,
                                    above=D.c[i19] > r10[0], mx=D.h[i40:i19 + 1].max() / D.o[i40] - 1))
        if di % 20 == 0: print(f"  {d} {len(B)}종목 기본 {len(res[COMBOS[0][0]])}건", file=sys.stderr, flush=True)
    return res, inv, days, feat


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(OUT, "open_high_rebreak.txt"), "w", encoding="utf-8")
    res, inv, days, feat = build()
    nU = sum(cls_of(feat[d]) == "U" for d in days)
    say(f"장 초 급등 고점 재돌파 — {days[0]}~{days[-1]} {len(days)}일 (강한 상승장 U {nU}일), 1분봉 출처 minute_history(+kang_minute)")
    say(f"시험한 조합 {len(COMBOS)}개 × 날 3가지. 같은 자료에서 고른 것이라 가장 좋은 하나는 우연일 수 있음 (30개 중 하나가 ★ 나올 확률 꽤 됨).")
    say("1천만/일 = 그날 산 종목 수로 나눔. R% = 매수가→첫 손절선 거리(최대 3%), R배 = 수익률÷R% 평균. 보유 = 매수~매도 분 (매도 (c) 는 다음 날).")
    hdr = (f"   {'조합':24s} {'건수':>4s} {'날':>4s} {'건당':>6s} {'앞':>6s} {'뒤':>6s} {'1천만/일':>7s} {'최고5일빼':>7s} {'낙폭':>5s} {'승률':>4s} "
           f"{'보유':>6s} {'R%':>5s} {'R배':>6s}")
    for title, flt in (("모든 날", lambda x: True), ("강한 상승장(U) 날", lambda x: x["U"]), ("강한 상승장 아닌 날", lambda x: not x["U"])):
        say("\n" + "=" * 130); say(f"[{title}]"); say(hdr)
        for nm, P in COMBOS:
            line(nm, stats([x for x in res[nm] if flt(x)]))
    # 기본 조합 매도 이유·시각
    nm0 = COMBOS[0][0]
    say("\n기본 조합 매도 이유: " + ", ".join(f"{k} {v}" for k, v in sorted(
        {w: sum(1 for x in res[nm0] if x["why"] == w) for w in {x["why"] for x in res[nm0]}}.items(), key=lambda z: -z[1])))
    tm = [tmin(x["t"]) for x in res[nm0]]
    if tm: say(f"기본 조합 돌파 봉 시각 중앙 {int(np.median(tm)) // 60:02d}:{int(np.median(tm)) % 60:02d}")
    # 역선택
    say("\n" + "=" * 130)
    say("역선택 점검 — R10 급등 고점(+3%↑)이 있고 09:40 누적 대금 100위 안 종목. 그날 결과 = 09:40 시가 → 15:19 종가 (비용 전), 고점 = 09:40 뒤 최고")
    base_keys = {(x["d"], x["c"]) for x in res[nm0]}
    for title, flt in (("모든 날", lambda x: True), ("U 날", lambda x: x["U"]), ("U 아닌 날", lambda x: not x["U"])):
        g = [x for x in inv if x["up"] >= 0.03 and flt(x)]
        y = [x for x in g if (x["d"], x["c"]) in base_keys]; n = [x for x in g if (x["d"], x["c"]) not in base_keys]
        f = lambda z, k: np.mean([q[k] for q in z]) if z else float("nan")
        bt = [x for x in res[nm0] if flt(x)]
        say(f"  {title:10s} 신호 난 종목을 09:40 → 매수까지 {np.mean([x['pre'] for x in bt]):+.2%} 이미 오름, 매수 → 15:19 (손절 없이·비용 전) {np.mean([x['raw'] for x in bt]):+.2%}")
        say(f"  {title:10s} 신호 난 {len(y):4d}종목: 그날 {f(y, 'ret'):+.2%} · 09:40 뒤 최고 {f(y, 'mx'):+.2%} · R 위 마감 {f(y, 'above'):.0%} | "
            f"안 난 {len(n):5d}종목: 그날 {f(n, 'ret'):+.2%} · 최고 {f(n, 'mx'):+.2%} · R 위 마감 {f(n, 'above'):.0%}")
    pickle.dump(dict(res=res, inv=inv), open(os.path.join(os.environ.get("TEMP", "."), "open_high_rebreak.pkl"), "wb"))


def today_examples():
    say("\n" + "=" * 130)
    say("오늘(2026-10-28) 예시 — KRX 1분봉 data/leader_capture/bars_krx.pkl (526종목 안 누적 대금 순위). 다음 날 없음 → (c) 는 15:30 종가로 표시")
    B = pickle.load(open(os.path.join(E.DATA, "leader_capture", "bars_krx.pkl"), "rb"))
    d = date(2026, 10, 28)
    allD = {}
    for (c, dd), raw in B.items():
        if dd != d: continue
        b = [(x[0].time(), *x[1:]) for x in raw if time(9, 0) <= x[0].time() <= time(15, 30)]
        if len(b) >= 60: allD[c] = Day(b)
    grid = [time(9 + (m // 60), m % 60) for m in range(0, 391)]
    cum = {}
    for c, D in allD.items():
        arr, last, pos = [], 0.0, 0
        for t in grid:
            while pos < len(D.t) and D.t[pos] <= t: last = D.cumv[pos]; pos += 1
            arr.append(last)
        cum[c] = arr

    def rank_at(c, t):
        i = grid.index(t); v = cum[c][i]
        return 1 + sum(1 for x in cum.values() if x[i] > v)

    for c, nm in (("356680", "엑스게이트"), ("010170", "대한광통신"), ("069540", "빛과전자"), ("003160", "디아이")):
        D = allD.get(c)
        if not D: say(f"  {nm}({c}) 1분봉 없음"); continue
        rs = {k: D.R(k) for k in ("R5", "R10", "R15", "R첫")}
        say(f"  {nm}({c}) 시가 {D.o[0]:,.0f} · " + " · ".join(
            f"{k} {v[0]:,.0f}({v[0] / D.o[0] - 1:+.1%}, {D.t[v[1]].strftime('%H:%M')} 확정)" if v else f"{k} 없음" for k, v in rs.items())
            + f" · 15:30 종가 {D.c[-1]:,.0f}")
        for nm2, P in COMBOS:
            f = signal(D, P["R"], P["a"], P["T"], P["kv"], P["al"], lambda k: rank_at(c, D.t[k]) <= P["N"])
            if not f:
                if nm2 in (COMBOS[0][0], "R5", "R15", "R첫(−3%)", "a5", "T60", "×3", "정배열 없음", "상위40"):
                    # 왜 없는지: 순위 조건 빼고 다시
                    g = signal(D, P["R"], P["a"], P["T"], P["kv"], P["al"], lambda k: True)
                    why = f" (순위 빼면 {D.t[g[0]].strftime('%H:%M')} 신호 → 순위 탈락)" if g else ""
                    say(f"     {nm2:24s} 신호 없음{why}")
                continue
            k, R = f
            nx = D.c[-1]
            ret, hold, rp, buy, why, te = run_exit(D, k, R, P["st"], P["ex"], nx + E.COST * 0)
            say(f"     {nm2:24s} R {R:,.0f} 돌파 {D.t[k].strftime('%H:%M')} (거래량 {D.v[k] / D.v[k - 20:k].mean():.1f}배, 순위 {rank_at(c, D.t[k])}) "
                f"→ {D.t[k + 1].strftime('%H:%M')} 매수 {buy:,.0f} → {why}" + (f" {te.strftime('%H:%M')}" if te else "")
                + f" {ret:+.2%} ({ret / rp:+.1f}R)")


if __name__ == "__main__":
    main()
    today_examples()
    F.close()
