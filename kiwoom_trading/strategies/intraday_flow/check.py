"""장중 1분봉 모양 매수에 '장중 수급'(외국인·기관 잠정치, 프로그램 순매수)을 붙이면 나아지나? (2026-10-27)

사용자 질문: "장중 1분봉 모양만으로 사는 매매는 1년 손실이었다 → 장중 수급을 붙이면 나아지나?"
기간: 2026-10-14 ~ 10-27 (10 거래일, 장중 잠정치가 쌓인 기간 전부). 프로그램은 10-26·27 이틀만 있음. ※ 표본이 아주 작다.

자료
- 1분봉: 키움 ka10080 통합(AL, 08:00~20:00, 없으면 KRX). base_dt = 다음 거래일로 받아 그날·다음 날 09:00 시가·전날 정규장 종가를 한 번에 얻음.
  (minute_history.duckdb 는 다른 프로세스가 쓰는 중이라 안 씀) 캐시: %TEMP%/intraday_flow_bars.pkl
- 대상: 전날 일봉 대금 200위 보통주 (그날 순위는 미래 정보라 안 씀) + 그날 실제로 뜬 '눌림 돌파' 신호 종목(실제 신호용).
- 수급: screener.duckdb investor_intraday(외국인 ~09:20 첫 발표·기관 ~09:55 첫 발표, 하루 4~9번),
        program_intraday(10분마다, 10-26·27).
  매수 봉 시작 시각 '전'에 나온 마지막 스냅샷만 씀(미래 정보 없음). 첫 스냅샷 전 신호 = '수급 자료 없음'.
  '증가' = 직전 스냅샷보다 순매수가 큼 (그날 첫 스냅샷이면 장 시작 0 대비 → 순매수 > 0 과 같음).

매수 방식 (1분봉 모양만, 기존 생성기 그대로 재사용)
  A1·A2·A3 (갭 없는 종목) · B0·B2 (눌림 돌파 계열) — intraday_early/timing.py
  E1 시가 회복 (프리장 갭 2%↑ 뒤 흔들기) — premarket_reclaim/timing.py 의 setup·entries 를 그대로 옮김
     (그 모듈은 import 때 backtest.engine 이 minute_history.duckdb 를 복사·열어서 여기선 직접 import 안 함)
  실제 '눌림 돌파' — buy_signals 의 실제 알림: 신호 분 다음 봉 시가 매수, 손절 = 알림의 stop
매도 (규칙): 각 생성기 손절, 절반 +2R → 나머지 트레일 3%(max(손절, 본전, 고점×0.97)), 같은 봉이면 손절 먼저,
  15:19 까지 남으면 다음 날 09:00 시가. 비용 0.25%. 10-27 신호는 다음 날 자료가 없어 15:19 종가로 대신함(표시).
참고(규칙 아님): 15:19 까지 최고 상승폭, 15:19 종가 매도.

실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.intraday_flow.check   → data/intraday_flow/check.txt
"""
import os
import pickle
import shutil
import sys
import tempfile
import time as _time
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import duckdb
import numpy as np

from kiwoom_trading.strategies.intraday_early import timing as T

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "intraday_flow")
TMP = tempfile.gettempdir()
CACHE = os.path.join(TMP, "intraday_flow_bars.pkl")
D0, D1 = date(2026, 10, 14), date(2026, 10, 27)
COST = T.COST
LIVE = "실제 눌림 돌파"


def _open_ro(name):
    p = os.path.join(DATA, name)
    try:
        return duckdb.connect(p, read_only=True)
    except Exception:
        dst = os.path.join(TMP, "iflow_" + name)
        shutil.copy(p, dst)
        return duckdb.connect(dst, read_only=True)


# ---------------------------------------------------------------- E1 (premarket_reclaim/timing.py 에서 옮김)
GAP, SHAKE, HOLD = 0.02, 0.02, 0.01


def e1_setup(b, prev_close):
    pre = [x for x in b if x[0] < time(9, 0)]
    reg = [i for i, x in enumerate(b) if x[0] >= time(9, 0)]
    if len(pre) < 10 or len(reg) < 60:
        return None
    pre_hi = max(x[2] for x in pre)
    if pre_hi < prev_close * (1 + GAP):
        return None
    early = [i for i in reg if b[i][0] <= time(9, 10)]
    if not early:
        return None
    k = min(early, key=lambda i: b[i][3])
    lo = b[k][3]
    if not (lo <= pre_hi * (1 - SHAKE) and lo >= prev_close * (1 - HOLD)):
        return None
    return pre_hi, b[reg[0]][1], lo, k, reg[0]


