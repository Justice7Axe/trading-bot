"""☕ 카페(불개미 '수학은직관력') 테마 대장 돌파 1년 백테스트 (2026-10-27 사용자: 카페 관점을 우리 규칙에 넣자).

카페 10-26 일지(로보티즈 +2.5%, 루닛 +9.4%) 의 순서를 규칙으로 옮김:
  ① 장 초반 테마 형성 → 그 대장   : 네이버 테마(naver_groups) 에서 그 시각 +4%↑ 종목 2개↑, 그중 누적 대금 1위이고 +5%↑
  ② 최근 기관 수급               : 전날까지 3거래일 중 기관 순매수 + 인 날 2일↑ (investor_daily 확정치, 2026-10-13 까지만 있음)
  ③ NXT 프리장 햄버거 → 시간 제한 해제 : 08:00~08:59 통합 1분봉 누적 대금 ≥ PRE_VALUE 면 09:00 부터, 아니면 9시 15분 규칙(09:15 부터)
  ④ 매수 = 1분봉 당일 고점 돌파 + 햄버거(그 봉 대금 ≥ 10억 & 직전 5봉 평균 2배↑) → 다음 봉 시가 (돌파)
            또는 돌파한 고점에 지정가, 10분 안에 눌리면 체결 (눌림, 카페 로보티즈 '1차 돌파 2차 눌림')
  ⑤ 매도 = 나눠 팔기: 절반 +2.5% (일봉 저항 근사), 나머지 상한가 닿으면 상한가 / 손절 −2% 즉시 / 아니면 다음 날 09:00.
대상 = 전날 대금 200위 안(그날 1분봉이 있는 것 — 그날 순위로 고르면 미래 정보). 매수 09:00(또는 09:15)~10:30, 종목당 하루 1번.
테마 소속은 지금(2026-10) 네이버 목록 → 과거에 없던 테마가 섞일 수 있음(근사).
비교: 같은 매수 자리에서 ①②③ 을 하나씩 빼 보고, 시장(코스피·코스닥 20일선)별로 나눠 본다.

실행: .venv/Scripts/python.exe -m kiwoom_trading.analysis.run_cafe_leader_backtest [--report-only]  → data/cafe/backtest.txt
"""
from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime, time

import duckdb
import numpy as np

from kiwoom_trading.backtest import engine as E  # noqa: E402  (공통 엔진, docs/architecture.md)
from kiwoom_trading.common.leader import theme_leaders  # noqa: E402
from kiwoom_trading.common.market import ma20_tag  # noqa: E402

OUT = os.path.join(E.DATA, "cafe")
os.makedirs(OUT, exist_ok=True)
PRE_VALUE = 5e9          # 프리장 누적 대금 50억↑ → 시간 제한 해제
BAR_VALUE = 1e9          # 햄버거 봉 최소 10억
BAR_MULT = 2.0
LAST_BUY = time(10, 30)
HALF_TP = 0.025
STOP = 0.02


def themes():
    con = duckdb.connect(E._cp("naver_groups.duckdb"), read_only=True)
    d = con.execute("SELECT max(date) FROM naver_groups").fetchone()[0]
    m = defaultdict(set)
    for name, c in con.execute("SELECT name, code FROM naver_groups WHERE kind='테마' AND date=?", [d]).fetchall():
        m[c].add(name)
    return m


THEME = themes()


def val(x):
    return x[5] * (x[2] + x[3] + x[4]) / 3      # 햄버거 스킬 2장: 대금 = 거래량 × (고+저+종)/3


def inst_recent(c, d):
    """전날까지 3거래일 중 기관 순매수 + 인 날 수. 자료 없으면 None."""
    xs = [E.inv(c, E.prev_day(d, k)) for k in (1, 2, 3)]
    if any(x is None for x in xs):
        return None
    return sum(1 for x in xs if x[1] > 0)


