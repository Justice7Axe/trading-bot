"""종가배팅 다시 보기 (2026-10-30) — 1분봉 1년 자료 만들기.

대상: 그날 최종 대금 상위 300(주식, stocks 표) 중 1분봉 있는 종목. 각 종목·일에 아래를 붙여 data/closing_bet_review/rows.pkl 로 저장.
  가격은 모두 1분봉(받은 날 원가격) 기준. 전일 종가 = 일봉(바로잡은 daily_day) × f (엔진 factor, 가격 기준 맞추기만).
  rk_reg   정규장(09:00~15:30) 1분봉 대금(종가×거래량) 순위 — 300 모집단 안 (9-14 뒤 일봉 대금은 애프터 포함이라 이걸 씀)
  rk1519 / rk1430   그 시각까지 누적 대금 순위 (판단 시각 정보만)
  chg / chg1519 / chg1430   전일 대비 (종가 / 15:19 / 14:30 가격)
  pos / pos1519 / pos1430   (가격−저가)/(고가−저가) 그 시각까지
  close    정규장 마지막 봉(15:30 동시호가) 종가 = 정규장 종가 매수가
  moon     🌙: 17:00~17:59 첫 봉 종가 > 정규장 종가 → (시각, 가격). pre17 = 16:55~16:59 마지막 가격
  b1431    🧭: 14:31 봉 시가 · nh1430 250일 신고가 · rnd1430 라운드 피겨 ±3% · nxt 전날 19:30 뒤 봉 있음(애프터 거래 종목)
  r_close / r_moon / r_1431   다음 날 09:00 시가 매도 수익률 (비용 0.25%, 엔진 next_day_exits)
  fi/ii    그날 외인/기관 순매수(확정치, 일봉 DB investor_daily) · pfi/pii 전날 · mcap 시총(지금 상장주식수×일봉 종가)
  lead1519 15:19 시점 👑 테마 대장 (common.leader, 네이버 테마 지금 목록 — 근사)
  med1519  그 시각 대금 상위 200 주식 등락 중앙 (4️⃣ 시장 대비 기준)
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.closing_bet_review.build
"""
import os
import pickle
import sys
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.common.leader import load_themes, theme_leaders

OUT = os.path.join(E.DATA, "closing_bet_review")
os.makedirs(OUT, exist_ok=True)
ROUND = sorted({m * 10 ** k for k in range(2, 8) for m in (1, 2.5, 5)})
T1519, T1430 = time(15, 19), time(14, 30)


def near_round(p):
    return any(0.97 <= p / x <= 1.03 for x in ROUND)


def upto(reg, t):
    return [x for x in reg if x[0] <= t]


