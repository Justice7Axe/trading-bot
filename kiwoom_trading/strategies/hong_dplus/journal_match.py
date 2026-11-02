"""🔺 홍인기 D+ — 홍인기 매매일지(data/hong/journal_trades.csv)의 실제 매매 종목이 우리 대장 흐름(D+0~D+3) 안에 있었나
(2026-11-02 사용자 '대장주를 제대로 찾기나 한가?').

종목은 이름으로 찾음 (일지의 code 칸은 0126Z0 같은 새 코드가 숫자로 깨져 있음 — 삼성에피스홀딩스 → 012620 원일특강).
비교 기준: 그날 대금 50위 안 아무 종목 / 그중 +5%↑ 아무 종목이 같은 방식으로 몇 % 걸리나.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.strategies.hong_dplus.journal_match
  → data/hong_dplus/journal_match.txt (backtest.py 의 trades.pkl 필요)
"""
import os
import pickle
import random
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.hong_dplus.backtest import OUT, THEME, day_lead


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(os.path.join(OUT, "journal_match.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); f.write(s + "\n")

    J = pd.read_csv(os.path.join(E.DATA, "hong", "journal_trades.csv"))
    J = J[(J.name != "매매 없음") & (J.type != "지수/ETF") & ~J.name.str.contains("KODEX|TIGER|선물|코스피|코스닥|ETF", na=False)]
    d0, _ = pickle.load(open(os.path.join(OUT, "trades.pkl"), "rb"))
    big, small = defaultdict(set), defaultdict(set)
    for r in d0:
        (small if r.get("small_lead") else big)[r["date"]].add(r["code"])
    days = set(E.days())

    def tag(c, d):
        if c in big[d] or c in day_lead(d)[1]:
            return "D+0 대장"
        if c in small[d]:
            return "D+0 중소형 대장"
        for k in (1, 2, 3):
            p = E.prev_day(d, k)
            if c in day_lead(p)[1] or c in big.get(p, ()) or c in small.get(p, ()):
                return f"D+{k}"
        return "안 잡힘"

    rows = []
    for _, row in J.iterrows():
        d = pd.Timestamp(row.date).date()
        if d not in days:
            continue
        c = E.code_by_name(row["name"])
        if not c and row.code == row.code:
            c0 = f"{int(row.code):06d}"
            c = c0 if c0 in E.NAME else None
        rows.append((d, row["name"], c, tag(c, d) if c else "코드 모름", row.type, str(row.entry_reason)))
    df = pd.DataFrame(rows, columns=["date", "name", "code", "tag", "type", "reason"])
    lead = df[df.reason.str.contains("대장")]
    hit = lambda x: (x.tag.str.startswith("D+")).mean()
    say(f"일지 매매 {len(df)}건 (지수·ETF 빼고, 백테스트 기간) — 우리 대장 흐름 안 {hit(df):.0%}")
    say("  " + str(df.tag.value_counts().to_dict()))
    say(f"그가 '대장'이라고 적은 {len(lead)}건 — {hit(lead):.0%}")
    say("  " + str(lead.tag.value_counts().to_dict()))
    say("유형별:")
    for t, g in df.groupby("type"):
        say(f"  {t} {len(g)}건 {hit(g):.0%} {g.tag.value_counts().to_dict()}")
    say("\n'대장'이라 적었는데 못 잡은 것:")
    for r in lead[lead.tag == "안 잡힘"].itertuples():
        say(f"  {r.date} {r.name} [{r.type}] 섹터 {sorted(THEME.get(r.code, ()))} 대금 {E.value_rank(r.date).get(r.code)}위 "
            f"{(E.chg(r.code, r.date) or 0):+.1%} | {r.reason[:70]}")

    random.seed(0)
    say(f"\n## 비교 기준 (하루 대장 평균 {np.mean([len(big[d]) for d in days]):.1f}개 + 중소형 {np.mean([len(small[d]) for d in days]):.1f}개)")
    for lab, up in (("그날 대금 50위 안 아무 종목", None), ("그날 대금 50위 안 +5%↑ 아무 종목", 0.05)):
        h = n = 0
        for d in sorted(days):
            top = [c for c, r in E.value_rank(d).items() if r <= 50 and E.is_common(c)]
            if up:
                top = [c for c in top if (E.chg(c, d) or 0) >= up]
            for c in random.sample(top, min(3, len(top))):
                n += 1; h += tag(c, d).startswith("D+")
        say(f"  {lab}: {h}/{n} = {h / n:.0%}")


if __name__ == "__main__":
    main()