def day_trades(d, mkt):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    pd_ = E.daily_day(p)
    U = [c for c, r in vr.items() if r <= 200 and E.is_common(c) and c in pd_]
    B = E.load_day(U, d)
    info = {}
    for c in U:
        b = B[c]
        reg = E.regular(b)
        f = E.factor(c, d)
        if len(reg) < 60 or not f:
            continue
        pre = [x for x in b if x[0] < time(9, 0)]
        info[c] = dict(reg=reg, pre=pre, pc=pd_[c][3] * f, prev=sum(val(x) for x in pre))
    if not info:
        return []
    # 분 단위 표: 시각 → {code: (등락률, 누적 대금)}
    times = sorted({x[0] for v in info.values() for x in v["reg"] if x[0] <= LAST_BUY})
    out = []
    for c, v in info.items():
        reg, pc = v["reg"], v["pc"]
        free = v["prev"] >= PRE_VALUE
        start = time(9, 0) if free else time(9, 15)
        hi = None
        bought = False
        for j, x in enumerate(reg):
            t = x[0]
            if t > LAST_BUY or bought:
                break
            if hi is not None and j >= 3 and t >= start and x[4] > hi and x[4] > x[1]:
                prev5 = [val(y) for y in reg[max(0, j - 5):j]]
                bv = val(x)
                if bv >= BAR_VALUE and bv >= BAR_MULT * (np.mean(prev5) if prev5 else 0) and j + 1 < len(reg):
                    lead, theme_n = leader_at(c, d, t, info)
                    tr = dict(code=c, date=d, t=t, level=hi, j=j, free=free, prev=v["prev"], lead=lead, theme_n=theme_n,
                              inst=inst_recent(c, d), chg=x[4] / pc - 1, mkt=mkt.get(d))
                    tr["ret_break"] = exit_from(c, d, reg, j + 1, reg[j + 1][1], pc)
                    # 눌림: 돌파 고점(hi)에 지정가, 다음 10봉 안
                    fill = None
                    for k in range(j + 1, min(j + 11, len(reg))):
                        if reg[k][3] <= hi:
                            fill = (k, min(reg[k][1], hi)); break
                    tr["ret_pull"] = exit_from(c, d, reg, fill[0], fill[1], pc, same_bar_open=False) if fill else None
                    out.append(tr)
                    bought = True
            hi = x[2] if hi is None else max(hi, x[2])
    return out


def leader_at(c, d, t, info):
    """t 시각 c 가 자기 테마 중 하나에서 대장인가: 그 테마 종목(대상 안) 중 +4%↑ 2개↑, c 가 누적 대금 1위 & +5%↑."""
    mine = THEME.get(c, ())
    rows = []
    for o, v in info.items():
        if not (THEME.get(o, set()) & set(mine)):
            continue
        upto = [x for x in v["reg"] if x[0] <= t]
        if upto:
            rows.append((o, upto[-1][4] / v["pc"] - 1, sum(val(x) for x in v["pre"]) + sum(val(x) for x in upto)))
    lead = theme_leaders(rows, {o: THEME.get(o, set()) & set(mine) for o, _, _ in rows})
    return (True, lead[c][1]) if c in lead else (False, 0)


def exit_from(c, d, reg, k, buy, pc, same_bar_open=True):
    """reg[k] 봉에서 buy 에 매수 → 절반 +2.5%, 나머지 상한가/다음 날 09:00, 손절 −2% (같은 봉이면 손절 먼저). 비용 0.25%."""
    sp, tp, lim = buy * (1 - STOP), buy * (1 + HALF_TP), pc * 1.295
    left, r, half = 1.0, 0.0, False
    for x in reg[k:]:
        if x[3] <= sp:
            return r + left * (min(x[1], sp) / buy - 1) - E.COST
        if x is reg[k] and not same_bar_open:   # 지정가 체결 봉: 고가가 체결 전인지 알 수 없어 익절·상한가는 다음 봉부터
            continue
        if not half and x[2] >= tp:
            r += 0.5 * (max(x[1], tp) / buy - 1)
            left, half = 0.5, True
        if x[2] >= lim:
            return r + left * (lim / buy - 1) - E.COST
    nx = E.next_day_exits(c, d, buy)
    if "09:00 시가" not in nx:
        return None
    return r + left * (nx["09:00 시가"] + E.COST) - E.COST


