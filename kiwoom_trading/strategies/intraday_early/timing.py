"""장중에 뜨는 종목의 '이른' 매수 타점 비교 (2026-10-27).

사용자 관점: 오른 뒤 고점 돌파에서 사면 손절까지 멀어 손익비가 나쁘다 → 같은 종목을 더 일찍(손절선 가까이) 잡으면 나은가.
대상: 전날 대금 200위 · 보통주 (그날 순위는 미래 정보라 안 씀). 신호는 정규장 1분봉(09:00~15:30), 프리장(08:00~08:59 통합)은 갭 확인에만.
매수 = 신호 봉 다음 봉 시가, 매수 봉 09:03~11:00. (종목·매수 방식·날) 하나에 첫 신호 한 번.

PART A — 갭 없이 장중에 뜨는 종목 (프리장 고가 < 전일 종가 +1%, 09:00 시가가 전일 종가 −2%~+1%)
  A1 첫 대금 폭발 돌파: 봉 대금 ≥ 10억 & 직전 10봉 평균 3배, 종가 > 그때까지 당일 고가 & VWAP, 등락 +1~+5%. 손절 = 그 봉 저가 −0.1%
  A2 시가 탈환: 09:00~09:30 에 시가 −1% 아래로 내려갔다가 종가가 시가 위 & 봉 대금 ≥ 10억·직전 5봉 2배. 손절 = 시가 뒤 최저가 −0.1%
  A3 첫 눌림 반등(VWAP 지지): 첫 상승(고가 ≥ 시가 +2%) 뒤 저가가 VWAP(또는 20봉 이평) 0.3% 안까지 왔다가 종가는 그 위,
     이어 종가가 직전 봉 고가 위 & 봉 대금 ≥ 직전 5봉 1.5배 → 매수 (옛 고점 재돌파 전). 손절 = 눌림 저가 −0.1%
PART B — 🎯 눌림 돌파를 더 일찍 (등락 +2%↑, 첫 고점 ≥ 시가 +2%, 눌림 몸통 저점 ≤ 고점 −0.7% & ≥ VWAP −1%)
  B0 기존: 양봉 종가가 첫 고점 위 & VWAP·5봉 이평 위 & 봉 대금 ≥ 눌림 평균. 손절 = 눌림 몸통 저점 −0.5% (최대 −5%)
  B1 눌림 반등 먼저: 눌림 중 종가 > 직전 봉 고가 & 5봉 이평 위, 아직 첫 고점 아래. 손절 = 눌림 저가 −0.1%
  B2 돌파 가격 지정가: B0 신호 뒤 10봉 안에 첫 고점까지 내려오면 체결 (추격 안 함). 손절은 B0 와 같음
  B3 B0 중 신호 10:00 전만
각 매수 방식마다 '매수 때 등락 ≤ +5%' 변형도 함께 본다.
매도: M0 손절만 → 다음 날 09:00 / M1 절반 +2% → 나머지 트레일 3% / M3 절반 +2R → 나머지 트레일 3%
  (트레일 = max(손절, 본전, 고점 × 0.97), 15:19 까지 남으면 다음 날 09:00 시가, 같은 봉이면 손절 먼저, 비용 0.25%, |수익률| > 35% 뺌)

실행:
  .venv/Scripts/python.exe -m kiwoom_trading.strategies.intraday_early.timing          → data/intraday_early/timing.txt
  .venv/Scripts/python.exe -m kiwoom_trading.strategies.intraday_early.timing --check 2026-10-27 009150 007810 0013Y0 222800
     (엔진 기간 밖 날짜 — 키움에서 1분봉을 받아 같은 신호 함수로 확인)
"""
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time

import numpy as np

COST = 0.0025
VAL_MIN = 1e9
TRAIL = 0.03
T_SIG0, T_SIG1 = time(9, 2), time(10, 59)     # 신호 봉 → 매수 봉 09:03~11:00
DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "intraday_early")


# ---------------------------------------------------------------- 공통 계산
def arrays(reg):
    o = np.array([x[1] for x in reg], float); h = np.array([x[2] for x in reg], float)
    l = np.array([x[3] for x in reg], float); c = np.array([x[4] for x in reg], float)
    v = np.array([x[5] for x in reg], float)
    val = c * v
    tp = (h + l + c) / 3
    cv = np.cumsum(v)
    vwap = np.where(cv > 0, np.cumsum(tp * v) / np.maximum(cv, 1), c)
    cs = np.r_[0, np.cumsum(c)]
    idx = np.arange(len(c))

    def ma(n):
        lo = np.maximum(0, idx - n + 1)
        return (cs[idx + 1] - cs[lo]) / (idx + 1 - lo)
    return o, h, l, c, val, vwap, ma(5), ma(20)


