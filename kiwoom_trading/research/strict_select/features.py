"""단타(장중 매수) 매매에 '매수 전에 아는' 종목 정보를 붙인다 — 더 엄격한 종목 선정 연구 (2026-10-30).

입력: data/account_alloc/trades.pkl (build_trades.py)
  ☕ 는 지금 실전 규칙(PR #148, 일봉 박스 조건 없음)으로 바꿔 넣는다:
     data/cafe/trades.pkl 의 lead and free and ret_pull is not None (601건), 매수 = 돌파 고점 지정가(level), 신호 다음 분.
     장중 청산 시각 xt 는 add_exits.cafe_exit 와 같게 (−2% 또는 상한가).
붙이는 정보 (모두 전날까지 또는 신호 순간 값 — 그날 마감 정보 안 씀):
  pvr 전날 대금 순위 · fb/ib 전날 외인/기관 순매수 · mc 전날 시총 · up20 전날 종가 > 20일선(전날까지 20일)
  n52 전날 종가 ≥ 52주 고가(전날까지) × 0.9 · reg 시장 판정(09:10 에 앎 → 09:10 전 신호엔 None) · common 보통주 · px 매수 가격(원가격)
출력: data/strict_select/trades_feat.pkl
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.strict_select.features
"""
import os
import pickle
import sys
from collections import Counter
from datetime import time

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import cls
from kiwoom_trading.research.account_alloc.add_exits import cafe_exit

SRC = os.path.join(E.DATA, "account_alloc", "trades.pkl")
OUT = os.path.join(E.DATA, "strict_select")
os.makedirs(OUT, exist_ok=True)
INTRA = {"1️⃣", "2️⃣", "3️⃣", "5️⃣", "6️⃣", "📕", "🔁", "☕"}


def cafe_rows():
    out = []
    for t in pickle.load(open(os.path.join(E.DATA, "cafe", "trades.pkl"), "rb")):
        if not (t["lead"] and t["free"] and t["ret_pull"] is not None):
            continue
        if not (E.P0 <= t["date"] <= E.P1):
            continue
        m = t["t"].hour * 60 + t["t"].minute + 1
        tt = time(m // 60, m % 60)
        d, c, e = t["date"], t["code"], float(t["level"])
        b = E.regular(E.bars(c, d))
        pc = E.daily_day(E.prev_day(d)).get(c); f = E.factor(c, d)
        hit = cafe_exit(b, tt, e, pc[3] * f if pc and f else None) if b else None
        out.append(dict(date=d, t=tt, kind="☕", code=c, px=e, ret=float(t["ret_pull"]), xt=hit[0] if hit else None))
    return out


def feat(t):
    d, c = t["date"], t["code"]
    p = E.prev_day(d)
    t["pvr"] = E.value_rank(p).get(c, 9999)
    iv = E.inv(c, p)
    t["fb"] = None if iv is None or iv[0] is None else iv[0] > 0
    t["ib"] = None if iv is None or iv[1] is None else iv[1] > 0
    t["mc"] = E.mcap(c, p)
    h = E.hist(c, d, 20)
    t["up20"] = (h[0][4] > sum(x[4] for x in h) / 20) if len(h) == 20 else None
    hi = E.hi_n(c, d, 250)
    t["n52"] = (h[0][4] >= hi * 0.9) if h and hi else None
    t["reg"] = cls(d) if t["t"] >= time(9, 10) else None
    t["common"] = E.is_common(c)
    return t


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = [t for t in pickle.load(open(SRC, "rb")) if t["kind"] != "☕"]
    C = cafe_rows()
    print(f"☕ 박스 없는 규칙 {len(C)}건 (장중 청산 {sum(1 for x in C if x['xt'])}건)")
    T += C
    miss = Counter()
    for i, t in enumerate(T):
        if t["kind"] in INTRA:
            feat(t)
            for k in ("fb", "ib", "up20", "n52"):
                if t[k] is None: miss[(t["kind"], k)] += 1
        if i % 1000 == 0:
            print(f"  {i}/{len(T)}", flush=True)
    pickle.dump(T, open(os.path.join(OUT, "trades_feat.pkl"), "wb"))
    print("정보 없음(None) 건수:", dict(miss))


if __name__ == "__main__":
    main()