def e1_entry(b, s):
    """E1 시가 회복: 흔들기 저가 뒤 종가 > 09:00 시가 & 봉 대금 ≥ 10억·직전 5봉 2배 → (매수 봉 index, 매수가, 신호 봉 index)."""
    pre_hi, op, lo, k, r0 = s
    vals = np.array([x[4] * x[5] for x in b], float)
    for i in range(k + 1, len(b) - 1):
        x = b[i]
        if x[0] > time(10, 30) or x[3] < lo:
            break
        if x[4] > op and vals[i] >= T.VAL_MIN and vals[i] >= 2 * vals[i - 5:i].mean():
            return i + 1, b[i + 1][1], i
    return None


# ---------------------------------------------------------------- 1분봉 받기
def fetch_span(cl, code, base_day, oldest_dt, exch):
    """base_day 부터 과거로 oldest_dt 보다 이전 봉이 나올 때까지 → {date: [(time,o,h,l,c,v)]}."""
    sfx = {"KRX": "", "AL": "_AL"}[exch]
    body = {"stk_cd": code + sfx, "tic_scope": "1", "upd_stkpc_tp": "1", "base_dt": base_day.strftime("%Y%m%d")}
    cont, nk = "N", ""
    out = defaultdict(dict)
    for _ in range(5):
        pl, cont, nk = cl._post("/api/dostk/chart", "ka10080", body, cont, nk)
        items = pl.get("stk_min_pole_chart_qry") or []
        last = None
        for it in items:
            tm = str(it.get("cntr_tm") or "")
            if len(tm) < 14:
                continue
            ts = datetime.strptime(tm, "%Y%m%d%H%M%S")
            last = ts
            f = lambda k: abs(float(str(it.get(k) or 0).replace("+", "").replace("-", "") or 0))
            out[ts.date()][ts.time()] = (ts.time(), f("open_pric"), f("high_pric"), f("low_pric"), f("cur_prc"),
                                         abs(float(it.get("trde_qty") or 0)))
        if not items or last is None or last < oldest_dt or cont != "Y" or not nk:
            break
    return {d: sorted(v.values()) for d, v in out.items()}


def get_bars(cl, cache, code, d, prev, nxt):
    key = (code, d)
    if key in cache:
        return cache[key]
    base = nxt or d
    oldest = datetime.combine(prev, time(15, 0))
    got = fetch_span(cl, code, base, oldest, "AL")
    ex = "AL"
    if len([x for x in got.get(d, []) if time(9, 0) <= x[0] <= time(15, 30)]) < 100:
        g2 = fetch_span(cl, code, base, oldest, "KRX")
        if len(g2.get(d, [])) > len([x for x in got.get(d, []) if time(9, 0) <= x[0] <= time(15, 30)]):
            got, ex = g2, "KRX"
    cache[key] = {"ex": ex, "d": got.get(d, []), "prev": got.get(prev, []), "next": got.get(nxt, []) if nxt else []}
    return cache[key]


# ---------------------------------------------------------------- 수급 스냅샷
class Flow:
    def __init__(self, sc):
        self.inv = defaultdict(list)     # (date, code, investor) → [(ts, net)]
        for d, ts, code, iv, net in sc.execute("""SELECT date, ts, code, investor, net_amount FROM investor_intraday
                WHERE date BETWEEN ? AND ? ORDER BY ts""", [D0, D1]).fetchall():
            self.inv[(d, code, iv)].append((ts, float(net or 0)))
        self.prog = defaultdict(list)
        for d, ts, code, net in sc.execute("""SELECT date, ts, code, net_amount FROM program_intraday
                WHERE date BETWEEN ? AND ? ORDER BY ts""", [D0, D1]).fetchall():
            self.prog[(d, code)].append((ts, float(net or 0)))
        self.prog_days = {d for d, _ in self.prog}
        self.first = {}
        for (d, code, iv), v in self.inv.items():
            k = (d, iv)
            self.first[k] = min(self.first.get(k, v[0][0]), v[0][0])

    @staticmethod
    def _at(v, t):
        """t 전 마지막 값, 그 직전 값(없으면 0)."""
        prev, cur = 0.0, None
        for ts, net in v:
            if ts >= t:
                break
            prev, cur = (cur if cur is not None else 0.0), net
        return cur, prev

    def get(self, d, code, t):
        f, fp = self._at(self.inv.get((d, code, "foreign"), []), t)
        i, _ = self._at(self.inv.get((d, code, "institution"), []), t)
        p, pp = self._at(self.prog.get((d, code), []), t)
        return dict(f=f, f_up=(f is not None and f > fp), i=i, p=p, p_up=(p is not None and p > pp))