def no_gap(pre, op, pc):
    """프리장 고가 < 전일 종가 +1% (프리장 거래 없으면 통과), 09:00 시가 전일 종가 −2%~+1%."""
    if pre and max(x[2] for x in pre) >= pc * 1.01:
        return False
    return pc * 0.98 < op < pc * 1.01


def _avg(a):
    return a.mean() if len(a) else np.inf


def sig_window(t):
    return T_SIG0 <= t <= T_SIG1


# ---------------------------------------------------------------- PART A
def entries_a(reg, pc):
    """이름 → (매수 봉 index, 매수가, 손절가, 지정가 여부, 신호 봉 index)."""
    o, h, l, c, val, vwap, ma5, ma20 = arrays(reg)
    op = o[0]
    out = {}
    dipped = False
    push = None          # A3 첫 상승 봉
    touched = None       # A3 눌림 지지 봉
    for i in range(len(reg) - 1):
        t = reg[i][0]
        if t > T_SIG1:
            break
        chg = c[i] / pc - 1
        # A1
        if "A1" not in out and i >= 2 and sig_window(t):
            if (val[i] >= VAL_MIN and val[i] >= 3 * _avg(val[max(0, i - 10):i]) and c[i] > h[:i].max()
                    and c[i] > vwap[i] and 0.01 <= chg <= 0.05):
                out["A1"] = (i + 1, o[i + 1], l[i] * 0.999, False, i)
        # A2
        if t <= time(9, 30) and l[i] <= op * 0.99:
            dipped = True
        if "A2" not in out and dipped and i >= 1 and sig_window(t):
            if c[i] > op and val[i] >= VAL_MIN and val[i] >= 2 * _avg(val[max(0, i - 5):i]):
                out["A2"] = (i + 1, o[i + 1], l[:i + 1].min() * 0.999, False, i)
        # A3
        if push is None:
            if h[i] >= op * 1.02:
                push = i
            continue
        if "A3" in out:
            continue
        if touched is not None and i > touched:
            if c[i] < vwap[i] * 0.99:            # 지지가 깨지면 다시 지지 확인을 기다림
                touched = None
            elif sig_window(t) and c[i] > h[i - 1] and val[i] >= 1.5 * _avg(val[max(0, i - 5):i]):
                out["A3"] = (i + 1, o[i + 1], l[push + 1:i + 1].min() * 0.999, False, i)
                continue
        if i > push and touched is None:
            for L in (vwap[i], ma20[i]):
                if l[i] <= L * 1.003 and c[i] > L:
                    touched = i
                    break
    return out


# ---------------------------------------------------------------- PART B
def entries_b(reg, pc):
    o, h, l, c, val, vwap, ma5, ma20 = arrays(reg)
    op = o[0]
    out = {}
    hi = h[0]
    state = "push"           # push · pull · bad
    fh = pstart = None
    pbody, pvals, plow = [], [], None
    for i in range(1, len(reg) - 1):
        t = reg[i][0]
        if t > T_SIG1:
            break
        chg = c[i] / pc - 1
        body = min(o[i], c[i])
        if state in ("push", "bad"):
            if h[i] > hi:
                hi = h[i]; state = "push"
                continue
            if state == "push" and hi >= op * 1.02 and body <= hi * 0.993:
                state, fh, pstart = "pull", hi, i
                pbody, pvals, plow = [body], [val[i]], l[i]
                if body < vwap[i] * 0.99:
                    state = "bad"
            continue
        # state == pull
        if c[i] > fh:
            if (c[i] > o[i] and c[i] > vwap[i] and c[i] > ma5[i] and val[i] >= np.mean(pvals) and chg >= 0.02
                    and sig_window(t) and "B0" not in out):
                stop_ = min(pbody) * 0.995
                e = o[i + 1]
                out["B0"] = (i + 1, e, max(stop_, e * 0.95), False, i)
                if t < time(10, 0):
                    out["B3"] = out["B0"]
                for j in range(i + 1, min(i + 11, len(reg))):
                    if l[j] <= fh:
                        ef = min(fh, o[j])
                        out["B2"] = (j, ef, max(stop_, ef * 0.95), o[j] > fh, i)   # 시가가 이미 아래면 시가 체결
                        break
            state, hi = "push", max(hi, h[i])
            continue
        if body < vwap[i] * 0.99:
            state = "bad"
            continue
        if ("B1" not in out and i > pstart and c[i] > h[i - 1] and c[i] > ma5[i] and c[i] < fh and chg >= 0.02
                and sig_window(t)):
            out["B1"] = (i + 1, o[i + 1], min(plow, l[i]) * 0.999, False, i)
        pbody.append(body); pvals.append(val[i]); plow = min(plow, l[i])
    return out


