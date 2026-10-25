"""강창권 『주식투자 단기 트레이딩의 정석』 일봉 기법 2년 백테스트 (전 종목 일봉, 2024-10 ~ 2026-10).

공통: 신호일 D 의 일봉이 다 만들어진 뒤 판단 → D 종가 매수 (종가 베팅). 비용 0.25%, 건당 100만.
대상: D 거래대금 ≥ 30억, 종가 ≥ 1,000원, 상한가(+29.5%↑) 마감 종목은 못 사니 뺀다.
매도 (memory backtest-exit-rules — 종가 매도 없음):
  종가 베팅형  → D+1 시가 (갭 상승 노림)
  스윙형      → 익절가에 닿으면 그 가격, 손절가에 닿으면 그 가격 (같은 날이면 손절 먼저, 시가가 이미 넘으면 시가),
                이동평균선 이탈은 그날 종가로 확인하고 다음 날 시가 매도. 최대 보유 일수 지나면 다음 날 시가.
책이 숫자를 안 준 자리(거래량 배수·지지 판정·손절 %)는 여러 값을 나란히 본다 → 스킬 kang 7장.

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/kang/scripts/kang_daily_bt.py > data/kang/daily_bt.txt
"""
import os
import shutil
import sys
import tempfile
from collections import defaultdict

import duckdb
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
COST = 0.0025


def _copy(name):
    dst = os.path.join(tempfile.gettempdir(), "kangd_" + name)
    shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


con = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
df = con.execute("""SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.value, s.listed_shares,
                           i.foreign_, i.institution
                    FROM daily_ohlcv d JOIN stocks s USING (code)
                    LEFT JOIN investor_daily i ON i.code = d.code AND i.date = d.date
                    WHERE d.open > 0 AND d.close > 0 ORDER BY d.code, d.date""").df()
g = df.groupby("code", sort=False)
for n in (5, 10, 20, 60, 120, 240):
    df[f"ma{n}"] = g["close"].transform(lambda s, n=n: s.rolling(n, min_periods=n).mean())
df["v5"] = g["volume"].transform(lambda s: s.shift(1).rolling(5).mean())
df["v20"] = g["volume"].transform(lambda s: s.shift(1).rolling(20).mean())
df["pc"] = g["close"].shift(1)
df["chg"] = df["close"] / df["pc"] - 1
df["hi250"] = g["high"].transform(lambda s: s.shift(1).rolling(250, min_periods=200).max())
df["hi20"] = g["high"].transform(lambda s: s.shift(1).rolling(20).max())
for k in (1, 2, 3, 4):
    for c in ("open", "high", "low", "close", "volume", "chg"):
        df[f"{c}_{k}"] = g[c].shift(k)
for k in (1, 2):
    df[f"ma240_{k}"] = g["ma240"].shift(k)
    df[f"f_{k}"] = g["foreign_"].shift(k)
    df[f"i_{k}"] = g["institution"].shift(k)
df["body"] = (df["close"] - df["open"]).abs()
df["rng"] = df["high"] - df["low"]
df["doji"] = (df["body"] <= 0.3 * df["rng"]) & (df["body"] / df["open"] <= 0.015)
df["cap"] = df["close"] * df["listed_shares"]
df["ok"] = (df["value"] >= 3e9) & (df["close"] >= 1000) & (df["chg"] < 0.295)
# 최근 25일 안 급등: 10일 동안 저가 대비 종가 +50% 이상, 그 고점 날짜
c10min = g["low"].transform(lambda s: s.rolling(10).min())
df["run10"] = df["close"] / c10min - 1
df["run_max25"] = g["run10"].transform(lambda s: s.shift(1).rolling(25).max())
df["peak25"] = g["close"].transform(lambda s: s.shift(1).rolling(25).max())
df["upday20"] = g["chg"].transform(lambda s: s.shift(1).rolling(20).max())

