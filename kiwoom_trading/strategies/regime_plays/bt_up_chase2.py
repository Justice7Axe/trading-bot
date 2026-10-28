"""1️⃣ 상승장 장 초 — '신호가 +1% 넘으면 추격 안 함' 대신 다른 걸러내기 규칙 1년 시험 (2026-10-28 사용자).

사용자: "신호가보다 +1% 넘으면 추격 안 함은 너무 단편적. 09:10~09:30 은 강세장에서 괜찮은 시간대이고 15% 처럼 이미 많이 오른 상태가 아니잖아."

후보 = bt_up_chart_exits.py 와 같음 (u_cands.pkl: 강한 상승장 U 날 09:10 대금 40위·시가 위·전날 외인·기관 둘 다 − 제외).
신호가 = 09:10 봉 종가. 매수 = 신호 뒤 n분 봉 시가 (n=1 → 09:11 시가, n=2 → 09:12 시가 …), 상한가 근처(+29%↑) 못 삼.
매도: 손절 −4%(−6% 도) 닿으면 그 가격(시가가 이미 아래면 시가), 아니면 다음 날 09:00 시가. 익절 없음. 비용 0.25%. 15:19 봉까지 장중 확인.
전일 종가 = 그 종목 전날 1분봉 정규장 마지막 종가 (일봉은 9-14 이후 20:00 통합값이라 안 씀), 두 날 가격 기준 다르면 factor 비율로 맞춤.
  전날 1분봉이 없으면 오늘 시가 ÷ (1+갭) 으로 대신 (건수 표시).
걸러내기 규칙 (매수 시점 가격 = 그 봉 시가 기준, 그때 아는 값만):
  R0 없음 / R1 신호가 +1% 넘으면 안 삼 (지금) / R2 +2%, +3% / R3 전일 종가 대비 +10/15/20% 넘으면 안 삼
  R4 당일 시가 대비 +5/8/10% 넘으면 안 삼 / R5 R3(15%) 또는 R1 중 하나라도 걸리면 안 삼
기준선: n=1 (09:11 시가)·R0·−4% = bt_up_chart_exits '숫자 −4% · T1' 619건 건당 +0.85% 와 같아야 함.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.regime_plays.bt_up_chase2 → data/backtest/up_chase2.txt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import date, time, datetime, timedelta

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load
from kiwoom_trading.strategies.regime_plays.bt_up_chart_exits import prev_regular

OUT = os.path.join(E.DATA, "backtest"); os.makedirs(OUT, exist_ok=True)
UNTIL = time(15, 19)
F = open(os.path.join(OUT, "up_chase2.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def run_exit(b, j, buy, nx, stop):
    sp = buy * (1 - stop)
    for x in b[j:]:
        if x[0] > UNTIL: break
        if x[3] <= sp:
            return min(x[1], sp) / buy - 1 - E.COST
    return nx


RULES = [  # (이름, 함수(t) → True 면 안 삼)
    ("R0 없음", lambda t: False),
    ("R1 신호가 +1% 넘으면 안 삼(지금)", lambda t: t["ch"] > 0.01),
    ("R2 신호가 +2%", lambda t: t["ch"] > 0.02),
    ("R2 신호가 +3%", lambda t: t["ch"] > 0.03),
    ("R3 전일 종가 +10%", lambda t: t["fp"] > 0.10),
    ("R3 전일 종가 +15%", lambda t: t["fp"] > 0.15),
    ("R3 전일 종가 +20%", lambda t: t["fp"] > 0.20),
    ("R4 당일 시가 +5%", lambda t: t["fo"] > 0.05),
    ("R4 당일 시가 +8%", lambda t: t["fo"] > 0.08),
    ("R4 당일 시가 +10%", lambda t: t["fo"] > 0.10),
    ("R5 R3(15%) 또는 R1", lambda t: t["fp"] > 0.15 or t["ch"] > 0.01),
]
SHORT = ["R0 없음", "R1 신호가 +1% 넘으면 안 삼(지금)", "R2 신호가 +2%", "R3 전일 종가 +15%", "R4 당일 시가 +8%", "R5 R3(15%) 또는 R1"]
PLAN = {1: SHORT, 2: [r[0] for r in RULES], 3: SHORT, 5: SHORT}   # 시험 조합 = 6+11+6+6 = 29
NS = (1, 2, 3, 4, 5)


def stats(tr, title, w=34):
    """tr = [(date, ret)]."""
    if len(tr) < 5:
        say(f"   {title:{w}s} {len(tr):4d}건 (적음)" + (f" 건당 {np.mean([x for _, x in tr]):+.2%}" if tr else "")); return None
    ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; bb = [x for d, x in tr if d >= h]
    bd = defaultdict(list)
    for d, x in tr: bd[d].append(x)
    dr = {d: np.mean(x) for d, x in bd.items()}
    s = sorted(dr.values(), reverse=True)
    eq = np.cumsum([dr[d] for d in sorted(dr)]) * 1000
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    say(f" {star} {title:{w}s} {len(v):4d}건 {len(dr):2d}일 건당 {v.mean():+.2%} | 앞 {np.mean(a):+.2%} 뒤 {np.mean(bb):+.2%} | "
        f"1천만/일 {sum(s) * 1000:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 1000:+5.0f}만 낙폭 {mdd:4.0f}만")
    return dict(n=len(v), mean=v.mean(), tot=sum(s) * 1000)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    say(f"1️⃣ 후보 {len(sel)}건 {len({r['date'] for r in sel})}일 ({min(r['date'] for r in sel)} ~ {max(r['date'] for r in sel)}), 1분봉 출처 {E.P0}~{E.P1}")
    T = {n: [] for n in NS}; miss = defaultdict(int); base = []
    for r in sel:
        d, c = r["date"], r["code"]
        b = E.regular(E.bars(c, d))
        idx = {x[0]: i for i, x in enumerate(b)}
        if not all(t in idx for t in (time(9, 10), time(9, 11))):
            miss["09:10~11 봉 없음"] += 1; continue
        pc0 = b[0][1] / (1 + r["gap"])
        pc, _ = prev_regular(c, d)
        if pc is None:
            miss["전날 1분봉 없음 → 갭으로 전일 종가"] += 1; pc = pc0
        sig = b[idx[time(9, 10)]][4]; o0 = b[0][1]
        # 기준선 (bt_up_chart_exits 와 같은 걸러짐: 09:11 시가 기준 상한가 근처, 다음 날 09:00)
        buy11 = b[idx[time(9, 11)]][1]
        if buy11 / pc0 - 1 < 0.29:
            nx = E.next_day_exits(c, d, buy11).get("09:00 시가")
            if nx is not None:
                base.append((d, run_exit(b, idx[time(9, 11)], buy11, nx, 0.04)))
        for n in NS:
            tt = time(9, 10 + n)
            if tt not in idx:
                miss[f"n={n} 봉 없음"] += 1; continue
            j = idx[tt]; buy = b[j][1]
            if buy / pc0 - 1 >= 0.29:
                miss[f"n={n} 상한가 근처"] += 1; continue
            nx = E.next_day_exits(c, d, buy).get("09:00 시가")
            if nx is None:
                miss[f"n={n} 다음 날 09:00 없음"] += 1; continue
            T[n].append(dict(d=d, c=c, ch=buy / sig - 1, fp=buy / pc - 1, fo=buy / o0 - 1,
                             s4=run_exit(b, j, buy, nx, 0.04), s6=run_exit(b, j, buy, nx, 0.06)))
    say("빠진 것: " + ", ".join(f"{k} {v}" for k, v in sorted(miss.items())))
    say("\n[기준선] 09:11 시가·걸러내기 없음·손절 −4% (bt_up_chart_exits '숫자 −4% · T1' 619건 +0.85% 와 같아야 함)")
    stats(base, "기준선 재현")

    say("\n[매수 시점 가격 분포] (중앙값 / 넘는 비율)")
    for n in NS:
        tt = T[n]; ch = np.array([t["ch"] for t in tt]); fp = np.array([t["fp"] for t in tt]); fo = np.array([t["fo"] for t in tt])
        say(f"  n={n} (09:{10 + n} 시가) {len(tt)}건 | 신호가 대비 중앙 {np.median(ch):+.2%}, >+1% {np.mean(ch > .01):.0%} >+2% {np.mean(ch > .02):.0%} >+3% {np.mean(ch > .03):.0%}"
            f" | 전일 종가 대비 중앙 {np.median(fp):+.1%}, >10% {np.mean(fp > .1):.0%} >15% {np.mean(fp > .15):.0%} >20% {np.mean(fp > .2):.0%}"
            f" | 당일 시가 대비 중앙 {np.median(fo):+.1%}, >5% {np.mean(fo > .05):.0%} >8% {np.mean(fo > .08):.0%} >10% {np.mean(fo > .1):.0%}")

    say(f"\n시험한 조합 {sum(len(v) for v in PLAN.values())}개 (매수 시점 n=1·3·5 × 규칙 6개 + n=2 × 규칙 11개), 각각 손절 −4%·−6% 두 가지로 봄.")
    say("같은 619건에서 여러 규칙을 골라 본 것이라 가장 좋은 하나는 우연으로 좋아 보일 수 있음 (특히 걸러지는 건수가 수십 건뿐인 규칙).")
    rn = dict(RULES)
    for n in (2, 1, 3, 5):
        for stop in ("s4", "s6"):
            say("\n" + "=" * 150)
            say(f"n={n} → 09:{10 + n} 시가 매수, 손절 {'−4%' if stop == 's4' else '−6%'} — 산 것 / (걸러진 것을 샀다면)")
            say("=" * 150)
            tt = T[n]
            for name in PLAN[n]:
                f = rn[name]
                stats([(t["d"], t[stop]) for t in tt if not f(t)], name)
                if name != "R0 없음":
                    stats([(t["d"], t[stop]) for t in tt if f(t)], "   └ 걸러진 것")
    # 참고: n=4 는 R0·R1·R3(15)·R5 만, 조합 수에 안 넣음
    say("\n[참고] n=4 (09:14 시가), 손절 −4%")
    for name in ("R0 없음", "R1 신호가 +1% 넘으면 안 삼(지금)", "R3 전일 종가 +15%", "R5 R3(15%) 또는 R1"):
        stats([(t["d"], t["s4"]) for t in T[4] if not rn[name](t)], name)
    pickle.dump(T, open(os.path.join(E.TMP, "up_chase2_T.pkl"), "wb"))


# ---------------- 10-28 예시 ----------------
def examples():
    B = pickle.load(open(os.path.join(E.DATA, "leader_capture", "bars_krx.pkl"), "rb"))
    d, p = date(2026, 10, 28), date(2026, 10, 27)
    say("\n" + "=" * 150)
    say("10-28 예시 (KRX 1분봉, 다음 날 09:00 아직 없음 → 오늘 정규장 종가로 셈, 손절 −4%)")
    say("=" * 150)
    for c, nm, real in (("010170", "대한광통신", (time(9, 12, 32), 0.011)), ("069540", "빛과전자", (None, 0.030))):
        b = [(x[0].time(), *x[1:]) for x in B[(c, d)] if time(9, 0) <= x[0].time() <= time(15, 30)]
        pb = B.get((c, p))
        if pb is None:
            try:
                from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
                from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
                pb = [(x["ts"], x["open"], x["high"], x["low"], x["close"], x["volume"]) for x in fetch_minute_bars(build_client(), c, p, "KRX")]
            except Exception as e:
                say(f"{nm} 전날 1분봉 못 받음: {e}"); pb = []
        pr = [x for x in pb if time(9, 0) <= x[0].time() <= time(15, 30)]
        pc = pr[-1][4] if pr else None
        idx = {x[0]: i for i, x in enumerate(b)}
        sig = b[idx[time(9, 10)]][4]; o0 = b[0][1]; close = b[-1][4]
        say(f"\n{nm}({c}): 첫 봉 {b[0][0]} 시가 {o0:,} | 전일 종가(1분봉) {pc:,} | 신호가(09:10 종가) {sig:,} ({sig / pc - 1:+.1%}) | 정규장 종가 {close:,} ({b[-1][0]})"
            f" | 09:10 뒤 최저 {min(x[3] for x in b[idx[time(9, 11)]:]):,} 최고 {max(x[2] for x in b[idx[time(9, 11)]:]):,}")
        def first_at(t):   # 그 시각 봉이 없으면(VI 등) 그 뒤 첫 봉
            return next(i for i, x in enumerate(b) if x[0] >= t)
        pts = []
        for n in (1, 2, 3):
            j = first_at(time(9, 10 + n))
            pts.append((f"09:{10 + n} 시가" + ("" if b[j][0] == time(9, 10 + n) else f"(봉 없음→{b[j][0].strftime('%H:%M')})"), b[j][1], j))
        pts.append((f"실제 시도 (신호가 {real[1]:+.1%})", sig * (1 + real[1]), first_at(time(9, 12)) if real[0] else first_at(time(9, 11))))
        for lbl, buy, j in pts:
            t = dict(ch=buy / sig - 1, fp=buy / pc - 1, fo=buy / o0 - 1)
            sp = buy * 0.96; ret = None
            for x in b[j:]:
                if x[0] > UNTIL: break
                if x[3] <= sp:
                    ret = (min(x[1], sp) / buy - 1 - E.COST, x[0]); break
            r = ret[0] if ret else close / buy - 1 - E.COST
            lab = {"R0 없음": "R0", "R1 신호가 +1% 넘으면 안 삼(지금)": "R1", "R5 R3(15%) 또는 R1": "R5"}
            buyset = [lab.get(nm_, nm_.split()[0] + nm_.split()[-1]) for nm_, f in RULES if not f(t)]
            say(f"  {lbl:24s} {buy:8,.0f} | 신호가 {t['ch']:+.1%} 전일 종가 {t['fp']:+.1%} 당일 시가 {t['fo']:+.1%} | 결과 {r:+.1%}"
                + (f" (손절 {ret[1]})" if ret else " (종가까지 보유)") + f" | 사는 규칙: {', '.join(buyset)}")


if __name__ == "__main__":
    main()
    examples()
    F.close()
