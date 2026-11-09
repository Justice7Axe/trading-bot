"""'선 하나' = 일봉 거래량 가중 이동평균 100 (VWMA100) 돌파 매수 — 1년 검증
(2026-11-07 사용자: 불장단타왕 '선 하나로 월 13억도 벌어봤습니다', https://youtu.be/msQZetf7_UI, 정리 docs/lectures/bulljang_one_line.md)

영상 규칙(코인 현물 롱, 국내 주식에 옮김):
  선 = 일봉 VWMA(100, 종가) — 화면 범례 'VWMA 100'·'거래량 가중이동평균 100 close 0' (key/08·09·20).
  사는 자리 = 오래 VWMA 아래에 있던 종목이 VWMA 를 처음 뚫는 순간. VWMA 가 빠르게 내려오고(바닥 매집), 값이 VWMA 근처에서
             옆으로 붙어 있다 뚫는 것이 좋음. 멀리 아래서 치고 올라와 박는 것·이미 한 번 뚫고 크게 오른 것·뚫고 내려온 것은 안 함.
  손절 = VWMA 깨지면(거가 깨지면 팔아야). 익절 = 10~15% 또는 다음 날 올랐으면 절반.
숫자 가정:
  아래 머문 기간 L: 전날까지 L일 연속 종가 < VWMA (기본 20, 시험 5·60)
  VWMA 기울기: 전날 VWMA ÷ 21일 전 VWMA − 1 < 0 (기본), 시험 '조건 없음'·'< −5%'
  가까움: 전날 종가 ≥ 전날 VWMA × 0.95 (기본), 시험 '조건 없음'
  매수(A 장중 돌파): 그날 09:00~15:19 정규장 1분봉에서 처음 고가 ≥ 전날 VWMA(1분봉 가격으로 환산) 인 봉 → max(시가, 선 가격) 체결.
  매수(B 종가 확인): 그날 종가 > 그날 VWMA → 다음 날 09:00 시가.
  매도 ① 하루짜리(공통 원칙): 선 −s% 손절(s=2·4), 익절 tp(없음·+5·+10%), 둘 다 아니면 다음 날 09:00 시가. 비용 0.25%.
  매도 ② 영상식 보유: 일봉 종가 < 그날 VWMA → 다음 날 시가, 익절 +10·+15%(닿으면), 최대 20거래일.
대상: 전날 대금 상위 100 (보통주, 상장 120거래일↑). 시장: 전날 코스피 종가 vs 코스피 대금 가중 100일선.
"""
import os
import sys
from collections import defaultdict
from datetime import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\Ellie\trading")
from kiwoom_trading.backtest import engine as E  # noqa: E402

OUT = r"D:\Ellie\trading\data\lectures\yt\msQZetf7_UI"
COST = E.COST
N = 100

# ---------------- 일봉 VWMA100 (수정주가 일봉끼리)
D0 = E.CAL[E.CIDX[E.P0] - 200]
df = E.DM.execute("SELECT code, date, open, high, low, close, volume FROM daily_ohlcv WHERE date >= ? AND close > 0", [D0]).df()
df["date"] = pd.to_datetime(df["date"]).dt.date
C = df.pivot(index="date", columns="code", values="close").sort_index()
V = df.pivot(index="date", columns="code", values="volume").sort_index().fillna(0)
H = df.pivot(index="date", columns="code", values="high").sort_index()
L_ = df.pivot(index="date", columns="code", values="low").sort_index()
O = df.pivot(index="date", columns="code", values="open").sort_index()
PV = (C * V)
VW = PV.rolling(N, min_periods=N).sum() / V.rolling(N, min_periods=N).sum()
BELOW = (C < VW).astype(float)
SLOPE = VW / VW.shift(20) - 1
GAP = C / VW - 1
NROWS = C.notna().cumsum()
DIDX = {d: i for i, d in enumerate(C.index)}

# 코스피 대금 가중 100일선
ix = E.IX.execute("SELECT date, close, value FROM idx_daily WHERE code='001' ORDER BY date").df()
ix["date"] = pd.to_datetime(ix["date"]).dt.date
ix = ix.set_index("date")
ix["vw"] = (ix.close * ix.value).rolling(N).sum() / ix.value.rolling(N).sum()
ix["ma20"] = ix.close.rolling(20).mean()
MKT_UP = (ix.close > ix.vw).to_dict()
MKT20 = (ix.close > ix.ma20).to_dict()


def below_run(code, i, L):
    """i 일까지 L일 연속 종가 < VWMA."""
    s = BELOW[code].iloc[i - L + 1:i + 1]
    return len(s) == L and s.min() == 1.0


def swing_exit(code, d, buy_adj, tps, maxhold=20):
    """d일 매수(일봉 가격 buy_adj). 이후 일봉으로: 익절 tp 닿으면 그 값, 종가 < VWMA → 다음 날 시가, 최대 maxhold일 뒤 다음 날 시가."""
    out = {}
    i0 = DIDX[d]
    for tp in tps:
        tpp = buy_adj * (1 + tp) if tp else None
        ret = None; why = None
        exit_next = False
        for k in range(i0, min(i0 + maxhold + 2, len(C.index))):
            dk = C.index[k]
            o, h, c = O[code].iloc[k], H[code].iloc[k], C[code].iloc[k]
            if np.isnan(c):
                continue
            if exit_next:
                ret = o / buy_adj - 1 - COST; break
            if k > i0 and tpp and h >= tpp:
                ret = max(o, tpp) / buy_adj - 1 - COST; why = "익절"; break
            if c < VW[code].iloc[k] or k - i0 >= maxhold:
                exit_next = True
        if ret is None:   # 자료 끝: 마지막 종가로 평가
            ret = C[code].dropna().iloc[-1] / buy_adj - 1 - COST
        out[tp] = ret
    return out