def index_mkt():
    return ma20_tag(E.IX)


def run():
    mkt = index_mkt()
    allt = []
    for i, d in enumerate(E.days()):
        allt += day_trades(d, mkt)
        if i % 20 == 0:
            print(f"  {d} 매수 자리 누적 {len(allt)}", file=sys.stderr)
    with open(os.path.join(OUT, "trades.pkl"), "wb") as f:
        pickle.dump(allt, f)
    return allt


class Rep(E.Report):
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")


def box_tags(t, n=15, width=0.30):
    """④ 일봉 박스 돌파: 직전 n일 고가÷저가 −1 ≤ width 이고 그 시각 가격(전날 일봉 종가 × (1+등락률)) > n일 고가. 종가 박스도 같이."""
    h = E.hist(t["code"], t["date"], n)
    if len(h) < n:
        return False, False
    px = h[0][4] * (1 + t["chg"])
    hi, lo = max(x[2] for x in h), min(x[3] for x in h)
    hc, lc = max(x[4] for x in h), min(x[4] for x in h)
    return (px > hi and hi / lo - 1 <= width), (px > hc and hc / lc - 1 <= width)


def report(allt):
    R = Rep(os.path.join(OUT, "backtest.txt"))
    for t in allt:
        t["box"], t["boxc"] = box_tags(t)
    days = E.days()
    R.say(f"☕ 카페 테마 대장 돌파 1년 ({days[0]} ~ {days[-1]}) — 대상 전날 대금 200위 안, 비용 0.25%, 1건 100만 기준 '만'")
    R.say("매도: 절반 +2.5% · 나머지 상한가 또는 다음 날 09:00 · 손절 −2% 즉시.  ★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +\n")
    known = [t for t in allt if t["inst"] is not None]
    sets = [
        ("기준: 1분봉 고점 돌파+햄버거 (필터 없음)", allt),
        ("① 테마 대장", [t for t in allt if t["lead"]]),
        ("③ 프리장 햄버거(50억↑) 시간 해제", [t for t in allt if t["free"]]),
        ("①+③", [t for t in allt if t["lead"] and t["free"]]),
        ("[기관 자료 있는 기간] 기준", known),
        ("[기관 자료 있는 기간] ② 최근 기관 2/3일↑", [t for t in known if t["inst"] >= 2]),
        ("[기관 자료 있는 기간] ①+②", [t for t in known if t["lead"] and t["inst"] >= 2]),
        ("[기관 자료 있는 기간] ①+②+③ (카페 전부)", [t for t in known if t["lead"] and t["inst"] >= 2 and t["free"]]),
        ("[기관 자료 있는 기간] ②+③", [t for t in known if t["inst"] >= 2 and t["free"]]),
        ("④ 고가 박스(15일·30%) 돌파", [t for t in allt if t["box"]]),
        ("①+③+④ 고가 박스 ★ 가상 장부 규칙", [t for t in allt if t["lead"] and t["free"] and t["box"]]),
        ("①+③+④ 종가 박스", [t for t in allt if t["lead"] and t["free"] and t["boxc"]]),
    ]
    for kind, key in (("돌파 다음 봉 시가", "ret_break"), ("돌파 고점 눌림 지정가", "ret_pull")):
        R.say(f"## 매수 = {kind}")
        for name, ts in sets:
            R.stats([(t["date"], t[key]) for t in ts if t[key] is not None], name, 50)
        R.say("")
    R.say("## 시장별 (돌파 다음 봉 시가)")
    for name, ts in sets[:4] + sets[8:9] + sets[-2:-1]:
        for m in ("둘 다 20일선 아래", "둘 중 하나↑ 20일선 위"):
            R.stats([(t["date"], t["ret_break"]) for t in ts if t["mkt"] == m and t["ret_break"] is not None], f"{name} · {m}", 60)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--report-only" in sys.argv:
        with open(os.path.join(OUT, "trades.pkl"), "rb") as f:
            report(pickle.load(f))
        return
    report(run())


if __name__ == "__main__":
    main()
