"""지금 매매표 전체(PR #72 까지) 1년 백테스트 — ①~⑦ + 🧭 디앤서 종가 + 🌙 종가 재돌파.
(원래 세션 스크래치 d9b9b62e/full_bt.py, 2026-10-27 저장소로 옮김 — docs/architecture.md 4장 1단계)

매매 기록 출처 (모두 1분봉/일봉 1년, 비용 0.25%(인버스 0.05%), 미래 정보 없음):
  ①②③④⑤ events_15.build (regime-playbook·regime-improve 백테스트), ⑥ np_cands.pkl, ⑦ trend7 (일봉),
  🧭·🌙 closing-bet dans_bars.pkl + danswer select_bt.py 특징.
계좌: 1,000만 원 하나, 현금을 나눠 씀. 그날 신호가 온 시각 순서로 금액을 채우고, 현금이 모자라면 못 삼.
  다음 날 09:00 에 파는 매매는 아침에 현금이 돌아온다고 본다. ⑦ 은 들고 있는 동안 그 돈을 못 씀.
모듈로 불러 쓰기: from kiwoom_trading.backtest.playbook import full_bt as FB → FB.EV(매매 목록)·FB.T7c·FB.account(compound, only)
실행: python -m kiwoom_trading.backtest.playbook.full_bt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import date, time
import numpy as np

from kiwoom_trading.backtest.playbook import events_15
from kiwoom_trading.backtest.playbook.paths import pb, patch_copy, PROJECT_ROOT
from kiwoom_trading.backtest.playbook.regime import cls

P0, P1 = date(2025, 10, 15), date(2026, 10, 23)
SPLIT = date(2026, 4, 20)
SEED = 10_000_000


def quiet(fn):
    so, se = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        return fn()
    finally:
        sys.stdout, sys.stderr = so, se


# ①~⑤
_T15, _days = events_15.build()
days = [d for d in _days if P0 <= d <= P1]
EV = []   # (date, 시각 키, 매매, 기본 금액, 수익률, code)
for d, k, a, r, tk in _T15:
    EV.append((d, tk, k, a, r, None))

# ⑥ 주도주 신고가 (U·N+)
R6 = pickle.load(open(pb("np_cands.pkl"), "rb"))
seen = set()
for r in sorted(R6, key=lambda r: (r["date"], r["t"])):
    if cls(r["date"]) not in ("U", "N+") or r["vrank"] > 10: continue
    A = r["kind"] == "E52" and r["t"] <= time(11, 0)
    B = r["kind"] == "E10" and r["open_over52"] and r["from_open"] > 0
    v = r["ex"][(None, 0.04, "n")]
    if (A or B) and (r["date"], r["code"]) not in seen and v == v and abs(v) < 0.4:
        seen.add((r["date"], r["code"]))
        EV.append((r["date"], (max(r["t"], time(9, 10)), r["vrank"]), "⑥ 주도주 신고가", 1_000_000, v, r["code"]))

# 🧭 디앤서 종가 / 🌙 종가 재돌파
patch_copy()   # 잠긴 1분봉 DB 는 전에 복사한 것, PLAYBOOK_DAILY_DB 면 일봉 스냅샷
sb = os.path.join(PROJECT_ROOT, ".claude", "skills", "danswer", "scripts", "select_bt.py")
src = open(sb, encoding="utf-8").read().split("\ndef at_open")[0]
ns = {"__file__": sb, "__name__": "x"}
quiet(lambda: exec(src, ns))
DR = ns["R"]
COSTC = 0.0025
nd = defaultdict(int)
for r in DR:
    if not (P0 <= r["date"] <= P1) or not (r["rk"] <= 10 and 0 < r["chg"] < 0.295): continue
    reg = [b for b in r["n_bars"] if b[0] >= time(9, 0)]
    if not reg or reg[0][0] > time(9, 5): continue
    o = reg[0][1]
    both_sell = r["inv_ok"] and r["f"] is not None and r["f"] <= 0 and r["i"] <= 0
    if (r["prk"] is not None and r["sector_n"] >= 1 and r["hi250"] is not None and r["hi250"] >= 0.95
            and r["ma120"] is not None and r["ma120"] >= 0 and not both_sell):
        EV.append((r["date"], (time(15, 15), r["rk"]), "🧭 디앤서 종가", 1_000_000, o / r["close"] - 1 - COSTC, r["code"]))
        nd["🧭"] += 1
    rb = next((b for b in r["d_bars"] if time(17, 0) <= b[0] < time(18, 0) and b[4] > r["close"]), None)
    if rb:
        EV.append((r["date"], (rb[0], r["rk"]), "🌙 종가 재돌파", 1_000_000, o / rb[4] - 1 - COSTC, r["code"]))

# ⑦ 주도주 추세 (일봉, 동시 10)
from kiwoom_trading.backtest.playbook import trend7  # noqa: E402
T7 = quiet(lambda: trend7.trades(trend7.f7))
held = []; T7c = []
for t in sorted(T7, key=lambda t: (t["buy_d"], trend7.VR.get((t["code"], t["sig"]), 999))):
    held = [h for h in held if h["sell_d"] > t["buy_d"]]
    if len(held) >= 10 or not (P0 <= t["buy_d"] <= P1): continue
    held.append(t); T7c.append(t)

# 같은 날 같은 종목은 먼저 온 매매만 (보유 중이면 안 삼)
EV.sort(key=lambda e: (e[0], e[1]))
dedup = []; got = set()
for e in EV:
    if not (P0 <= e[0] <= P1): continue
    if e[5] is not None:
        if (e[0], e[5]) in got: continue
        got.add((e[0], e[5]))
    dedup.append(e)
EV = dedup
KINDS = ["① 상승장 장 초", "② 저항 돌파", "③ 막힌 고점 돌파", "④ 역행 강세 종가", "⑤ 약세장 인버스", "⑥ 주도주 신고가",
         "🧭 디앤서 종가", "🌙 종가 재돌파", "⑦ 주도주 추세"]
CN = {"U": "강한 상승장", "N+": "상승 흐름 보통", "N-": "하락 흐름 보통", "D": "강한 하락장"}


def stat_line(nm, xs, amt):
    """xs = [(날짜, 수익률)]"""
    if not xs:
        print(f"  {nm:16s} 0건"); return
    r = np.array([v for _, v in xs]); a = [v for d, v in xs if d < SPLIT]; b = [v for d, v in xs if d >= SPLIT]
    byd = defaultdict(float)
    for d, v in xs: byd[d] += v * amt
    cum = np.cumsum([byd[k] for k in sorted(byd)]); mdd = float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max())
    print(f"  {nm:16s} {len(r):5d}건 건당 {r.mean()*100:+6.2f}% 승률 {(r>0).mean()*100:3.0f}% 앞 {np.mean(a)*100 if a else 0:+6.2f} 뒤 {np.mean(b)*100 if b else 0:+6.2f} "
          f"| 합계 {r.sum()*amt/1e4:+7,.0f}만 (건당 {amt//10000}만) 낙폭 {mdd/1e4:5,.0f}만")


def account(compound: bool, only=None):
    seven = defaultdict(list)                  # 매수일 → ⑦
    for t in T7c: seven[t["buy_d"]].append(t)
    byd = defaultdict(list)
    for e in EV:
        if only is None or e[2] in only: byd[e[0]].append(e)
    eq = SEED; curve = []; kinds = defaultdict(float); n = defaultdict(int); skip = 0
    tied = []                                  # (sell_d, 금액, 수익률)
    for d in days:
        # ⑦ 매도 (09:00) → 현금 돌아옴, 손익 반영
        keep = []
        for sd, amt, r in tied:
            if sd <= d:
                eq += amt * r; kinds["⑦ 주도주 추세"] += amt * r
            else:
                keep.append((sd, amt, r))
        tied = keep
        scale = eq / SEED if compound else 1.0
        left = (eq if compound else SEED) - sum(a for _, a, _ in tied)
        pnl = 0.0
        if only is None or "⑦ 주도주 추세" in only:
            for t in seven.get(d, []):
                amt = min(1_000_000 * scale, left)
                if amt <= 0: skip += 1; continue
                left -= amt; tied.append((t["sell_d"], amt, t["r"])); n["⑦ 주도주 추세"] += 1
        for e in sorted(byd.get(d, []), key=lambda e: e[1]):
            amt = min(e[3] * scale, left)
            if amt <= 0: skip += 1; continue
            left -= amt; pnl += amt * e[4]; kinds[e[2]] += amt * e[4]; n[e[2]] += 1
        eq += pnl
        curve.append((d, eq + sum(a * 0 for _, a, _ in tied)))
    for sd, amt, r in tied:                       # 끝까지 들고 있는 ⑦ 은 마지막 평가로
        eq += amt * r; kinds["⑦ 주도주 추세"] += amt * r
    curve[-1] = (curve[-1][0], eq)
    v = np.array([x for _, x in curve]); pk = np.maximum.accumulate(np.r_[SEED, v])[1:]
    i = int(np.argmax((pk - v) / pk))
    return eq, (pk[i] - v[i]) / pk[i], curve, kinds, n, skip




def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"기간 {P0} ~ {P1} ({len(days)}거래일): " + ", ".join(f"{CN[c]} {sum(1 for d in days if cls(d)==c)}일" for c in CN))
    print("\n[1] 매매별 단독 (한도·현금 무시)")
    for k in KINDS:
        if k == "⑦ 주도주 추세":
            stat_line(k, [(t["buy_d"], t["r"]) for t in T7c], 1_000_000)
        else:
            xs = [(e[0], e[4]) for e in EV if e[2] == k]
            stat_line(k, xs, [e[3] for e in EV if e[2] == k][0] if xs else 1)
    print(f"  (⑦ 보유 평균 {np.mean([t['days'] for t in T7c]):.1f}일, 디앤서 조건 통과 {nd['🧭']}건 — 같은 날 같은 종목이 앞 매매와 겹치면 뺌)")

    print("\n[2] 시장 상황별 (단독, 매수일 기준, 만 원)")
    for c in CN:
        parts = []
        for k in KINDS:
            if k == "⑦ 주도주 추세":
                v = [t["r"] * 1e6 for t in T7c if cls(t["buy_d"]) == c]
            else:
                v = [e[4] * e[3] for e in EV if e[2] == k and cls(e[0]) == c]
            if v: parts.append(f"{k.split()[0]} {sum(v)/1e4:+.0f}({len(v)})")
        print(f"  {CN[c]:10s} " + " · ".join(parts))


    for lab, comp in (("고정 1,000만 (번 돈은 따로 빼 둠)", False), ("복리 (번 돈을 계속 굴림)", True)):
        eq, dd, curve, kinds, n, skip = account(comp)
        print(f"\n[3] 계좌 하나 — {lab}")
        print(f"  최종 {eq/1e4:,.0f}만 원 ({eq/SEED*100-100:+.0f}%), 최대 낙폭 {dd*100:.1f}% (실현 손익 기준), 현금 부족으로 못 산 신호 {skip}건")
        print("  매매별: " + " · ".join(f"{k.split()[0]} {kinds[k]/1e4:+,.0f}만({n[k]})" for k in KINDS if n[k]))
        bym = {}; prev = SEED; out = []
        for d, v in curve: bym[d.strftime("%y-%m")] = v
        for m, v in bym.items(): out.append(f"{m} {(v/prev-1)*100:+.1f}%"); prev = v
        print("  월별: " + " · ".join(out))
        half = [v for d, v in curve if d < SPLIT][-1]
        print(f"  앞 반기 끝 {half/1e4:,.0f}만 → 끝 {eq/1e4:,.0f}만 (뒤 반기 {(eq/half-1)*100:+.1f}%)")

    print("\n[4] 비교 (복리)")
    for lab, only in (("①~⑤ (어제까지 매매표)", set(KINDS[:5])), ("①~⑥", set(KINDS[:6])), ("①~⑥ + 🧭·🌙", set(KINDS[:8])),
                      ("전체 (+ ⑦)", None), ("⑦ 만", {"⑦ 주도주 추세"}), ("🧭·🌙 만", {"🧭 디앤서 종가", "🌙 종가 재돌파"})):
        eq, dd, *_ = account(True, only)
        print(f"  {lab:22s} 최종 {eq/1e4:6,.0f}만 ({eq/SEED*100-100:+5.0f}%) 최대 낙폭 {dd*100:4.1f}%")


if __name__ == "__main__":
    main()
