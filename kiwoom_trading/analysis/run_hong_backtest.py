"""📕 홍인기 상한가 풀림 매수 1년 백테스트 (2026-10-27).

규칙(indicators/hong.py): 상한가에 잠겼던 종목이 풀리면 산다 → 다시 상한가 닿으면 절반 상한가 매도, 나머지 다음 날 시가.
자료·체결은 디앤서 공통 엔진(.claude/skills/danswer/scripts/engine.py)을 그대로 쓴다:
  1분봉 = minute_history + kang_minute(장중 +15%↑ 종목·일 전부 → 상한가 종목은 거래대금과 관계없이 다 있음, 쏠림 없음),
  9-14 이후 일봉은 정규장 값으로 바로잡음, 다음 날 가격은 두 날 가격 기준이 다르면 맞춤, 비용 0.25%.
상한가 판정: 그날 정규장 1분봉 최고가 ≥ 전날 종가(1분봉 기준으로 환산) × 1.29, 그 가격을 상한가로 본다.

1부: 수급 조건 없이 1년 (2025-10-16 ~ 2026-10-22).
2부: 장중 기관·외국인 잠정치(investor_intraday, 2026-10-14~)·프로그램(program_intraday, 10-26~) 이 있는 날만 수급 조건 붙여 비교.

실행: .venv/Scripts/python.exe -m kiwoom_trading.analysis.run_hong_backtest  [--report-only]
결과: data/hong/backtest.txt, trades.pkl, events.csv
"""
from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict
from datetime import date, datetime, time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "danswer", "scripts"))
import engine as E  # noqa: E402

from kiwoom_trading.analysis.indicators.hong import HongParams, find_entry, simulate_exit, upper_limit  # noqa: E402

OUT = os.path.join(E.DATA, "hong")
os.makedirs(OUT, exist_ok=True)
LIMIT_RATIO = 1.29
BASE = HongParams()


def build_configs():
    c = {}
    c["기본: 1분↑ 잠김 뒤 풀림·풀린 봉 종가 | 절반 상한가·나머지 다음 날 09:00"] = BASE
    c["잠김 없이 첫 풀림"] = BASE.with_(min_lock=0)
    c["5분↑ 잠김 뒤 풀림"] = BASE.with_(min_lock=5)
    c["15분↑ 잠김 뒤 풀림"] = BASE.with_(min_lock=15)
    c["다음 봉 시가 매수"] = BASE.with_(entry="next")
    c["풀림 깊이 2%↑ (저가 ≤ 상한가−2%)"] = BASE.with_(min_dip=0.02)
    c["풀림 깊이 4%↑"] = BASE.with_(min_dip=0.04)
    c["09:00~10:30 풀림만"] = BASE.with_(t_to=time(10, 30))
    c["10:30~15:00 풀림만"] = BASE.with_(t_from=time(10, 31))
    c["매도: 전부 다음 날 (절반 매도 없음)"] = BASE.with_(half_at_limit=False)
    c["매도: 다시 상한가면 전부"] = BASE.with_(all_at_limit=True)
    c["손절 −5%"] = BASE.with_(stop_pct=0.05)
    c["손절 −8%"] = BASE.with_(stop_pct=0.08)
    c["5분↑ 잠김 + 손절 −5%"] = BASE.with_(min_lock=5, stop_pct=0.05)
    c["매수가 1호가 비싸게 (미끄러짐)"] = BASE.with_(slip_ticks=1)
    c["매수가 2호가 비싸게"] = BASE.with_(slip_ticks=2)
    c["5분↑ 잠김 + 2호가 비싸게"] = BASE.with_(min_lock=5, slip_ticks=2)
    c["5분↑ 잠김 + 2호가 + 전부 다음 날"] = BASE.with_(min_lock=5, slip_ticks=2, half_at_limit=False)
    return c


CONFIGS = build_configs()


