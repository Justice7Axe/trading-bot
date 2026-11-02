"""🔺 홍인기 D+ 대장 후보 고르기·체결 연구 — 자료 만들기 (2026-11-02 사용자: '고르기·체결을 어떻게 맞춰서 수익을 올릴 수 있을지').

후보 = strategies/hong_dplus 의 D+0 장중 대장(대금 20위 기준) + 중소형 대장, 09:30~14:30 에 처음 대장이 된 순간(신호 분 i).
특징 = 신호 분 i 까지 알 수 있는 것만 (그 분 누적 대금·등락률, 섹터 동료, 전날까지 일봉·수급, 지수 그 시각).
결과 = 사는 방법 × 파는 방법 수익률 (비용 0.25%, 같은 봉이면 손절 먼저, 종가 매도 없음):
  사기  E1 다음 봉 시가(+28%↑ 면 못 삼) / E2 신호가 −2% 지정가 30분 안 / E3 상한가(+29.5%) 닿은 뒤 그날 풀린 적 있을 때만 상한가 체결
  팔기  X1 −3% 손절 아니면 다음 날 09:00 / X2 손절 없이 다음 날 09:00 / X3 손절 없이 다음 날 NXT 08:00 시가 / X4 −3% 손절 · 15:19 매도(당일 정리)
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.hong_pick.build
  → data/hong_pick/cands.parquet
"""
import os
import sys
from datetime import time

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.hong_dplus import backtest as B
from kiwoom_trading.strategies.hong_dplus import rules as R

OUT = os.path.join(E.DATA, "hong_pick")
os.makedirs(OUT, exist_ok=True)
_IX = {}


def idx_min(code, d):
    if (code, d) not in _IX:
        rows = E.IX.execute("SELECT ts, close FROM idx_min WHERE code=? AND ts >= ? AND ts < ? ORDER BY ts",
                            [code, pd.Timestamp(d) + pd.Timedelta(hours=9), pd.Timestamp(d) + pd.Timedelta(hours=15, minutes=31)]).fetchall()
        _IX[(code, d)] = {B.tidx(r[0].time()): r[1] for r in rows}
    return _IX[(code, d)]


IDXC = {c: dict(E.IX.execute("SELECT date, close FROM idx_daily WHERE code=?", [c]).fetchall()) for c in ("001", "101")}


def idx_chg(code, d, i):
    m = idx_min(code, d); p = IDXC[code].get(E.prev_day(d))
    ks = [k for k in m if k <= i]
    return m[max(ks)] / p - 1 if ks and p else np.nan


def exits(c, d, reg, k, buy, limit_fill=False):
    out = {}
    nx = E.next_day_exits(c, d, buy)
    r, _, xt = B.exit_path(reg, k, buy, sp=buy * 0.97, until=time(15, 30), skip_tp_first=limit_fill)
    out["X1"] = r if r is not None else nx.get("09:00 시가")
    out["X2"] = nx.get("09:00 시가")
    out["X3"] = nx.get("08:00 NXT 시가")
    r, _, xt = B.exit_path(reg, k, buy, sp=buy * 0.97, until=time(15, 19))
    out["X4"] = r if r is not None else E.at(reg, time(15, 19)) / buy - 1 - E.COST
    return out


