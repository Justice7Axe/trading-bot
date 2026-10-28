"""📅 일정 시나리오 매매 백테스트 (2026-10-28) — DART 공시 사건 앞뒤로 사고파는 규칙을 일봉 2년으로 시험.

python -m kiwoom_trading.strategies.event_scenario.backtest   → data/event_scenario/backtest.txt · trades.csv

두 방식
- 따라가기(F): 공시 접수일 다음 거래일 시가에 산다 (DART 목록엔 접수 시각이 없음 → 장중 공시도 다음 날 시가, 보수적).
  매도: 손절가 닿으면 즉시(같은 날이면 손절 먼저), 익절가 닿으면 그 가격, 둘 다 아니면 보유 H일째 다음 날 시가.
- 사두기(P): 미리 알려진 날짜(실적 공시 예정일·배당 기준일·무상 신주배정 기준일)의 N거래일 전 시가에 사서
  예정일(또는 권리락일) 시가 / 그다음 날 시가에 판다. 날짜를 알린 공시가 매수일 전에 접수된 것만 (미래 정보 금지).
가격: engine.daily_day (수정주가, 9-14 뒤 정규장 보정). 현금배당은 수정주가에 반영 안 됨 → 배당 사두기는 배당금을 따로 더한 값도 보인다.
대상: 보통주, 전날 거래대금 ≥ 10억, 전날 시총 ≥ 500억. 정정·자회사 공시 제외, 같은 종목·같은 종류 10거래일 안 중복 제외.
"""
import csv, os
from collections import defaultdict
from datetime import timedelta

import duckdb
import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.common.market import ma20_tag

OUT = os.path.join(E.DATA, "event_scenario"); os.makedirs(OUT, exist_ok=True)
EV = duckdb.connect(E._cp("events.duckdb"), read_only=True)
D0, D1 = E.CAL[25], E.CAL[-2]
TAG = ma20_tag(E.IX)


class Rep(E.Report):
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")


R = Rep("backtest.txt")
TRADES = []


def trade_day(d):
    """d 이후(포함) 첫 거래일."""
    for _ in range(10):
        if d in E.CIDX: return d
        d += timedelta(days=1)
    return None


def shift(d, n):
    i = E.CIDX[d] + n
    return E.CAL[i] if 0 <= i < len(E.CAL) else None


def ok_universe(c, d):
    if not E.is_common(c): return False
    p = shift(d, -1)
    r = E.daily_day(p).get(c) if p else None
    return bool(r and (r[5] or 0) >= 1e9 and E.mcap(c, p) >= 5e10)


def bar(c, d):
    return E.daily_day(d).get(c)


def hold(c, d, H, stop=None, tp=None):
    """d 시가에 사서 보유. 반환 (수익률, 매도 사유, 매도일) 또는 None."""
    b0 = bar(c, d)
    if not b0 or not b0[0]: return None
    buy = b0[0]
    sp = buy * (1 - stop) if stop else None
    tpp = buy * (1 + tp) if tp else None
    x = d
    for k in range(H):
        b = bar(c, x)
        if not b: return None
        o, h, l = b[0], b[1], b[2]
        if k > 0 and sp and o <= sp: return o / buy - 1 - E.COST, "손절(시가)", x
        if k > 0 and tpp and o >= tpp: return o / buy - 1 - E.COST, "익절(시가)", x
        if sp and l <= sp: return sp / buy - 1 - E.COST, "손절", x
        if tpp and h >= tpp: return tpp / buy - 1 - E.COST, "익절", x
        x = shift(x, 1)
        if not x: return None
    b = bar(c, x)
    if not b or not b[0]: return None
    return b[0] / buy - 1 - E.COST, "기한", x


_BASE = {}


def mkt(d_buy, d_sell):
    """같은 날 시가에 사서 같은 날 시가에 판 대상 종목(대금·시총 조건) 전체의 평균 수익률 — 시장 흐름 빼기용."""
    k = (d_buy, d_sell)
    if k not in _BASE:
        p = shift(d_buy, -1); P = E.daily_day(p) if p else {}
        A, B = E.daily_day(d_buy), E.daily_day(d_sell)
        v = [B[c][0] / A[c][0] - 1 for c in A
             if c in B and A[c][0] and B[c][0] and E.is_common(c) and c in P and (P[c][5] or 0) >= 1e9
             and (E.SHARES.get(c) or 0) * P[c][3] >= 5e10]
        v = [x for x in v if abs(x) < 0.6]
        _BASE[k] = float(np.mean(v)) if v else 0.0
    return _BASE[k]


def buy_sell_open(c, d_buy, d_sell):
    a, b = bar(c, d_buy), bar(c, d_sell)
    if not a or not b or not a[0] or not b[0]: return None
    r = b[0] / a[0] - 1 - E.COST
    return r if abs(r) < 0.6 else None        # 액면분할 등 가격 기준 어긋남 방지


