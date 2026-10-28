"""C — 그날 처음 터진 종목 잡기: 전날 대금 200위 밖 종목이 장 초(09:01~09:30)에 대금 상위 N 안으로 빠르게 들어오는 순간 매수 (2026-10-28).

조건 (그 분 봉이 끝난 시점까지 아는 값만):
  · 전날 대금 순위(일봉, 전 종목) > 200  — 비교용으로 '전날 200위 안' 도 같은 조건으로 따로 본다
  · 09:00 부터 그 분까지 누적 대금(1분봉 거래량 × (고+저+종)/3) 순위 ≤ N  (순위는 1분봉이 있는 종목 안에서 — 아래 한계)
  · 누적 대금 ≥ X × 20일 평균 하루 대금(일봉 value, 전날까지 20일)
  · 전일 대비 ≥ +Y% 이고 < +25% (상한가 근처는 못 산다고 봄)
  처음 조건을 채운 분의 다음 봉 시가에 매수 (매수가 +29%↑면 뺌).
매도: (1) 익절 없음 · −4% 손절 · 아니면 다음 날 09:00 시가   (2) −4% 손절 · 아니면 당일 15:19 봉 종가 (비교용 예외)
비용 0.25%. 우선주·스팩 제외. 시장 분위기는 regime_feat.pkl cls_of (U = 강한 상승장, 09:10 판정).
한계: minute_history 는 (그날 대금 상위 200·전날 200의 다음 날) + kang_minute(장중 +15%↑) 만 있다 → 장 초에 상위 N 에 들었다가
      그날 200위 밖으로 밀려난 종목(대개 실패한 것)이 빠져 결과가 부풀 수 있다. 오늘 스냅숏(rank_snapshots 13일)으로 빠지는 비율을 따로 잰다.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_capture.bt_new_theme → data/leader_capture/bt_new_theme.txt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "leader_capture")
F = open(os.path.join(OUT, "bt_new_theme.txt"), "w", encoding="utf-8")
NS, XS, YS = (20, 40, 100), (0.3, 0.5, 1.0), (0.05, 0.10)
TIMES = [time(9, m) for m in range(1, 31)]


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def stats(tr, title):
    if len(tr) < 8:
        say(f"   {title:46s} {len(tr)}건 (적음)"); return None
    ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; b = [x for d, x in tr if d >= h]
    bd = defaultdict(float)
    for d, x in tr: bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]) * 25
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
    say(f" {star} {title:46s} {len(v):4d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 25만씩 합계 {v.sum() * 25:+5.0f}만 "
        f"최고5일 빼면 {sum(s[5:]) * 25:+5.0f}만 낙폭 {mdd:.0f}만 | 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%}")
    return v.mean()


def build():
    feat = _load("regime_feat.pkl")
    days = [d for d in E.days() if E.next_day(d) and d in feat]
    ev = []   # 한 줄 = (d, U, code, prev_in200, t, rank, cumx, chg, ret_nx, ret_1519)
    for k, d in enumerate(days):
        p = E.prev_day(d)
        dd_p = E.daily_day(p)
        prank = {c: i + 1 for i, (c, _) in enumerate(sorted(((c, r[5] or 0) for c, r in dd_p.items()), key=lambda x: -x[1]))}
        codes = [c for c in E._min_codes(d) if E.is_common(c) and c in dd_p and "스팩" not in (E.NAME.get(c) or "")]
        B = {c: E.regular(b) for c, b in E.load_day(codes, d).items()}
        B = {c: b for c, b in B.items() if len(b) >= 60 and b[0][0] <= time(9, 1)}
        # 누적 대금 표 (09:00 ~ t 봉까지)
        cum = {}
        for c, b in B.items():
            acc, out, i = 0.0, [], 0
            for t in TIMES:
                while i < len(b) and b[i][0] <= t:
                    acc += b[i][5] * (b[i][2] + b[i][3] + b[i][4]) / 3; i += 1
                out.append((acc, b[i - 1][4] if i else None, i))
            cum[c] = out
        ranks = []
        for ti in range(len(TIMES)):
            order = sorted(cum, key=lambda c: -cum[c][ti][0])
            ranks.append({c: r + 1 for r, c in enumerate(order)})
        U = cls_of(feat[d]) == "U"
        for c, b in B.items():
            h = E.hist(c, d, 20)
            if len(h) < 10: continue
            avg = np.mean([x[6] or 0 for x in h])
            f = E.factor(c, d)
            if not avg or not f: continue
            pc = dd_p[c][3] * f
            fired = {}
            for ti, t in enumerate(TIMES):
                acc, last, i = cum[c][ti]
                if not last or i >= len(b): continue
                chg = last / pc - 1
                for N in NS:
                    for X in XS:
                        for Y in YS:
                            key = (N, X, Y)
                            if key in fired: continue
                            if ranks[ti][c] <= N and acc >= X * avg and Y <= chg < 0.25:
                                fired[key] = (ti, i, chg, acc / avg, ranks[ti][c])
            if not fired: continue
            res = {}
            for key, (ti, j, chg, cx, rk) in fired.items():
                if j in res: continue
                buy = b[j][1]
                if buy / pc - 1 >= 0.29: res[j] = None; continue
                sp = buy * 0.96; hit = None
                for x in b[j:]:
                    if x[0] > time(15, 19): break
                    if x[3] <= sp: hit = min(x[1], sp) / buy - 1 - E.COST; break
                last1519 = E.at(b, time(15, 19))
                nx = E.next_day_exits(c, d, buy).get("09:00 시가")
                res[j] = (hit if hit is not None else nx, hit if hit is not None else last1519 / buy - 1 - E.COST)
            for key, (ti, j, chg, cx, rk) in fired.items():
                if res.get(j) is None or res[j][0] is None: continue
                ev.append(dict(d=d, U=U, c=c, out=prank.get(c, 9999) > 200, key=key, t=TIMES[ti], rank=rk, cx=cx, chg=chg,
                               nx=res[j][0], c1519=res[j][1]))
        # 메모리: 지난 날 1분봉 버림
        for kk in [kk for kk in E._bars_cache if kk[1] < p]:
            del E._bars_cache[kk]
        if k % 20 == 0:
            print(f"{d} {len(B)}종목 누적 {len(ev)}줄", flush=True)
    return ev


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pk = os.path.join(OUT, "new_theme_events.pkl")
    if os.path.exists(pk) and "--rebuild" not in sys.argv:
        ev = pickle.load(open(pk, "rb"))
    else:
        ev = build(); pickle.dump(ev, open(pk, "wb"))
    days = sorted({e["d"] for e in ev})
    say(f"C — 전날 대금 200위 밖 → 장 초(09:01~09:30) 대금 상위 N 진입 매수. 기간 {days[0]} ~ {days[-1]}")
    say("격자 N(장중 누적 대금 순위) × X(누적 대금 ÷ 20일 평균 하루 대금) × Y(전일 대비) = 18 조합 × 날 2가지 → 고른 값은 우연일 수 있음")
    say("매도 nx = −4% 손절·아니면 다음 날 09:00 / 1519 = −4% 손절·아니면 당일 15:19 (비교용)\n")
    for grp, gname in ((True, "전날 200위 밖 (새 얼굴)"), (False, "전날 200위 안 (비교)")):
        say("=" * 120); say(f"[{gname}]"); say("=" * 120)
        for U, un in ((True, "강한 상승장 날만"), (None, "모든 날")):
            say(f"\n-- {un}")
            for N in NS:
                for X in XS:
                    for Y in YS:
                        tr = [e for e in ev if e["out"] == grp and e["key"] == (N, X, Y) and (U is None or e["U"])]
                        if not tr:
                            say(f"   N{N} X{X} Y+{Y:.0%} 0건"); continue
                        mt = np.median([e["t"].hour * 60 + e["t"].minute for e in tr]) - 540
                        stats([(e["d"], e["nx"]) for e in tr], f"N≤{N:3d} X≥{X:.1f} Y≥+{Y:.0%} [다음날] (중앙 09:{int(mt):02d})")
                        stats([(e["d"], e["c1519"]) for e in tr], f"N≤{N:3d} X≥{X:.1f} Y≥+{Y:.0%} [15:19]")
    F.close()


if __name__ == "__main__":
    main()
