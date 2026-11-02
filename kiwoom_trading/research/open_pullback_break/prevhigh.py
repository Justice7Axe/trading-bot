r"""장 초 고점 눌림 재돌파 + '전일 고가(·종가)보다 높은 재돌파' 조건 (2026-11-03 사용자 텔레그램).

four.trade(need=...) 로: 재돌파 봉 종가가 장 초 고점 H0 와 함께 ① 전일 종가 ② 전일 고가 ③ 전일 고가·종가 둘 다 를 넘어야 매수.
대상: 검증된 4종목(SK하이닉스·삼성전자·한미반도체·제주반도체) + 비교로 전날 대금 30위.
매도: A 역배열(5<20<60<120) / C 손절(눌림 저가)만·다음 날 09:00.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\Ellie\trading .venv\Scripts\python.exe -m kiwoom_trading.research.open_pullback_break.prevhigh
  → data/open_pullback_break/prevhigh.txt
"""
import os
import sys

import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.research.open_pullback_break.bt import prepend_prev
from kiwoom_trading.research.open_pullback_break.four import CODES, OUT, trade


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rp = E.Report.__new__(E.Report); rp.f = open(os.path.join(OUT, "prevhigh.txt"), "w", encoding="utf-8")
    rp.say("장 초 고점 눌림 재돌파 + 전일 가격 위 재돌파 조건 — 1년, 손절 = 눌림 저가, 비용 0.25%")
    rows = []
    for d in E.days():
        if not E.next_day(d):
            continue
        p = E.prev_day(d); pdd = E.daily_day(p)
        top = [c for c, r in sorted(E.value_rank(p).items(), key=lambda x: x[1]) if E.is_common(c)][:30]
        for c in sorted(set(top) | set(CODES)):
            reg = E.regular(E.bars(c, d)); fct = E.factor(c, d)
            if len(reg) < 100 or not fct or c not in pdd:
                continue
            full, off = prepend_prev(c, d, reg)
            pc, ph = pdd[c][3] * fct, pdd[c][1] * fct
            for lab, need in (("조건 없음(기존)", None), ("① 전일 종가 위", pc), ("② 전일 고가 위", ph), ("③ 전일 고가·종가 둘 다 위", max(pc, ph))):
                r = trade(c, d, full, off, pc, need=need)
                if r and r.get("entry"):
                    r.update(cond=lab, four=c in CODES, top30=c in top); rows.append(r)
    df = pd.DataFrame(rows)
    df.to_parquet(os.path.join(OUT, "prevhigh.parquet"))
    for uni, sel in (("검증된 4종목", df.four), ("전날 대금 30위", df.top30)):
        rp.say(f"\n## {uni}")
        for lab in df.cond.unique():
            g = df[sel & (df.cond == lab)]
            rp.say(f" [{lab}]")
            rp.stats([(r.date, r.A) for r in g.itertuples() if r.A == r.A], "   A 역배열 매도")
            rp.stats([(r.date, r.C) for r in g.itertuples() if r.C == r.C], "   C 손절만·다음 날 09:00")
            if uni.startswith("검증"):
                rp.say("     종목별 C: " + " · ".join(f"{CODES[c]} {len(x)}건 {x.C.mean():+.2%}" for c, x in g.groupby("code")))


if __name__ == "__main__":
    main()