# ---------------------------------------------------------------- 시장 (지수 20일선)
def index_below_ma20():
    """{date: (코스피 전날 종가 < 20일선, 코스닥 전날 종가 < 20일선)} — 판단은 전날 마감 기준."""
    out = {}
    for code in ("001", "101"):
        rows = E.IX.execute("SELECT date, close FROM idx_daily WHERE code=? ORDER BY date", [code]).fetchall()
        ds = [r[0] for r in rows]; cl = np.array([r[1] for r in rows], float)
        for i in range(20, len(ds)):
            below = cl[i - 1] < cl[i - 20:i].mean()      # i 날 판단 = i-1 날 종가 vs i-1 까지 20일 평균
            out.setdefault(ds[i], [None, None])[0 if code == "001" else 1] = below
    return {d: tuple(v) for d, v in out.items()}


# ---------------------------------------------------------------- 후보·매매
def day_candidates(d):
    """그날 상한가 닿은 종목 → [(code, reg, limit, pc)]."""
    pd_ = E.daily_day(E.prev_day(d))
    codes = [c for c in E._min_codes(d) if c in pd_ and E.is_common(c)]
    B = E.load_day(codes, d)
    out = []
    for c in codes:
        reg = E.regular(B[c])
        if len(reg) < 30:
            continue
        f = E.factor(c, d)
        if not f:
            continue
        pc = pd_[c][3] * f
        hi = max(x[2] for x in reg)
        if not pc or hi < pc * LIMIT_RATIO or hi > pc * 1.31:
            continue
        if len(E.hist(c, d, 5)) < 5:      # 신규 상장 직후(상한가 폭 다름) 제외
            continue
        out.append((c, reg, hi, pc))
    return out


def exact_limit(hi, pc):
    """1분봉 최고가가 기준가(전날 종가 환산) × 1.3 호가 내림과 정확히 같은가 — 기준가가 애프터 종가로 어긋난 종목·일 점검용."""
    return any(hi == upper_limit(b) for b in (pc, round(pc)))


def trade_return(c, d, reg, limit, p: HongParams):
    e = find_entry(reg, limit, p)
    if not e:
        return None
    j, buy, start, run = e
    parts = simulate_exit(reg, start, buy, limit, p)
    nx = E.next_day_exits(c, d, buy)
    rets = {}
    for basis in ("09:00 시가", "08:00 NXT 시가"):
        r, ok = 0.0, True
        for frac, px, why in parts:
            if px is None:
                if basis not in nx:
                    ok = False; break
                r += frac * (nx[basis] + E.COST)          # next_day_exits 는 비용 뺀 값 → 되돌림
            else:
                r += frac * (px / buy - 1)
        if ok:
            rets[basis] = r - E.COST
    if "09:00 시가" not in rets:
        return None
    cumv = sum(x[4] * x[5] for x in reg[:j + 1])
    return dict(code=c, date=d, t=reg[j][0], buy=buy, limit=limit, run=run, parts=parts, rets=rets,
                cumv=cumv, dip=min(x[3] for x in reg[j:j + 1]) / limit - 1)


def tags(tr, mkt, d, c, reg, limit):
    out = ["전체"]
    kb, qb = mkt.get(d, (None, None))
    out.append("코스피·코스닥 둘 다 20일선 아래" if kb and qb else "둘 중 하나↑ 20일선 위")
    n = E.streak_limitup(c, d)
    out.append("첫 상한가" if n == 0 else "2연상 이후")
    cap = E.mcap(c, E.prev_day(d))
    out.append("시총 3천억↑" if cap >= 3e11 else "시총 1천~3천억" if cap >= 1e11 else "시총 1천억↓")
    out.append("매수 시점 누적 대금 300억↑" if tr["cumv"] >= 3e10 else "누적 대금 100~300억" if tr["cumv"] >= 1e10 else "누적 대금 100억↓")
    first = next(x[0] for x in reg if x[2] >= limit)
    out.append("첫 상한가 10:00 전" if first < time(10, 0) else "첫 상한가 10:00 뒤")
    out.append("상한가 가격 정확히 맞음" if exact_limit(limit, tr["pc"]) else "상한가 가격 어긋남(기준가 의심)")
    b = tr["buy"]
    out.append("매수가 1천원↓" if b < 1000 else "매수가 1천~5천원" if b < 5000 else "매수가 5천원↑")
    closed = reg[-1][4] >= limit
    out.append("[참고·미래] 상한가 마감" if closed else "[참고·미래] 상한가 못 지킴")
    return out


