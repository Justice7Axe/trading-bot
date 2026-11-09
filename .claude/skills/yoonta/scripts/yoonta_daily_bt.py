"""윤타 『주식 단타 특공대』 일봉 규칙 2년 확인 (전 종목 일봉, 2024-10 ~ 2026-10).

1장 캔들·거래량 해석(57~73쪽)이 다음 날·5일 뒤 실제로 맞는지, 그리고 책이 '반드시 외워두라'고 한 문장(87쪽)
"거래량이 터진 양봉 → 거래량이 줄면서 눌림 → 그 자리에서 지지가 확인되면 매수" 의 일봉판, 저돌(197쪽)의 일봉 종가판.
공통: 신호일 D 일봉이 끝난 뒤 판단 → D 종가 매수. 비용 0.25%, 건당 100만. 대상: D 대금 ≥ 30억, 종가 ≥ 1,000원,
우선주·스팩 제외, 상한가(+29.5%↑) 마감은 못 사니 뺀다.
매도 (메모리 backtest-exit-rules): 다음 날 시가 / 스윙은 익절·손절가 닿으면 그 가격(같은 날이면 손절 먼저, 시가가 넘으면 시가),
  일봉 4선 이탈(4턴4꺾)은 종가 확인 → 다음 날 시가. 최대 보유 지나면 다음 날 시가.

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_daily_bt.py > data/yoonta/daily_bt.txt
"""
import os
import shutil
import sys
import tempfile
from collections import defaultdict

import duckdb
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
COST = 0.0025


def _copy(name):
    dst = os.path.join(tempfile.gettempdir(), "yoontad_" + name)
    shutil.copy(os.path.join(ROOT, "data", name), dst)
    return dst


con = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
df = con.execute("""SELECT d.code, s.name, d.date, d.open, d.high, d.low, d.close, d.volume, d.value
                    FROM daily_ohlcv d JOIN stocks s USING (code)
                    WHERE d.open > 0 AND d.close > 0 AND right(d.code, 1) = '0' AND s.name NOT LIKE '%스팩%'
                    ORDER BY d.code, d.date""").df()
g = df.groupby("code", sort=False)
df["ma4"] = g["close"].transform(lambda s: s.rolling(4).mean())
df["v20"] = g["volume"].transform(lambda s: s.shift(1).rolling(20).mean())
df["vmax60"] = g["volume"].transform(lambda s: s.shift(1).rolling(60).max())
df["pc"] = g["close"].shift(1)
df["pvol"] = g["volume"].shift(1)
df["chg"] = df["close"] / df["pc"] - 1
df["hi60"] = g["high"].transform(lambda s: s.shift(1).rolling(60).max())
df["hi120"] = g["high"].transform(lambda s: s.shift(1).rolling(120, min_periods=100).max())
df["lo120"] = g["low"].transform(lambda s: s.shift(1).rolling(120, min_periods=100).min())
df["rng"] = df["high"] - df["low"]
df["body"] = df["close"] - df["open"]
df["up3"] = g["chg"].transform(lambda s: (s > 0).astype(int).rolling(3).sum().shift(1)) >= 3
df["ok"] = (df["value"] >= 3e9) & (df["close"] >= 1000) & (df["chg"] < 0.295)
# 바닥권 = 120일 범위 아래 1/3, 고가권 = 위 1/3 (책 '바닥권/단기 고점'에 숫자가 없음)
pos = (df["close"] - df["lo120"]) / (df["hi120"] - df["lo120"])
df["bottom"] = pos <= 1 / 3
df["top"] = pos >= 2 / 3
df["long_bull"] = (df["chg"] >= 0.07) & (df["body"] >= 0.6 * df["rng"])
df["long_bear"] = (df["chg"] <= -0.07) & (-df["body"] >= 0.6 * df["rng"])
df["volx3"] = df["volume"] >= 3 * df["v20"]

C = {c: df[c].values for c in ("code", "date", "open", "high", "low", "close", "volume", "ma4")}
codes = C["code"]
nxt = np.r_[codes[1:] == codes[:-1], False]
START = np.datetime64("2024-10-15")


