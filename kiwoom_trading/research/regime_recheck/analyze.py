"""장중 재판정 → 4️⃣ 역행 강세 종가 켜기 — 2단계: 집계·계좌 시뮬 (2026-11-06, 복기 노트 후보 A).

입력: data/regime_recheck/days.pkl (build.py). 출력: data/regime_recheck/report.txt
기존(지금 운영) = 09:10 또는 09:20 강한 하락장. 새로 켜지는 날 = 그 둘 다 아니고(매매표 regime_feat 09:10 D 도 아님) T 시각 재판정이 강한 하락장.
계좌: strict_select.choose.real_sim (10만·종목당 3만·1주 넘으면 1주·예수금, 지금 실전 6️⃣📕5️⃣4️⃣1️⃣2️⃣🌙, B안 선정) — up_open_review 와 같은 설정.
      새로 켜지는 날의 4️⃣ (실전 = 고가 부근 조건 없음) 만 더한다. 1년(2025-10-16~2026-10-22) + 최근 63거래일.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.regime_recheck.analyze
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest.playbook.regime import cls
from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select import choose as C

DATA = S.DATA
OUT = os.path.join(DATA, "regime_recheck")
SPLIT = date(2026, 4, 20)
RECENT = date(2026, 8, 1)
T910, T920 = time(9, 10), time(9, 20)
RECHECK = [time(14, 0), time(14, 30), time(15, 0), time(15, 15)]
REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}
rep = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(str(s) + "\n"); rep.flush()


def stats(tr):
    """tr = [(date, ret)] → 요약 dict. 합계는 건당 100만 원 기준(만 원)."""
    if not tr:
        return dict(n=0, days=0, mean=0, sum=0, a=None, b=None, rec=None, nrec=0, top5d=0, top3=None, star=False)
    v = np.array([r for _, r in tr]); bd = defaultdict(float)
    for d, r in tr: bd[d] += r
    a = [r for d, r in tr if d < SPLIT]; b = [r for d, r in tr if d >= SPLIT]; rc = [r for d, r in tr if d >= RECENT]
    s = sorted(bd.values(), reverse=True)
    top3 = np.mean(sorted(v)[:-3]) if len(v) > 3 else None
    star = bool(a and b and np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0)
    return dict(n=len(v), days=len(bd), mean=v.mean(), sum=v.sum() * 100, a=np.mean(a) if a else None, b=np.mean(b) if b else None,
                nb=len(b), na=len(a), rec=np.mean(rc) if rc else None, nrec=len(rc), top5d=sum(s[5:]) * 100, top3=top3, star=star, win=np.mean(v > 0))


def f(x):
    return "  —  " if x is None else f"{x:+.2%}"


def line(lab, tr):
    s = stats(tr)
    say(f" {'★' if s['star'] else ' '} {lab:40s} {s['n']:4d}건 {s['days']:3d}일 건당 {f(s['mean'])} 합계 {s['sum']:+5.0f}만 "
        f"| 앞 {f(s['a'])}({s.get('na', 0)}) 뒤 {f(s['b'])}({s.get('nb', 0)}) | 8월~ {f(s['rec'])}({s['nrec']}) "
        f"| 최고5일 빼면 {s['top5d']:+5.0f}만 · 최고3건 빼면 건당 {f(s['top3'])} | 승률 {s.get('win', 0):.0%}")
    return s


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    D = pickle.load(open(os.path.join(OUT, "days.pkl"), "rb"))
    by = {x["date"]: x for x in D}
    days = sorted(by)
    fd = lambda d: cls(d) == "D"
    base = {d for d in days if by[d]["reg"][T910]["down"] or by[d]["reg"][T920]["down"]}
    b910 = {d for d in days if by[d]["reg"][T910]["down"]}
    feat_d = {d for d in days if fd(d)}
    say(f"기간 {days[0]} ~ {days[-1]} {len(days)}일 (마지막 날 11-05 는 다음 날 시가가 아직 없어 결과 제외)")
    say(f"09:10 강한 하락장(재계산) {len(b910)}일 / 09:10 또는 09:20(운영 규칙) {len(base)}일 / 매매표 regime_feat 09:10 D {len(feat_d)}일 "
        f"(재계산 09:10 과 겹침 {len(b910 & feat_d)}일, regime_feat 에만 {len(feat_d - b910)}일, 재계산에만 {len(b910 - feat_d - {d for d in days if not cls(d)})}일)")
    on = base | feat_d

    say("\n## 1. 재판정 시각별 강한 하락장 날 수")
    say("   시각   그 시각 강한 하락장 | 새로 켜지는 날(09:10·09:20 아님) | 그중 마감 코스피 −1σ↓ 또는 마감 중앙 −1.5%↓")
    newd = {}
    for t in RECHECK:
        dn = {d for d in days if by[d]["reg"][t]["down"]}
        nw = sorted(dn - on)
        newd[t] = nw
        end = [d for d in nw if (by[d]["med_close"] or 0) <= -0.015 or (by[d]["kchg_close"] or 0) <= -0.02]
        say(f"   {t:%H:%M}  {len(dn):3d}일 | {len(nw):3d}일 | {len(end)}일")
    say("\n   새로 켜지는 날 목록 (14:30 기준, 코스피 마감 등락·마감 중앙값·14:30 z·중앙):")
    for d in newd[time(14, 30)]:
        r = by[d]["reg"][time(14, 30)]
        flags = "".join(t.strftime("%H%M ") if d in newd[t] else "  ·  " for t in RECHECK)
        say(f"     {d} 코스피 마감 {f(by[d]['kchg_close'])} 중앙 마감 {f(by[d]['med_close'])} | 14:30 z {r['z'] if r['z'] is None else round(r['z'], 2)} 중앙 {f(r['med'])} | 켜지는 시각 {flags}")

    say("\n## 2. 4️⃣ 역행 강세 종가 건당 (매수 = 15:30 종가, 매도 = 다음 날 09:00 시가, 비용 0.25%, 합계는 건당 100만)")
    pk = lambda ds, near=False: [(p["date"], p["ret"]) for d in ds for p in by[d]["picks"] if p["ret"] is not None and (not near or p["pos"] >= 0.8)]
    T0 = pickle.load(open(os.path.join(DATA, "strict_select", "trades_feat.pkl"), "rb"))
    old4 = [(t["date"], t["ret"]) for t in T0 if t["kind"] == "4️⃣"]
    say(" [기존 날 — 지금도 켜지는 날]")
    line("기존 날(09:10·09:20) 실전 조건 없이", pk(sorted(base)))
    line("기존 날(09:10·09:20) 모의 고가 부근 80%↑", pk(sorted(base), True))
    line("(참고) 계좌 시뮬 입력 4️⃣ (regime_feat D·일봉 순위)", old4)
    res = {}
    for t in RECHECK:
        say(f" [새로 켜지는 날 — {t:%H:%M} 재판정, {len(newd[t])}일]")
        res[t] = (line(f"{t:%H:%M} 새 날 실전 조건 없이", pk(newd[t])), line(f"{t:%H:%M} 새 날 모의 고가 부근 80%↑", pk(newd[t], True)))
    say("\n 새 날 4️⃣ 한 건씩 (14:30 기준):")
    for d in newd[time(14, 30)]:
        for p in by[d]["picks"]:
            say(f"     {d} {p['name']}({p['code']}) 대금 {p['rk']}위 {p['chg']:+.1%} 시장 대비 +{p['rel'] * 100:.1f}%p 고가 부근 {p['pos']:.0%} "
                f"{p['px']:,.0f}원 → {f(p['ret'])}")

    say("\n## 3. 계좌 시뮬 — 10만 실전 (종목당 3만·1주 넘으면 1주·예수금, 실전 6️⃣📕5️⃣4️⃣1️⃣2️⃣🌙, B안)")
    BASE_T = [t for t in C.apply(T0, C.ALT) if t["kind"] != "7️⃣"]
    DAYS1 = list(S.DAYS); SPLIT0 = S.SPLIT; last = DAYS1[-1]; d3 = DAYS1[-63]
    say(f"   기간 {DAYS1[0]} ~ {last} (다른 매매 기록이 여기까지), 최근 3달 = {d3} ~ (63거래일, 10만에서 다시 시작)")

    def add(ds, near=False, kind="4️⃣"):
        return [dict(date=d, t=time(15, 20), kind=kind, code=p["code"], px=p["px"], ret=p["ret"], rk=p["rk"], xt=None)
                for d in ds if d <= last for p in by[d]["picks"] if p["ret"] is not None and (not near or p["pos"] >= 0.8)]

    def acct(T, d_from=None, seed=100_000):
        if d_from:
            dd = [d for d in DAYS1 if d >= d_from]; S.DAYS = dd; S.SPLIT = dd[len(dd) // 2]
            T = [t for t in T if t["date"] >= d_from]
        r = C.real_sim(T, kinds=REAL, seed=seed)
        S.DAYS = DAYS1; S.SPLIT = SPLIT0
        return r

    def show(lab, T):
        a = acct(T); b = acct(T, d3)
        say(f"   {'★' if a['star'] else ' '} {lab:44s} {a['final']:>11,.0f}원 낙폭 {a['mdd']:.0%} 앞 {a['front']:+.0%} 뒤 {a['back']:+.0%} "
            f"| 4️⃣ {a['n'].get('4️⃣', 0):3d}건 {a['pnl'].get('4️⃣', 0):+9,.0f}원 | 3달 {b['final']:>9,.0f}원 (4️⃣ {b['n'].get('4️⃣', 0)}건 {b['pnl'].get('4️⃣', 0):+,.0f}원)")
        return a, b

    acc = {}
    acc["base"] = show("지금 (09:10 D 날만 4️⃣)", BASE_T)
    only920 = sorted(base - feat_d)
    acc["base920"] = show(f"지금 + 09:20 판정 날 {len([d for d in only920 if d <= last])}일 (운영과 같게)", BASE_T + add(only920))
    for t in RECHECK:
        acc[t] = show(f"+ {t:%H:%M} 재판정 새 날 4️⃣", BASE_T + add(only920) + add(newd[t]))
    say("   (4️⃣ 단독 10만 계좌 — 다른 매매 없이)")
    only4 = [t for t in BASE_T if t["kind"] == "4️⃣"] + add(only920)
    acc["solo"] = show("4️⃣ 단독 지금", only4)
    for t in RECHECK:
        acc[("solo", t)] = show(f"4️⃣ 단독 + {t:%H:%M} 새 날", only4 + add(newd[t]))

    say("\n## 4. 1천만 모의 계좌 (sim.run, 지금 모의 배분·PICK 선정, 3️⃣ 뺌) — 새 날 4️⃣ 고가 부근 80%↑ 만 더함")
    MOCK = C.apply(T0, C.PICK)
    r0 = S.run({"kinds": set(S.KINDS) - {"3️⃣"}}, trades=MOCK + add(only920, True))
    say(f"   지금: {r0['final'] / 1e4:,.0f}만 낙폭 {r0['mdd']:.1%}")
    for t in RECHECK:
        r = S.run({"kinds": set(S.KINDS) - {"3️⃣"}}, trades=MOCK + add(only920, True) + add(newd[t], True))
        say(f"   + {t:%H:%M}: {r['final'] / 1e4:,.0f}만 낙폭 {r['mdd']:.1%} (4️⃣ {r['n_k'].get('4️⃣', 0)}건)")

    say("\n## 5. 11-05 (복기 사례)")
    x = by.get(date(2026, 11, 5))
    if x:
        for t, r in x["reg"].items():
            say(f"   {t:%H:%M} 코스피 {f(r['kchg'])} z {r['z']:+.2f} 대금 상위 중앙 {f(r['med'])} → {'강한 하락장' if r['down'] else '보통'}")
        for p in x["picks"]:
            say(f"   4️⃣ 후보 {p['name']}({p['code']}) 대금 {p['rk']}위 {p['chg']:+.1%} 시장 대비 +{p['rel'] * 100:.1f}%p 고가 부근 {p['pos']:.0%} 매수 {p['px']:,.0f}원")
    pickle.dump(dict(newd=newd, res=res, acc={str(k): (v[0]["final"], v[1]["final"], v[0]["mdd"]) for k, v in acc.items()}),
                open(os.path.join(OUT, "summary.pkl"), "wb"))


if __name__ == "__main__":
    main()