def events(kinds):
    q = f"""SELECT d.rcept_no, d.rcept_dt, d.code, d.corp_name, d.kind, d.title, e.*
            FROM disclosures d LEFT JOIN event_details e USING(rcept_no)
            WHERE d.kind IN ({','.join("'" + k + "'" for k in kinds)}) AND NOT d.fixed AND d.title NOT LIKE '%자회사%'
            ORDER BY d.rcept_dt, d.rcept_no"""
    cur = EV.execute(q); cols = [x[0] for x in cur.description]
    out, last = [], {}
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        d = trade_day(r["rcept_dt"])
        if not d: continue
        key = (r["code"], r["kind"])
        if key in last and E.CIDX[d] - E.CIDX[last[key]] < 10: continue
        last[key] = d
        r["day"] = d
        out.append(r)
    return out


def show(title, tr, ex=None):
    R.stats([(d, x) for d, x, *_ in tr], title, width=58)
    if ex is not None and len(ex) >= 15:
        R.stats(ex, "     (시장 대비: 비용 낸 뒤 같은 날 대상 평균 뺌)", width=58)


def by_tag(name, tr):
    g = defaultdict(list)
    for t in tr: g[TAG.get(t[0], "?")].append(t)
    for k in sorted(g): show(f"   └ {name} · {k}", g[k])


# ---------------------------------------------------------------- 따라가기
def follow(name, evs, filt=lambda r: True, label=""):
    R.say(f"\n■ F {name} {label} — 공시 다음 날 시가 매수")
    base = []
    picks = [r for r in evs if filt(r)]
    for H, stop, tp in [(1, None, None), (3, None, None), (5, None, None), (10, None, None),
                        (5, 0.05, 0.10), (5, 0.08, 0.15), (10, 0.08, 0.20)]:
        tr, ex = [], []
        for r in picks:
            d = E.next_day(r["day"])          # 접수일 다음 거래일
            if not d or not (D0 <= d <= D1) or not ok_universe(r["code"], d): continue
            x = hold(r["code"], d, H, stop, tp)
            if not x: continue
            gap = bar(r["code"], d)[0] / bar(r["code"], r["day"])[3] - 1
            tr.append((d, x[0], r["code"], gap))
            ex.append((d, x[0] - mkt(d, x[2])))
            TRADES.append(dict(way="F", kind=name, label=label, H=H, stop=stop, tp=tp, code=r["code"], name=r["corp_name"],
                               rcept=r["rcept_dt"], buy=d, sell=x[2], ret=round(x[0], 4), why=x[1], gap=round(gap, 4)))
        show(f"보유 {H}일" + (f" 손절 −{stop:.0%} 익절 +{tp:.0%}" if stop else ""), tr, ex)
        if H == 3 and not stop: base = tr
    if base:
        show("   └ 3일 · 다음 날 시가 갭 +3% 미만", [t for t in base if t[3] < 0.03])
        show("   └ 3일 · 다음 날 시가 갭 +3% 이상", [t for t in base if t[3] >= 0.03])
        by_tag("3일", base)


# ---------------------------------------------------------------- 사두기
def pre(name, evs, target, Ns=(1, 3, 5, 10), label="", div=False):
    """target(r) → (기준 날짜, 매도 기준일) — 매도는 기준일 시가 / 다음 날 시가 두 가지."""
    R.say(f"\n■ P {name} {label} — 예정일 N거래일 전 시가 매수")
    for N in Ns:
        for sell_k, sname in [(0, "예정일 시가"), (1, "다음 날 시가")]:
            tr, ex = [], []
            seen = set()
            for r in evs:
                t = target(r)
                if not t: continue
                t = trade_day(t)
                if not t or (r["code"], t) in seen: continue
                b = shift(t, -N); s = shift(t, sell_k)
                if not b or not s or not (D0 <= b <= D1) or s > E.CAL[-1]: continue
                if r["day"] >= b: continue                       # 날짜를 알린 공시가 매수일보다 먼저여야 함
                if not ok_universe(r["code"], b): continue
                x = buy_sell_open(r["code"], b, s)
                if x is None: continue
                seen.add((r["code"], t))
                tr.append((b, x, r["code"], r))
                ex.append((b, x - mkt(b, s)))
                TRADES.append(dict(way="P", kind=name, label=label, H=N, stop=sname, tp=None, code=r["code"], name=r["corp_name"],
                                   rcept=r["rcept_dt"], buy=b, sell=s, ret=round(x, 4), why=str(t), gap=None))
            show(f"{N}일 전 → {sname}", tr, ex)
            if div and tr:
                # 권리락일 시가 이후에 팔면 배당을 받는다 (권리락일 전날 장 마감까지 보유)
                tr2 = [(b, x + (r.get("dps") or 0) / bar(c, b)[0], c, r) for b, x, c, r in tr if r.get("dps")]
                show(f"   └ 배당금 있는 것만, 배당금 포함 (세전)", tr2)
            if N == 3 and sell_k == 0 and tr:
                by_tag(f"{N}일 전", tr)


