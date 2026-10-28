"""한 계좌 1년 시뮬레이션 — 매매별 돈 배분·동시 한도·시드 크기 (2026-10-29).

입력: data/account_alloc/trades.pkl (build_trades.py). 결과: data/account_alloc/report.txt
계좌 규칙 (full_bt.account 를 넓힘):
  - 그날 신호를 '신호 시각' 순서로 채운다 (그 시각에 아는 것만). 다음 날 09:00 에 파는 매매는 그날 아침 현금이 돌아온다고 본다.
    장중 손절·익절로 다 팔린 매매(add_exits 의 xt)는 그 시각 뒤 신호부터 현금·자리를 다시 쓴다 (reuse=False 면 안 씀).
  - 7️⃣ 은 09:00 먼저, 전용 몫(자산 × pool) 안에서만, 팔 때까지 그 돈을 못 씀. 같은 종목 7️⃣ 보유 중이면 다른 매매로 안 삼.
  - 같은 날 같은 종목은 먼저 산 것만.
  - 금액 = 자산 × (매매별 비율) (복리). 6️⃣ 은 테마 대장 ×lead / 아님 ×nonlead (모의 규칙 2배·0.5배).
  - 동시 한도: 1️⃣·7️⃣ 빼고 그날 산 종목 수 ≤ max_pos (모의 10), 1️⃣ 은 up_max(40) 까지.
  - 정수 주(integer=True): 지정가 = 가격 +1% 호가 올림, 수량 = 금액 ÷ 지정가 내림, 0주면 못 삼(1주 값 > 금액). 손익 = 수량 × 가격 × 수익률.
  - 실전 방식(real=True): 하루 1종목(첫 신호, 전액). 1️⃣ 이 먼저 오면 1️⃣ 만 up_slots 종목까지 (자산 ÷ up_slots).
최대 낙폭은 날마다 마감 자산(실현 기준) 기준. ★ = 앞 반·뒤 반 모두 + 이고 가장 좋은 5일을 빼도 +.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.account_alloc.sim
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest.playbook.regime import cls

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "account_alloc")
T_ALL = pickle.load(open(os.path.join(OUT, "trades.pkl"), "rb"))
SPLIT = date(2026, 4, 20)
DAYS = sorted({d for d in __import__("kiwoom_trading.backtest.playbook.regime", fromlist=["feat"]).feat if cls(d)})
DAYS = [d for d in DAYS if min(t["date"] for t in T_ALL) <= d <= max(t["date"] for t in T_ALL)]
KINDS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "🌙", "📕", "🔁", "☕", "7️⃣"]
FULLNAME = {"1️⃣": "1️⃣ 상승장 장 초", "2️⃣": "2️⃣ 저항 돌파", "3️⃣": "3️⃣ 막힌 고점", "4️⃣": "4️⃣ 역행 강세 종가", "5️⃣": "5️⃣ 약세장 인버스",
            "6️⃣": "6️⃣ 주도주 신고가", "🌙": "🌙 종가 재돌파", "📕": "📕 상한가 풀림", "🔁": "🔁 시가 탈환", "☕": "☕ 카페 대장", "7️⃣": "7️⃣ 주도주 추세"}
ETF = {"123310"}
REAL_KINDS = {"1️⃣", "6️⃣", "2️⃣", "5️⃣", "📕", "🔁", "☕"}


def tick_up(price):
    unit = 1 if price < 2_000 else 5 if price < 5_000 else 10 if price < 20_000 else 50 if price < 50_000 \
        else 100 if price < 200_000 else 500 if price < 500_000 else 1_000
    return -(-price // unit) * unit


# 지금 모의 배분 (1천만 기준 비율): 종목당 100만, 1️⃣ 25만 × 40, 6️⃣ 대장 2배·아님 0.5배, 7️⃣ 몫 300만 (100만 × 10)
NOW = dict(amt={k: 0.10 for k in KINDS} | {"1️⃣": 0.025}, lead=2.0, nonlead=0.5, max_pos=10, up_max=40, pool=0.30, k7_amt=0.10,
           kinds=set(KINDS), order="time", real=False, up_slots=4, integer=False, cap=None)


def tt(t):
    """실제로 사는 순서의 시각. 3️⃣ 은 09:10 시장 판정 전에 난 돌파를 판정 뒤(09:10)에 산다 (live.BlockedHighWatcher)."""
    return max(t["t"], time(9, 10)) if t["kind"] == "3️⃣" else t["t"]


def run(cfg, seed=10_000_000, trades=None, collect=False):
    c = dict(NOW); c.update(cfg)
    T = trades if trades is not None else T_ALL
    if c.get("slip"):    # 추가 미끄러짐 (건당 수익률에서 뺌)
        T = [dict(t, ret=t["ret"] - c["slip"]) for t in T]
    byd = defaultdict(list)
    for t in T:
        if t["kind"] in c["kinds"]:
            byd[t["date"]].append(t)
    if c["order"] == "ev":   # 미래 정보: 그날 나중에 올 신호까지 다 보고 매매별 기대값 순으로 채움 (참고용)
        rank = c["ev_rank"]
        keyf = lambda t: (rank.get(t["kind"], 99), tt(t), t.get("rk", 0))
    else:
        keyf = lambda t: (tt(t), t.get("rk", 0), KINDS.index(t["kind"]))
    eq = float(seed); curve = []; tied = []   # tied = [(sell_d, 원금, 수익률, 수량가격 기준 손익)]
    pnl_k = defaultdict(float); n_k = defaultdict(int); dpnl = []
    skip = defaultdict(lambda: [0, 0.0])      # 이유 → [건수, 기본 금액으로 샀다면 손익]
    sig_n = 0; bought = []
    for d in DAYS:
        keep = []; dp = 0.0
        for sd, a, r, code in tied:
            if sd <= d:
                eq += a * r; pnl_k["7️⃣"] += a * r; dp += a * r
            else:
                keep.append((sd, a, r, code))
        tied = keep
        day = sorted(byd.get(d, []), key=keyf)
        left = eq - sum(a for _, a, _, _ in tied)
        pnl = 0.0; got = set(c7[3] for c7 in tied); npos = 0; nup = 0; first = None
        nk = defaultdict(int); res_used = 0.0
        rsv = c.get("reserve")          # (자산 비율, 이 시각까지, 이 매매들 몫) — 그 시각 전엔 다른 매매가 못 씀 (미래 정보 아님)
        live = []                       # 장중에 팔릴 보유 (xt, 원금, 수익률, 종류)
        for t in day:
            k = t["kind"]; sig_n += 1
            if c.get("reuse", True):    # 이 신호 전에 장중 손절·익절로 다 팔린 것 → 현금·자리 돌아옴
                now = tt(t); keep2 = []
                for x in live:
                    if x[0] < now:
                        left += x[1] * (1 + x[2])
                        if x[3] == "1️⃣": nup -= 1
                        elif not c["real"]: npos -= 1
                    else:
                        keep2.append(x)
                live = keep2
            base = eq * (c["k7_amt"] if k == "7️⃣" else c["amt"][k])
            if k == "6️⃣":
                base *= c["lead"] if t.get("lead") else c["nonlead"]
            ref = base * t["ret"]                          # 이 신호를 기본 금액으로 샀다면 손익
            if t["code"] in got:
                skip["같은 종목 이미 보유(중복)"][0] += 1; continue
            if c["real"]:
                sl = c.get("slots", 1)        # 1️⃣ 아닌 신호 하루 몇 종목 (지금 실전 1)
                if first is not None and (first == "1️⃣") != (k == "1️⃣"):
                    skip["실전 하루 종목 수"][0] += 1; skip["실전 하루 종목 수"][1] += ref; continue
                if k == "1️⃣" and nup >= c["up_slots"]:
                    skip["1️⃣ 칸 다 참"][0] += 1; skip["1️⃣ 칸 다 참"][1] += ref; continue
                if k != "1️⃣" and npos >= sl:
                    skip["실전 하루 종목 수"][0] += 1; skip["실전 하루 종목 수"][1] += ref; continue
                base = eq / c["up_slots"] if k == "1️⃣" else eq / sl
                if c.get("cap"): base = min(base, c["cap"])
            elif k == "7️⃣":
                used7 = sum(a for _, a, _, _ in tied)
                if used7 + base > eq * c["pool"] + 1:
                    skip["7️⃣ 몫 다 씀"][0] += 1; skip["7️⃣ 몫 다 씀"][1] += ref; continue
            elif k == "1️⃣":
                if nup >= c["up_max"]:
                    skip["1️⃣ 한도"][0] += 1; skip["1️⃣ 한도"][1] += ref; continue
            elif npos >= c["max_pos"]:
                skip["동시 보유 한도"][0] += 1; skip["동시 보유 한도"][1] += ref; continue
            if c.get("kcap") and nk[k] >= c["kcap"].get(k, 999):
                skip["매매별 하루 한도"][0] += 1; skip["매매별 하루 한도"][1] += ref; continue
            avail = left
            if rsv and k not in rsv[2] and tt(t) < rsv[1]:
                avail = left - max(0.0, eq * rsv[0] - res_used)
            partial = c.get("partial", c["real"])   # 모의는 주문 금액보다 현금이 적으면 안 삼, 실전은 있는 돈만큼
            amt = min(base, avail) if partial else base
            if c["integer"]:
                px = t["px"]
                if not px == px or px <= 0:
                    skip["가격 모름"][0] += 1; continue
                lim = tick_up(px * 1.01)
                q = int(amt // lim)
                if q < 1:
                    why = "1주 값 > 종목당 금액" if lim > base else "현금 부족"
                    skip[why][0] += 1; skip[why][1] += ref
                    continue                   # 실전: 1주도 못 사면 다음 신호
                amt = q * px
            if amt > avail + 1 or avail <= 0:
                skip["현금 부족"][0] += 1; skip["현금 부족"][1] += ref
                continue
            if partial and amt < base * 0.999 and not c["integer"]:
                skip["현금 모자라 덜 삼(건수만)"][0] += 1; skip["현금 모자라 덜 삼(건수만)"][1] += (base - amt) * t["ret"]
            left -= amt; got.add(t["code"]); n_k[k] += 1; nk[k] += 1
            if collect: bought.append(t)
            if rsv and k in rsv[2]: res_used += amt
            if first is None: first = k
            if k == "7️⃣":
                tied.append((t["sell_d"], amt, t["ret"], t["code"]))
            else:
                pnl += amt * t["ret"]; pnl_k[k] += amt * t["ret"]
                if k == "1️⃣": nup += 1
                else: npos += 1
                if t.get("xt") is not None:
                    live.append((t["xt"], amt, t["ret"], k))
        eq += pnl; dp += pnl
        curve.append((d, eq)); dpnl.append((d, dp))
    for sd, a, r, code in tied:
        eq += a * r; pnl_k["7️⃣"] += a * r
    curve[-1] = (curve[-1][0], eq)
    v = np.array([x for _, x in curve]); pk = np.maximum.accumulate(np.r_[seed, v])[1:]
    mdd = float(((pk - v) / pk).max())
    sp = SPLIT if curve[0][0] < SPLIT <= curve[-1][0] else curve[len(curve) // 2][0]   # 반기 기간만 돌릴 땐 그 기간 가운데
    half = [x for d, x in curve if d < sp][-1]
    top5 = sum(sorted((p for _, p in dpnl), reverse=True)[:5])
    star = half > seed and eq > half and (eq - seed - top5) > 0
    res = dict(final=eq, ret=eq / seed - 1, mdd=mdd, front=half / seed - 1, back=eq / half - 1, star=star,
               pnl_k=dict(pnl_k), n_k=dict(n_k), skip={k: tuple(v) for k, v in skip.items()}, sig_n=sig_n)
    if collect:
        res["curve"] = curve; res["bought"] = bought
    return res


def window(cfg, d0, d1, seed=10_000_000):
    """d0~d1 기간만 따로 (그 기간 시작 자산 = seed)."""
    global DAYS
    keep = DAYS
    DAYS = [d for d in keep if d0 <= d <= d1]
    try:
        T = [t for t in T_ALL if d0 <= t["date"] <= d1]
        return run(cfg, seed, trades=T)
    finally:
        DAYS = keep


def ev_front():
    """앞 6개월(SPLIT 전) 매매별 건당 수익률 — 배분을 정할 때 쓰는 유일한 정보."""
    out = {}
    for k in KINDS:
        v = [t["ret"] for t in T_ALL if t["kind"] == k and t["date"] < SPLIT]
        out[k] = (np.mean(v) if v else 0.0, len(v))
    return out