def day_rows(d):
    dy = B.Day(d)
    if not dy.keep:
        return []
    p = E.prev_day(d); pdd = E.daily_day(p)
    seen, out = set(), []
    for i in range(B.tidx(time(*R.FIRST_BUY)), B.tidx(time(*R.LAST_BUY)) + 1):
        lead, leaders = dy.lead[i]
        cands = [(c, th, 0) for c, th in leaders.items()] + [(c, th, 1) for c, th in dy.small[i].items()]
        for c, th, small in cands:
            if c in seen:
                continue
            seen.add(c)
            j = dy.idx[c]; reg = dy.REG[c]; f = dy.F[c]; pc = dy.PC[j]; ch = dy.CH[j, i]
            mem = lead[th]                                   # [(code, chg)] 대금 20위 안 +5%↑ 동료
            mch = sorted([m[1] for m in mem], reverse=True)
            mrank = [dy.rank(m[0], i) for m in mem if m[0] in dy.idx]
            others = [x for x in mch if x != ch] or [0]
            h20 = E.hist(c, d, 20)
            v20 = np.mean([x[6] or 0 for x in h20]) if h20 else np.nan
            hi = E.hi_n(c, d, 250)
            ma20 = E.ma_n(c, d, 20)
            iv = E.inv(c, p)
            mc = E.mcap(c, p)
            prev_chg = E.chg(c, p)
            pre = dy.PRE.get(c)
            row = dict(date=d, code=c, name=E.NAME.get(c, c), theme=th, small=small, t_sig=i,
                       chg=ch, rank=dy.rank(c, i), cv=dy.CV[j, i] / 1e8, accel=dy.CV[j, i] / v20 if v20 else np.nan,
                       n_mem=len(mem), mem_mean=np.mean(mch), mem_n15=sum(x >= 0.15 for x in mch), mem_rank=np.mean(mrank) if mrank else np.nan,
                       margin=ch - max(others), lmcap=np.log10(mc) if mc else np.nan, dist_hi=(dy.CL[j, i] / f) / hi - 1 if hi else np.nan,
                       ma20_pos=(pdd[c][3] / ma20 - 1) if ma20 else np.nan, prev_chg=prev_chg, gap=reg[0][1] / pc - 1,
                       pre_chg=pre / pc - 1 if pre else np.nan, nxt=int(pre is not None),
                       kospi=idx_chg("001", d, i), kosdaq=idx_chg("101", d, i),
                       frg=(iv[0] if iv else np.nan), ins=(iv[1] if iv else np.nan),
                       f_recent=int(B.recent_theme(th, d)), f_past=int(B.past_leader(c, d, th)), f_quiet=int(B.first_big(c, d)), f_kki=int(B.kki(c, d)),
                       lead_cnt60=sum(c in B.day_lead(E.prev_day(d, k))[1] for k in range(1, 61)),
                       sec_cnt20=sum(th in B.day_lead(E.prev_day(d, k))[0] for k in range(1, 21)))
            # E1 다음 봉 시가
            k = next((n for n, x in enumerate(reg) if B.tidx(x[0]) > i), None)
            if k is not None and ch < 0.28:
                buy = reg[k][1]; row.update(px1=buy, t1=reg[k][0])
                row.update({f"E1{x}": v for x, v in exits(c, d, reg, k, buy).items()})
            # E2 신호가 −2% 지정가, 30분 안
            sig_px = dy.CL[j, i]; lim = sig_px * 0.98
            k2 = next((n for n, x in enumerate(reg) if i < B.tidx(x[0]) <= i + 30 and x[3] <= lim), None)
            if k2 is not None:
                buy = min(reg[k2][1], lim); row.update(px2=buy, t2=reg[k2][0])
                row.update({f"E2{x}": v for x, v in exits(c, d, reg, k2, buy, limit_fill=True).items()})
            # E3 상한가 닿은 뒤 풀린 적 있으면 상한가 체결
            limp = pc * 1.295
            k3 = next((n for n, x in enumerate(reg) if B.tidx(x[0]) > i and x[2] >= limp), None)
            row["hit_limit"] = int(k3 is not None)
            if k3 is not None and B.limit_released(reg, k3, limp):
                kf = next(n for n in range(k3 + 1, len(reg)) if reg[n][3] < limp * 0.995)
                row.update(px3=limp, t3=reg[kf][0])
                row.update({f"E3{x}": v for x, v in exits(c, d, reg, kf, limp, limit_fill=True).items()})
            out.append(row)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for n, d in enumerate(E.days()):
        if not E.next_day(d):
            continue
        rows += day_rows(d)
        if n % 20 == 0:
            print(f"  {d} 후보 {len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(os.path.join(OUT, "cands.parquet"))
    print("저장", len(df))


if __name__ == "__main__":
    main()