def fwd(i, k):
    """i 번째 행 종가 매수 → k 일 뒤 종가 (사실 확인용, 매매 결과 아님)."""
    j = i + k
    if j >= len(codes) or codes[j] != codes[i]:
        return np.nan
    return C["close"][j] / C["close"][i] - 1


def next_open(i):
    if not nxt[i]:
        return None
    return C["open"][i + 1] / C["close"][i] - 1 - COST


def swing(i, tp=None, stop=None, trail4=False, maxd=10):
    """i 종가 매수. tp/stop = 가격. trail4 = 일봉 종가 < 4일선 → 다음 날 시가."""
    buy = C["close"][i]
    for k in range(1, maxd + 1):
        j = i + k
        if j >= len(codes) or codes[j] != codes[i]:
            return None
        o, h, l, c = C["open"][j], C["high"][j], C["low"][j], C["close"][j]
        if stop and l <= stop:
            return min(o, stop) / buy - 1 - COST
        if tp and h >= tp:
            return max(o, tp) / buy - 1 - COST
        if (trail4 and c < C["ma4"][j]) or k == maxd:
            if j + 1 < len(codes) and codes[j + 1] == codes[i]:
                return C["open"][j + 1] / buy - 1 - COST
            return None
    return None


def stats(rows, title):
    rows = [r for r in rows if r[1] is not None]
    if len(rows) < 20:
        print(f"   {title:46s} {len(rows):4d}건 (적음)")
        return
    v = np.array([r[1] for r in rows])
    ds = sorted(r[0] for r in rows); half = ds[len(ds) // 2]
    a = [x for d, x in rows if d < half]; b = [x for d, x in rows if d >= half]
    bd = defaultdict(float)
    for d, x in rows:
        bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    w = v[v > 0]; ls = v[v <= 0]
    pf = w.mean() / -ls.mean() if len(w) and len(ls) else float("nan")
    ok = "★" if np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
    print(f"  {ok}{title:46s} {len(v):5d}건 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+6.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+6.0f}만 "
          f"손익비 {pf:.2f} 승률 {len(w) / len(v):.0%} | 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} | 낙폭 {mdd * 100:.0f}만")


m = (df["date"].values >= START) & df["ok"].values
print("윤타 『주식 단타 특공대』 일봉 규칙 확인 — 2024-10-15 ~, 대금 30억↑·1,000원↑, 비용 0.25%, 건당 100만. ★ = 앞·뒤 반 모두 + · 최고 5일 빼도 +")

# ---------------------------------------------------------------- 1장 캔들·거래량 해석 (사실 확인)
print("\n### 1장 캔들·거래량 해석이 맞나 (종가 기준 다음 날 시가 / 5일 뒤 종가 / 20일 뒤 종가 평균, 비용 없음)")
base = np.where(m)[0]


def fact(mask, title):
    idx = np.where(m & mask)[0]
    if len(idx) < 30:
        print(f"  {title:52s} {len(idx)}건 (적음)"); return
    no = np.array([next_open(i) for i in idx if next_open(i) is not None]) + COST
    f5 = np.array([fwd(i, 5) for i in idx]); f20 = np.array([fwd(i, 20) for i in idx])
    print(f"  {title:52s} {len(idx):6d}건 | 다음 날 시가 {np.nanmean(no):+.2%} | 5일 뒤 {np.nanmean(f5):+.2%} (오른 비율 {np.nanmean(f5 > 0):.0%})"
          f" | 20일 뒤 {np.nanmean(f20):+.2%}")


fact(np.ones(len(df), bool), "기준: 대상 전부")
fact(df["bottom"].values & df["long_bull"].values & df["volx3"].values, "바닥권 + 거래량 3배 장대양봉 → 추세 전환 (58쪽)")
fact(df["top"].values & df["long_bear"].values & df["volx3"].values, "고가권 + 거래량 3배 장대음봉 → 탈출 신호 (59쪽)")
fact(df["bottom"].values & df["long_bear"].values & df["volx3"].values, "바닥권 + 거래량 3배 장대음봉 → 마지막 투매 (59쪽)")
upper = (df["high"] - df[["open", "close"]].max(axis=1)) >= 0.5 * df["rng"]
fact((df["body"] > 0).values & upper.values & (df["volume"] >= 3 * df["v20"]).values & df["top"].values,
     "고가권 윗꼬리 긴 양봉 + 거래량 폭증 → 물량 넘김 (73쪽)")
fact(df["up3"].values & (df["body"] > 0).values & (df["volume"] > df["vmax60"]).values,
     "3일 연속 상승 끝 양봉 + 60일 최대 거래량 → 하락 (73쪽)")
lower = (df[["open", "close"]].min(axis=1) - df["low"]) >= 0.5 * df["rng"]
fact((df["body"] > 0).values & lower.values & df["bottom"].values, "[R04] 바닥권 아래꼬리 긴 양봉 → 반등 (61쪽)")
fact((df["body"] < 0).values & upper.values & df["top"].values, "[R04] 고가권 윗꼬리 긴 음봉 → 하락 초입 (63쪽)")
fact((df["body"] < 0).values & upper.values & df["bottom"].values, "[R04] 바닥권 윗꼬리 긴 음봉 → 반등 실패, 다음 날 약세 (63쪽)")
doji = (df["body"].abs() <= 0.1 * df["rng"]) & (df["rng"] > 0)
for lab, mk in (("고가권", df["top"]), ("바닥권", df["bottom"])):
    idx = np.where(m & (doji & mk).values)[0]
    nx = np.array([C["close"][i + 1] / C["close"][i] - 1 for i in idx if nxt[i]])
    print(f"  [R04] {lab} 도지 → 다음 날 방향이 정해짐 (64쪽): {len(idx)}건 | 다음 날 종가 평균 {nx.mean():+.2%}, "
          f"움직임 크기 |등락| {np.abs(nx).mean():.2%} (기준: 전부 {np.nanmean(np.abs(df['chg'].shift(-1).values[m])):.2%})")
up5 = g["chg"].transform(lambda s: s.rolling(5).sum()).values > 0
ma20 = g["close"].transform(lambda s: s.rolling(20).mean()).values
fact((df["body"] < 0).values & (df["volume"] < 0.5 * df["v20"]).values & (df["close"].values > ma20) & up5,
     "[R05] 상승 중(20일선 위·5일 상승) 거래량 작은(20일 평균 ½↓) 음봉 → 눌림 매수 (72쪽)")
uprep = upper & (df["high"] >= df["hi60"] * 0.97)
rep = g["chg"].transform(lambda s: s * 0).values.astype(bool)
uu = uprep.values.astype(int)
cnt5 = df.assign(u=uu).groupby("code", sort=False)["u"].transform(lambda s: s.rolling(5).sum()).values
fact((cnt5 >= 2) & uprep.values, "[R04] 단기 고점(60일 고가 −3% 안)에서 5일 안 윗꼬리 2번↑ → 매물 소화 뒤 돌파 (60쪽)")
bb = df["bottom"].values & df["long_bull"].values & df["volx3"].values
conf = np.zeros(len(df), bool)
conf[1:] = bb[:-1] & (codes[1:] == codes[:-1]) & (C["close"][1:] > C["open"][1:]) & (C["volume"][1:] >= 0.5 * C["volume"][:-1])
fact(conf, "[R04] 바닥권 거래량 장대양봉 다음 날 양봉 + 거래량 절반↑ 유지 확인 (58·71쪽)")
gp = (df["open"] >= df["pc"] * 1.03).values & m
print(f"  [R52] 갭 +3%↑ 날 저가가 시가 −1% 안에서 지켜진 비율 {np.mean((C['low'] >= C['open'] * 0.99)[gp]):.0%}, "
      f"종가 ≥ 시가 {np.mean((C['close'] >= C['open'])[gp]):.0%} ({gp.sum()}건, 263쪽 '갭 시가는 세력이 지켜 줌')")
sp = m & (df["volume"] >= 10 * df["v20"]).values
nv = np.array([C["volume"][i + 1] / C["volume"][i] for i in np.where(sp)[0] if nxt[i]])
print(f"  [R05] 거래량 20일 평균 10배↑ 폭증 다음 날 거래량 = 그날의 {np.median(nv):.0%} (중앙값, {len(nv)}건, 68쪽 '뉴스 거래량은 다음 날 뚝 끊김')")
gapup = (df["open"] >= df["pc"] * 1.03) & (df["body"] > 0)
for lab, mk in (("거래량 전날보다 적음", df["volume"] < df["pvol"]), ("거래량 전날보다 많음", df["volume"] >= df["pvol"])):
    idx = np.where(m & (gapup & mk).values)[0]
    fill = [C["low"][i + 1] <= df["pc"].values[i] for i in idx if nxt[i]]
    print(f"  갭 +3%↑ 양봉 · {lab}: {len(idx)}건 | 다음 날 갭 메움(저가 ≤ 전날 종가) {np.mean(fill):.0%} | 다음 날 시가 "
          f"{np.mean([next_open(i) + COST for i in idx if nxt[i]]):+.2%} (73쪽: 거래량 줄면 다음 날 갭 메우며 빠지는 경우 많음)")

# ---------------------------------------------------------------- 87쪽: 거래량 양봉 → 거래량 줄며 눌림 → 지지 → 매수 (일봉판)
print("\n### 87쪽 '거래량 터진 양봉 → 거래량 줄며 눌림 → 지지 확인 → 매수' 일봉판 (A = 거래량 3배 +7%↑ 장대양봉)")
TR = defaultdict(list)
vol, close, open_, high, low = C["volume"], C["close"], C["open"], C["high"], C["low"]
dates = C["date"]
for i in np.where(m & df["long_bull"].values & df["volx3"].values)[0]:
    for sup_lab, sup in (("양봉 시가 지지", open_[i]), ("양봉 중간 지지", (open_[i] + close[i]) / 2)):
        pulls = 0
        for k in range(1, 8):
            j = i + k
            if j >= len(codes) or codes[j] != codes[i]:
                break
            if low[j] < sup or vol[j] >= 0.5 * vol[i] or close[j] > close[i] * 1.03:
                break
            if pulls >= 2 and close[j] > high[j - 1] and df["ok"].values[j]:     # 2일↑ 눌린 뒤 전날 고가 위 종가 = 지지 확인
                d = dates[j]
                TR[(sup_lab, "다음 날 시가")].append((d, next_open(j)))
                TR[(sup_lab, "익절 +10% · 지지 −1% 손절 (10일)")].append((d, swing(j, tp=close[j] * 1.10, stop=sup * 0.99)))
                TR[(sup_lab, "4턴4꺾: 일봉 4선 이탈 · 지지 −1% 손절")].append((d, swing(j, stop=sup * 0.99, trail4=True, maxd=20)))
                TR[(sup_lab, "익절 +5% · 손절 −3% (10일)")].append((d, swing(j, tp=close[j] * 1.05, stop=close[j] * 0.97)))
                break
            pulls += 1
for (sl, xl), rows in sorted(TR.items()):
    stats(rows, f"{sl} → {xl}")

# ---------------------------------------------------------------- 저돌 일봉 종가판 (197쪽, 장중 돌파 순간이 아니라 종가로 뚫은 날)
print("\n### 저돌 일봉 종가판: 몸통(종가)이 60일 최고가 위 + 시가는 아래(갭으로 넘은 것 제외) + 거래량 2배 + 양봉")
TR = defaultdict(list)
jd = m & (df["close"] > df["hi60"]).values & (df["open"] < df["hi60"]).values & (df["volume"] >= 2 * df["v20"]).values & (df["body"] > 0).values
for i in np.where(jd)[0]:
    d = dates[i]
    room = df["hi120"].values[i]
    tag = "다음 저항(120일 고가) 3%↑ 남음" if room > close[i] * 1.03 else "120일 신고가 쪽"
    for t in ("전부", tag):
        TR[(t, "다음 날 시가")].append((d, next_open(i)))
        TR[(t, "반반이 일봉: +5% 절반 · 4선 이탈 · 손절 −3%")].append(
            (d, None if (a := swing(i, tp=close[i] * 1.05, stop=close[i] * 0.97)) is None or (b := swing(i, stop=close[i] * 0.97, trail4=True, maxd=20)) is None
             else (a + b) / 2 if a > 0.04 else b))
        TR[(t, "4턴4꺾: 일봉 4선 이탈 · 손절 −3%")].append((d, swing(i, stop=close[i] * 0.97, trail4=True, maxd=20)))
for (t, xl), rows in sorted(TR.items()):
    stats(rows, f"{t} → {xl}")
