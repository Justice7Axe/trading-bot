"""시장 분위기 판정 시각 재검증 (2026-11-01 사용자 '9시 10분은 너무 늦지 않나? 강한 상승·하락 판단에 좋은 시점인지 재검증, 틀리면 좋은 시각도').

판정값: 그 시각까지 끝난 1분봉 기준, 전날 대금 300위 주식(우선주 제외)의 전일 대비 등락 중앙값 M_T.
시각마다 '강한 상승'·'강한 하락' 날 수를 지금 09:10 규칙과 같게(상위 40일·하위 47일) 맞춰 비교 (경계값은 1년 분포 — 시각끼리 공정 비교용).
1) 맞히기: 실제 날 = 15:30 종가 기준 같은 중앙값 상위 40일(강한 상승)·하위 47일(강한 하락). 정밀도·재현율.
2) 매매: 1️⃣ 상승장 장 초 — 강한 상승 판정 시각 T 다음 봉 시가에 그 시각 누적 대금 40위 & 시가 위 종목 매수, −4% 손절, 다음 날 09:00 매도.
         5️⃣ 약세장 인버스 — 보통·약세(52주 −10% 밖) 판정 날 T 다음 봉 TIGER 인버스 매수 +5/−3, 다음 날 09:00.
         4️⃣ 역행 강세 종가 — 15:15 대금 30위 & 시장 중앙 대비 +3%p, 정규장 종가 매수 → 다음 날 09:00. 판정 시각은 매수와 무관하므로 '어느 시각 판정이 4️⃣ 좋은 날을 고르나'만 봄.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/regime_timing/timing.py
"""
import os, pickle, sys
from datetime import time
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.paths import pb
from kiwoom_trading.backtest.playbook.regime import cls, feat as RF

OUT = os.path.join(E.DATA, "regime_timing"); os.makedirs(OUT, exist_ok=True)
TS = [time(8, 50), time(9, 0), time(9, 3), time(9, 5), time(9, 10), time(9, 15), time(9, 20), time(9, 30), time(10, 0)]
TS_ALL = TS + [time(15, 15)]            # 15:15 는 4️⃣ 역행 강세 종가 판정용 (매수 직전)
TOPN, NU, ND = 300, 40, 47


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep("report.txt")
lab = lambda t: t.strftime("%H:%M")


def price_at(b, t):
    """t 시각까지 끝난 봉의 종가. 09:00 은 정규장 시가, 08:50 은 프리장 마지막 값."""
    if t == time(9, 0):
        x = next((y for y in b if time(9, 0) <= y[0] <= time(9, 5)), None)
        return x[1] if x else None
    x = [y for y in b if y[0] < t]
    return x[-1][4] if x else None


def build():
    days = [d for d in E.days() if E.next_day(d)]
    per_day, picks = {}, {}
    for d in days:
        pdv = E.value_rank(E.prev_day(d))
        prev = sorted((c for c in pdv if E.is_common(c)), key=lambda c: pdv[c])[:TOPN]
        codes = [c for c in prev if c in E._min_codes(d)]
        B = E.load_day(codes, d); pr = E.daily_day(E.prev_day(d))
        rets = {t: [] for t in TS_ALL}; close = []; info = {}
        for c in codes:
            b = B[c]; reg = E.regular(b)
            if len(reg) < 300: continue
            f = E.factor(c, d)
            if not f or c not in pr: continue
            pc = pr[c][3] * f
            if abs(reg[0][1] / pc - 1) > 0.31: continue
            for t in TS_ALL:
                p = price_at(b if t < time(9, 0) else reg, t)
                if p: rets[t].append(p / pc - 1)
            close.append(reg[-1][4] / pc - 1)
            info[c] = (reg, pc)
        per_day[d] = {t: np.median(v) if len(v) > 50 else np.nan for t, v in rets.items()}
        per_day[d]["close"] = np.median(close) if close else np.nan
        picks[d] = info
        print(d, len(info), file=sys.stderr)
    return per_day, picks


