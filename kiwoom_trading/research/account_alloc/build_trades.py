"""지금 돌리는 매매 전부의 1년 매매 목록을 한 표로 모은다 (한 계좌 배분 시뮬레이션 입력).

출처 (모두 기존 백테스트 입력·규칙을 그대로 씀, 비용 0.25%·ETF 0.05% 포함, 매도 = 익절/손절/다음 날 09:00):
  1️⃣ 상승장 장 초  u_cands(다시 만든 것) → bt_up_chase2 의 n=1(09:11 시가)·전일 대비 +15% 넘으면 안 삼·손절 −6% (10-28 규칙)
  2️⃣ 저항 돌파 · 3️⃣ 막힌 고점 · 4️⃣ 역행 강세 종가 · 5️⃣ 약세장 인버스   events_15.build (full_bt 와 같음)
  6️⃣ 주도주 신고가  np_cands (full_bt 와 같은 조건) + 테마 대장 여부(data/hong/playbook_leader.pkl)
  🌙 종가 재돌파    data/closing_bet/dans_bars.pkl (full_bt 와 같은 조건)
  📕 상한가 풀림    data/hong/trades.pkl '5분↑ 잠김 + 2호가 + 전부 다음 날' (실전 규칙)
  🔁 시가 탈환      reclaim.pkl (build_reclaim.py, E1·절반 +2R·트레일 3%)
  ☕ 카페 테마 대장  data/cafe/trades.pkl ①+③+④(15일 고가 박스 30%)·돌파 고점 눌림 지정가
  7️⃣ 주도주 추세    trend7 (일봉, 동시 10)
가격 px = 매수 시점 1분봉 원가격(정수 주 계산용). 1분봉에 없으면 출처의 가격.
실행: PLAYBOOK_DAILY_DB=data/backtest/playbook/daily_ohlcv_20261025.duckdb PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.account_alloc.build_trades
"""
import os
import pickle
import sys
from collections import Counter
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook import events_15
from kiwoom_trading.backtest.playbook.paths import pb
from kiwoom_trading.backtest.playbook.regime import cls
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "account_alloc")
os.makedirs(OUT, exist_ok=True)
COST = 0.0025
K1, K2, K3, K4, K5, K6, K7 = "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"
KM, KH, KR, KC = "🌙", "📕", "🔁", "☕"


def px_at(c, d, t):
    """t 시각(또는 그 뒤 첫 봉) 1분봉 시가 — 원가격."""
    b = E.bars(c, d)
    x = next((y for y in b if y[0] >= t), None)
    return float(x[1]) if x else None


def prev_regular(c, d):
    """bt_up_chart_exits.prev_regular 와 같음 (그 모듈은 불러오면 결과 파일을 비우므로 옮겨 씀)."""
    p = E.prev_day(d)
    if not p: return None
    r = E.regular(E.bars(c, p))
    if len(r) < 30: return None
    k = 1.0
    fd, fp = E.factor(c, d), E.factor(c, p)
    if fd and fp and abs(fd / fp - 1) > 0.003: k = fd / fp
    return r[-1][4] * k