def run():
    mkt = index_below_ma20()
    trades = {name: [] for name in CONFIGS}
    events = []
    days = E.days()
    for i, d in enumerate(days):
        for c, reg, limit, pc in day_candidates(d):
            events.append((d, c))
            for name, p in CONFIGS.items():
                tr = trade_return(c, d, reg, limit, p)
                if tr:
                    tr["pc"] = pc
                    tr["tags"] = tags(tr, mkt, d, c, reg, limit)
                    trades[name].append(tr)
        if i % 20 == 0:
            print(f"  {d} 상한가 종목 누적 {len(events)}", file=sys.stderr)
    with open(os.path.join(OUT, "trades.pkl"), "wb") as f:
        pickle.dump(dict(trades=trades, events=events), f)
    return trades, events


# ---------------------------------------------------------------- 보고
class Rep(E.Report):
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")


def report(trades, events):
    R = Rep(os.path.join(OUT, "backtest.txt"))
    days = E.days()
    R.say(f"📕 홍인기 상한가 풀림 매수 1년 ({days[0]} ~ {days[-1]}, {len(days)}일) — 비용 0.25% 포함, 1건 = 100만 원 기준 '만'")
    R.say(f"상한가 닿은 종목·일 {len(events)}건 (우선주·신규 상장 제외)")
    R.say("★ = 앞·뒤 반 모두 + 이고 가장 좋은 5일을 빼도 +\n")
    R.say("## 조건별 (다음 날 09:00 시가 기준)")
    for name, tr in trades.items():
        R.stats([(t["date"], t["rets"]["09:00 시가"]) for t in tr], name, 52)
    R.say("\n## 다음 날 08:00 NXT 시가에 팔면 (NXT 거래 종목만)")
    for name in list(CONFIGS)[:1] + ["매도: 전부 다음 날 (절반 매도 없음)"]:
        tr = [t for t in trades[name] if "08:00 NXT 시가" in t["rets"]]
        R.stats([(t["date"], t["rets"]["08:00 NXT 시가"]) for t in tr], name + " — NXT 08:00", 52)
        R.stats([(t["date"], t["rets"]["09:00 시가"]) for t in tr], name + " — 같은 종목 09:00", 52)
    for name in [list(CONFIGS)[0], "5분↑ 잠김 + 2호가 비싸게"]:
        R.say(f"\n## 나눠 보기 — {name}")
        by = defaultdict(list)
        for t in trades[name]:
            for g in t["tags"]:
                by[g].append((t["date"], t["rets"]["09:00 시가"]))
        for g in sorted(by, key=lambda g: (g != "전체", g)):
            R.stats(by[g], g, 52)
    # 절반 매도 비율 등
    tr = trades[list(CONFIGS)[0]]
    half = sum(1 for t in tr if any(w == "상한가 절반" for _, _, w in t["parts"]))
    R.say(f"\n기본 규칙: 매수 {len(tr)}건 중 다시 상한가 닿아 절반 판 것 {half}건 ({half / max(len(tr), 1):.0%})")
    R.say(f"매수 시각 분포: " + ", ".join(f"{h}시 {sum(1 for t in tr if t['t'].hour == h)}" for h in range(9, 16)))
    # 월별
    R.say("\n월별 (기본 규칙, 건당 평균·합계 만)")
    bym = defaultdict(list)
    for t in tr:
        bym[t["date"].strftime("%y-%m")].append(t["rets"]["09:00 시가"])
    R.say(" · ".join(f"{m} {np.mean(v):+.1%}({len(v)}건,{sum(v) * 100:+.0f})" for m, v in sorted(bym.items())))
    flow_part(R, trades)
    import csv
    with open(os.path.join(OUT, "trades_base.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "code", "name", "buy_time", "buy", "limit", "locked_min", "ret_0900", "ret_0800", "parts", "tags"])
        for t in tr:
            w.writerow([t["date"], t["code"], E.NAME.get(t["code"], ""), t["t"], round(t["buy"]), t["limit"], t["run"],
                        round(t["rets"]["09:00 시가"], 4), round(t["rets"].get("08:00 NXT 시가", float("nan")), 4),
                        "; ".join(f"{fr:.2f}@{px if px else '다음날'}({w_})" for fr, px, w_ in t["parts"]), "|".join(t["tags"])])


def load_flows():
    """screener.duckdb 장중 잠정치 → {(date, code): [(ts, investor, net_amount)]}, 프로그램 {(date, code): [(ts, net)]}."""
    import duckdb
    con = duckdb.connect(E._cp("screener.duckdb"), read_only=True)
    inv, prog = defaultdict(list), defaultdict(list)
    for ts, d, who, c, v in con.execute("SELECT ts, date, investor, code, net_amount FROM investor_intraday ORDER BY ts").fetchall():
        inv[(d, c)].append((ts, who, v))
    for ts, d, c, v in con.execute("SELECT ts, date, code, net_amount FROM program_intraday ORDER BY ts").fetchall():
        prog[(d, c)].append((ts, v))
    days = sorted({d for d, _ in inv} | {d for d, _ in prog})
    return inv, prog, days


def flow_at(inv, prog, d, c, t):
    """매수 시각 t 직전(그 시각까지 저장된) 기관·외국인·프로그램 순매수(원). 그날 자료가 아직 없으면 None."""
    at_ = datetime.combine(d, t)
    last = {}
    for ts, who, v in inv.get((d, c), []):
        if ts <= at_:
            last[who] = v
    p = None
    for ts, v in prog.get((d, c), []):
        if ts <= at_:
            p = v
    return last.get("institution"), last.get("foreign"), p


def flow_part(R, trades):
    """2부: 장중 수급 자료가 있는 날만 — 기관 가집계 순매수 + 인 풀림 매수 vs 아닌 것."""
    try:
        inv, prog, fdays = load_flows()
    except Exception as e:
        R.say(f"\n## 2부 수급 조건: 자료를 못 읽음 ({e})"); return
    R.say(f"\n## 2부: 장중 수급 조건 (자료 있는 날 {fdays[0]} ~ {fdays[-1]}, {len(fdays)}일 중 1분봉·다음 날 가격까지 있는 날만)")
    R.say("  기관 = 매수 시각까지 나온 마지막 기관 가집계(보통 09:50 무렵 첫 발표) / 프로그램 = 10분마다 저장 (10-26 부터)")
    for name in [list(CONFIGS)[0], "5분↑ 잠김 뒤 풀림", "매도: 전부 다음 날 (절반 매도 없음)"]:
        rows = [t for t in trades[name] if t["date"] in set(fdays)]
        groups = defaultdict(list)
        R.say(f"\n  [{name}] {len(rows)}건")
        for t in sorted(rows, key=lambda t: (t["date"], t["t"])):
            ins, fo, pg = flow_at(inv, prog, t["date"], t["code"], t["t"])
            g = "기관 자료 전" if ins is None else ("기관 +" if ins > 0 else "기관 −")
            groups[g].append(t["rets"]["09:00 시가"])
            if name == list(CONFIGS)[0]:
                R.say(f"    {t['date']} {t['t']:%H:%M} {E.NAME.get(t['code'], t['code'])[:8]:8s} 매수 {t['buy']:,.0f} (상한가 {t['limit']:,.0f}) "
                      f"기관 {'-' if ins is None else f'{ins / 1e8:+.0f}억'} 외국인 {'-' if fo is None else f'{fo / 1e8:+.0f}억'} "
                      f"프로그램 {'-' if pg is None else f'{pg / 1e8:+.0f}억'} → {t['rets']['09:00 시가']:+.1%}")
        for g, v in groups.items():
            R.say(f"    {g:10s} {len(v):3d}건 건당 {np.mean(v):+.2%} 합계 {sum(v) * 100:+.0f}만 (수익 {np.mean(np.array(v) > 0):.0%})")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--report-only" in sys.argv:
        with open(os.path.join(OUT, "trades.pkl"), "rb") as f:
            x = pickle.load(f)
        report(x["trades"], x["events"])
        return
    trades, events = run()
    report(trades, events)


if __name__ == "__main__":
    main()
