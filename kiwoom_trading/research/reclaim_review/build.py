"""🔁 시가 탈환 재점검 (2026-11-06 복기 노트 후보 B) — 1년 매매 목록 + 매수 전에 아는 특징값.

규칙 = 지금 live.py·paper.py 그대로 (timing.py E1 시가 회복 · M3 절반 +2R → 남은 절반 고점 −3% 트레일링(본전 아래로 안 내림), 못 닿으면 다음 날 09:00)
  대상 전날 대금 200위 주식(우선주 빼고), ① 프리장 고점 ≥ 전일 종가 +2% ② 09:00~09:10 저가 ≤ 프리장 고점 −2% & ≥ 전일 종가 −1%
  ③ 흔들기 저가 봉 뒤 ~10:30 1분봉 종가 > 09:00 시가 & 봉 대금 10억↑ & 직전 5봉 평균 2배↑ → 다음 봉 시가 매수, 손절 = 흔들기 저가 × 0.999
특징값 (모두 매수 전에 앎): 전날 외인·기관 순매수, 전날 대금 순위, 시총, 프리장 갭, 09:00 시가 갭, 흔들기 깊이, 손절까지 거리, 매수 시각,
  09:10 시장 분위기(U/N+/N-/D)·코스피 52주 고점 대비, 상장 거래일 수, 신호가 대비 다음 봉 시가(추격 +1%↑ 표시), 그날 몇 번째 셋업(live MAX_WATCH 30).
시장 분위기: 2026-10-23 까지 보존본 regime_feat.pkl, 그 뒤는 build_regime 과 같은 계산으로 새로 만듦.
실행: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m kiwoom_trading.research.reclaim_review.build → data/reclaim_review/trades.pkl
"""
import os
import pickle
import sys
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook import build_regime as BR
from kiwoom_trading.backtest.playbook.regime import feat as RF0
from kiwoom_trading.strategies.premarket_reclaim.timing import TRAIL, entries, setup

OUT = os.path.join(E.DATA, "reclaim_review")
os.makedirs(OUT, exist_ok=True)


def sell_t(b, j, e, stop0, nopen, half_at):
    """timing.sell 과 같은 규칙 + 다 팔린 시각(xt, 다음 날로 넘기면 None)·이유."""
    stop, hi, done, got = stop0, e, False, 0.0
    for x in b[j:]:
        if x[0] > time(15, 19):
            break
        if x[3] <= stop:
            px = min(x[1], stop)
            r = got + (0.5 if done else 1.0) * (px / e - 1)
            return r - E.COST, x[0], ("트레일링" if done else "손절")
        if not done and x[2] >= half_at:
            got, done = 0.5 * (half_at / e - 1), True
        hi = max(hi, x[2])
        if done:
            stop = max(stop, e, hi * (1 - TRAIL))
    if nopen is None:
        return None, None, None
    r = got + (0.5 if done else 1.0) * (nopen / e - 1)
    return r - E.COST, None, ("절반 익절 뒤 다음 날" if done else "다음 날 09:00")


def entry_live(b, s):
    """live.py 그대로: 09:11 에 ①② 를 보고(09:00~09:10 저가 다 본 뒤), 흔들기 저가 봉 뒤 첫 시가 회복 봉 i 를 찾음.
    매수 = max(i+1, 09:11 봉) 시가. paper.py: 그 가격이 신호가(i 봉 종가) +1% 넘으면 추격 안 함, 손절선 이하면 안 삼.
    → (매수 봉, 매수가, 신호 봉, 건너뛴 이유 또는 None) 또는 None(신호 없음)."""
    pre_hi, op, lo, k, r0 = s
    vals = [x[4] * x[5] for x in b]
    i0 = next((i for i, x in enumerate(b) if x[0] >= time(9, 11)), None)
    if i0 is None:
        return None
    for i in range(k + 1, len(b) - 1):
        x = b[i]
        if x[0] > time(10, 30):
            return None
        if x[3] < lo:
            return None
        if i < 5:
            continue
        avg5 = sum(vals[i - 5:i]) / 5
        if x[4] > op and vals[i] >= 1e9 and vals[i] >= 2 * avg5:
            j = max(i + 1, i0)
            if j >= len(b) or b[j][0] > time(10, 31):
                return None
            e = b[j][1]
            if any(b[m][3] < lo for m in range(i + 1, j)):
                return None
            why = "추격" if e > x[4] * 1.01 else "손절선 아래" if e <= lo * 0.999 else None
            return j, e, i, why
    return None


