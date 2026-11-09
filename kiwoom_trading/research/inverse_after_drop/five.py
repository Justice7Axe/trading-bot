"""2)·3) 5️⃣ 약세장 인버스 1년 재현 → 전날 코스피 구간별 성적 → 개선 후보 (매수 전에 아는 정보만).

5️⃣ 날 = 하락 흐름 보통 날(N-): regime.cls (2025-10-15~2026-10-23) + 10-23 뒤 스캐너 기록(10-26·11-02·11-05, 모두 약세장·강한 날 아님).
매매 = 09:11 첫 봉 시가 매수, +5% 익절 / −3% 손절(같은 봉이면 손절 먼저), 못 닿으면 다음 날 09:00 시가, 비용 0.05%.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.inverse_after_drop.five
결과: data/inverse_after_drop/five.txt, five.pkl
"""
import os
import pickle
import sys
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest.playbook.regime import cls, feat
from kiwoom_trading.research.inverse_after_drop import common as C

rep = open(os.path.join(C.OUT, "five.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(s + "\n"); rep.flush()


LIVE_N = [date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 5)]
KD = {r["date"]: r for r in C.idx_daily("001")}
KDAYS = sorted(KD)
KM = C.idx_min("001")


def kinfo(d):
    i = KDAYS.index(d)
    p1, p2 = KD[KDAYS[i - 1]], KD[KDAYS[i - 2]]
    k = KM.get(d, [])
    b11 = next((b for b in k if b["ts"].time() >= time(9, 11)), None)
    return dict(prev=p1["close"] / p2["close"] - 1, prev_oc=p1["close"] / p1["open"] - 1,
                gap=KD[d]["open"] / p1["close"] - 1,
                k0910=(b11["open"] / p1["close"] - 1) if b11 else None,       # 09:11 매수 순간 코스피 (전날 대비)
                run=(b11["open"] / KD[d]["open"] - 1) if b11 else None)        # 09:00→09:11 코스피


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    days = sorted([d for d in feat if cls(d) == "N-"] + LIVE_N)
    say(f"# 5️⃣ 약세장 인버스 재현 — 하락 흐름 보통 날 {len(days)}일 ({days[0]} ~ {days[-1]})")

    # 0. 재현 확인: 매매표 입력(trades_feat 5️⃣)과 같은가, 대용 인버스는 맞나
    T0 = pickle.load(open(os.path.join(C.DATA, "strict_select", "trades_feat.pkl"), "rb"))
    old = {t["date"]: t["ret"] for t in T0 if t["kind"] == "5️⃣"}
    rows = []
    for d in days:
        x, src, xt = C.trade(d)
        y, _, _ = C.trade(d, use_real=False)
        rows.append(dict(date=d, ret=x, src=src, xt=xt, proxy=y, **kinfo(d)))
    same = [r for r in rows if r["date"] in old]
    diff = [r for r in same if abs(r["ret"] - old[r["date"]]) > 1e-9]
    say(f"\n## 0. 재현 확인: 매매표 입력 5️⃣ {len(old)}건 중 같은 날 {len(same)}건, 수익률 다른 건 {len(diff)}건")
    for r in diff[:5]:
        say(f"   다름 {r['date']} 재현 {r['ret']:+.2%} 입력 {old[r['date']]:+.2%}")
    both = [r for r in rows if r["src"] == "real" and r["proxy"] is not None]
    say(f"   대용 인버스(코스피200 반대) 맞는지: 실제 1분봉 있는 {len(both)}건 실제 건당 {np.mean([r['ret'] for r in both]):+.2%} / 대용 {np.mean([r['proxy'] for r in both]):+.2%}, "
        f"상관 {np.corrcoef([r['ret'] for r in both], [r['proxy'] for r in both])[0, 1]:.2f}, 결과 방향(익절·손절·넘김) 같은 비율 "
        f"{np.mean([np.sign(r['ret']) == np.sign(r['proxy']) for r in both]):.0%}")
    say("   자료 종류: " + ", ".join(f"{s} {sum(1 for r in rows if r['src'] == s)}건" for s in ("real", "mix", "proxy")))
    say("   10-21 뒤 날: " + " / ".join(f"{r['date']:%m-%d} {r['ret']:+.2%}({r['src']})" for r in rows if r["date"] > date(2026, 10, 20)))
    r1105 = next(r for r in rows if r["date"] == date(2026, 11, 5))
    say(f"   ⚠️ 11-05 매수분: 11-06 은 장 시작이 09:02 로 늦고(코스피 −8% 급락) 첫 체결이 상한가 1,817원 → 09:33 까지 거래 없음. "
        f"그 가격으로 팔면 {r1105['ret']:+.1%}, 대용(지수 반대) {r1105['proxy']:+.1%}. 아래 표는 이 한 건을 대용 값으로 바꾼 것을 '11-05 보정' 으로 같이 보임.")
    for r in rows:
        r["ret_adj"] = r["proxy"] if r["date"] == date(2026, 11, 5) else r["ret"]
    pickle.dump(rows, open(os.path.join(C.OUT, "five.pkl"), "wb"))

    tr = lambda g, k="ret": [(r["date"], r[k]) for r in g if r[k] is not None]
    say("\n## 1. 5️⃣ 전체")
    say(f"  지금 규칙            {C.fmt(C.summ(tr(rows)))}")
    say(f"  11-05 보정           {C.fmt(C.summ(tr(rows, 'ret_adj')))}")
    say(f"  매매표 입력 기간만(~10-22) {C.fmt(C.summ(tr([r for r in rows if r['date'] <= date(2026, 10, 22)])))}")

    say("\n## 2. 전날 코스피 구간별 5️⃣ (11-05 보정 값)")
    BINS = [("≤ −3%", -9, -0.03), ("−3 ~ −2%", -0.03, -0.02), ("−2 ~ −1%", -0.02, -0.01), ("−1 ~ 0%", -0.01, 0), ("0 ~ +1%", 0, 0.01), ("> +1%", 0.01, 9),
            ("≤ −2% 누적", -9, -0.02), ("≤ −1.5% 누적", -9, -0.015), ("≤ −1% 누적", -9, -0.01), ("> −1% 누적", -0.01, 9), ("> −2% 누적", -0.02, 9)]
    for lab, lo, hi in BINS:
        g = [r for r in rows if lo < r["prev"] <= hi]
        say(f"  {lab:14s} {C.fmt(C.summ(tr(g, 'ret_adj')))}")
    say("\n  전날 −2%↓ 다음 날 5️⃣ 하나씩:")
    for r in rows:
        if r["prev"] <= -0.02:
            say(f"   {r['date']} 전날 코스피 {r['prev']:+.1%} (전날 시가→종가 {r['prev_oc']:+.1%}) 오늘 갭 {r['gap']:+.1%} 09:11 {r['k0910']:+.1%} → 5️⃣ {r['ret_adj']:+.2%} "
                  f"{'손절' if r['xt'] and r['ret'] < 0 else '익절' if r['xt'] else '다음 날 시가'} ({r['src']})")

    say("\n## 3. 오늘 시가 갭 방향 × 전날 (11-05 보정)")
    for lab, f in (("전날 ≤ −2% & 오늘 갭 ≥ 0 (반등 출발)", lambda r: r["prev"] <= -0.02 and r["gap"] >= 0),
                   ("전날 ≤ −2% & 오늘 갭 < 0 (또 빠짐)", lambda r: r["prev"] <= -0.02 and r["gap"] < 0),
                   ("전날 > −2% & 오늘 갭 ≥ 0", lambda r: r["prev"] > -0.02 and r["gap"] >= 0),
                   ("전날 > −2% & 오늘 갭 < 0", lambda r: r["prev"] > -0.02 and r["gap"] < 0),
                   ("오늘 갭 ≥ +1%", lambda r: r["gap"] >= 0.01), ("오늘 갭 < +1%", lambda r: r["gap"] < 0.01),
                   ("09:00→09:11 코스피 + (장 초 반등 중)", lambda r: r["run"] is not None and r["run"] > 0),
                   ("09:00→09:11 코스피 − ", lambda r: r["run"] is not None and r["run"] <= 0),
                   ("전날 장중에 빠짐(전날 시가→종가 ≤ −1.5%)", lambda r: r["prev_oc"] <= -0.015),
                   ("전날 장중 −1.5% 안", lambda r: r["prev_oc"] > -0.015)):
        say(f"  {lab:38s} {C.fmt(C.summ(tr([r for r in rows if f(r)], 'ret_adj')))}")

    say("\n## 4. 매수 시각·익절/손절 바꾸기 (같은 날, 11-05 는 대용 값)")
    res = {}
    for lab, kw in (("09:11 +5/−3 (지금)", dict()), ("09:30 +5/−3", dict(entry=time(9, 30))), ("10:00 +5/−3", dict(entry=time(10, 0))),
                    ("10:30 +5/−3", dict(entry=time(10, 30))), ("11:00 +5/−3", dict(entry=time(11, 0)))):
        out = []
        for r in rows:
            x, src, xt = C.trade(r["date"], **kw)
            if r["date"] == date(2026, 11, 5):
                x, _, xt = C.trade(r["date"], use_real=False, **kw)
            if x is not None:
                out.append(dict(date=r["date"], ret=x, xt=xt, prev=r["prev"], t=kw.get("entry", time(9, 11))))
        res[lab] = out
        ex = [(o["date"], o["ret"]) for o in out if o["prev"] <= -0.02]
        say(f"  {lab:20s} 전체 {C.fmt(C.summ([(o['date'], o['ret']) for o in out]))}")
        say(f"  {'':20s} 전날 ≤ −2% {C.fmt(C.summ(ex))}")
        say(f"  {'':20s} 전날 > −2% {C.fmt(C.summ([(o['date'], o['ret']) for o in out if o['prev'] > -0.02]))}")
    pickle.dump(res, open(os.path.join(C.OUT, "five_entry.pkl"), "wb"))

    say("\n## 5. 개선 후보 (전날 코스피 −X% 이하면 안 삼 / 그날만 늦게 삼) — 남는 쪽 / 빠지는 쪽 (11-05 보정)")
    base = {o["date"]: o for o in res["09:11 +5/−3 (지금)"]}
    late = {o["date"]: o for o in res["10:00 +5/−3"]}
    late30 = {o["date"]: o for o in res["09:30 +5/−3"]}
    cands = []
    for X in (-0.015, -0.02, -0.03):
        keep = [(d, o["ret"]) for d, o in base.items() if o["prev"] > X]
        drop = [(d, o["ret"]) for d, o in base.items() if o["prev"] <= X]
        say(f"  전날 ≤ {X:+.1%} 안 삼   남는 {C.fmt(C.summ(keep))}")
        say(f"  {'':18s} 빠지는 {C.fmt(C.summ(drop))}")
        cands.append((f"skip{X}", {d for d, _ in drop}))
    for X in (-0.02, -0.03):
        mix = [(d, (late[d]["ret"] if o["prev"] <= X and d in late else o["ret"])) for d, o in base.items()]
        say(f"  전날 ≤ {X:+.1%} 면 10:00 매수 {C.fmt(C.summ(mix))}")
        mix = [(d, (late30[d]["ret"] if o["prev"] <= X and d in late30 else o["ret"])) for d, o in base.items()]
        say(f"  전날 ≤ {X:+.1%} 면 09:30 매수 {C.fmt(C.summ(mix))}")
    g2 = {r["date"] for r in rows if r["prev"] <= -0.02 and r["gap"] >= 0}
    keep = [(d, o["ret"]) for d, o in base.items() if d not in g2]
    say(f"  전날 ≤ −2% & 오늘 갭 ≥ 0 안 삼 남는 {C.fmt(C.summ(keep))}")
    say(f"  {'':24s} 빠지는 {C.fmt(C.summ([(d, o['ret']) for d, o in base.items() if d in g2]))}")


if __name__ == "__main__":
    main()