def main():
    themes = load_themes(os.path.join(E.DATA, "naver_groups.duckdb"))
    rows = []
    for d in E.days():
        nd = E.next_day(d)
        if nd is None:
            continue
        vr = E.value_rank(d)
        pool = [c for c, r in vr.items() if r <= 300]
        B = E.load_day(pool, d)
        prev = E.daily_day(E.prev_day(d))
        info = {}
        for c in pool:
            reg = E.regular(B[c])
            if len(reg) < 60 or c not in prev:
                continue
            f = E.factor(c, d)
            if f is None:
                continue
            pc = prev[c][3] * f
            if not pc:
                continue
            u19, u14 = upto(reg, T1519), upto(reg, T1430)
            if len(u19) < 30 or len(u14) < 20:
                continue
            info[c] = dict(reg=reg, pc=pc, f=f, u19=u19, u14=u14,
                           v_reg=sum(x[4] * x[5] for x in reg), v19=sum(x[4] * x[5] for x in u19),
                           v14=sum(x[4] * x[5] for x in u14))
        if not info:
            continue
        rank = {}
        for key in ("v_reg", "v19", "v14"):
            order = sorted(info, key=lambda c: -info[c][key])
            rank[key] = {c: i + 1 for i, c in enumerate(order)}
        chg19 = {c: x["u19"][-1][4] / x["pc"] - 1 for c, x in info.items()}
        top200 = [c for c, r in rank["v19"].items() if r <= 200]
        med19 = float(np.median([chg19[c] for c in top200]))
        leads = theme_leaders([(c, chg19[c], info[c]["v19"]) for c in info], themes)
        for c, x in info.items():
            reg, pc = x["reg"], x["pc"]
            rk_reg, rk19, rk14 = rank["v_reg"][c], rank["v19"][c], rank["v14"][c]
            if min(rk_reg, rk19, rk14) > 40:
                continue
            close = reg[-1][4]
            hi, lo = max(b[2] for b in reg), min(b[3] for b in reg)
            p19, p14 = x["u19"][-1][4], x["u14"][-1][4]
            h19, l19 = max(b[2] for b in x["u19"]), min(b[3] for b in x["u19"])
            h14, l14 = max(b[2] for b in x["u14"]), min(b[3] for b in x["u14"])
            h250 = E.hi_n(c, d, 250)
            aft = [b for b in B[c] if b[0] >= time(15, 40)]
            pre17 = [b for b in aft if time(16, 55) <= b[0] < time(17, 0)]
            moon = next(((b[0], b[4]) for b in aft if time(17, 0) <= b[0] < time(18, 0) and b[4] > close), None)
            nxt_b = next((b for b in reg if b[0] > T1430), None)
            b1431 = nxt_b[1] if nxt_b and nxt_b[0] <= time(14, 35) else None
            last_is_1530 = reg[-1][0] == time(15, 30)
            E.load_day([c], nd)
            rc = E.next_day_exits(c, d, close).get("09:00 시가") if last_is_1530 else None
            rm = E.next_day_exits(c, d, moon[1]).get("09:00 시가") if moon else None
            r14 = E.next_day_exits(c, d, b1431).get("09:00 시가") if b1431 else None
            nb = E.bars(c, nd)
            o9 = E.open_at(nb, time(9, 0), time(9, 5))
            iv, piv = E.inv(c, d), E.inv(c, E.prev_day(d))
            try:
                nxt = E.nxt_known(c, d)
            except Exception:
                nxt = None
            rows.append(dict(
                date=d, code=c, name=E.NAME.get(c), common=E.is_common(c),
                rk_reg=rk_reg, rk1519=rk19, rk1430=rk14, rk_daily=E.value_rank(d).get(c),
                chg=close / pc - 1, chg1519=p19 / pc - 1, chg1430=p14 / pc - 1,
                pos=(close - lo) / (hi - lo) if hi > lo else 1.0,
                pos1519=(p19 - l19) / (h19 - l19) if h19 > l19 else 1.0,
                pos1430=(p14 - l14) / (h14 - l14) if h14 > l14 else 1.0,
                close=close, p1519=p19, last_is_1530=last_is_1530,
                late30=close / (E.at(reg, time(15, 0)) or close) - 1,
                nh250=bool(h250) and close >= h250 * x["f"],
                nh1430=bool(h250) and p14 >= h250 * x["f"], rnd1430=near_round(p14),
                hi250_ratio=close / (h250 * x["f"]) - 1 if h250 else None,
                moon_t=moon[0] if moon else None, moon_px=moon[1] if moon else None,
                pre17=pre17[-1][4] if pre17 else None, has_after=bool(aft), last_after=aft[-1][4] if aft else None,
                b1431=b1431, nxt=nxt,
                r_close=rc, r_moon=rm, r_1431=r14, gap=o9 / close - 1 if o9 and close else None,
                fi=iv[0] if iv else None, ii=iv[1] if iv else None, pfi=piv[0] if piv else None, pii=piv[1] if piv else None,
                mcap=E.mcap(c, d), v_reg=x["v_reg"], lead1519=c in leads, med1519=med19,
                kospi=E.kospi_chg(d), unsure=(c, d) in E.UNSURE,
            ))
        print(d, len(rows), file=sys.stderr, flush=True)
    pickle.dump(rows, open(os.path.join(OUT, "rows.pkl"), "wb"))
    print("저장", len(rows), dict(E.BASIS_FIX))


if __name__ == "__main__":
    main()