def regime_feat():
    """보존본 + 10-24 이후 새로 계산."""
    BR.LAST_DAY, BR.DONE_BY = date(2100, 1, 1), __import__("datetime").datetime(2100, 1, 1)
    M0, B1 = BR.build_m0_b1(E.MIN_SRC[0], E.DM, set())
    ctx, snap = BR.index_parts(E.IX)
    new = BR.build_feat(M0, B1, ctx, snap)
    both = [d for d in new if d in RF0]
    same = sum(BR.cls_of(new[d]) == BR.cls_of(RF0[d]) for d in both)
    print(f"[분위기] 보존본 {len(RF0)}일 · 새로 {len(new)}일 · 겹침 {len(both)}일 분류 같음 {same}", file=sys.stderr)
    f = dict(RF0)
    for d, x in new.items():
        if d not in f:
            f[d] = x
    return f


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    E.P1 = E.CAL[-2]          # 다음 날 시가가 있는 마지막 날
    RF = regime_feat()
    from kiwoom_trading.backtest.playbook.regime import BAD
    LIST = dict(E.DM.execute("SELECT code, list_date FROM stocks").fetchall())
    rows = []
    for n, d in enumerate(E.days()):
        p = E.prev_day(d)
        U = [c for c, r in sorted(E.value_rank(p).items(), key=lambda x: x[1]) if r <= 200 and E.is_common(c)]
        B, P = E.load_day(U, d), E.load_day(U, p)
        k_setup = 0
        for c in U:
            b = B.get(c) or []
            pr = E.regular(P.get(c) or [])
            if len(b) < 100 or len(pr) < 30:
                continue
            prev_close = pr[-1][4]
            s = setup(b, prev_close)
            if not s:
                continue
            k_setup += 1
            pre_hi, op, lo, k, r0 = s
            stop0 = lo * 0.999
            fi = E.inv(c, p) or (None, None)
            ld = LIST.get(c)
            nlist = (E.CIDX[d] - next((i for i, x in enumerate(E.CAL) if x >= ld), E.CIDX[d]) + 1) if ld else None
            rf = RF.get(d) or {}
            vals = [x[4] * x[5] for x in b]
            base = dict(date=d, code=c, name=E.NAME.get(c, c), stop=float(stop0), gap=pre_hi / prev_close - 1, ogap=op / prev_close - 1,
                        shake=lo / pre_hi - 1, setup_k=k_setup, fb=fi[0], ib=fi[1], pvr=E.value_rank(p)[c], mc=E.mcap(c, p), pchg=E.chg(c, p),
                        up20=(lambda m: None if m is None else E.daily_day(p)[c][3] > m)(E.ma_n(c, d, 20)),
                        reg=BR.cls_of(rf) if rf else None, K1z=rf.get("K1z"), M0=rf.get("M0"), dd52=rf.get("dd52"),
                        nlist=nlist, bad=(c, d) in BAD)
            for mode, en in (("bt", entries(b, s).get("E1 시가 회복")), ("lv", entry_live(b, s))):
                if not en:
                    continue
                if mode == "bt":
                    j, e = en; i, skip = j - 1, None
                else:
                    j, e, i, skip = en
                if e <= stop0 and mode == "bt":
                    continue
                row = dict(base, mode=mode, t=b[j][0], sig_t=b[i][0], px=float(e), sig_px=b[i][4], risk=e / stop0 - 1,
                           sigval=vals[i], skip=skip, ret=None, xt=None, why=None)
                if skip is None:
                    ex = E.next_day_exits(c, d, e)
                    nopen = e * (1 + ex["09:00 시가"] + E.COST) if "09:00 시가" in ex else None
                    r, xt, why = sell_t(b, j, e, stop0, nopen, e + 2 * (e - stop0))
                    if r is None or abs(r) >= 0.35:
                        continue
                    row.update(ret=float(r), xt=xt, why=why)
                rows.append(row)
        if n % 20 == 0:
            print(f"{d} {len(rows)}", file=sys.stderr, flush=True)
    pickle.dump(rows, open(os.path.join(OUT, "trades.pkl"), "wb"))
    for m in ("bt", "lv"):
        v = np.array([x["ret"] for x in rows if x["mode"] == m and x["ret"] is not None])
        print(f"🔁 {m} {len(v)}건 건당 {v.mean():+.2%} — 기존 보고 2,273건 +0.33%")


if __name__ == "__main__":
    main()