def ex_date(record):
    """권리·배당락일 = 기준일 이전 마지막 거래일의 전 거래일 (결제 T+2). 기준일이 휴장(12-31)이어도 맞음."""
    if not record: return None
    d = record
    for _ in range(10):
        if d in E.CIDX: break
        d -= timedelta(days=1)
    else:
        return None
    return shift(d, -1)


def mc(r):
    d = shift(r["day"], -1)
    return E.mcap(r["code"], d) if d else 0


def main():
    R.say(f"📅 일정 시나리오 매매 백테스트 — {D0} ~ {D1}, 비용 {E.COST:.2%}, 일봉(수정주가)")
    R.say("★ = 앞 반·뒤 반 모두 + 이고 가장 좋은 5일을 빼도 +. 합계는 건당 100만 원 기준.")

    # 1) 실적
    ep = events(["earn_prelim"])
    follow("잠정실적 전체", ep)
    follow("잠정실적", ep, lambda r: (r["op_turn"] == "흑자전환") or (r["op_yoy"] or -1e9) >= 50, "영업이익 전년 대비 +50%↑ 또는 흑자전환")
    follow("잠정실적", ep, lambda r: (r["op_yoy"] or 1e9) <= -30 or r["op_turn"] == "적자전환", "영업이익 −30%↓ 또는 적자전환")
    en = events(["earn_notice"])
    pre("실적 공시 예정일", en, lambda r: r.get("due"))
    # 작년 같은 분기 발표일 + 1년 (공시 예고가 없는 회사 포함, 그날 아는 정보만)
    est = []
    for r in ep:
        est.append(dict(r, due=r["rcept_dt"] + timedelta(days=364)))
    pre("실적 발표 짐작일(작년 같은 분기)", [dict(x, day=x["day"]) for x in est], lambda r: r.get("due"), label="작년 발표일 +52주")

    # 2) 자사주
    bb = events(["buyback"]); tr_ = events(["buyback_trust"]); cn = events(["cancel"])
    follow("자사주 취득 결정 전체", bb)
    follow("자사주 취득 결정", bb, lambda r: r["amount"] and mc(r) and r["amount"] / mc(r) >= 0.02, "시총 2%↑")
    follow("자사주 신탁 계약", tr_)
    follow("주식 소각 결정 전체", cn)
    follow("주식 소각 결정", cn, lambda r: (r["ratio"] or 0) >= 0.02, "발행주식 2%↑")

    # 3) 배당·밸류업
    dv = events(["dividend"])
    follow("현금배당 결정 전체", dv)
    follow("현금배당 결정", dv, lambda r: (r["yield_pct"] or 0) >= 4, "시가배당률 4%↑")
    rec = events(["div_record", "dividend"])
    # 배당 공시엔 dps 가 있고 기준일 공시엔 없다 → 같은 기준일의 배당 결정 dps 를 붙인다
    dps = {(r["code"], r["record"]): r["dps"] for r in dv if r.get("record") and r.get("dps")}
    for r in rec:
        if not r.get("dps"): r["dps"] = dps.get((r["code"], r.get("record")))
    pre("배당락", rec, lambda r: ex_date(r.get("record")), div=True, label="(예정일 = 배당락일)")
    vu = events(["valueup"])
    follow("기업가치 제고 계획(밸류업)", vu, lambda r: "예고" not in r["title"], "본 공시")
    follow("기업가치 제고 계획(밸류업)", vu, lambda r: "예고" in r["title"], "예고 공시")

    # 4) 무상증자·액면분할
    bo = events(["bonus"])
    follow("무상증자 결정", bo)
    # 권리락일 = 신주배정 기준일 전 거래일 → 그 전날까지 보유 후 권리락일 시가에 판다
    pre("무상증자 권리락", bo, lambda r: ex_date(r.get("record")), Ns=(1, 3, 5, 10, 20),
        label="(예정일 = 권리락일)")
    sp = events(["split"])
    follow("주식분할 결정", sp)

    with open(os.path.join(OUT, "trades.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(TRADES[0].keys())); w.writeheader(); w.writerows(TRADES)
    R.say(f"\n9-14 뒤 정규장으로 못 바꾼 종목·일(통합 시가·고저 사용): {len(E.UNSURE)}")


if __name__ == "__main__":
    main()