def up_trades(d, info, t):
    """1️⃣ 비슷: t 시각 누적 대금 40위 & 시가 위 → t 다음 봉 시가 매수, −4%, 다음 날 09:00."""
    cand = []
    for c, (reg, pc) in info.items():
        x = [y for y in reg if y[0] < t]
        if not x or t <= time(9, 0): continue
        cv = sum(y[4] * y[5] for y in x)
        if x[-1][4] > reg[0][1]: cand.append((cv, c))
    out = []
    for cv, c in sorted(cand, reverse=True)[:40]:
        b = E.bars(c, d)
        j = next((i for i, y in enumerate(b) if y[0] >= t), None)
        if j is None: continue
        r, _ = E.intraday_exit(b, j, b[j][1], stop=0.04, tp=None, hold=lambda _: True, c=c, d=d)
        out.append(r)
    return out


def contra_trades(d, info):
    """4️⃣ 비슷: 15:15 대금 30위 & 시장 중앙 대비 +3%p, 정규장 종가 매수 → 다음 날 09:00."""
    rows = []
    for c, (reg, pc) in info.items():
        x = [y for y in reg if y[0] < time(15, 15)]
        if not x: continue
        rows.append((sum(y[4] * y[5] for y in x), c, x[-1][4] / pc - 1, reg[-1][4]))
    if len(rows) < 50: return []
    med = np.median([r[2] for r in rows]); out = []
    for cv, c, ch, cl in sorted(rows, reverse=True)[:30]:
        if ch - med >= 0.03 and ch < 0.295:
            ex = E.next_day_exits(c, d, cl)
            if "09:00 시가" in ex: out.append(ex["09:00 시가"])
    return out


def inv_trade(inv, idays, d, t, tp=0.05, sl=0.03):
    if d not in inv or not inv[d]: return None
    i = idays.index(d)
    if i + 1 >= len(idays): return None
    bars = inv[d]; k = next((j for j, b in enumerate(bars) if b["ts"].time() >= t), None)
    if k is None: return None
    e = bars[k]["open"]
    for b in bars[k:]:
        if b["ts"].time() >= time(15, 20): break
        if b["low"] <= e * (1 - sl): return min(b["open"], e * (1 - sl)) / e - 1 - 0.0005
        if b["high"] >= e * (1 + tp): return max(b["open"], e * (1 + tp)) / e - 1 - 0.0005
    return inv[idays[i + 1]][0]["open"] / e - 1 - 0.0005