def up_trades():
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    out, miss = [], Counter()
    for r in sel:
        d, c = r["date"], r["code"]
        b = E.regular(E.bars(c, d))
        idx = {x[0]: i for i, x in enumerate(b)}
        if time(9, 11) not in idx or time(9, 10) not in idx:
            miss["봉 없음"] += 1; continue
        pc0 = b[0][1] / (1 + r["gap"])
        pc = prev_regular(c, d) or pc0
        j = idx[time(9, 11)]; buy = b[j][1]
        if buy / pc0 - 1 >= 0.29:
            miss["상한가 근처"] += 1; continue
        if buy / pc - 1 > 0.15:
            miss["전일 대비 +15% 넘음(규칙상 안 삼)"] += 1; continue
        nx = E.next_day_exits(c, d, buy).get("09:00 시가")
        if nx is None:
            miss["다음 날 없음"] += 1; continue
        sp = buy * 0.94; ret = nx
        for x in b[j:]:
            if x[0] > time(15, 19): break
            if x[3] <= sp:
                ret = min(x[1], sp) / buy - 1 - E.COST; break
        out.append(dict(date=d, t=time(9, 11), kind=K1, code=c, px=float(buy), ret=float(ret), rk=r["vrank"]))
    print(f"1️⃣ {len(out)}건 건당 {np.mean([x['ret'] for x in out]):+.2%} (기존 up_chase2 n=1·+15%·−6%: 574건 +1.06%) 빠짐 {dict(miss)}")
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = up_trades()

    # 2️⃣3️⃣4️⃣5️⃣ — events_15 그대로 (1️⃣ 옛 규칙은 버림)
    ev, _ = events_15.build(with_code=True)
    name = {"② 저항 돌파": K2, "③ 막힌 고점 돌파": K3, "④ 역행 강세 종가": K4, "⑤ 약세장 인버스": K5}
    inv = pickle.load(open(pb("inv_bars.pkl"), "rb"))
    for d, k, a, r, tk, code in ev:
        if k not in name: continue
        if name[k] == K5:
            b = next(x for x in inv[d] if x["ts"].time() >= time(9, 11)); px = float(b["open"])
        elif name[k] == K4:
            rg = E.regular(E.bars(code, d)); px = float(rg[-1][4]) if rg else None
        else:
            px = px_at(code, d, tk[0])
        T.append(dict(date=d, t=tk[0], kind=name[k], code=code, px=px, ret=float(r), rk=tk[1]))

    # 6️⃣ — full_bt 와 같은 조건 + 상한가 근처 매수 불가 표시 + 테마 대장
    lead = {(t["date"], t["code"]): t["lead"] for t in pickle.load(open(os.path.join(E.DATA, "hong", "playbook_leader.pkl"), "rb"))
            if t["kind"] == "⑥ 주도주 신고가"}
    seen = set(); n_lim = 0
    for r in sorted(pickle.load(open(pb("np_cands.pkl"), "rb")), key=lambda r: (r["date"], r["t"])):
        if cls(r["date"]) not in ("U", "N+") or r["vrank"] > 10: continue
        A = r["kind"] == "E52" and r["t"] <= time(11, 0)
        B = r["kind"] == "E10" and r["open_over52"] and r["from_open"] > 0
        v = r["ex"][(None, 0.04, "n")]
        if (A or B) and (r["date"], r["code"]) not in seen and v == v and abs(v) < 0.4:
            seen.add((r["date"], r["code"]))
            if r["chg"] >= 0.29:
                n_lim += 1
            T.append(dict(date=r["date"], t=max(r["t"], time(9, 10)), kind=K6, code=r["code"], px=float(r["entry"]), ret=float(v), rk=r["vrank"],
                          lead=bool(lead.get((r["date"], r["code"]))), near_limit=r["chg"] >= 0.29))
    print(f"6️⃣ 매수 때 이미 +29%↑(상한가 근처) {n_lim}건 — 표시만")

    # 🌙 — full_bt 와 같은 조건 (dans_bars)
    D = pickle.load(open(os.path.join(E.DATA, "closing_bet", "dans_bars.pkl"), "rb"))
    for r in D["rows"]:
        if not (r["rk"] <= 10 and 0 < r["chg"] < 0.295): continue
        reg = [b for b in r["n_bars"] if b[0] >= time(9, 0)]
        if not reg or reg[0][0] > time(9, 5): continue
        rb = next((b for b in r["d_bars"] if time(17, 0) <= b[0] < time(18, 0) and b[4] > r["close"]), None)
        if rb:
            T.append(dict(date=r["date"], t=rb[0], kind=KM, code=r["code"], px=float(rb[4]), ret=float(reg[0][1] / rb[4] - 1 - COST), rk=r["rk"]))

    # 📕 — 실전 규칙 (5분↑ 잠김, 2호가 비싸게, 전부 다음 날 09:00)
    H = pickle.load(open(os.path.join(E.DATA, "hong", "trades.pkl"), "rb"))["trades"]["5분↑ 잠김 + 2호가 + 전부 다음 날"]
    for t in H:
        if "09:00 시가" in t["rets"]:
            T.append(dict(date=t["date"], t=t["t"], kind=KH, code=t["code"], px=float(t["buy"]), ret=float(t["rets"]["09:00 시가"])))

    # 🔁
    for t in pickle.load(open(os.path.join(OUT, "reclaim.pkl"), "rb")):
        T.append(dict(date=t["date"], t=t["t"], kind=KR, code=t["code"], px=t["px"], ret=t["ret"]))

    # ☕ ①+③+④ 고가 박스 15일·30%, 눌림 지정가
    from kiwoom_trading.strategies.cafe_leader.backtest import box_tags
    for t in pickle.load(open(os.path.join(E.DATA, "cafe", "trades.pkl"), "rb")):
        if t["lead"] and t["free"] and t["ret_pull"] is not None and box_tags(t)[0]:
            tt = (t["t"].hour * 60 + t["t"].minute + 1)
            T.append(dict(date=t["date"], t=time(tt // 60, tt % 60), kind=KC, code=t["code"], px=float(t["level"]), ret=float(t["ret_pull"])))

    # 7️⃣ (일봉) — full_bt 와 같음: 동시 10
    from kiwoom_trading.backtest.playbook import trend7
    T7 = trend7.trades(trend7.f7)
    held = []; n7 = 0
    for t in sorted(T7, key=lambda t: (t["buy_d"], trend7.VR.get((t["code"], t["sig"]), 999))):
        held = [h for h in held if h["sell_d"] > t["buy_d"]]
        if len(held) >= 10: continue
        held.append(t); n7 += 1
        T.append(dict(date=t["buy_d"], t=time(9, 0), kind=K7, code=t["code"], px=float(t["buy"]), ret=float(t["r"]), sell_d=t["sell_d"],
                      rk=trend7.VR.get((t["code"], t["sig"]), 999)))

    T = [t for t in T if E.P0 <= t["date"] <= E.P1]
    for t in T:
        if t["px"] is None:   # 1분봉 없음 → 0 (정수 주 시험에서 '가격 모름'으로 셈)
            t["px"] = float("nan")
    pickle.dump(T, open(os.path.join(OUT, "trades.pkl"), "wb"))
    print(f"\n기간 {E.P0} ~ {E.P1}, 매매 {len(T)}건")
    for k in (K1, K2, K3, K4, K5, K6, KM, KH, KR, KC, K7):
        v = np.array([t["ret"] for t in T if t["kind"] == k])
        if len(v):
            print(f"  {k} {len(v):5d}건 건당 {v.mean():+.2%} 합계(100만/건) {v.sum()*100:+,.0f}만 · 가격 없음 {sum(1 for t in T if t['kind']==k and t['px']!=t['px'])}")


if __name__ == "__main__":
    main()
