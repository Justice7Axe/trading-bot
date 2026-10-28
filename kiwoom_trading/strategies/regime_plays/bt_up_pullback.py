"""1️⃣ 상승장 장 초 — 09:11 시가 대신 '눌림'에서 사면 나은가 (2026-10-28 사용자: "이전 고점의 1/2 지점이라던가").

후보·유니버스·자료는 bt_up_chart_exits.py 와 똑같이 (u_cands.pkl, 강한 상승장 U 날 09:10 대금 40위·시가 위·전날 외인·기관 둘 다 − 제외,
상한가 근처·09:10~11 봉 없음·다음 날 09:00 없음 제외 → 619건). 1분봉 = engine (원가격, AL 통합). 일봉 수정주가 안 씀.
매수 방식:
  B0 09:11 봉 시가 (지금)
  B1 되돌림 지정가: O = 09:00 시가, H = 그 봉 직전까지 고가(매 분 갱신, 미래 정보 없음), L = H − r×(H−O).
     창(09:11~10:30 / 11:30) 안 봉 저가 ≤ L 이면 L 체결 (봉 시가가 이미 L 아래면 시가).
  B2 같은 L 에 닿은 뒤(L·H 는 닿은 순간 고정) 1분봉 종가 > L 이고 고가 > 직전 봉 고가 → 다음 봉 시가 매수 (확인 봉이 창 안).
  B3 09:10 에 시가 < 전날 고가(1분봉 정규장) < 09:10 종가 이면, 09:11~10:30 에 전날 고가까지 눌릴 때 그 가격 체결.
손절: −4% / −6% / 눌림 저점 (B1·B3 = 레벨 × 0.99, B2 = 닿은 뒤 확인까지 최저가). 체결 봉부터 확인 (레벨을 지나야 저가에 가므로).
매도: 손절 닿으면 그 가격(시가가 이미 아래면 시가), 아니면 다음 날 09:00 시가. 비용 0.25%. 체결가 상한가 근처(+29%↑) 못 삼.
하루 1천만 원 = 그날 산 종목 수로 나눔 (못 산 돈은 0). ★ = 앞·뒤 반기 둘 다 + 이고 가장 좋은 5일 빼도 +.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.regime_plays.bt_up_pullback → data/backtest/up_pullback.txt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "backtest"); os.makedirs(OUT, exist_ok=True)
UNTIL = time(15, 19)
F = open(os.path.join(OUT, "up_pullback.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def prev_regular(c, d):
    """전날 1분봉 정규장 (종가, 고가) — 오늘 1분봉 가격 기준으로 맞춤 (bt_up_chart_exits 와 같음)."""
    p = E.prev_day(d)
    if not p: return None, None
    r = E.regular(E.bars(c, p))
    if len(r) < 30: return None, None
    k = 1.0
    fd, fp = E.factor(c, d), E.factor(c, p)
    if fd and fp and abs(fd / fp - 1) > 0.003: k = fd / fp
    return r[-1][4] * k, max(x[2] for x in r) * k


def fill_b1(b, r, t_end, start=time(9, 11)):
    """→ (봉 인덱스, 체결가, 레벨, H) 또는 None."""
    O = b[0][1]; H = None
    for k, x in enumerate(b):
        t, o, h, l = x[:4]
        if t >= start:
            if t > t_end: return None
            L = H - r * (H - O)
            if l <= L:
                return k, min(o, L), L, H
        H = h if H is None else max(H, h)
    return None


def fill_b2(b, r, t_end):
    """닿은 뒤 반등 확인 → 다음 봉 시가. → (봉 인덱스, 체결가, 레벨, 눌림 저점) 또는 None."""
    O = b[0][1]; H = None; L = None; low = None; k1 = None
    for k, x in enumerate(b):
        t, o, h, l, c = x[:5]
        if t >= time(9, 11):
            if t > t_end: return None
            if L is None:
                Lc = H - r * (H - O)
                if l <= Lc:
                    L, low, k1 = Lc, l, k
            else:
                low = min(low, l)
            if L is not None and k > k1 and c > L and h > b[k - 1][2]:
                if k + 1 < len(b) and b[k + 1][0] <= UNTIL:
                    return k + 1, b[k + 1][1], L, low
                return None
        H = h if H is None else max(H, h)
    return None


def fill_b3(b, ph, j10, t_end):
    O = b[0][1]; c10 = b[j10][4]
    if ph is None or not (O < ph < c10): return None
    for k, x in enumerate(b):
        t, o, h, l = x[:4]
        if t < time(9, 11): continue
        if t > t_end: return None
        if l <= ph: return k, min(o, ph), ph, None
    return None


def exit_ret(b, k, fill, stop_px, nxt_open):
    if stop_px is not None and stop_px >= fill * 0.995:
        stop_px = fill * 0.96
    if stop_px is not None:
        for x in b[k:]:
            t, o, h, l = x[:4]
            if t > UNTIL: break
            if l <= stop_px:
                return min(o, stop_px) / fill - 1 - E.COST, 1
    return nxt_open / fill - 1 - E.COST, 0


def stats(tr, title):
    """tr = [(date, ret, stopped)]."""
    if len(tr) < 5:
        say(f"   {title:30s} {len(tr)}건 (적음)"); return None
    ds = sorted({x[0] for x in tr}); h = ds[len(ds) // 2]
    v = np.array([x[1] for x in tr]); a = [x[1] for x in tr if x[0] < h]; bb = [x[1] for x in tr if x[0] >= h]
    bd = defaultdict(list)
    for x in tr: bd[x[0]].append(x[1])
    dr = {d: np.mean(x) for d, x in bd.items()}
    s = sorted(dr.values(), reverse=True)
    eq = np.cumsum([dr[d] for d in sorted(dr)]) * 1000
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    return dict(n=len(v), days=len(dr), mean=v.mean(), a=np.mean(a), b=np.mean(bb), tot=sum(s) * 1000, ex5=sum(s[5:]) * 1000,
                mdd=mdd, star=star, stop=np.mean([x[2] for x in tr]))


COMBOS = [  # (이름, 방식, r, 창 끝, 손절)  'pb' = 눌림 저점
    ("B0 09:11 시가 −4% (지금)", "B0", None, None, 0.04),
    ("B0 09:11 시가 −6%", "B0", None, None, 0.06),
    ("B0 09:11 시가 손절 없음", "B0", None, None, None),
    ("B1 1/3 ~10:30 −4%", "B1", 1 / 3, time(10, 30), 0.04),
    ("B1 1/3 ~10:30 −6%", "B1", 1 / 3, time(10, 30), 0.06),
    ("B1 1/3 ~10:30 눌림저점", "B1", 1 / 3, time(10, 30), "pb"),
    ("B1 1/2 ~10:30 −4%", "B1", 0.5, time(10, 30), 0.04),
    ("B1 1/2 ~10:30 −6%", "B1", 0.5, time(10, 30), 0.06),
    ("B1 1/2 ~10:30 눌림저점", "B1", 0.5, time(10, 30), "pb"),
    ("B1 0.618 ~10:30 −4%", "B1", 0.618, time(10, 30), 0.04),
    ("B1 0.618 ~10:30 −6%", "B1", 0.618, time(10, 30), 0.06),
    ("B1 0.618 ~10:30 눌림저점", "B1", 0.618, time(10, 30), "pb"),
    ("B1 1/2 ~11:30 −4%", "B1", 0.5, time(11, 30), 0.04),
    ("B1 1/2 ~11:30 −6%", "B1", 0.5, time(11, 30), 0.06),
    ("B2 1/2 확인 ~10:30 −4%", "B2", 0.5, time(10, 30), 0.04),
    ("B2 1/2 확인 ~10:30 −6%", "B2", 0.5, time(10, 30), 0.06),
    ("B2 1/2 확인 ~10:30 눌림저점", "B2", 0.5, time(10, 30), "pb"),
    ("B3 전날고가 ~10:30 −4%", "B3", None, time(10, 30), 0.04),
    ("B3 전날고가 ~10:30 −6%", "B3", None, time(10, 30), 0.06),
    ("B3 전날고가 ~10:30 눌림저점", "B3", None, time(10, 30), "pb"),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    say(f"1️⃣ 후보 {len(sel)}건 {len({r['date'] for r in sel})}일, 1분봉 출처 {E.P0}~{E.P1}")
    miss = defaultdict(int)
    res = defaultdict(list)          # 이름 → [(date, ret, stopped)]
    filled = defaultdict(set)        # 이름 → 체결된 후보 키
    b0ret = {}                       # 후보 키 → B0 −4% 수익률
    fillinfo = defaultdict(list)     # 이름 → (체결가/09:11시가 −1, 체결 분)
    keys = []
    for r in sel:
        d, c = r["date"], r["code"]
        if not E.is_common(c) and not os.environ.get("KEEP_PREF"): miss["우선주"] += 1; continue   # KEEP_PREF=1 → 기준선(619건) 맞추기용
        b = E.regular(E.bars(c, d))
        idx = {x[0]: i for i, x in enumerate(b)}
        if not all(t in idx for t in (time(9, 10), time(9, 11))):
            miss["09:10~11 봉 없음"] += 1; continue
        j = idx[time(9, 11)]; buy0 = b[j][1]
        pc0 = b[0][1] / (1 + r["gap"])
        if buy0 / pc0 - 1 >= 0.29:
            miss["상한가 근처"] += 1; continue
        nx = E.next_day_exits(c, d, buy0).get("09:00 시가")
        if nx is None:
            miss["다음 날 09:00 없음"] += 1; continue
        nxt_open = (nx + E.COST + 1) * buy0
        pc, ph = prev_regular(c, d)
        key = (d, c); keys.append(key)
        for name, kind, rr, tend, st in COMBOS:
            if kind == "B0":
                f = (j, buy0, None, None)
            elif kind == "B1":
                f = fill_b1(b, rr, tend)
            elif kind == "B2":
                f = fill_b2(b, rr, tend)
            else:
                f = fill_b3(b, ph, idx[time(9, 10)], tend)
            if f is None: continue
            k, px, L, low = f
            if px / pc0 - 1 >= 0.29: continue
            if st is None: sp = None
            elif st == "pb": sp = low if kind == "B2" else L * 0.99
            else: sp = px * (1 - st)
            ret, stp = exit_ret(b, k, px, sp, nxt_open)
            res[name].append((d, ret, stp)); filled[name].add(key)
            fillinfo[name].append((px / buy0 - 1, (b[k][0].hour - 9) * 60 + b[k][0].minute))
            if name.startswith("B0 09:11 시가 −4%"): b0ret[key] = ret
    say("빠진 것: " + ", ".join(f"{k} {v}" for k, v in miss.items()) + f" → 남은 후보 {len(keys)}건")
    say(f"\n시험한 조합 {len(COMBOS)}개 (B0 기준 3 + 눌림 17). 같은 자료에서 17개를 골라 본 것이라 가장 좋은 하나는 우연으로 좋아 보일 수 있음.")
    say("1천만/일 = 그날 산 종목에만 나눔 (그날 하나도 못 사면 0). '산 것 B0' = 체결된 종목을 09:11 에 −4% 로 샀다면, '놓친 것 B0' = 체결 안 된 종목의 B0 −4%.")
    say("=" * 170)
    say(f"   {'조합':30s} {'체결':>9s} {'건당':>7s} {'앞':>7s} {'뒤':>7s} {'1천만/일':>8s} {'최고5일빼면':>9s} {'낙폭':>6s} {'손절':>4s} | "
        f"{'산 것 B0':>8s} {'놓친 것 B0':>10s} {'놓친 B0 합(건당×건)':>14s} | 체결가 vs 09:11시가 · 체결 시각 중앙")
    for name, kind, *_ in COMBOS:
        s = stats(res[name], name)
        if s is None: continue
        fk = filled[name]
        fb = [b0ret[k] for k in keys if k in fk and k in b0ret]
        mb = [b0ret[k] for k in keys if k not in fk and k in b0ret]
        fi = fillinfo[name]
        disc = np.median([x[0] for x in fi]); tm = int(np.median([x[1] for x in fi]))
        say(f" {s['star']} {name:30s} {s['n']:3d}/{len(keys)} {s['n'] / len(keys):4.0%} {s['mean']:+.2%} {s['a']:+.2%} {s['b']:+.2%} "
            f"{s['tot']:+7.0f}만 {s['ex5']:+8.0f}만 {s['mdd']:5.0f}만 {s['stop']:4.0%} | "
            f"{(np.mean(fb) if fb else 0):+8.2%} {(np.mean(mb) if mb else 0):+10.2%} {(sum(mb) * 100 if mb else 0):+12.0f}%p | "
            f"{disc:+.1%} · {9 + tm // 60:02d}:{tm % 60:02d} ({s['days']}일)")
    say("\n★ = 앞·뒤 반기 둘 다 + 이고 가장 좋은 5일 빼도 합계 +")


def today_examples():
    say("\n" + "=" * 170)
    say("오늘(2026-10-28) 예시 — KRX 1분봉 (data/leader_capture/bars_krx.pkl), B1 1/2 지정가. 다음 날 09:00 없음 → 오늘 정규장 종가로 표시")
    B = pickle.load(open(os.path.join(E.DATA, "leader_capture", "bars_krx.pkl"), "rb"))
    d = date(2026, 10, 28)
    for c, nm in (("003160", "디아이"), ("069540", "빛과전자"), ("010170", "대한광통신"), ("253590", "네오셈")):
        raw = B.get((c, d))
        if not raw: say(f"  {nm}({c}) 1분봉 없음"); continue
        b = [(x[0].time(), *x[1:]) for x in raw if time(9, 0) <= x[0].time() <= time(15, 30)]
        idx = {x[0]: i for i, x in enumerate(b)}
        if time(9, 11) not in idx: say(f"  {nm}({c}) 09:11 봉 없음"); continue
        j = idx[time(9, 11)]; buy0 = b[j][1]; close = b[-1][4]
        h910 = max(x[2] for x in b[:j]); O = b[0][1]
        lo = min(range(j, len(b)), key=lambda k: b[k][3])
        line = (f"  {nm}({c}) 시가 {O:,.0f} 09:10까지 고가 {h910:,.0f} → 09:11 시점 1/2 레벨 {h910 - 0.5 * (h910 - O):,.0f} | "
                f"09:11 시가 {buy0:,.0f} → 종가 {close:,.0f} ({close / buy0 - 1 - E.COST:+.1%}) | 09:11 뒤 최저 {b[lo][3]:,.0f} ({b[lo][0].strftime('%H:%M')})")
        say(line)
        for tend in (time(10, 30), time(11, 30)):
            f = fill_b1(b, 0.5, tend)
            if f is None:
                say(f"     ~{tend.strftime('%H:%M')}: 체결 안 됨"); continue
            k, px, L, H = f
            stop = any(x[3] <= px * 0.96 for x in b[k:] if x[0] <= UNTIL)
            say(f"     ~{tend.strftime('%H:%M')}: {b[k][0].strftime('%H:%M')} 체결 {px:,.0f} (그때 H {H:,.0f}, 09:11 시가 대비 {px / buy0 - 1:+.1%}) "
                f"→ 종가 {close / px - 1 - E.COST:+.1%}" + (" [−4% 손절 닿음]" if stop else ""))


if __name__ == "__main__":
    main()
    today_examples()
    F.close()