NAMES = {"A1": "A1 첫 대금 폭발 돌파", "A2": "A2 시가 탈환", "A3": "A3 첫 눌림 반등(VWAP 지지)",
         "B0": "B0 기존 눌림 돌파", "B1": "B1 눌림 반등 먼저", "B2": "B2 돌파 가격 지정가", "B3": "B3 B0 중 10시 전"}


# ---------------------------------------------------------------- 매도
def sell(b, j, e, stop0, nopen, half_at, limit_bar=False):
    """b[j] 에서 e 에 매수 → (수익률, R 배수). half_at = 절반 익절 가격(None = 없음)."""
    R = e - stop0
    stop, hi, done, got = stop0, e, False, 0.0
    for n, x in enumerate(b[j:]):
        if x[0] > time(15, 19):
            break
        if x[3] <= stop:
            px = min(x[1], stop) if not (limit_bar and n == 0) else stop
            r = got + (0.5 if done else 1.0) * (px / e - 1)
            return r - COST, (r * e) / R
        if half_at and not done and x[2] >= half_at and not (limit_bar and n == 0):
            got, done = 0.5 * (max(half_at, x[1]) / e - 1), True
        hi = max(hi, x[2])
        if done:
            stop = max(stop, e, hi * (1 - TRAIL))
    if nopen is None:
        return None, None
    r = got + (0.5 if done else 1.0) * (nopen / e - 1)
    return r - COST, (r * e) / R


EXITS = ("M0 손절만 · 다음 날 09:00", "M1 절반 +2% · 트레일 3%", "M3 절반 +2R · 트레일 3%")


