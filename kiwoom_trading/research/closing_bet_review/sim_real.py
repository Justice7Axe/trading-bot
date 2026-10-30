"""새 실전 규칙 계좌 1년 — 종가 계열(🌙·4️⃣·🧭·기본)을 바꿔 보며 (2026-10-30).

실전 규칙 (execution/real.py, strict_select choose.real_sim 그대로): 시드 10만, 종목당 3만 원(1주 > 3만이면 1주), 예수금 안에서,
  지정가 = 가격 +1% 호가 올림(증거금), 같은 종목 보유 중·같은 날 같은 종목은 안 삼, 다음 날 09:00 매도 → 그날 아침 현금.
종가 계열 매매는 이 연구의 다시 만든 것(plays.pkl)으로 바꿔 넣는다:
  🌙 17:00~17:59 첫 종가 위 봉 종가 / 4️⃣ 15:19 가격 / 🧭 14:31 시가 / 기본 15:20(종가 동시호가, 매수가 = 15:30 종가)
A. 종가 계열만 (다른 매매 없음)  B. 실전 전체 (strict_select trades_feat + ALT=실전 B안, ☕·🔁·3️⃣ 빼고, 7️⃣·5️⃣·1️⃣·2️⃣·6️⃣·📕 포함)
출력: data/closing_bet_review/sim_real.txt
"""
import os
import pickle
from datetime import time

import numpy as np

from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select import choose as C

OUT = os.path.join(S.DATA, "closing_bet_review")
P = pickle.load(open(os.path.join(OUT, "plays.pkl"), "rb"))
S.KINDS.extend(["🧭", "기본"])          # real_sim 정렬용 (이름만)
rep = open(os.path.join(OUT, "sim_real.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(str(s) + "\n"); rep.flush()


def mk(rows, kind, px, ret, t, cond=lambda r: True):
    out = []
    for r in rows:
        if r.get(ret) is None or not r.get(px) or not cond(r):
            continue
        out.append(dict(date=r["date"], t=r[t] if isinstance(t, str) else t, kind=kind, code=r["code"], px=float(r[px]),
                        ret=float(r[ret]), rk=r.get("rk_reg", 0), xt=None))
    return out


MOON = lambda cond=lambda r: True: mk(P["moon"], "🌙", "moon_px", "r_moon", "moon_t", cond)
CONTRA = mk(P["contra"], "4️⃣", "p1519", "r19", time(15, 19))
COMPASS = mk(P["compass"], "🧭", "b1431", "r_1431", time(14, 31))
COMPASS_NH = mk(P["compass"], "🧭", "b1431", "r_1431", time(14, 31), lambda r: r["nh1430"])
BASIC = mk(P["basic"], "기본", "close", "r_close", time(15, 20))
BIG = lambda r: r["mcap"] >= 2e13
MID = lambda r: r["mcap"] >= 3e12
STAR = lambda r: r["pre17"] is not None and r["pre17"] > r["close"]

T_ALL = pickle.load(open(os.path.join(S.DATA, "strict_select", "trades_feat.pkl"), "rb"))
OTHER = [t for t in C.apply(T_ALL, C.ALT) if t["kind"] not in ("🌙", "4️⃣", "☕", "🔁", "3️⃣")]
KINDS = set(S.KINDS) - {"🔁", "3️⃣", "☕"}


def run(lab, T, seed=100_000):
    r = C.real_sim(T, seed=seed, kinds=KINDS)
    say(f" {'★' if r['star'] else ' '} {lab:46s} {r['final']:11,.0f}원 낙폭 {r['mdd']:.1%} 앞 {r['front']:+.0%} 뒤 {r['back']:+.0%}")
    say(f"      건수 {r['n']} | 손익(원) { {k: round(v) for k, v in r['pnl'].items()} } | 못 삼 {r['skip']}")
    return r


def bear_part(T, seed=100_000):
    """7월부터만 따로 (시드 10만에서 다시 시작)."""
    from datetime import date
    return C.real_sim([t for t in T if t["date"] >= date(2026, 7, 1)], seed=seed, kinds=KINDS)


say(f"새 실전 규칙 1년 ({S.DAYS[0]} ~ {S.DAYS[-1]}, 시드 10만, 종목당 3만, 정수 주) — 최종 자산·낙폭·앞/뒤(반기 {S.SPLIT})")
CASES = [
    ("🌙 + 4️⃣ (지금 실전)", MOON() + CONTRA),
    ("🌙 만", MOON()),
    ("4️⃣ 만", CONTRA),
    ("🌙 시총 3조↑ + 4️⃣", MOON(MID) + CONTRA),
    ("🌙 시총 20조↑ + 4️⃣", MOON(BIG) + CONTRA),
    ("🌙 ★(17시 전 종가 위)만 + 4️⃣", MOON(STAR) + CONTRA),
    ("🌙 + 4️⃣ + 🧭(신고가·라운드)", MOON() + CONTRA + COMPASS),
    ("🌙 + 4️⃣ + 🧭(신고가만)", MOON() + CONTRA + COMPASS_NH),
    ("🌙 + 4️⃣ + 기본(15:20 종가, 같은 종목은 기본이 먼저)", MOON() + CONTRA + BASIC),
    ("기본 + 4️⃣ (🌙 대신 정규장 종가)", BASIC + CONTRA),
]
say("\n## A. 종가 계열만")
for lab, T in CASES:
    run(lab, T)
    b = bear_part(T)
    say(f"      └ 7월부터 따로(10만 시작): {b['final']:,.0f}원 낙폭 {b['mdd']:.1%}")
say("\n## B. 실전 전체 (다른 매매 = strict_select ALT 실전 B안, ☕·🔁·3️⃣ 뺌)")
for lab, T in CASES:
    run(lab, OTHER + T)
    b = bear_part(OTHER + T)
    say(f"      └ 7월부터 따로(10만 시작): {b['final']:,.0f}원 낙폭 {b['mdd']:.1%}")

say("\n## C. 🧭 와 6️⃣ (실전 B안: 전날 기관 +) 겹침 — 같은 날 같은 종목")
six = [t for t in OTHER if t["kind"] == "6️⃣"]
k6 = {(t["date"], t["code"]) for t in six}
ov = [t for t in COMPASS if (t["date"], t["code"]) in k6]; no = [t for t in COMPASS if (t["date"], t["code"]) not in k6]
km = {(t["date"], t["code"]) for t in MOON()}
f = lambda v: f"{len(v)}건 건당 {np.mean([t['ret'] for t in v]):+.2%}" if v else "0건"
say(f"  🧭 {f(COMPASS)} | 6️⃣ 와 겹침 {f(ov)} | 안 겹침 {f(no)} | 안 겹침 중 🌙 와도 안 겹침 {f([t for t in no if (t['date'], t['code']) not in km])}")
from datetime import date
say(f"  7월부터 🧭 {f([t for t in COMPASS if t['date'] >= date(2026, 7, 1)])} | 6️⃣ 실전 B안 7월부터 {f([t for t in six if t['date'] >= date(2026, 7, 1)])}")
say(f"  1주 가격 > 3만 원 비율: 🌙 {np.mean([t['px'] > 30000 for t in MOON()]):.0%}, 4️⃣ {np.mean([t['px'] > 30000 for t in CONTRA]):.0%}, 🧭 {np.mean([t['px'] > 30000 for t in COMPASS]):.0%}"
    f" / 1주 > 10만(시드로 1주도 못 살 수 있음): 🌙 {np.mean([t['px'] > 100000 for t in MOON()]):.0%}")
