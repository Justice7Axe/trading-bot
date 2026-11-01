"""🔺 홍인기 D+ — 1년 D+0 대장주·D+1 선정 종목과 뽑힌 이유 목록 (2026-11-02 사용자: '어떤 원리로 어떤 종목이 선정됐는지 1년치로').

D+0 (종가 기준): 그날 대금 20위 안 +5%↑ 3개↑ 테마 = 주도 섹터, 그 안 등락률 1위 = 대장, 그날 +10%↑ 장대양봉인 것.
  강의 걸러내기(최근 강세 섹터 · 과거 대장 · 장대양봉 뒤 2주 · 시총 5천억↑ · 신고가 근처 · 끼)를 ○/× 로 표시.
D+1: 그 대장의 다음 날 — 갭(+1%↑ 이어야 함), 같은 섹터 D+ 종목 중 시가 갭 1위인지, 전일 종가 +1% 지정가 체결·결과 (backtest.py 의 trades.pkl).
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.strategies.hong_dplus.leaders
  → data/hong_dplus/leaders_1y.txt · leaders_1y.csv
"""
import csv
import os
import pickle
import sys

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.hong_dplus import rules as R
from kiwoom_trading.strategies.hong_dplus.backtest import OUT, day_lead, first_big, kki, past_leader, recent_theme


def ox(b):
    return "○" if b else "×"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d0, d12 = pickle.load(open(os.path.join(OUT, "trades.pkl"), "rb"))
    d1 = {(r["date"], r["code"]): r for r in d12 if r["k"] == 1}
    f = open(os.path.join(OUT, "leaders_1y.txt"), "w", encoding="utf-8")
    rows = []

    def say(s=""):
        print(s); f.write(s + "\n")

    say("🔺 홍인기 D+ — 1년 D+0 대장주(종가 기준) · D+1 선정 (2025-10-16 ~ 2026-10-29)")
    say("D+0 규칙: 대금 20위 안 +5%↑ 종목 3개↑ 테마 = 주도 섹터 → 그 안 등락률 1위 = 대장, 그날 +10%↑ 장대양봉")
    say("강의 걸러내기: 최근=최근 20일 주도 섹터 / 과거대장=60일 안 대장 / 2주=앞 10일 장대양봉 없음 / 시총=5천억↑ / 고가=250일 고가 92%↑ / 끼=60일 안 3일 +25%")
    say("D+1: 갭 +1%↑ 출발 & 같은 섹터 D+ 종목 중 시가 갭 1위 → 전일 종가 +1% 지정가, 손절 전일 종가 −2%, 목표 시가, 아니면 다음 날 09:00\n")
    n0 = n_all = n1 = 0
    for d in E.days():
        nd = E.next_day(d)
        if not nd:
            continue
        lead, leaders = day_lead(d)
        vr = E.value_rank(d)
        for c, th in sorted(leaders.items(), key=lambda x: -E.chg(x[0], d)):
            ch = E.chg(c, d)
            if ch is None or ch < R.BIG:
                continue
            n0 += 1
            p = E.prev_day(d)
            hi = E.hi_n(c, d, 250)
            cl = E.daily_day(d)[c][3]
            fl = dict(최근=recent_theme(th, d), 과거대장=past_leader(c, d), 주2=first_big(c, d), 시총=E.mcap(c, p) >= R.MCAP_MIN,
                      고가=bool(hi and cl >= R.NEAR_HIGH * hi), 끼=kki(c, d))
            allok = all(fl.values()); n_all += allok
            mem = " · ".join(f"{E.NAME.get(m, m)} {mc:+.0%}" for m, mc in sorted(lead[th], key=lambda x: -x[1]))
            nx = E.daily_day(nd).get(c)
            nxt = nx[3] / cl - 1 if nx and cl else None
            r1 = d1.get((nd, c))
            if r1 is None:
                t1 = "D+1 자료 없음"
            elif r1["gap"] < 0.01:
                t1 = f"D+1 갭 {r1['gap']:+.1%} → 갭상승 아님, 안 삼"
            elif not r1["f_strong"]:
                t1 = f"D+1 갭 {r1['gap']:+.1%} → 같은 섹터에 더 강한 종목, 안 삼"
            elif r1["x_101"][0] is None:
                t1 = f"D+1 갭 {r1['gap']:+.1%} 섹터 1위 → 전일 종가 +1% 까지 안 눌려 못 삼"
            else:
                n1 += 1
                t1 = f"D+1 갭 {r1['gap']:+.1%} 섹터 1위 ✅ {r1['x_101_t']:%H:%M} 매수 → {r1['x_101'][0]:+.1%}" + (" (첫 장대양봉)" if r1["f_quiet"] else "")
            say(f"{d} {E.NAME.get(c, c)}({c}) {ch:+.1%} 대금 {vr.get(c)}위 시총 {E.mcap(c, p) / 1e12:.1f}조 [{th}] {len(lead[th])}개{'(초강세)' if len(lead[th]) >= 5 else ''}"
                f"{' ★강의 조건 전부' if allok else ''}")
            say(f"    섹터: {mem}")
            say("    걸러내기: " + " ".join(f"{k}{ox(v)}" for k, v in fl.items()) + (f" | 다음 날 종가 {nxt:+.1%}" if nxt is not None else ""))
            say(f"    {t1}")
            rows.append(dict(date=d, code=c, name=E.NAME.get(c, c), chg=round(ch, 4), value_rank=vr.get(c), theme=th, n=len(lead[th]),
                             members=mem, **{k: int(v) for k, v in fl.items()}, all_ok=int(allok),
                             next_close=None if nxt is None else round(nxt, 4), d1=t1))
    say(f"\n합계: D+0 대장(+10%↑) {n0}건, 강의 조건 전부 {n_all}건, D+1 실제 매수 {n1}건")
    with open(os.path.join(OUT, "leaders_1y.csv"), "w", encoding="utf-8-sig", newline="") as g:
        w = csv.DictWriter(g, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