# ---------------------------------------------------------------- 1년 백테스트
def main():
    from kiwoom_trading.backtest import engine as E
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    out = open(os.path.join(OUT, "timing.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); out.write(s + "\n"); out.flush()

    res = defaultdict(list)      # (진입, 매도) → [(date, ret, R, risk, 매수 시각, code)]
    nday = 0; n_nogap = 0
    for d in E.days():
        p = E.prev_day(d)
        U = [c for c, r in E.value_rank(p).items() if r <= 200 and E.is_common(c)]
        B, P = E.load_day(U, d), E.load_day(U, p)
        nday += 1
        for c in U:
            b = B.get(c) or []
            reg = E.regular(b); pr = E.regular(P.get(c) or [])
            if len(reg) < 100 or len(pr) < 30:
                continue
            pc = pr[-1][4]
            if not pc or abs(reg[0][1] / pc - 1) > 0.3:
                continue
            pre = [x for x in b if x[0] < time(9, 0)]
            ents = {}
            if no_gap(pre, reg[0][1], pc):
                n_nogap += 1
                ents.update(entries_a(reg, pc))
            ents.update(entries_b(reg, pc))
            if not ents:
                continue
            for key, (j, e, stop0, lim, si) in ents.items():
                if e <= stop0 or j >= len(reg):
                    continue
                risk = e / stop0 - 1
                ex = E.next_day_exits(c, d, e)
                nopen = e * (1 + ex["09:00 시가"] + COST) if "09:00 시가" in ex else None
                R = e - stop0
                variants = [NAMES[key]]
                if e / pc - 1 <= 0.05:
                    variants.append(NAMES[key] + " · 매수 때 ≤+5%")
                for mn, half in zip(EXITS, (None, e * 1.02, e + 2 * R)):
                    r, rr = sell(reg, j, e, stop0, nopen, half, limit_bar=lim)
                    if r is None or abs(r) >= 0.35:
                        continue
                    for vn in variants:
                        res[(vn, mn)].append((d, r, rr, risk, reg[j][0], c))
        if nday % 25 == 0:
            print(f"  ... {d} ({nday}일)", file=sys.stderr, flush=True)

    say(f"장중 이른 매수 타점 비교 1년 ({E.P0} ~ {E.P1}, {nday}일), 전날 대금 200위 보통주, 매수 09:03~11:00, 비용 0.25%")
    say(f"갭 없는 종목·일 {n_nogap}개 (PART A 대상)")
    say("열: 건수 · 건당 % · 기대값 R · 손익비(평균 이익÷평균 손실) · 승률 | 앞/뒤 반 | 최고 5일 빼면(100만/건, 만 원) | 손절까지 평균 거리")
    days_all = sorted({x[0] for v in res.values() for x in v}); half_d = days_all[len(days_all) // 2]
    summary = {}

    def line(v, title, width=34):
        r = np.array([x[1] for x in v]); R = np.array([x[2] for x in v]); risk = np.mean([x[3] for x in v])
        win, loss = r[r > 0], r[r <= 0]
        pf = (win.mean() / -loss.mean()) if len(win) and len(loss) else float("nan")
        A = [x[1] for x in v if x[0] < half_d]; Bb = [x[1] for x in v if x[0] >= half_d]
        a = np.mean(A) if A else float("nan"); bb = np.mean(Bb) if Bb else float("nan")
        bd = defaultdict(float)
        for x in v: bd[x[0]] += x[1]
        top5 = sum(sorted(bd.values(), reverse=True)[5:])
        star = "★" if len(v) >= 15 and a > 0 and bb > 0 and top5 > 0 else " "
        say(f" {star}{title:{width}s} {len(v):5d}건 건당 {r.mean():+.2%} 기대값 {R.mean():+.2f}R 손익비 {pf:.2f} 승률 {np.mean(r > 0):.0%} "
            f"| 앞 {a:+.2%} 뒤 {bb:+.2%} | 합계 {r.sum() * 100:+.0f}만 최고5일 빼면 {top5 * 100:+.0f}만 | 손절까지 {risk:.1%}")
        return dict(n=len(v), mean=r.mean(), R=R.mean(), star=star == "★")

    order = sorted({k[0] for k in res})
    for part, pref in (("PART A — 갭 없이 장중에 뜨는 종목", "A"), ("PART B — 눌림 돌파를 더 일찍", "B")):
        say(f"\n######## {part}")
        for en in [x for x in order if x.startswith(pref)]:
            say(f"\n== {en} ==")
            for mn in EXITS:
                v = res.get((en, mn), [])
                if v:
                    summary[(en, mn)] = line(v, mn)

    # 가장 좋은 두 매수 방식(변형 제외, 매도 중 가장 좋은 건당 %, 100건↑) → 매수 시각별
    base = [k for k in summary if "≤+5%" not in k[0] and summary[k]["n"] >= 100]
    best_by_entry = {}
    for en, mn in base:
        s = summary[(en, mn)]
        if en not in best_by_entry or s["mean"] > best_by_entry[en][1]:
            best_by_entry[en] = (mn, s["mean"])
    top2 = sorted(best_by_entry, key=lambda en: -best_by_entry[en][1])[:2]
    say("\n######## 매수 시각별 (건당 % 가 가장 좋은 두 매수 방식)")
    for en in top2:
        say(f"\n== {en} ==")
        for mn in EXITS:
            v = res.get((en, mn), [])
            for t0, t1, nm in ((time(9, 3), time(9, 30), "09:03~09:30"), (time(9, 30), time(10, 0), "09:30~10:00"),
                               (time(10, 0), time(11, 1), "10:00~11:00")):
                w = [x for x in v if t0 <= x[4] < t1]
                if len(w) >= 10:
                    line(w, f"{mn[:14]} {nm}")
    out.close()


# ---------------------------------------------------------------- 하루 확인 (키움 1분봉)
def check(day, codes):
    sys.stdout.reconfigure(encoding="utf-8")
    from kiwoom_trading.screener import run_intraday as ri
    from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
    cl = ri.build_client(); mk = ri.KiwoomMarket(cl)
    for code in codes:
        raw = fetch_minute_bars(cl, code, day, "AL")
        b = [(x["ts"].time(), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x["volume"])) for x in raw]
        reg = [x for x in b if time(9, 0) <= x[0] <= time(15, 30)]
        pre = [x for x in b if x[0] < time(9, 0)]
        q = mk.quote(code, integrated=False)
        pc = float(q.base_price) if q and q.base_price else None
        if not reg or not pc:
            print(f"{code}: 1분봉 {len(reg)}개 / 전일 종가 {pc} — 확인 불가"); continue
        ng = no_gap(pre, reg[0][1], pc)
        pre_hi = max((x[2] for x in pre), default=None)
        print(f"\n{code} 전일 종가 {pc:,.0f} · 프리장 고가 {pre_hi if pre_hi is None else f'{pre_hi:,.0f} ({pre_hi / pc - 1:+.1%})'} · "
              f"09:00 시가 {reg[0][1]:,.0f} ({reg[0][1] / pc - 1:+.1%}) · 갭 없음 조건 {'통과' if ng else '안 됨'}")
        ea = entries_a(reg, pc); eb = entries_b(reg, pc)
        for key in ("A1", "A2", "A3", "B0", "B1", "B2", "B3"):
            src = ea if key.startswith("A") else eb
            if key in src:
                j, e, st, lim, si = src[key]
                note = "" if (not key.startswith("A") or ng) else " (갭 조건 밖이라 실제로는 대상 아님)"
                print(f"  {NAMES[key]:24s} 신호 봉 {reg[si][0].strftime('%H:%M')} 종가 {reg[si][4]:,.0f} → 매수 {reg[j][0].strftime('%H:%M')} "
                      f"{e:,.0f} ({e / pc - 1:+.1%}) 손절 {st:,.0f} (−{e / st - 1:.1%}){note}")
            else:
                print(f"  {NAMES[key]:24s} 신호 없음")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--check":
        check(datetime.strptime(sys.argv[2], "%Y-%m-%d").date(), sys.argv[3:])
    else:
        main()