# ---------------------------------------------------------------- 메인
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    from kiwoom_trading.screener import run_intraday as ri
    dm = _open_ro("daily_ohlcv.duckdb")
    sc = _open_ro("screener.duckdb")
    cal = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date >= '2026-09-01' ORDER BY 1").fetchall()]
    days = [d for d in cal if D0 <= d <= D1]
    prev_of = {d: cal[cal.index(d) - 1] for d in days}
    next_of = {d: (cal[cal.index(d) + 1] if cal.index(d) + 1 < len(cal) else None) for d in days}

    live = defaultdict(list)
    for d, code, ts, stop in sc.execute("""SELECT date, code, ts, stop FROM buy_signals WHERE kind='눌림 돌파'
            AND date BETWEEN ? AND ? ORDER BY ts""", [D0, D1]).fetchall():
        live[d].append((code, ts, stop))
    flow = Flow(sc)

    cache = {}
    if os.path.exists(CACHE):
        cache = pickle.load(open(CACHE, "rb"))
    cl = ri.build_client()

    universe = {}
    for d in days:
        p = prev_of[d]
        rows = dm.execute("SELECT code, value FROM daily_ohlcv WHERE date=? ORDER BY value DESC NULLS LAST", [p]).fetchall()
        U = [c for c, v in rows if T_is_common(c)][:200]
        universe[d] = (U, sorted({c for c, *_ in live[d]}))

    n_new = 0
    for d in days:
        U, L = universe[d]
        for code in list(dict.fromkeys(U + L)):
            if (code, d) not in cache:
                try:
                    get_bars(cl, cache, code, d, prev_of[d], next_of[d])
                except Exception as e:
                    print(f"  {code} {d} 받기 실패: {e}", file=sys.stderr)
                    continue
                n_new += 1
                if n_new % 100 == 0:
                    pickle.dump(cache, open(CACHE, "wb"))
                    print(f"  ... {d} 1분봉 {n_new}건 받음", file=sys.stderr, flush=True)
    pickle.dump(cache, open(CACHE, "wb"))

    # ---- 신호 만들기
    sigs = []   # dict(d, code, entry, j, e, stop, reg, nopen, nxt_missing)
    for d in days:
        U, L = universe[d]
        for code in U:
            bb = cache.get((code, d))
            if not bb:
                continue
            b = bb["d"]; reg = [x for x in b if time(9, 0) <= x[0] <= time(15, 30)]
            pr = [x for x in bb["prev"] if time(9, 0) <= x[0] <= time(15, 30)]
            if len(reg) < 100 or len(pr) < 30:
                continue
            pc = pr[-1][4]
            if not pc or abs(reg[0][1] / pc - 1) > 0.3:
                continue
            pre = [x for x in b if x[0] < time(9, 0)]
            ents = {}
            if T.no_gap(pre, reg[0][1], pc):
                ents.update({k: v for k, v in T.entries_a(reg, pc).items()})
            ents.update({k: v for k, v in T.entries_b(reg, pc).items() if k in ("B0", "B2")})
            s = e1_setup(b, pc)
            if s:
                r = e1_entry(b, s)
                if r:
                    jb, e, si = r
                    jt = b[jb][0]; st = b[si][0]
                    j = next((n for n, x in enumerate(reg) if x[0] == jt), None)
                    si_r = next((n for n, x in enumerate(reg) if x[0] == st), None)
                    if j is not None:
                        ents["E1"] = (j, e, s[2] * 0.999, False, si_r)
            for key, (j, e, stop0, lim, si) in ents.items():
                if key in ("A1", "A2", "A3", "B0", "B2", "E1"):
                    sigs.append(dict(d=d, code=code, kind=key, j=j, e=e, stop=stop0, lim=lim, reg=reg, bb=bb, pc=pc))
        for code, ts, stop in live[d]:
            bb = cache.get((code, d))
            if not bb or not stop:
                continue
            reg = [x for x in bb["d"] if time(9, 0) <= x[0] <= time(15, 30)]
            st = ts.time().replace(second=0, microsecond=0)
            j = next((n for n, x in enumerate(reg) if x[0] > st), None)
            if j is None:
                continue
            sigs.append(dict(d=d, code=code, kind=LIVE, j=j, e=reg[j][1], stop=float(stop), lim=False, reg=reg, bb=bb, pc=None))

    # ---- 매도·수급 붙이기
    trades = []
    for s in sigs:
        reg, j, e, stop0 = s["reg"], s["j"], s["e"], s["stop"]
        if e <= stop0 or j >= len(reg):
            continue
        nb = [x for x in s["bb"]["next"] if time(9, 0) <= x[0] <= time(9, 5)]
        upto = [x for x in reg[j:] if x[0] <= time(15, 19)]
        if not upto:
            continue
        c1519 = upto[-1][4]
        nopen, sub = (nb[0][1], False) if nb else (c1519, True)
        R = e - stop0
        r, rr = T.sell(reg, j, e, stop0, nopen, e + 2 * R, limit_bar=s["lim"])
        if r is None or abs(r) >= 0.35:
            continue
        ent_dt = datetime.combine(s["d"], reg[j][0])
        fl = flow.get(s["d"], s["code"], ent_dt)
        cumval = sum(x[4] * x[5] for x in reg[:j])
        trades.append(dict(d=s["d"], code=s["code"], kind=s["kind"], t=reg[j][0], r=r, rr=rr, sub=sub,
                           mx=max(x[2] for x in upto) / e - 1, c1519=c1519 / e - 1 - COST, cumval=cumval,
                           risk=e / stop0 - 1, **fl))

    # ---- 집계
    out = open(os.path.join(OUT, "check.txt"), "w", encoding="utf-8")

    def say(x=""):
        print(x); out.write(x + "\n"); out.flush()

    kinds = ["A1", "A2", "A3", "B0", "B2", "E1", LIVE]
    KN = {"A1": "A1 첫 대금 폭발 돌파", "A2": "A2 갭 없는 시가 탈환", "A3": "A3 첫 눌림 반등", "B0": "B0 눌림 돌파(생성기)",
          "B2": "B2 돌파 가격 지정가", "E1": "E1 갭 뒤 시가 탈환", LIVE: "실제 '눌림 돌파' 알림", "ALL": "모든 매수 방식 합침"}
    groups = [
        ("전체", lambda x: True),
        ("수급 자료 없음(첫 발표 전 등)", lambda x: x["f"] is None),
        ("수급 자료 있음", lambda x: x["f"] is not None),
        ("외국인 순매수 > 0", lambda x: x["f"] is not None and x["f"] > 0),
        ("외국인 순매수 증가", lambda x: x["f"] is not None and x["f_up"]),
        ("외국인·기관 둘 다 > 0", lambda x: (x["f"] or 0) > 0 and (x["i"] or 0) > 0),
        ("외국인 ≥ 누적 대금 5%", lambda x: x["f"] is not None and x["cumval"] > 0 and x["f"] >= 0.05 * x["cumval"]),
        ("외국인 순매도 (< 0)", lambda x: x["f"] is not None and x["f"] < 0),
        ("[10-26·27] 전체", lambda x: x["d"] in flow.prog_days),
        ("[10-26·27] 프로그램 > 0 & 증가", lambda x: x["d"] in flow.prog_days and (x["p"] or 0) > 0 and x["p_up"]),
        ("[10-26·27] 프로그램 순매도", lambda x: x["d"] in flow.prog_days and x["p"] is not None and x["p"] < 0),
    ]

    nsub = sum(x["sub"] for x in trades)
    say(f"장중 1분봉 모양 매수 + 장중 수급 거르기 — {days[0]} ~ {days[-1]} ({len(days)} 거래일). ※ 표본 아주 작음: 결론 아님, 방향만 봄")
    say(f"대상: 전날 대금 200위 보통주 {np.mean([len(universe[d][0]) for d in days]):.0f}개/일 + 실제 '눌림 돌파' 종목. 1분봉 키움 AL(없으면 KRX)")
    say(f"매도(규칙): 생성기 손절 · 절반 +2R → 트레일 3% · 남으면 다음 날 09:00 시가 · 비용 0.25%. "
        f"10-27 신호 {nsub}건은 다음 날 자료가 없어 15:19 종가로 대신함")
    say("참고(규칙 아님): '최고' = 매수 뒤 15:19 까지 최고 상승폭(비용 전), '15:19' = 15:19 종가 매도(비용 뒤)")
    say("열: 건수 · 건당 % · 승률 · 합계(100만/건, 만 원) | 참고 최고 · 15:19 · 평균 손절 거리")

    # 수급 자료가 있기는 한가 — 첫 발표 시각과 매수 시각
    say("\n== 수급 첫 발표 시각 (그날 가장 이른 스냅샷) ==")
    for d in days:
        f0 = flow.first.get((d, "foreign")); i0 = flow.first.get((d, "institution"))
        say(f"  {d} 외국인 {f0.strftime('%H:%M') if f0 else '-'} · 기관 {i0.strftime('%H:%M') if i0 else '-'}")
    say("\n== 매수 시각 분포와 '수급 자료 없음' 비율 (매수 방식별) ==")
    for k in kinds:
        v = [x for x in trades if x["kind"] == k]
        if not v:
            say(f"  {KN[k]:22s} 0건"); continue
        f_first = [flow.first.get((x["d"], "foreign")) for x in v]
        i_first = [flow.first.get((x["d"], "institution")) for x in v]
        before_f = sum(1 for x, f0 in zip(v, f_first) if f0 is None or datetime.combine(x["d"], x["t"]) <= f0)
        before_i = sum(1 for x, i0 in zip(v, i_first) if i0 is None or datetime.combine(x["d"], x["t"]) <= i0)
        nof = sum(x["f"] is None for x in v)
        ts = sorted(x["t"] for x in v)
        say(f"  {KN[k]:22s} {len(v):4d}건 · 매수 시각 중앙 {ts[len(ts) // 2].strftime('%H:%M')} · "
            f"외국인 첫 발표 전 {before_f}건({before_f / len(v):.0%}) · 기관 첫 발표 전 {before_i}건({before_i / len(v):.0%}) · "
            f"그 종목 외국인 자료 없음 {nof}건({nof / len(v):.0%})")

    def line(v, title, w=30):
        if not v:
            say(f"   {title:{w}s}    0건"); return
        r = np.array([x["r"] for x in v])
        say(f"   {title:{w}s} {len(v):4d}건 건당 {r.mean():+.2%} 승률 {np.mean(r > 0):3.0%} 합계 {r.sum() * 100:+6.0f}만 "
            f"| 참고 최고 {np.mean([x['mx'] for x in v]):+.2%} · 15:19 {np.mean([x['c1519'] for x in v]):+.2%} · 손절 {np.mean([x['risk'] for x in v]):.1%}")

    for k in ["ALL"] + kinds:
        v0 = trades if k == "ALL" else [x for x in trades if x["kind"] == k]
        say(f"\n== {KN[k]} ==")
        for gn, g in groups:
            line([x for x in v0 if g(x)], gn)

    # 같은 날·종목 중복을 줄인 보기: 종목·일 하나에 가장 이른 매수만
    say("\n== 모든 매수 방식 합침, 종목·일 하나에 가장 이른 매수만 (중복 제거) ==")
    first = {}
    for x in sorted(trades, key=lambda x: x["t"]):
        first.setdefault((x["d"], x["code"]), x)
    v0 = list(first.values())
    for gn, g in groups:
        line([x for x in v0 if g(x)], gn)

    # 날짜별 (하루 몰림 확인)
    say("\n== 날짜별 (모든 매수 방식, 중복 제거) — 전체 vs 외국인 순매수 > 0 ==")
    for d in days:
        a = [x for x in v0 if x["d"] == d]; b_ = [x for x in a if x["f"] is not None and x["f"] > 0]
        say(f"  {d} 전체 {len(a):3d}건 {np.mean([x['r'] for x in a]) if a else float('nan'):+.2%} · "
            f"외국인>0 {len(b_):3d}건 {np.mean([x['r'] for x in b_]) if b_ else float('nan'):+.2%}")
    out.close()


def T_is_common(c):
    return c[-1] not in "579K"


if __name__ == "__main__":
    main()
