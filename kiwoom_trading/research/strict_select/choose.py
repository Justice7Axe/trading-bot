"""고른 '엄격한 종목 선정' 규칙 → 매매별 점검 + 계좌 1년 (2026-10-30).

입력: data/strict_select/trades_feat.pkl (features.py, ☕ = 박스 없는 지금 규칙). 출력: data/strict_select/choose.txt
1) 매매별 후보 규칙: 건수·건당·합계·고정 반기·★·약세장 기간(코스피 52주 고점 −10% 밖 날) 건당
2) 계좌: sim.run (모의 배분, 시드 1천만) — 기준 / 엄격 규칙
3) 새 실전 규칙 (real.py 10-30): 시드 10만, 하루 종목 수 제한 없음, 종목당 3만 원(1주 > 3만 이면 1주), 예수금 안에서,
   같은 종목 보유 중·같은 날 같은 종목은 안 삼, 🔁 은 실전 안 함. 4️⃣·🌙·7️⃣ 는 그대로 넣음. 지정가 = 가격 +1% 호가 올림(증거금), 손익 = 수량 × 가격 × 수익률.
   다음 날 09:00 매도 → 그날 아침 현금 돌아옴, 장중 청산(xt) → 그 시각 뒤 신호부터 현금, 7️⃣ 는 sell_d 아침.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.strict_select.choose
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest.playbook.regime import feat as RF
from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select.filters import Rep, star, summ

DATA = S.DATA
OUT = os.path.join(DATA, "strict_select")
BEAR = {d for d, x in RF.items() if x["dd52"] <= -0.10}   # 약세장 기간 (장 전 앎) — 2026-07 부터 거의 계속

fb = lambda t: bool(t["fb"]); ib = lambda t: bool(t["ib"]); both = lambda t: fb(t) and ib(t)
one = lambda t: fb(t) or ib(t)
# 매매별 후보 (이름, 조건). 첫 줄 = 기준.
CAND = {
    "1️⃣": [("기준", lambda t: True),
           ("전날 외인 +", fb),
           ("신호 순간 대금 ≤20위", lambda t: t["rk"] <= 20),
           ("신호 순간 대금 ≤30위", lambda t: t["rk"] <= 30),
           ("전날 종가 20일선 위", lambda t: t["up20"] is True),
           ("대금 ≤20위 + 전날 외인 +", lambda t: t["rk"] <= 20 and fb(t)),
           ("대금 ≤30위 + 전날 외인 +", lambda t: t["rk"] <= 30 and fb(t)),
           ("대금 ≤20위 또는 전날 외인 +", lambda t: t["rk"] <= 20 or fb(t)),
           ("전날 외인 + + 20일선 위", lambda t: fb(t) and t["up20"] is True)],
    "2️⃣": [("기준", lambda t: True),
           ("시총 ≥3천억 + 전날 기관 +", lambda t: t["mc"] >= 3e11 and ib(t)),
           ("시총 ≥1조", lambda t: t["mc"] >= 1e12),
           ("시총 ≥5천억 + 전날 기관 +", lambda t: t["mc"] >= 5e11 and ib(t))],
    "6️⃣": [("기준", lambda t: True),
           ("전날 기관 +", ib),
           ("전날 외인 +", fb),
           ("테마 대장", lambda t: bool(t["lead"])),
           ("테마 대장 또는 전날 외인·기관 둘 다 +", lambda t: bool(t["lead"]) or both(t)),
           ("테마 대장 또는 전날 기관 +", lambda t: bool(t["lead"]) or ib(t)),
           ("전날 기관 + + 테마 대장", lambda t: ib(t) and bool(t["lead"]))],
    "📕": [("기준", lambda t: True),
           ("전날 외인 +", fb),
           ("전날 외인·기관 하나↑ +", one),
           ("전날 외인 + + 20일선 위", lambda t: fb(t) and t["up20"] is True)],
    "☕": [("기준", lambda t: True),
           ("전날 대금 ≤50위", lambda t: t["pvr"] <= 50),
           ("전날 대금 ≤30위", lambda t: t["pvr"] <= 30),
           ("전날 대금 ≤70위", lambda t: t["pvr"] <= 70),
           ("전날 외인 +", fb),
           ("전날 대금 ≤50위 + 전날 외인 +", lambda t: t["pvr"] <= 50 and fb(t)),
           ("전날 대금 ≤50위 또는 전날 외인 +", lambda t: t["pvr"] <= 50 or fb(t))],
    "🔁": [("기준", lambda t: True),
           ("전날 기관 +", ib),
           ("전날 외인·기관 하나↑ +", one),
           ("전날 기관 + + 20일선 위", lambda t: ib(t) and t["up20"] is True),
           ("전날 외인·기관 둘 다 +", both)],
}
# 추천 (CAND 이름) — 종목 정보만 씀 (시장 상황 조건은 약세장인 지금 매매를 거의 다 끄는 것이라 '종목 선정'이 아님)
# A 손익 유지형: 빠지는 매매의 건당이 0 근처인 조건만 (one_by_one.py 로 계좌 영향 확인 뒤 고름 — 10-30)
PICK = {"1️⃣": "신호 순간 대금 ≤20위", "2️⃣": "시총 ≥3천억 + 전날 기관 +", "6️⃣": "기준", "📕": "기준", "☕": "전날 대금 ≤50위", "🔁": "전날 기관 +"}
# B 강하게 줄임: A + 📕·6️⃣ 도 거름 (빠지는 📕·6️⃣ 도 건당 +1.2~1.4% 라 모의 합계는 줆)
ALT = dict(PICK, **{"📕": "전날 외인 +", "6️⃣": "전날 기관 +"})


def rule(kind, name):
    return dict(CAND[kind])[name]


def apply(T, pick):
    return [t for t in T if t["kind"] not in pick or rule(t["kind"], pick[t["kind"]])(t)]


def tick_up(p):
    return S.tick_up(p)


def real_sim(T, seed=100_000, per=30_000, kinds=None, collect=False):
    """새 실전 규칙 1년 (정수 주)."""
    kinds = kinds or (set(S.KINDS) - {"🔁", "3️⃣"})
    byd = defaultdict(list)
    for t in T:
        if t["kind"] in kinds: byd[t["date"]].append(t)
    cash = float(seed); hold = []    # (돌아오는 날, 그날 시각(None=아침), 금액+손익, 종목)
    curve = []; n = defaultdict(int); pnl_k = defaultdict(float); skip = defaultdict(int); dp = []
    for d in S.DAYS:
        keep = []; day_p = 0.0
        for h in hold:
            if h[0] < d or (h[0] == d and h[1] is None):
                cash += h[2]; day_p += h[4]
            else: keep.append(h)
        hold = keep
        got = {h[3] for h in hold}
        for t in sorted(byd.get(d, []), key=lambda t: (S.tt(t), t.get("rk", 0) or 0, S.KINDS.index(t["kind"]))):
            now = S.tt(t); keep = []
            for h in hold:                      # 장중 청산된 것 → 현금 돌아옴
                if h[0] == d and h[1] is not None and h[1] < now:
                    cash += h[2]; day_p += h[4]
                else: keep.append(h)
            hold = keep
            if t["code"] in got:
                skip["같은 종목"] += 1; continue
            px = t["px"]
            if not px == px or px <= 0:
                skip["가격 모름"] += 1; continue
            lim = tick_up(px * 1.01)
            q = min(max(1, int(per // lim)), int(cash // lim))
            if q < 1:
                skip["예수금 부족"] += 1; continue
            cash -= q * lim
            p = q * px * t["ret"]; back = q * lim + p          # 지정가 증거금만큼 잡아 두고 팔 때 돌려받음
            got.add(t["code"]); n[t["kind"]] += 1; pnl_k[t["kind"]] += p
            if t["kind"] == "7️⃣":
                hold.append((t["sell_d"], None, back, t["code"], p))
            elif t.get("xt") is not None:
                hold.append((d, t["xt"], back, t["code"], p))
            else:
                nd = S.DAYS[S.DAYS.index(d) + 1] if S.DAYS.index(d) + 1 < len(S.DAYS) else d
                hold.append((nd, None, back, t["code"], p))
        eq = cash + sum(h[2] - h[4] for h in hold)   # 실현 기준 (보유분은 원금)
        curve.append((d, eq)); dp.append(day_p)
    for h in hold: cash += h[2]
    eq = cash; curve[-1] = (curve[-1][0], eq)
    v = np.array([x for _, x in curve]); pk = np.maximum.accumulate(np.r_[seed, v])[1:]
    half = [x for dd, x in curve if dd < S.SPLIT][-1]
    top5 = sum(sorted(dp, reverse=True)[:5])
    return dict(final=eq, mdd=float(((pk - v) / pk).max()), front=half / seed - 1, back=eq / half - 1,
                star=half > seed and eq > half and eq - seed - top5 > 0, n=dict(n), pnl=dict(pnl_k), skip=dict(skip))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = pickle.load(open(os.path.join(OUT, "trades_feat.pkl"), "rb"))
    R = Rep(os.path.join(OUT, "choose.txt"))
    R.say("고른 엄격한 종목 선정 — 1년, 합계 100만/건, 반기 2026-04-20, '약세장' = 코스피 52주 고점 −10% 밖 날(장 전 앎, 2026-07~ 거의 계속)")
    for k, cs in CAND.items():
        rows = [t for t in T if t["kind"] == k]; base = summ(rows)
        R.say(f"\n## {k}")
        for nm, f in cs:
            sub = [t for t in rows if f(t)]; s = summ(sub)
            bear = [t["ret"] for t in sub if t["date"] in BEAR]
            mark = (" ◀A" if PICK[k] == nm else "") + (" ◀B" if ALT[k] == nm else "")
            out = [t["ret"] for t in rows if not f(t)]
            R.say(f" {'★' if star(sub) else ' '} {nm:32s} {s['n']:5d}건({s['n'] / base['n']:4.0%}) 건당 {s['mean']:+.2%} 합계 {s['sum']:+6.0f}만 "
                  f"| 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%} | 약세장 {len(bear):4d}건 {np.mean(bear) if bear else 0:+.2%} | 빠지는 {len(out):4d}건 {np.mean(out) if out else 0:+.2%}{mark}")

    old = S.T_ALL
    TA = apply(T, ALT); TP = apply(T, PICK)
    intra = lambda X: sum(1 for t in X if t["kind"] in ("1️⃣", "2️⃣", "6️⃣", "📕", "☕", "🔁"))
    R.say(f"\n## 단타 매매 건수 (1️⃣2️⃣6️⃣📕☕🔁, 1년) 기준 {intra(T)} → A {intra(TP)} → B {intra(TA)}")
    R.say("\n## 모의 계좌 1년 (sim.run, 시드 1천만, 지금 모의 배분) — 최종 자산·낙폭·앞/뒤·★·산 건수(단타)")
    cfgs = [("지금 배분 (3️⃣ 포함, 옛 기준 7,837만)", {}), ("모의 지금 (3️⃣ 뺌)", {"kinds": set(S.KINDS) - {"3️⃣"}}),
            ("B6 (🔁·3️⃣ 뺌)", {"kinds": set(S.KINDS) - {"🔁", "3️⃣"}})]
    for lab, cfg in cfgs:
        for tl, X in (("옛 trades.pkl(☕ 박스)", old), ("기준(☕ 박스 없음)", T), ("A 손익 유지형", TP), ("B 강하게 줄임", TA)):
            r = S.run(cfg, trades=X)
            nb = sum(v for kk, v in r["n_k"].items() if kk in ("1️⃣", "2️⃣", "6️⃣", "📕", "☕", "🔁"))
            R.say(f" {'★' if r['star'] else ' '} {lab:28s} {tl:22s} {r['final'] / 1e4:9,.0f}만 낙폭 {r['mdd']:.1%} 앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} | 단타 산 건수 {nb}")
    R.say("\n## 새 실전 규칙 1년 (시드 10만, 종목당 3만 원·1주 > 3만 이면 1주, 하루 제한 없음, 🔁·3️⃣ 안 함, 4️⃣🌙7️⃣ 포함)")
    for tl, X in (("기준(☕ 박스 없음)", T), ("A 손익 유지형", TP), ("B 강하게 줄임", TA)):
        r = real_sim(X)
        nb = sum(v for kk, v in r["n"].items() if kk in ("1️⃣", "2️⃣", "6️⃣", "📕", "☕"))
        R.say(f" {'★' if r['star'] else ' '} {tl:22s} {r['final']:10,.0f}원 낙폭 {r['mdd']:.1%} 앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} | 산 건수 {sum(r['n'].values())} (단타 {nb})")
        R.say(f"      매매별 건수 {r['n']}")
        R.say(f"      매매별 손익(원) { {k: round(v) for k, v in r['pnl'].items()} } 못 삼 {r['skip']}")
    pickle.dump(dict(PICK=PICK, ALT=ALT), open(os.path.join(OUT, "pick.pkl"), "wb"))


if __name__ == "__main__":
    main()