ARR = {c: g for c, g in df.groupby("code", sort=False)}
IDX = {c: {d: i for i, d in enumerate(x["date"].values)} for c, x in ARR.items()}
DAYS = sorted(df["date"].unique())


def days_since_peak(x, i, look=25):
    seg = x["close"].values[max(0, i - look):i]
    return len(seg) - int(np.argmax(seg)) if len(seg) else 0


def exit_next_open(x, i):
    """D 종가 매수 → D+1 시가 매도."""
    if i + 1 >= len(x):
        return None
    return x["open"].values[i + 1] / x["close"].values[i] - 1 - COST


def exit_swing(x, i, tp=None, sl=None, ma=None, ma_days=1, hold=20):
    """D 종가 매수. 익절가·손절가는 장중 닿으면 그 가격 (같은 날 둘 다면 손절 먼저, 시가가 이미 넘었으면 시가).
    ma 이탈 = 종가 < 그 선이 ma_days 일 연속 → 다음 날 시가. hold 일 지나면 다음 날 시가."""
    o, h, l, c = (x[k].values for k in ("open", "high", "low", "close"))
    buy = c[i]
    mav = x[ma].values if ma else None
    under = 0
    for j in range(i + 1, min(len(x), i + 1 + hold)):
        if sl and l[j] <= buy * (1 - sl):
            return min(o[j], buy * (1 - sl)) / buy - 1 - COST
        if tp and h[j] >= buy * (1 + tp):
            return max(o[j], buy * (1 + tp)) / buy - 1 - COST
        if ma is not None and c[j] < mav[j]:
            under += 1
            if under >= ma_days:
                return (o[j + 1] if j + 1 < len(x) else c[j]) / buy - 1 - COST
        else:
            under = 0
    j = min(len(x) - 1, i + hold + 1)
    return o[j] / buy - 1 - COST if j > i else None


