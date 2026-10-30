"""종가배팅 다시 보기 (2026-10-30) — rows.pkl(build.py) 로 1~5번 질문 분석.

매매 정의 (모두 다음 날 09:00 시가 매도, 비용 0.25%, 가격 = 1분봉 원가격):
  기본  정규장 대금(rk_reg) 10위 · 상승 마감(0~+29.5%) → 15:30 종가 매수              (옛 비교 기준)
  기본19 15:19 누적 대금 10위 · 15:19 가격 상승 → 15:30 종가 매수                     (개선 후보 2, 미래 정보 없음)
  🌙    기본 대상 중 17:00~17:59 첫 '정규장 종가 위' 봉 종가 매수                       (지금 실전 규칙)
  4️⃣    강한 하락장(cls D) · 15:19 대금 30위 · 15:19 등락 − 대금 상위 200 중앙 ≥ +3%p · 고가 부근(15:19 기준) ≥ 0.8
         → 실전은 15:15~15:19 에 산다 → 매수가 15:19 가격 (종가 매수도 같이 봄)
  🧭    14:30 누적 대금 10위 · 우선주 제외 · 14:30 상승 · 애프터 거래 종목(전날 19:30 뒤 봉) · (250일 신고가 또는 라운드 ±3%) → 14:31 시가
출력: data/closing_bet_review/analyze.txt
"""
import os
import pickle
from collections import defaultdict
from datetime import date

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import cls, feat as RF