def nextday_open(code, d):
    n = E.next_day(d)
    if not n:
        return None
    b = E.bars(code, n)
    return E.open_at(b, time(9, 0), time(9, 5))


rows = []
days = [d for d in E.days() if d in DIDX]
for di, d in enumerate(days):
    prev = E.prev_day(d)
    if prev not in DIDX:
        continue
    ip = DIDX[prev]
    vr = E.value_rank(prev)
    codes = [c for c, r in vr.items() if r <= 100 and E.is_common(c) and c in VW.columns]
    for c in codes:
        if NROWS[c].iloc[ip] < 120 or np.isnan(VW[c].iloc[ip]):
            continue
        cl, vw = C[c].iloc[ip], VW[c].iloc[ip]
        if np.isnan(cl) or cl >= vw:
            continue   # 전날 이미 VWMA 위 → '처음 뚫음' 아님
        run = 0
        while run < 120 and BELOW[c].iloc[ip - run] == 1.0:
            run += 1
        base = dict(date=d, code=c, run=run, slope=SLOPE[c].iloc[ip], gap=GAP[c].iloc[ip],
                    mkt=MKT_UP.get(prev), mkt20=MKT20.get(prev))
        f = E.factor(c, d)
        if not f:
            continue
        lvl = vw * f
        b = E.regular(E.bars(c, d))
        # ---- A: 장중 돌파
        j = next((k for k, x in enumerate(b) if x[0] <= time(15, 19) and x[2] >= lvl), None)
        if j is not None:
            x = b[j]
            buy = max(x[1], lvl)
            gapopen = j == 0 and x[1] >= lvl
            r = dict(base, kind="A", t=x[0].strftime("%H:%M"), buy=buy, gapopen=gapopen, gapopen_pct=x[1] / lvl - 1 if j == 0 else 0.0)
            ex = E.next_day_exits(c, d, buy)
            o9 = ex.get("09:00 시가")
        if j is not None and o9 is not None:
            for s in (0.02, 0.04):
                sp = lvl * (1 - s)
                for tp in (None, 0.05, 0.10):
                    tpp = buy * (1 + tp) if tp else None
                    ret = None
                    for y in b[j + 1:]:
                        if y[3] <= sp:
                            ret = min(y[1], sp) / buy - 1 - COST; break
                        if tpp and y[2] >= tpp:
                            ret = max(y[1], tpp) / buy - 1 - COST; break
                    if ret is None:
                        ret = o9
                        # 다음 날 시가가 손절선 아래면 그대로 시가 (o9 에 이미 반영)
                    r[f"r_s{int(s*100)}_tp{int(tp*100) if tp else 0}"] = ret
            # 영상식 보유 (일봉, 매수가를 일봉 기준으로)
            sw = swing_exit(c, d, buy / f, (None, 0.10, 0.15))
            for tp, v in sw.items():
                r[f"sw_tp{int(tp*100) if tp else 0}"] = v
            rows.append(r)
        # ---- B: 종가 확인 → 다음 날 09:00 시가
        i0 = DIDX[d]
        if C[c].iloc[i0] > VW[c].iloc[i0]:
            n = E.next_day(d)
            if n and n in DIDX:
                fn = E.factor(c, n)
                o = nextday_open(c, d)
                if fn and o:
                    buy_adj = o / fn
                    r = dict(base, kind="B", t="09:00", buy=o, gapopen=False, gapopen_pct=0.0)
                    ex = E.next_day_exits(c, n, o)
                    if "09:00 시가" in ex:
                        bn = E.regular(E.bars(c, n))
                        lvlb = VW[c].iloc[i0] * fn
                        for s in (0.02, 0.04):
                            sp = lvlb * (1 - s)
                            for tp in (None, 0.05, 0.10):
                                tpp = o * (1 + tp) if tp else None
                                ret = None
                                for y in bn[1:]:
                                    if y[3] <= sp:
                                        ret = min(y[1], sp) / o - 1 - COST; break
                                    if tpp and y[2] >= tpp:
                                        ret = max(y[1], tpp) / o - 1 - COST; break
                                r[f"r_s{int(s*100)}_tp{int(tp*100) if tp else 0}"] = ret if ret is not None else ex["09:00 시가"]
                        sw = swing_exit(c, n, buy_adj, (None, 0.10, 0.15))
                        for tp, v in sw.items():
                            r[f"sw_tp{int(tp*100) if tp else 0}"] = v
                        rows.append(r)
    if di % 20 == 0:
        print(d, len(rows), file=sys.stderr, flush=True)

T = pd.DataFrame(rows)
T.to_csv(os.path.join(OUT, "trades.csv"), index=False, encoding="utf-8-sig")
print("저장", len(T))