HALF = DAYS[len(DAYS) // 2]


def stats(tr, title):
    if len(tr) < 15:
        print(f"   {title:58s} {len(tr):4d}건 (적음)")
        return
    v = np.array([t[1] for t in tr])
    half = sorted(d for d, _ in tr)[len(tr) // 2]   # 신호 날짜 가운데로 앞/뒤
    a = [x for d, x in tr if d < half]; b = [x for d, x in tr if d >= half]
    bd = defaultdict(float)
    for d, x in tr:
        bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    w = v[v > 0]; ls = v[v <= 0]
    pf = (w.mean() / -ls.mean()) if len(w) and len(ls) and ls.mean() < 0 else float("nan")
    ok = "★" if a and b and np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
    print(f"  {ok}{title:58s} {len(v):4d}건 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+6.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+6.0f}만 "
          f"승률 {len(w) / len(v):.0%} 손익비 {pf:.2f} | 앞 {np.mean(a) if a else 0:+.2%} 뒤 {np.mean(b) if b else 0:+.2%} | 낙폭 {mdd * 100:.0f}만")


def run(title, cond, exits):
    sig = df[df["ok"] & cond]
    print(f"\n=== {title}  (신호 {len(sig)}건, {sig['date'].min()} ~ {sig['date'].max()})")
    for name, fn in exits:
        tr = []
        for code, d in zip(sig["code"].values, sig["date"].values):
            x = ARR[code]; i = IDX[code][d]
            r = fn(x, i)
            if r is not None:
                tr.append((d, r))
        stats(tr, name)


NEXT = [("다음 날 시가 매도", exit_next_open)]
SWING = [
    ("다음 날 시가 매도 (비교)", exit_next_open),
    ("익절 +10% / 손절 −5% / 최대 20일", lambda x, i: exit_swing(x, i, tp=0.10, sl=0.05)),
    ("익절 +10% / 손절 −8% / 최대 20일", lambda x, i: exit_swing(x, i, tp=0.10, sl=0.08)),
    ("익절 +5% / 손절 −5% / 최대 10일", lambda x, i: exit_swing(x, i, tp=0.05, sl=0.05, hold=10)),
]

if __name__ == "__main__":
    print("강창권 일봉 기법 백테스트 — 대상: 대금 30억↑·1,000원↑, 종가 매수, 비용 0.25%, 건당 100만. ★ = 앞·뒤 반 모두 + 이고 최고 5일 빼도 +")
    print(f"기간 {str(DAYS[0])[:10]} ~ {str(DAYS[-1])[:10]}, 앞/뒤 = 기법마다 신호 날짜 가운데로 나눔. 낙폭 = 날짜별 합계 누적의 최대 하락(겹친 보유 포함)")
    print("⚠️ 일봉 DB 는 지금 상장된 종목만 있어 상장 폐지 종목이 빠짐 → 긴 보유(스윙) 결과는 실제보다 좋게 나올 수 있음")
    run("[기준선] 대상 종목 전부 종가 매수 → 다음 날 시가", df["chg"] > -1, NEXT)
    run("[기준선] 오늘 +5%↑ 오른 종목 종가 매수", df["chg"] >= 0.05, NEXT)
    big_bull = (df["close"] / df["open"] - 1 >= 0.05) & (df["chg"] >= 0.05)
    # 9-3 바닥권 거래량 300%↑ + 장대 양봉이 240일선 종가 돌파
    for vx in (3, 4):
        cross = (df["close"] > df["ma240"]) & (df["close_1"] <= df["ma240_1"])
        run(f"[9-3] 거래량 {vx}배↑ + 장대양봉(+5%) + 240일선 종가 돌파 → 종가 매수", big_bull & cross & (df["volume"] >= vx * df["v20"]),
            SWING + [("240일선 아래 종가 2일 → 다음 날 시가", lambda x, i: exit_swing(x, i, ma="ma240", ma_days=2, hold=60))])
    run("[9-3] 위 + 바닥권(종가 ≤ 250일 고가 × 0.6)", big_bull & (df["close"] > df["ma240"]) & (df["close_1"] <= df["ma240_1"])
        & (df["volume"] >= 3 * df["v20"]) & (df["close"] <= 0.6 * df["hi250"]), SWING)
    # 9-2 도지 종가 베팅
    d1 = (df["chg_1"] >= 0.10) & (df["close_1"] > df["open_1"]) & (df["high_1"] - df["close_1"] >= (df["close_1"] - df["open_1"]) / 3)
    run("[9-2] 전날 +10%↑ 위꼬리(몸통 1/3↑) → 오늘 거래량 감소 도지 → 종가 매수", d1 & df["doji"] & (df["volume"] < df["volume_1"]), NEXT)
    run("[9-2] 위 + 전날 +15%↑", d1 & (df["chg_1"] >= 0.15) & df["doji"] & (df["volume"] < df["volume_1"]), NEXT)
    # 10-3 / 16-2 10일선 도지
    pull4 = (df["close"] < df["close_4"]) & (df["close_1"] < df["close_4"])
    run("[10-3] 20일 안 +15%↑ 급등 → 4일 조정 → 10일선 지지 도지·거래량 감소 → 종가 매수",
        (df["upday20"] >= 0.15) & pull4 & (df["low"] <= df["ma10"] * 1.01) & (df["close"] >= df["ma10"]) & df["doji"] & (df["volume"] < df["v5"]), NEXT)
    # 4-2 / 16-1 / 16-3 급등 후 20일선 눌림
    surge = df["run_max25"] >= 0.5
    for ma, lo, hi in (("ma20", 8, 20), ("ma10", 10, 20)):
        touch = (df["low"] <= df[ma] * 1.02) & (df["close"] >= df[ma])
        dry = df["volume"] <= 0.5 * df["v20"]
        base = surge & touch & dry & (df["close"] <= df["peak25"] * 0.9)
        sel = df[df["ok"] & base]
        keep = [days_since_peak(ARR[c], IDX[c][d]) for c, d in zip(sel["code"].values, sel["date"].values)]
        mask = pd.Series(False, index=df.index)
        mask.loc[sel.index] = [lo <= k <= hi for k in keep]
        run(f"[4-2/16장] 25일 안 +50%↑ 급등 → 고점 뒤 {lo}~{hi}일 조정·거래량 절반↓ → {ma[2:]}일선 지지", mask,
            SWING + [(f"{ma[2:]}일선 아래 종가 5일 → 다음 날 시가 (책: 1주일 안 회복)", lambda x, i, m=ma: exit_swing(x, i, ma=m, ma_days=5, hold=30))])
    # 4-3 60일선 반등
    sel60 = surge & (df["low"] <= df["ma60"] * 1.02) & (df["close"] >= df["ma60"]) & (df["close"] <= df["peak25"] * 0.8) & (df["volume"] <= 0.6 * df["v20"])
    run("[4-3] +50%↑ 급등 후 60일선까지 눌림·거래량 감소 → 종가 매수", sel60, SWING)
    # 9-1 기관·외인 종가 베팅 (확정 수급 = 미래 정보 주의)
    newhi = (df["close"] >= df["hi20"]) & (df["close"] >= 0.97 * df["high"])
    run("[9-1] 기관·외인 둘 다 순매수 + 일봉 20일 고가 갱신 → 종가 매수 (확정치)", newhi & (df["foreign_"] > 0) & (df["institution"] > 0), NEXT)
    run("[9-1] 기관 순매수 + 일봉 20일 고가 갱신 → 종가 매수 (확정치)", newhi & (df["institution"] > 0), NEXT)
    run("[9-1 비교] 일봉 20일 고가 갱신만 (수급 조건 없음)", newhi, NEXT)
    # 13-1 / 13-4 신고가 돌파 + 정배열 + 거래량 → 5일선 보유
    nh = (df["close"] > df["hi250"]) & (df["volume"] >= 2 * df["v20"]) & (df["ma5"] > df["ma20"]) & (df["ma20"] > df["ma60"]) & (df["ma60"] > df["ma120"])
    run("[13-1 비교] 정배열 + 거래량 2배↑ + 양봉 (신고가 아님)", (df["close"] <= df["hi250"]) & (df["close"] > df["open"]) & (df["volume"] >= 2 * df["v20"])
        & (df["ma5"] > df["ma20"]) & (df["ma20"] > df["ma60"]) & (df["ma60"] > df["ma120"]),
        NEXT + [("20일선 아래 종가 → 다음 날 시가", lambda x, i: exit_swing(x, i, ma="ma20", hold=120))])
    run("[13-1] 250일 신고가 돌파 + 정배열 + 거래량 2배↑ → 종가 매수", nh,
        NEXT + [("5일선 아래 종가 → 다음 날 시가 (책 5일선 보유)", lambda x, i: exit_swing(x, i, ma="ma5", hold=60)),
                ("20일선 아래 종가 → 다음 날 시가", lambda x, i: exit_swing(x, i, ma="ma20", hold=120)),
                ("5일선 이탈 + 손절 −5%", lambda x, i: exit_swing(x, i, ma="ma5", sl=0.05, hold=60))])
    # B-9 5·20 골든크로스 (정배열 초기)
    gc = (df["ma5"] > df["ma20"]) & (g["ma5"].shift(1) <= g["ma20"].shift(1)) & (df["close"] > df["open"]) & (df["volume"] >= 1.5 * df["v20"])
    run("[2장] 5·20일 골든크로스 + 양봉 + 거래량 1.5배↑ → 종가 매수", gc,
        NEXT + [("20일선 아래 종가 → 다음 날 시가", lambda x, i: exit_swing(x, i, ma="ma20", hold=60))])
    sys.stdout.flush()