OUT = os.path.join(E.DATA, "closing_bet_review")
R = pickle.load(open(os.path.join(OUT, "rows.pkl"), "rb"))
US = pickle.load(open(os.path.join(OUT, "us_map.pkl"), "rb"))
LIM = E.LIMIT
BEAR0 = date(2026, 7, 1)
LAST3 = date(2026, 7, 23)
rep = open(os.path.join(OUT, "analyze.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(str(s) + "\n"); rep.flush()


def r19(r):
    """15:19 가격에 샀을 때 다음 날 09:00 수익 (r_close 에서 환산)."""
    if r["r_close"] is None or not r["p1519"]:
        return None
    return (1 + r["r_close"] + E.COST) * r["close"] / r["p1519"] - 1 - E.COST


for r in R:
    r["reg"] = cls(r["date"])
    r["dd52"] = RF.get(r["date"], {}).get("dd52")
    r["r19"] = r19(r)
    r["us_prev"] = US["prior"].get(r["date"])
    r["us_tonight"] = US["tonight"].get(r["date"])

basic = [r for r in R if r["rk_reg"] <= 10 and 0 < r["chg"] < LIM and r["r_close"] is not None]
basic19 = [r for r in R if r["rk1519"] <= 10 and 0 < r["chg1519"] < LIM and r["r_close"] is not None]
moon = [r for r in basic if r["r_moon"] is not None]
contra = [r for r in R if r["reg"] == "D" and r["rk1519"] <= 30 and r["chg1519"] - r["med1519"] >= 0.03
          and r["chg1519"] < LIM and r["pos1519"] >= 0.8 and r["r_close"] is not None]
compass_all = [r for r in R if r["rk1430"] <= 10 and r["common"] and 0 < r["chg1430"] < LIM and r["nxt"] and r["r_1431"] is not None]
compass = [r for r in compass_all if r["nh1430"] or r["rnd1430"]]
PLAYS = {"기본(정규장 종가)": (basic, "r_close"), "기본19(15:19 판단)": (basic19, "r_close"), "🌙 종가 재돌파": (moon, "r_moon"),
         "4️⃣ 역행 강세(15:19 매수)": (contra, "r19"), "4️⃣ 역행 강세(종가 매수)": (contra, "r_close"),
         "🧭 14:30 신고가·라운드": (compass, "r_1431")}


def stats(rows, key, title, width=46):
    tr = [(r["date"], r[key]) for r in rows if r.get(key) is not None]
    if len(tr) < 15:
        v = [x for _, x in tr]
        say(f"  {title:{width}s} {len(tr)}건" + (f" 건당 {np.mean(v):+.2%} (적음)" if v else ""))
        return None
    ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; b = [x for d, x in tr if d >= h]
    bd = defaultdict(float)
    for d, x in tr: bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    ok = "★" if np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
    say(f" {ok}{title:{width}s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만"
        f" | 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} | 승률 {np.mean(v > 0):.0%} 낙폭 {mdd * 100:.0f}만")
    return v.mean()


def by_period(rows, key):
    q = defaultdict(list); m = defaultdict(list)
    for r in rows:
        if r.get(key) is None: continue
        d = r["date"]; q[f"{d.year}Q{(d.month - 1) // 3 + 1}"].append(r[key]); m[f"{d:%m}"].append(r[key])
    say("    분기: " + " | ".join(f"{k} {np.mean(v):+.2%}({len(v)})" for k, v in sorted(q.items())))
    say("    월:   " + " ".join(f"{k}월 {np.mean(v):+.2%}({len(v)})" for k, v in sorted(m.items(), key=lambda x: (x[0] < "10", x[0]))))
    a = [r[key] for r in rows if r.get(key) is not None and r["date"] < BEAR0]
    b = [r[key] for r in rows if r.get(key) is not None and r["date"] >= BEAR0]
    c = [r[key] for r in rows if r.get(key) is not None and r["date"] >= LAST3]
    f = lambda v: f"{np.mean(v):+.2%} ({len(v)}건, 합계 {sum(v) * 100:+.0f}만)" if v else "없음"
    say(f"    7월 전 {f(a)} | 7월부터(약세장) {f(b)} | 최근 3달(07-23~) {f(c)}")


say(f"종가배팅 다시 보기 — 1분봉 {min(r['date'] for r in R)} ~ {max(r['date'] for r in R)} (다음 날 09:00 매도, 비용 0.25%, 건당 100만)")
say("\n## 1. 매매별 1년 · 기간별")
for nm, (rows, key) in PLAYS.items():
    stats(rows, key, nm); by_period(rows, key)
say("  비교: 대금 상위 40 전체(밤사이 바탕)")
stats([r for r in R if r["rk_reg"] <= 40], "r_close", "대금 40위 전체 · 종가 매수"); by_period([r for r in R if r["rk_reg"] <= 40], "r_close")

say("\n## 1-b. 🌙 세부: 17시 직전 종가 위(★) / 아님, 18시 전 진입 시각")
stats([r for r in moon if r["pre17"] and r["pre17"] > r["close"]], "r_moon", "🌙 ★ (16:55~59 이미 종가 위)")
by_period([r for r in moon if r["pre17"] and r["pre17"] > r["close"]], "r_moon")
stats([r for r in moon if not (r["pre17"] and r["pre17"] > r["close"])], "r_moon", "🌙 ★ 아님")
by_period([r for r in moon if not (r["pre17"] and r["pre17"] > r["close"])], "r_moon")
stats([r for r in basic if r["r_moon"] is None and r["has_after"]], "r_close", "기본 중 🌙 못 산 종목(애프터 거래는 있음) 종가 매수")
stats([r for r in basic if not r["has_after"]], "r_close", "기본 중 애프터 거래 없는 종목 종가 매수")

say("\n## 2. 15:19 판단 vs 최종 정보 (개선 후보 2)")
k_f = {(r["date"], r["code"]) for r in basic}; k_19 = {(r["date"], r["code"]) for r in basic19}
say(f"  겹침: 최종 {len(k_f)} / 15:19 {len(k_19)} / 둘 다 {len(k_f & k_19)} ({len(k_f & k_19) / len(k_f):.0%})")
stats([r for r in basic19 if (r['date'], r['code']) not in k_f], "r_close", "15:19 에만 뽑힘 (최종엔 빠짐)")
stats([r for r in basic if (r['date'], r['code']) not in k_19], "r_close", "최종에만 뽑힘 (15:19 엔 없음)")
moon19 = [r for r in basic19 if r["r_moon"] is not None]
stats(moon19, "r_moon", "🌙 대상을 15:19 정보로 뽑으면")
for N in (5, 10, 20):
    stats([r for r in R if r["rk1519"] <= N and 0 < r["chg1519"] < LIM and r["r_close"] is not None], "r_close", f"15:19 대금 {N}위 · 상승 → 종가")

say("\n## 3. 나쁜 밤 거르기 후보 (매수 전에 아는 정보) — 기본 / 🌙")
FILTERS = [
    ("시장 판정 U", lambda r: r["reg"] == "U"), ("시장 판정 N+", lambda r: r["reg"] == "N+"),
    ("시장 판정 N-", lambda r: r["reg"] == "N-"), ("시장 판정 D", lambda r: r["reg"] == "D"),
    ("코스피 52주 고점 −10% 안", lambda r: r["dd52"] is not None and r["dd52"] > -0.10),
    ("코스피 52주 고점 −10~−25%", lambda r: r["dd52"] is not None and -0.25 < r["dd52"] <= -0.10),
    ("코스피 52주 고점 −25%↓", lambda r: r["dd52"] is not None and r["dd52"] <= -0.25),
    ("그날 코스피 −1%↓", lambda r: r["kospi"] is not None and r["kospi"] <= -0.01),
    ("그날 코스피 −1~+1%", lambda r: r["kospi"] is not None and -0.01 < r["kospi"] < 0.01),
    ("그날 코스피 +1%↑", lambda r: r["kospi"] is not None and r["kospi"] >= 0.01),
    ("그날 외인 + 기관 +", lambda r: r["fi"] is not None and r["fi"] > 0 and r["ii"] > 0),
    ("그날 외인 + 기관 −", lambda r: r["fi"] is not None and r["fi"] > 0 and r["ii"] <= 0),
    ("그날 외인 − 기관 +", lambda r: r["fi"] is not None and r["fi"] <= 0 and r["ii"] > 0),
    ("그날 외인 − 기관 −", lambda r: r["fi"] is not None and r["fi"] <= 0 and r["ii"] <= 0),
    ("전날 외인 +", lambda r: r["pfi"] is not None and r["pfi"] > 0), ("전날 외인 −", lambda r: r["pfi"] is not None and r["pfi"] <= 0),
    ("전날 기관 +", lambda r: r["pii"] is not None and r["pii"] > 0), ("전날 기관 −", lambda r: r["pii"] is not None and r["pii"] <= 0),
    ("가격 1만 원 미만", lambda r: r["close"] < 10_000), ("가격 1만~3만", lambda r: 10_000 <= r["close"] < 30_000),
    ("가격 3만~10만", lambda r: 30_000 <= r["close"] < 100_000), ("가격 10만↑", lambda r: r["close"] >= 100_000),
    ("시총 5천억 미만", lambda r: r["mcap"] < 5e11), ("시총 5천억~3조", lambda r: 5e11 <= r["mcap"] < 3e12),
    ("시총 3조~20조", lambda r: 3e12 <= r["mcap"] < 2e13), ("시총 20조↑", lambda r: r["mcap"] >= 2e13),
    ("15:19 테마 대장", lambda r: r["lead1519"]), ("테마 대장 아님", lambda r: not r["lead1519"]),
    ("등락 0~3%", lambda r: r["chg"] < 0.03), ("등락 3~8%", lambda r: 0.03 <= r["chg"] < 0.08),
    ("등락 8~15%", lambda r: 0.08 <= r["chg"] < 0.15), ("등락 15~29.5%", lambda r: r["chg"] >= 0.15),
    ("종가 위치 <0.5", lambda r: r["pos"] < 0.5), ("종가 위치 0.5~0.8", lambda r: 0.5 <= r["pos"] < 0.8), ("종가 위치 ≥0.8", lambda r: r["pos"] >= 0.8),
    ("250일 신고가 마감", lambda r: r["nh250"]), ("신고가 아님", lambda r: not r["nh250"]),
    ("막판 30분 상승", lambda r: r["late30"] > 0), ("막판 30분 하락·보합", lambda r: r["late30"] <= 0),
    ("어젯밤 나스닥100 −1%↓", lambda r: r["us_prev"] is not None and r["us_prev"] <= -0.01),
    ("어젯밤 나스닥100 −1~+1%", lambda r: r["us_prev"] is not None and -0.01 < r["us_prev"] < 0.01),
    ("어젯밤 나스닥100 +1%↑", lambda r: r["us_prev"] is not None and r["us_prev"] >= 0.01),
    ("(모름) 오늘 밤 나스닥100 −1%↓", lambda r: r["us_tonight"] is not None and r["us_tonight"] <= -0.01),
    ("(모름) 오늘 밤 나스닥100 +1%↑", lambda r: r["us_tonight"] is not None and r["us_tonight"] >= 0.01),
]
for nm, (rows, key) in (("기본", PLAYS["기본(정규장 종가)"]), ("🌙", PLAYS["🌙 종가 재돌파"])):
    say(f"\n-- {nm} (전체 / 7월부터 약세장)")
    for fn, f in FILTERS:
        sub = [r for r in rows if f(r)]
        bear = [r[key] for r in sub if r["date"] >= BEAR0]
        stats(sub, key, f"{fn}", 30)
        if bear: say(f"      └ 7월부터 {np.mean(bear):+.2%} ({len(bear)}건)")

say("\n## 4. 4️⃣ 세부 — 매수 시각, 보통 날로 넓히면")
stats(contra, "r19", "4️⃣ D날 15:19 매수"); stats(contra, "r_close", "4️⃣ D날 종가 매수")
for reg in ("N-", "N+", "U"):
    for rel, pos in ((0.03, 0.8), (0.05, 0.8), (0.10, 0.8)):
        sub = [r for r in R if r["reg"] == reg and r["rk1519"] <= 30 and r["chg1519"] - r["med1519"] >= rel and r["chg1519"] < LIM
               and r["pos1519"] >= pos and r["r_close"] is not None]
        stats(sub, "r19", f"{reg} 날 · 시장 대비 +{rel:.0%}p · 고가 부근 ≥{pos}")
        by_period(sub, "r19") if reg == "N-" else None
    sub = [r for r in R if r["reg"] == reg and r["rk1519"] <= 30 and r["chg1519"] - r["med1519"] >= 0.03 and r["chg1519"] < LIM
           and r["pos1519"] >= 0.8 and r["r_close"] is not None and r["pii"] is not None and r["pii"] > 0 and r["pfi"] > 0]
    stats(sub, "r19", f"{reg} 날 · +3%p · 고가 부근 · 전날 외인·기관 둘 다 +")
say("  4️⃣ 와 🌙 겹침: " + str(len({(r['date'], r['code']) for r in contra} & {(r['date'], r['code']) for r in moon})) + f" / 4️⃣ {len(contra)}")

say("\n## 5. 🧭 14:30 주도주 종가 (디앤서 ①) — 변형")
stats(compass_all, "r_1431", "14:30 대금 10위·상승·애프터 종목 전부"); by_period(compass_all, "r_1431")
stats(compass, "r_1431", "+ 신고가 또는 라운드 (알림 규칙)"); by_period(compass, "r_1431")
nh = [r for r in compass_all if r["nh1430"]]
stats(nh, "r_1431", "+ 250일 신고가"); by_period(nh, "r_1431")
nhp = [r for r in compass_all if r["nh1430"] and r["pos1430"] >= 0.8]
stats(nhp, "r_1431", "+ 고가 근처 ≥0.8 + 신고가 (★)"); by_period(nhp, "r_1431")
for fn, f in FILTERS[:7] + FILTERS[14:18]:
    stats([r for r in compass if f(r)], "r_1431", f"🧭 · {fn}", 30)
say("  🧭 와 🌙 겹침: " + str(len({(r['date'], r['code']) for r in compass} & {(r['date'], r['code']) for r in moon})) + f" / 🧭 {len(compass)}")
pickle.dump(dict(basic=basic, basic19=basic19, moon=moon, contra=contra, compass=compass, compass_all=compass_all),
            open(os.path.join(OUT, "plays.pkl"), "wb"))
