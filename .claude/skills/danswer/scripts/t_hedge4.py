"""하락장 헤지주 종가 베팅 ③ — 하락장을 운영과 같은 '09:10·09:20 강한 하락장 판정'으로 (t_contra.py 와 같은 날),
헤지주 목록을 기사 조사로 넓힘(보안·방산·유가(정유·석유)·해운·금융(은행·보험)·통신·전력가스·음식료·금) + 네이버 헤지 테마 구성 종목.
신호: 판정일, 헤지주가 상승 마감 & (고가 부근 ≥0.8 / 전체) → 종가 매수 → 다음 날 09:00 시가, 비용 0.25%.
⚠️ 네이버 테마 구성은 2026-10-26 것(지금 기준)이라 과거엔 없던 편입이 섞일 수 있음.
"""
import duckdb, numpy as np
from collections import defaultdict
from engine import *
import t_contra_lib as L

R = Report("t_hedge4.txt")
NG = duckdb.connect(os.path.join(DATA, "naver_groups.duckdb"), read_only=True)
HEDGE_THEMES = {"보안": ["보안주(정보)", "보안주(물리)"], "방산": ["방위산업/전쟁 및 테러"], "유가": ["정유", "주유소", "윤활유", "석유화학"],
                "해운": ["해운"], "금": ["귀금속(금/은)"], "통신": ["통신"], "음식료": ["음식료업종"], "금융": ["은행", "손해보험", "생명보험"]}
TH = defaultdict(set)
for g, names in HEDGE_THEMES.items():
    for (c,) in NG.execute(f"SELECT DISTINCT code FROM naver_groups WHERE kind='테마' AND name IN ({','.join('?'*len(names))})", names).fetchall():
        TH[c].add(g)
for (c,) in NG.execute("SELECT DISTINCT code FROM naver_groups WHERE kind='업종' AND name IN ('전기유틸리티','가스유틸리티')").fetchall():
    TH[c].add("전력가스")
R.say(f"헤지 테마 종목 {len(TH)}개: " + ", ".join(f"{g} {sum(g in v for v in TH.values())}" for g in list(HEDGE_THEMES) + ['전력가스']))

SD = [d for d in days() if L.strong_down(d)[0]]
R.say(f"강한 하락장 판정일 {len(SD)}일")
rows = []
for d in SD:
    ch = L.day_chg(d); vr = value_rank(d); t = daily_day(d)
    for c, gs in TH.items():
        x = ch.get(c)
        if x is None or x <= 0 or x >= LIMIT or c not in t: continue
        r = L.exit9(c, d, t[c][3])
        if r is None:
            n = next_day(d); nd = daily_day(n).get(c) if n else None
            if not nd or not nd[0]: continue
            r = nd[0] / t[c][3] - 1 - COST
            if abs(r) > 0.35: continue
        o, h, l, cl = t[c][:4]
        pos = (cl - l) / (h - l) if h > l else 1.0
        rows.append((d, c, gs, x, pos, vr.get(c, 9999), r))
R.stats([(d, r) for d, c, gs, x, pos, rk, r in rows], "헤지주 상승 마감 전체")
R.stats([(d, r) for d, c, gs, x, pos, rk, r in rows if pos >= 0.8], "헤지주 상승 & 고가 부근 ≥0.8")
R.stats([(d, r) for d, c, gs, x, pos, rk, r in rows if pos >= 0.8 and rk <= 100], "   + 대금 100위 안")
R.stats([(d, r) for d, c, gs, x, pos, rk, r in rows if pos >= 0.8 and x >= 0.03], "   + 3%↑ 상승")
R.stats([(d, r) for d, c, gs, x, pos, rk, r in rows if pos < 0.5], "헤지주 상승 & 고가에서 밀림 <0.5")
for g in list(HEDGE_THEMES) + ["전력가스"]:
    R.stats([(d, r) for d, c, gs, x, pos, rk, r in rows if g in gs and pos >= 0.8], f"  {g} · 고가 부근")
R.say("\n안랩 신호:")
for d, c, gs, x, pos, rk, r in rows:
    if c == "053800": R.say(f"  {d} 안랩 {x:+.1%} 고가부근 {pos:.2f} → 다음 날 09:00 {r:+.2%}")
