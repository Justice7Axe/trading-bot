"""디앤서 종가배팅 규칙 백테스트 (dans_collect.py 결과 사용).

A. 종가배팅: D일 대금 상위 10 · +8%↑(삼전·하이닉스 +3%↑) → 17:00 이후 정규장 종가 재돌파 때 매수,
   17:00 이후 애프터마켓 저가 이탈 시 손절, D+1 프리마켓(08:00)부터 매도.
B. 시가 지지 돌파: A 대상 종목 D+1 09:00~10:00, 갭 상승 시가 → 밀렸다가 시가 재돌파 매수, 목표 전일 고가(없으면 +5%) · 손절 −2%.
비용 0.25%, 건당 100만. 같은 봉이면 손절 먼저. 앞/뒤 = 날짜 중앙으로 나눔.
"""
import os, pickle
from collections import defaultdict
from datetime import time
import numpy as np

S = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")), "data", "closing_bet")
D = pickle.load(open(os.path.join(S, "dans_bars.pkl"), "rb"))
R, KOSPI = D["rows"], D["kospi"]
DAYS = sorted({r["date"] for r in R}); HALF = DAYS[len(DAYS) // 2]
COST = 0.0025
BIG = {"005930", "000660"}

# 코스피 월봉 신고가 구간: 그달 지금까지 고가 ≥ 이전 모든 달 고가 최고
kd = sorted(KOSPI); FEST = {}
mhi, prior = {}, 0.0
for d in kd:
    ym = (d.year, d.month)
    if ym not in mhi:
        prior = max([prior] + [v for k, v in mhi.items()]); mhi[ym] = 0.0
    mhi[ym] = max(mhi[ym], KOSPI[d]); FEST[d] = mhi[ym] >= prior > 0


def at(bars, t, field=4, after=True):
    b = next((b for b in bars if b[0] >= t), None)
    return None if b is None else b[field]


def is_a(r, top=10, th=0.08):
    return r["rk"] <= top and r["chg"] < 0.295 and r["chg"] >= (0.03 if r["code"] in BIG else th)


# ---- A 진입 ----
def entry(r, mode):
    """mode: rebreak(17시 이후 종가 아래 있다가 위로) / any(17시 이후 처음 종가 위) / reg(정규장 종가 그대로)"""
    c = r["close"]
    if mode == "reg":
        return dict(px=c, t=time(15, 30), stop=None)
    am = [b for b in r["d_bars"] if b[0] >= time(15, 40)]
    below = any(b[4] <= c for b in am if b[0] < time(17, 0))
    lo = None
    for i, b in enumerate(am):
        if b[0] < time(17, 0):
            continue
        lo = b[3] if lo is None else min(lo, b[3])
        if b[4] > c and (mode == "any" or below):
            return dict(px=b[4], t=b[0], stop=lo, rest=am[i + 1:])
        if b[4] <= c:
            below = True
    return None


def split_entry(r, e):
    """3번 나눠 사기: 재돌파 봉, 30분 뒤, 60분 뒤 (20시 전, 손절 전까지)"""
    pxs = [e["px"]]
    for add in (30, 60):
        tt = (e["t"].hour * 60 + e["t"].minute + add)
        t2 = time(tt // 60, tt % 60) if tt < 20 * 60 else None
        if t2 is None:
            break
        hit = False
        for b in e["rest"]:
            if b[0] > t2:
                break
            if b[3] < e["stop"]:
                hit = True; break
        if hit:
            break
        p = at(e["rest"], t2)
        if p:
            pxs.append(p)
    return float(np.mean(pxs))


def evening_stop(e):
    if e.get("stop") is None:
        return None
    for b in e["rest"]:
        if b[3] < e["stop"]:
            return min(b[1], e["stop"]) * 0.999
    return None


def exits(r, buy):
    nb = r["n_bars"]
    if not nb:
        return None
    pre = [b for b in nb if b[0] < time(9, 0)]
    reg = [b for b in nb if b[0] >= time(9, 0)]
    if not reg or reg[0][0] > time(9, 5):
        return None
    o9 = reg[0][1]
    o8 = pre[0][1] if pre and pre[0][0] <= time(8, 5) else o9
    p830 = at(pre, time(8, 30)) or o8; p849 = pre[-1][4] if pre else o9
    x = {"08:00 프리 시가": o8, "프리 3분할(08:00·08:30·08:50)": np.mean([o8, p830, p849]), "09:00 시가": o9,
         "갭이면 08:00 전량, 아니면 08:00·09:00·09:30": o8 if o8 > buy else np.mean([o8, o9, at(reg, time(9, 30)) or o9]),
         "정규 3분할(09:00·09:30·10:00)": np.mean([o9, at(reg, time(9, 30)) or o9, at(reg, time(10, 0)) or o9])}
    for tp in (0.02, 0.03, 0.05):   # 08:00~10:00 익절, 못 닿으면 10:00 (손절 없음 — 영상: 다음 날 시세까지는 본다)
        v = None
        for b in nb:
            if b[0] > time(10, 0):
                break
            if b[2] >= buy * (1 + tp):
                v = max(b[1], buy * (1 + tp)); break
        x[f"익절 +{tp:.0%} (08~10시, 없으면 10:00)"] = v or at(reg, time(10, 0)) or o9
    return {k: v / buy - 1 - COST for k, v in x.items()}, o8 is not o9


def stats(trades, title, key):
    """trades: [(date, ret)]"""
    if len(trades) < 15:
        print(f"  {title:44s} {len(trades)}건 (적음)"); return
    v = np.array([t[1] for t in trades])
    a = [t[1] for t in trades if t[0] < HALF]; b = [t[1] for t in trades if t[0] >= HALF]
    bd = defaultdict(float)
    for d, x in trades: bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    w, l = v[v > 0], v[v <= 0]
    ok = "★" if a and b and np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
    print(f"  {ok}{title:44s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+7.0f}만 "
          f"최고5일 빼면 {sum(s[5:]) * 100:+6.0f}만 | 앞 {np.mean(a) if a else 0:+.2%} 뒤 {np.mean(b) if b else 0:+.2%} "
          f"| 손익비 {(w.mean() / -l.mean()) if len(w) and len(l) else 0:.2f} 낙폭 {mdd * 100:.0f}만")


def run_a(rows, label):
    print(f"\n=== {label}: 대상 {len(rows)}건 {len({r['date'] for r in rows})}일")
    for mode, mname in (("reg", "정규장 종가 매수"), ("any", "17시 이후 처음 종가 위"), ("rebreak", "17시 이후 종가 재돌파 (영상)")):
        res = defaultdict(list); n_e = 0; n_stop = 0; n_pre = 0
        for r in rows:
            e = entry(r, mode)
            if not e:
                continue
            for split in ((False, True) if mode != "reg" else (False,)):
                buy = split_entry(r, e) if split else e["px"]
                st = evening_stop(e) if mode != "reg" else None
                ex = exits(r, buy)
                if ex is None:
                    continue
                xs, haspre = ex
                if not split:
                    n_e += 1; n_stop += st is not None; n_pre += haspre
                tag = " · 3분할 매수" if split else ""
                for k, v in xs.items():
                    res[k + tag].append((r["date"], v))
                    sv = (st / buy - 1 - COST) if st is not None else v
                    res[k + tag + " · 저가 이탈 손절"].append((r["date"], sv))
        print(f" -- {mname}: 진입 {n_e}건, 저녁 손절 {n_stop}건, 프리마켓 봉 있음 {n_pre}건")
        for k in sorted(res, key=lambda k: ("3분할" in k, "손절" in k, k)):
            if mode == "reg" and "손절" in k:
                continue
            if "3분할 매수" in k and "손절" not in k:
                continue
            stats(res[k], k, k)


def run_b(rows, label, tpmode="prevhigh", tend=time(10, 0)):
    tr = []
    for r in rows:
        nb = r["n_bars"]; reg = [b for b in nb if b[0] >= time(9, 0)]
        if not reg or reg[0][0] > time(9, 5):
            continue
        o9, pc = reg[0][1], r["close"]
        if o9 <= pc:
            continue
        dipped = False; buy = None
        for i, b in enumerate(reg):
            if b[0] > time(10, 0):
                break
            if b[4] < pc:           # 전일 종가 이탈 → 그날은 안 함
                break
            if i > 0 and b[3] < o9:
                dipped = True
            if dipped and b[4] > o9:
                buy = b[4]; rest = reg[i + 1:]; break
        if buy is None:
            continue
        tp = r["high"] if (tpmode == "prevhigh" and r["high"] > buy * 1.01) else buy * 1.05
        sl = buy * 0.98; out = None
        for b in rest:
            if b[0] > tend:
                break
            if b[3] <= sl:
                out = min(b[1], sl); break
            if b[2] >= tp:
                out = max(b[1], tp); break
        if out is None:
            out = at(reg, tend) or reg[-1][4]
        tr.append((r["date"], out / buy - 1 - COST))
    stats(tr, label, label)


if __name__ == "__main__":
    A10 = [r for r in R if is_a(r)]
    run_a(A10, "A 영상 그대로: 대금 10위 · +8%↑(삼전·하닉 +3%)")
    run_a([r for r in A10 if r["kchg"] is not None and r["kchg"] < 0], "A · 코스피 하락한 날만 (영상: 지수 빠지는데 강한 종목)")
    run_a([r for r in A10 if r["pchg"] is not None and r["pchg"] >= 0.08 and r["prk"]], "A · 연속성 (전날도 대금 30위 · +8%↑)")
    run_a([r for r in R if is_a(r, top=30)], "A 넓힘: 대금 30위 · +8%↑")
    run_a([r for r in R if r["rk"] <= 10 and r["chg"] < 0.295], "참고: 지금 규칙 대상 (대금 10위 · 상승 마감)")
    print("\n=== 장세별 (A 영상 그대로, 재돌파 · 09:00 시가 매도)")
    for lab, g in (("코스피 월봉 신고가 구간", lambda r: FEST.get(r["date"])), ("그 밖 (박스·하락)", lambda r: not FEST.get(r["date"]))):
        tr = []
        for r in A10:
            if not g(r):
                continue
            e = entry(r, "rebreak")
            ex = e and exits(r, e["px"])
            if ex:
                tr.append((r["date"], ex[0]["09:00 시가"]))
        stats(tr, lab, lab)
    print("\n=== B 시가 지지 돌파 (D+1 09:00~10:00, A 대상)")
    run_b(A10, "B 목표 전일 고가 · −2% · 10:00 정리")
    run_b(A10, "B 목표 +5% · −2% · 10:00 정리", "fixed")
    run_b(A10, "B 목표 전일 고가 · −2% · 15:19 정리", tend=time(15, 19))
    run_b([r for r in R if is_a(r, top=30)], "B (대금 30위 · +8%↑) 목표 전일 고가 · 10:00")