def main():
    cache = os.path.join(OUT, "per_day.pkl")
    per_day, picks = build()
    pickle.dump(per_day, open(cache, "wb"))
    days = sorted(per_day); hh = days[len(days) // 2]
    M = pd.DataFrame(per_day).T
    actual_u = set(M.close.nlargest(NU).index); actual_d = set(M.close.nsmallest(ND).index)
    R.say(f"표본 {len(days)}일 ({days[0]} ~ {days[-1]}), 반 나눔 {hh}. 실제 강한 상승 = 종가 중앙 상위 {NU}일(경계 {M.close.nlargest(NU).min():+.2%}), 강한 하락 = 하위 {ND}일(경계 {M.close.nsmallest(ND).max():+.2%})")
    cur_u = {d for d in days if cls(d) == "U"}; cur_d = {d for d in days if cls(d) == "D"}
    R.say(f"(지금 09:10 규칙 그대로: 강한 상승 {len(cur_u)}일 → 실제 맞힘 {len(cur_u & actual_u) / max(len(cur_u), 1):.0%} · 실제 중 잡음 {len(cur_u & actual_u) / NU:.0%} | "
          f"강한 하락 {len(cur_d)}일 → {len(cur_d & actual_d) / max(len(cur_d), 1):.0%} · {len(cur_d & actual_d) / ND:.0%})")

    R.say("\n## 1) 판정 시각별 맞히기 (같은 날 수로 맞춤) · 그 시각 판정과 종가 중앙값의 상관")
    sel = {}
    for t in TS_ALL:
        s = M[t].dropna()
        U = set(s.nlargest(NU).index); D = set(s.nsmallest(ND).index); sel[t] = (U, D)
        corr = np.corrcoef(s.values, M.loc[s.index, "close"].values)[0, 1]
        after = (M.loc[s.index, "close"] - s).values          # 그 시각 뒤 남은 움직임
        R.say(f"  {lab(t)}: 강한 상승 맞힘 {len(U & actual_u) / NU:.0%} · 강한 하락 맞힘 {len(D & actual_d) / ND:.0%} · 종가와 상관 {corr:.2f} · "
              f"판정 뒤 남은 움직임(강한 상승 판정 날) {np.mean([M.close[d] - s[d] for d in U]):+.2%} / (강한 하락 판정 날) {np.mean([M.close[d] - s[d] for d in D]):+.2%}")

    R.say("\n## 2) 1️⃣ 상승장 장 초 — 판정 시각 = 매수 시각 (강한 상승 판정 날만)")
    for t in TS[2:]:
        U = sel[t][0]; tr = []
        for d in sorted(U):
            for r in up_trades(d, picks[d], t): tr.append((d, r))
        v = np.array([r for _, r in tr]); a = np.mean([r for d, r in tr if d < hh]); b = np.mean([r for d, r in tr if d >= hh])
        R.say(f"  {lab(t)}: {len(v)}건 건당 {v.mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%}) 합계 {v.sum() * 25:+.0f}만(건당 25만)")

    R.say("\n## 3) 5️⃣ 약세장 인버스 — 그 시각 판정이 '강하지 않고 약세 국면'인 날, 그 시각 다음 봉 매수 +5/−3")
    inv = pickle.load(open(pb("inv_bars.pkl"), "rb")); idays = sorted(d for d in inv if inv[d])
    for t in TS[2:]:
        U, D = sel[t]; tr = []
        for d in days:
            if d in U or d in D or not (d in RF and RF[d]["dd52"] <= -0.10): continue
            x = inv_trade(inv, idays, d, t)
            if x is not None: tr.append((d, x))
        if not tr: continue
        v = np.array([x for _, x in tr]); a = np.mean([x for d, x in tr if d < hh] or [np.nan]); b = np.mean([x for d, x in tr if d >= hh] or [np.nan])
        R.say(f"  {lab(t)}: {len(v)}일 건당 {v.mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%}) 승률 {(v > 0).mean():.0%}")
    R.say("  (참고) 강한 하락 판정 날 인버스: " + " · ".join(
        f"{lab(t)} {np.mean([x for x in (inv_trade(inv, idays, d, t) for d in sel[t][1]) if x is not None]):+.2%}" for t in TS[2:]))

    R.say("\n## 4) 4️⃣ 역행 강세 종가 — 어느 시각 판정의 '강한 하락' 날이 4️⃣ 에 좋은가 (매수는 늘 종가)")
    ct = {d: contra_trades(d, picks[d]) for d in days}
    allv = [r for d in days for r in ct[d]]
    R.say(f"  모든 날 {len(allv)}건 {np.mean(allv):+.2%}")
    for t in TS_ALL:
        D = sel[t][1]; v = [r for d in D for r in ct[d]]; a = [r for d in D if d < hh for r in ct[d]]; b = [r for d in D if d >= hh for r in ct[d]]
        R.say(f"  {lab(t)}: {len(v)}건 건당 {np.mean(v):+.2%} (앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%})")
    v = [r for d in actual_d for r in ct[d]]
    R.say(f"  (참고: 장 마감 뒤 아는 실제 강한 하락 날) {len(v)}건 {np.mean(v):+.2%}  · 15:15 판정(매수 직전)도 위 표의 마지막 줄과 비교")


if __name__ == "__main__":
    main()
