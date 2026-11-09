"""6️⃣ 주도주 신고가 매매의 '테마 대장' 표시를 대장 규칙별로 다시 만든다 (2026-10-30 사용자: 대장 = 상승률 1위면?).

원본: 스크래치 playbook_leader.py (세션 0c8e9b25, 2026-10-27, 보존본 data/research_archive/0c8e9b25/playbook_leader.py)
 → data/hong/playbook_leader.pkl. 원본은 매매표 각 매매의 (날짜·종목·시각) 을 옛 스크래치 pkl 에서 다시 모은 뒤
   그날 '전날 대금 200위 ∪ 매매 종목' 1분봉으로 ☕ leader_at(그 시각) 을 불렀다.
여기서는 대장 판단 부분을 그대로 옮기고, 매매 목록은 계좌 시뮬 입력 data/account_alloc/trades.pkl 의 6️⃣ (date·code·t) 를 쓴다
(원본 ⑥ 목록과 같은 조건·같은 시각 max(t, 09:10), 367건).
같은 하루 자료로 by="value"(지금 규칙)·by="chg"(상승률 1위) 둘 다 계산 → value 가 원본 표시를 재현하는지도 확인.

결과: data/leader_rule/playbook_leader_{value,chg}.pkl  (data/hong/playbook_leader.pkl 은 건드리지 않음)
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_rule.playbook_leader
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import time

from kiwoom_trading.strategies.cafe_leader import backtest as C

E = C.E
OUT = os.path.join(E.DATA, "leader_rule")
os.makedirs(OUT, exist_ok=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = pickle.load(open(os.path.join(E.DATA, "account_alloc", "trades.pkl"), "rb"))
    TR = [(t["date"], t["code"], t["t"]) for t in T if t["kind"] == "6️⃣"]
    byday = defaultdict(list)
    for t in TR:
        byday[t[0]].append(t)
    out = {"value": [], "chg": []}
    for i, (d, ts) in enumerate(sorted(byday.items())):
        if d not in E.CIDX:
            continue
        p = E.prev_day(d)
        pd_ = E.daily_day(p)
        U = sorted({c for c, r in E.value_rank(p).items() if r <= 200 and E.is_common(c)} | {t[1] for t in ts})
        U = [c for c in U if c in pd_]
        B = E.load_day(U, d)
        info = {}
        for c in U:
            reg = E.regular(B[c]); f = E.factor(c, d)
            if len(reg) < 30 or not f:
                continue
            info[c] = dict(reg=reg, pre=[x for x in B[c] if x[0] < time(9, 0)], pc=pd_[c][3] * f)
        for (_, c, tt) in ts:
            for by in ("value", "chg"):
                lead, n = C.leader_at(c, d, tt, info, by=by) if c in info else (None, 0)
                out[by].append(dict(date=d, code=c, t=tt, kind="⑥ 주도주 신고가", lead=lead, n=n))
        if i % 30 == 0:
            print(" ", d, len(out["value"]), file=sys.stderr)
    for by, v in out.items():
        pickle.dump(v, open(os.path.join(OUT, f"playbook_leader_{by}.pkl"), "wb"))
        print(by, len(v), "대장", sum(1 for t in v if t["lead"]), "판단 못 함", sum(1 for t in v if t["lead"] is None))


if __name__ == "__main__":
    main()
