"""1️⃣ 상승장 장 초 — 손절·매도 자리를 '차트 레벨(지지·저항)'로 바꾸면 숫자 손절(−4/−6%)보다 나은가 (2026-10-28 사용자).

매수: 1️⃣ 그대로 = bt_chase_stop.py 와 같은 후보(u_cands.pkl, 강한 상승장 U 날 09:10 대금 40위·시가 위·전날 외인·기관 둘 다 − 제외),
      09:11 봉 시가 매수, 상한가 근처(+29%↑) 못 삼. 1분봉 = engine (원가격, AL 통합; minute_history 잠기면 engine 이 이전 복사본 사용).
손절 레벨 (모두 09:11 매수 시점까지 아는 값, 또는 그 뒤 봉이 끝난 뒤 아는 값):
  S1 09:00~09:10 저점 (시가 구간 저점)
  S2 전일 종가 (그 종목 전날 1분봉 정규장 마지막 종가 — 일봉 쓰지 않음, 두 날 가격 기준 다르면 factor 비율로 맞춤)
  S3 VWAP (09:00 부터 누적 Σ(고+저+종)/3×거래량 ÷ Σ거래량) 아래로 마감, 매수 뒤 10분(09:21 봉)부터 확인
  S4 S1 과 −6% 중 가까운 것(near) / 먼 것(far)
  S5 매수 뒤 10분(09:11~09:20) 최저가 — 09:21 봉부터 적용, 그 전엔 S1
  방식: 'c' = 1분봉 종가가 레벨 아래로 마감 → 다음 봉 시가 매도 / 't' = 저가가 레벨 닿으면 그 가격(시가가 이미 아래면 시가)
  이미 깨진 경우(레벨 ≥ 매수가 × 0.995): 차트 손절을 못 쓰므로 −4% 숫자 손절로 바꿔 씀 (몇 건인지 표시).
  S3 는 09:21 부터 그때 VWAP 와 비교하는 움직이는 레벨이라 '깨짐' 바꿔 쓰기 없음 (09:21 전엔 손절 없음).
익절·매도:
  T1 없음 → 다음 날 09:00 시가
  T2 저항: 매수가 < 전일 고가(1분봉 정규장)면 전일 고가, 아니면 52주 고가(일봉 250일 고가 × factor) 닿으면 절반 매도.
     둘 다 이미 위면 저항 없음 = T1. 나머지는 같은 손절 레벨 또는 다음 날 09:00.
  T3 2R 닿으면 절반 (R = 매수가 − 처음 손절 레벨; S3 는 09:11 VWAP) → 나머지 트레일링: 매수 뒤 고가 × 0.97 과 본전 중 높은 값 (닿으면 그 가격).
같은 봉에서 손절·익절이 둘 다면 손절 먼저 (종가 마감 방식은 그 봉 익절 무시). 15:19 봉까지만 장중 매도, 그 뒤는 다음 날 09:00. 비용 0.25%.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.regime_plays.bt_up_chart_exits → data/backtest/up_chart_exits.txt
"""
import os, sys
from collections import defaultdict
from datetime import date, datetime, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "backtest"); os.makedirs(OUT, exist_ok=True)
UNTIL = time(15, 19)
ACT = time(9, 21)
F = open(os.path.join(OUT, "up_chart_exits.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def vwap_series(b):
    """09:00 부터 각 봉이 끝났을 때의 VWAP."""
    pv = vv = 0.0; out = []
    for x in b:
        tp = (x[2] + x[3] + x[4]) / 3
        pv += tp * (x[5] or 0); vv += (x[5] or 0)
        out.append(pv / vv if vv else x[4])
    return out


def sim(b, j, buy, nx, stop_kind, mode, tgt, ctx):
    """b = 정규장 봉, j = 매수 봉 인덱스. stop_kind: ('pct',k) / 'S1' / 'S2' / 'S3' / 'S4n' / 'S4f' / 'S5' / None.
    mode 'c'/'t'. tgt: 'T1'/'T2'/'T3'. → (수익률, 장중 매도 비중, 보유 분(장중 매도분), 손절 비중, 깨짐여부)."""
    vw = ctx["vw"]
    lvl0 = None
    if stop_kind is None:
        lvl0 = None
    elif isinstance(stop_kind, tuple):
        lvl0 = buy * (1 - stop_kind[1])
    elif stop_kind in ("S1", "S5"):
        lvl0 = ctx["or_low"]
    elif stop_kind == "S2":
        lvl0 = ctx["pc"]
    elif stop_kind == "S3":
        lvl0 = vw[j - 1]
    elif stop_kind == "S4n":
        lvl0 = max(ctx["or_low"], buy * 0.94)
    elif stop_kind == "S4f":
        lvl0 = min(ctx["or_low"], buy * 0.94)
    broken = False
    if stop_kind != "S3" and lvl0 is not None and lvl0 >= buy * 0.995:
        broken = True; stop_kind = ("pct", 0.04); lvl0 = buy * 0.96; mode = "t"
    R = (buy - lvl0) if lvl0 is not None else buy * 0.04
    tp_px = None
    if tgt == "T2":
        if ctx["ph"] and buy < ctx["ph"]: tp_px = ctx["ph"]
        elif ctx["h52"] and buy < ctx["h52"]: tp_px = ctx["h52"]
    elif tgt == "T3":
        tp_px = buy + 2 * R
    pos, got, half, hi = 1.0, 0.0, False, buy
    intr_w, hold_m, stop_w = 0.0, 0.0, 0.0
    t_buy = datetime.combine(date.today(), b[j][0])
    pending = False   # 종가 마감 방식: 다음 봉 시가에 매도

    def mins(t):
        return (datetime.combine(date.today(), t) - t_buy).seconds / 60

    s5_low = None
    for k in range(j, len(b)):
        t, o, h, l, c = b[k][:5]
        if t > UNTIL: break
        if pending:
            got += pos * (o / buy - 1); intr_w += pos; hold_m += pos * mins(t); stop_w += pos
            return got - E.COST, intr_w, hold_m, stop_w, broken
        # 지금 이 봉의 손절 레벨
        lvl = lvl0
        if stop_kind == "S5":
            if t < ACT:
                lvl = ctx["or_low"]
            else:
                if s5_low is None:
                    s5_low = min(x[3] for x in b[j:k])
                lvl = s5_low
        if stop_kind == "S3":
            lvl = None if t < ACT else vw[k]    # 종가 마감 판단은 이 봉 끝의 VWAP
        trail = None
        if tgt == "T3" and half:
            trail = max(hi * 0.97, buy)
        # 1) 트레일링(터치)
        if trail is not None and l <= trail:
            px = min(o, trail)
            got += pos * (px / buy - 1); intr_w += pos; hold_m += pos * mins(t)
            return got - E.COST, intr_w, hold_m, stop_w, broken
        # 2) 지지 손절
        if lvl is not None:
            if mode == "t" and stop_kind != "S3" and l <= lvl:
                px = min(o, lvl)
                got += pos * (px / buy - 1); intr_w += pos; hold_m += pos * mins(t); stop_w += pos
                return got - E.COST, intr_w, hold_m, stop_w, broken
            if (mode == "c" or stop_kind == "S3") and c < lvl:
                pending = True
                hi = max(hi, h)
                continue        # 이 봉 익절은 무시 (손절 먼저)
        # 3) 절반 익절
        if tp_px is not None and not half and h >= tp_px:
            px = max(o, tp_px) if o >= tp_px else tp_px
            got += 0.5 * (px / buy - 1); pos = 0.5; half = True; intr_w += 0.5; hold_m += 0.5 * mins(t)
        hi = max(hi, h)
    got += pos * nx      # nx 는 비용 뺀 값 → 비용 다시 더해 한 번만 빼기
    return got + pos * E.COST - E.COST, intr_w, hold_m, stop_w, broken


def stats(tr, title):
    """tr = [(date, ret, intr_w, hold_m, stop_w, broken)]."""
    if len(tr) < 5:
        say(f"   {title:34s} {len(tr)}건 (적음)"); return None
    ds = sorted({x[0] for x in tr}); h = ds[len(ds) // 2]
    v = np.array([x[1] for x in tr]); a = [x[1] for x in tr if x[0] < h]; bb = [x[1] for x in tr if x[0] >= h]
    bd = defaultdict(list)
    for x in tr: bd[x[0]].append(x[1])
    dr = {d: np.mean(x) for d, x in bd.items()}
    s = sorted(dr.values(), reverse=True)
    eq = np.cumsum([dr[d] for d in sorted(dr)]) * 1000
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    iw = sum(x[2] for x in tr); hm = sum(x[3] for x in tr) / iw if iw else 0
    sw = np.mean([x[4] for x in tr]); br = sum(x[5] for x in tr)
    say(f" {star} {title:34s} {len(v):4d}건 건당 {v.mean():+.2%} | 앞 {np.mean(a):+.2%} 뒤 {np.mean(bb):+.2%} | 1천만/일 {sum(s) * 1000:+5.0f}만 "
        f"최고5일 빼면 {sum(s[5:]) * 1000:+5.0f}만 낙폭 {mdd:4.0f}만 | 장중 매도 {iw / len(tr):4.0%} (평균 {hm:4.0f}분) 손절 {sw:4.0%}"
        + (f" 깨짐→−4% {br}건" if br else ""))
    return dict(n=len(v), mean=v.mean(), tot=sum(s) * 1000, ex5=sum(s[5:]) * 1000, mdd=mdd, star=star)


COMBOS = [   # (이름, 손절, 방식, 익절)  — 기준선 6개 + 차트 규칙 16개
    ("숫자 −4% · T1 (지금 규칙)", ("pct", 0.04), "t", "T1"),
    ("숫자 −6% · T1", ("pct", 0.06), "t", "T1"),
    ("손절 없음 · T1", None, "t", "T1"),
    ("숫자 −4% · T2 저항 절반", ("pct", 0.04), "t", "T2"),
    ("숫자 −4% · T3 2R+트레일", ("pct", 0.04), "t", "T3"),
    ("숫자 −6% · T3 2R+트레일", ("pct", 0.06), "t", "T3"),
    ("S1 시가구간 저점 터치 · T1", "S1", "t", "T1"),
    ("S1 시가구간 저점 마감 · T1", "S1", "c", "T1"),
    ("S2 전일 종가 터치 · T1", "S2", "t", "T1"),
    ("S2 전일 종가 마감 · T1", "S2", "c", "T1"),
    ("S3 VWAP 마감 · T1", "S3", "c", "T1"),
    ("S4 S1·−6% 가까운 것 터치 · T1", "S4n", "t", "T1"),
    ("S4 S1·−6% 먼 것 터치 · T1", "S4f", "t", "T1"),
    ("S5 매수 뒤 10분 저점 터치 · T1", "S5", "t", "T1"),
    ("S5 매수 뒤 10분 저점 마감 · T1", "S5", "c", "T1"),
    ("S1 마감 · T2 저항 절반", "S1", "c", "T2"),
    ("S3 VWAP 마감 · T2 저항 절반", "S3", "c", "T2"),
    ("S4 먼 것 · T2 저항 절반", "S4f", "t", "T2"),
    ("S1 터치 · T3 2R+트레일", "S1", "t", "T3"),
    ("S1 마감 · T3 2R+트레일", "S1", "c", "T3"),
    ("S4 가까운 것 · T3 2R+트레일", "S4n", "t", "T3"),
    ("S5 터치 · T3 2R+트레일", "S5", "t", "T3"),
]


def prev_regular(c, d):
    """전날 1분봉 정규장 (종가, 고가) — 오늘 1분봉 가격 기준으로 맞춤."""
    p = E.prev_day(d)
    if not p: return None, None
    r = E.regular(E.bars(c, p))
    if len(r) < 30: return None, None
    k = 1.0
    fd, fp = E.factor(c, d), E.factor(c, p)
    if fd and fp and abs(fd / fp - 1) > 0.003: k = fd / fp
    return r[-1][4] * k, max(x[2] for x in r) * k


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    say(f"1️⃣ 후보 {len(sel)}건 {len({r['date'] for r in sel})}일 ({min(r['date'] for r in sel)} ~ {max(r['date'] for r in sel)}), 1분봉 출처 {E.P0}~{E.P1}")
    res = defaultdict(list); miss = defaultdict(int)
    dist = defaultdict(list)
    for r in sel:
        d, c = r["date"], r["code"]
        b = E.regular(E.bars(c, d))
        idx = {x[0]: i for i, x in enumerate(b)}
        if not all(t in idx for t in (time(9, 10), time(9, 11))):
            miss["09:10~11 봉 없음"] += 1; continue
        j = idx[time(9, 11)]; buy = b[j][1]
        pc0 = b[0][1] / (1 + r["gap"])
        if buy / pc0 - 1 >= 0.29:
            miss["상한가 근처"] += 1; continue
        nx = E.next_day_exits(c, d, buy).get("09:00 시가")
        if nx is None:
            miss["다음 날 09:00 없음"] += 1; continue
        pc, ph = prev_regular(c, d)
        if pc is None:
            miss["전날 1분봉 없음 → 일봉 갭으로 전일 종가"] += 1; pc = pc0
        f = E.factor(c, d); h250 = E.hi_n(c, d, 250)
        h52 = h250 * f if (f and h250) else None
        ctx = dict(or_low=min(x[3] for x in b[:j]), pc=pc, ph=ph, h52=h52, vw=vwap_series(b))
        dist["S1"].append(ctx["or_low"] / buy - 1); dist["S2"].append(pc / buy - 1); dist["S3"].append(ctx["vw"][j - 1] / buy - 1)
        if ph: dist["전일고가"].append(ph / buy - 1)
        if h52: dist["52주고가"].append(h52 / buy - 1)
        for name, sk, mode, tg in COMBOS:
            ret, iw, hm, sw, br = sim(b, j, buy, nx, sk, mode, tg, ctx)
            res[name].append((d, ret, iw, hm, sw, br))
    say("빠진 것: " + ", ".join(f"{k} {v}" for k, v in miss.items()))
    say("레벨 위치(매수가 대비, 중앙값 / 매수가 이상=이미 깨짐 비율): " + " | ".join(
        f"{k} {np.median(v):+.1%} ({np.mean(np.array(v) >= -0.005):.0%})" for k, v in dist.items()))
    say(f"\n시험한 조합 {len(COMBOS)}개 (숫자·없음 기준선 6 + 차트 레벨 16). 같은 자료에서 16개를 골라 본 것이라 가장 좋은 하나는 우연으로 좋아 보일 수 있음.")
    say("=" * 150)
    out = {}
    for name, *_ in COMBOS:
        if name == "S1 시가구간 저점 터치 · T1": say("-" * 150)
        out[name] = stats(res[name], name)
    say("\n★ = 앞·뒤 반기 둘 다 + 이고 가장 좋은 5일 빼도 합계 +")
    return out


# ---------------- 디아이 10-28 예시 ----------------
def diai():
    import pickle
    c, d, p = "003160", date(2026, 10, 28), date(2026, 10, 27)
    B = pickle.load(open(os.path.join(E.DATA, "leader_capture", "bars_krx.pkl"), "rb"))
    b = [(x[0].time(), *x[1:]) for x in B[(c, d)] if time(9, 0) <= x[0].time() <= time(15, 30)]
    pb = B.get((c, p))
    if pb is None:
        try:
            from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
            from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
            pb = [(x["ts"], x["open"], x["high"], x["low"], x["close"], x["volume"]) for x in fetch_minute_bars(build_client(), c, p, "KRX")]
        except Exception as e:
            say(f"디아이 전날 1분봉 못 받음: {e}"); pb = []
    pr = [x for x in pb if time(9, 0) <= x[0].time() <= time(15, 30)]
    pc = pr[-1][4] if pr else None; ph = max(x[2] for x in pr) if pr else None
    import duckdb
    dm = duckdb.connect(E._cp("daily_ohlcv.duckdb"), read_only=True)
    h52 = dm.execute("SELECT max(high) FROM daily_ohlcv WHERE code=? AND date < ? AND date >= ?", [c, d, date(2025, 10, 28)]).fetchone()[0]
    idx = {x[0]: i for i, x in enumerate(b)}; j = idx[time(9, 11)]
    for buy in (b[j][1], 42600):
        _diai_one(b, j, buy, pc, ph, h52)


def _diai_one(b, j, buy, pc, ph, h52):
    close = b[-1][4]
    nx = close / buy - 1 - E.COST     # 다음 날 09:00 은 아직 없음 → 오늘 15:30 종가로 대신 표시
    ctx = dict(or_low=min(x[3] for x in b[:j]), pc=pc, ph=ph, h52=h52, vw=vwap_series(b))
    say("\n" + "=" * 150)
    say(f"디아이(003160) 2026-10-28 예시 (KRX 1분봉): 매수가 {'실제 체결 ' if buy == 42600 else '09:11 시가 '} {buy:,.0f}, 정규장 종가 {close:,.0f} ({close / buy - 1:+.1%})")
    say(f"  레벨: S1 시가구간 저점 {ctx['or_low']:,.0f} ({ctx['or_low'] / buy - 1:+.1%}), 전일 종가 {pc:,.0f} ({pc / buy - 1:+.1%}), "
        f"09:11 VWAP {ctx['vw'][j - 1]:,.0f}, 전일 고가 {ph:,.0f} ({ph / buy - 1:+.1%}), 52주 고가(일봉) {h52:,.0f}")
    lo = min(range(j, len(b)), key=lambda k: b[k][3])
    say(f"  장중 최저 {b[lo][3]:,.0f} ({b[lo][0]}, {b[lo][3] / buy - 1:+.1%}), 최고 {max(x[2] for x in b[j:]):,.0f}")
    say("  ※ 다음 날 09:00 시가가 아직 없어 '들고 넘어간 몫'은 오늘 종가로 셈")
    for name, sk, mode, tg in COMBOS:
        ret, iw, hm, sw, br = sim(b, j, buy, nx, sk, mode, tg, ctx)
        say(f"   {name:34s} {ret:+6.1%}  {'손절' if sw else ('장중 매도' if iw >= 1 else ('절반 익절' if iw else '보유'))}"
            + (f" ({hm / iw:.0f}분 뒤)" if iw else "") + (" [깨짐→−4%]" if br else ""))


if __name__ == "__main__":
    main()
    diai()
    F.close()
