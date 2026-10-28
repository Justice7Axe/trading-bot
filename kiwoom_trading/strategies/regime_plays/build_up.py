"""1️⃣ 상승장 장 초 후보 u_cands.pkl 을 원본 자료에서 다시 만든다 (2026-10-27).

원래 만든 곳: 세션 8623875b 의 보조 에이전트가 스크래치에 쓴 u_build.py (파일은 지워졌고 대화 기록에서 원문을 찾아 옮김).
쓰는 곳: kiwoom_trading/backtest/playbook/events_15.py (1️⃣ = 09:10, U 날, 대금 40위 안, 시가 위, 전날 외인·기관 둘 다 − 제외,
         익절 없음 / 손절 −4% → ex[(None, 0.04)]).

무엇을 담나
  강한 상승장 날(09:10 판정 U10 또는 09:05 판정 U05) 마다, 전날 대금 상위 200 주식 중 그날 1분봉이 60개 이상이고 09:01 전에 시작하며
  다음 날 시가가 있고 가격 안 맞는 목록(mismatch)에 없는 종목.
  09:05 / 09:10 / 09:15 / 09:20 각 시각 T 에 그때까지 누적 대금 순위 120위 안이면 한 줄:
    chg 직전 봉 종가 전일 대비, from_open 시가 대비, gap 시가 갭, above 전일 고가 위, vrank 누적 대금 순위, mcap 시총(지금 상장주식 수 × 전일 종가),
    fr·ins 전날 외인·기관 순매수(daily_ohlcv.investor_daily), cval 누적 대금, hi_so_far 그때까지 고가,
    ex[(익절, 손절)] T 봉 시가 매수 → 익절가 닿으면 매도 / 손절가 닿으면 즉시(같은 봉이면 손절 먼저) / 둘 다 아니면 다음 날 시가, 비용 0.25%.
  info[d] = dict(U10, U05, M05, K05z, M0, K1z) — 그 날 판정 값 (U 아닌 날도 담음).

입력 (읽기만): 시장 상황 data/backtest/playbook_rebuilt/regime_feat.pkl·mismatch.pkl (없으면 data/backtest/playbook/ 보존본),
             일봉 스냅샷 data/backtest/playbook/daily_ohlcv_20261025.duckdb, 1분봉 data/minute_history.duckdb,
             지수 data/index.duckdb, 투자자 data/daily_ohlcv.duckdb(investor_daily)
출력: data/backtest/playbook_rebuilt/u_cands.pkl  = (rows, info)
실행: python -m kiwoom_trading.strategies.regime_plays.build_up            (만들고 보존본과 비교)
      python -m kiwoom_trading.strategies.regime_plays.build_up --compare  (비교만)
      python -m kiwoom_trading.strategies.regime_plays.build_up --latest   (보존본 기준 끄고 지금 있는 1분봉 전부)
먼저 python -m kiwoom_trading.backtest.playbook.build_regime 으로 시장 상황 파일을 만들어 둔다.
"""
import os
import pickle
import sys
import time as _clock
from collections import defaultdict
from datetime import datetime, time

import numpy as np

from kiwoom_trading.backtest.playbook.build_regime import (
    DATA, INDEX_DB, MINUTE_DB, PB, SNAP_DAILY, connect_ro, done_filter, out)

INVESTOR_DB = os.path.join(DATA, "daily_ohlcv.duckdb")   # investor_daily 매일 쌓임 (옛 investor_backfill 은 10-13 에 멈춤)
COST = 0.0025
TPS = (0.03, 0.05, 0.07, 0.10, None)
SLS = (0.02, 0.03, 0.04, 0.05)
TIMES = (time(9, 5), time(9, 10), time(9, 15), time(9, 20))


def _load(name):
    p = os.path.join(DATA, "backtest", "playbook_rebuilt", name)
    if not os.path.exists(p):
        p = os.path.join(PB, name)
        print(f"[알림] 다시 만든 {name} 없음 → 보존본 사용", file=sys.stderr)
    return pickle.load(open(p, "rb"))


def exits(H, L, O, e, nopen):
    """매도 격자 {(익절, 손절): 수익률}. H·L·O 는 매수 봉부터 15:19 봉까지."""
    res = {}
    for sl in SLS:
        st = e * (1 - sl)
        hs = np.nonzero(L <= st)[0]
        js = hs[0] if len(hs) else 10 ** 9
        for tp in TPS:
            jt = 10 ** 9
            if tp:
                ht = np.nonzero(H >= e * (1 + tp))[0]
                jt = ht[0] if len(ht) else 10 ** 9
            if js == 10 ** 9 and jt == 10 ** 9:
                px = nopen
            elif js <= jt:
                px = min(O[js], st)
            else:
                px = max(O[jt], e * (1 + tp))
            res[(tp, sl)] = px / e - 1 - COST
    return res


def build():
    feat = _load("regime_feat.pkl")
    BAD = _load("mismatch.pkl")
    m = connect_ro(MINUTE_DB)
    dm = connect_ro(SNAP_DAILY)
    iv = connect_ro(INVESTOR_DB)
    ix = connect_ro(INDEX_DB)
    days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done ORDER BY 1").fetchall()]
    all_days = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    pos = {d: i for i, d in enumerate(all_days)}
    shares = dict(dm.execute("SELECT code, listed_shares FROM stocks").fetchall())
    kmin = defaultdict(dict)
    for ts, c in ix.execute("SELECT ts, close FROM idx_min WHERE code='001'").fetchall():
        kmin[ts.date()][ts.time()] = c
    kclose = dict(ix.execute("SELECT date, close FROM idx_daily WHERE code='001'").fetchall())
    kdays = sorted(kclose)

    rows, dayinfo = [], {}
    for d in days:
        if d not in pos or d not in feat:
            continue
        k = pos[d]
        if k < 10 or k + 1 >= len(all_days):
            continue
        prev, nxt = all_days[k - 1], all_days[k + 1]
        x = feat[d]
        U10 = x["K1z"] >= 1 or x["M0"] >= 0.02
        kp = kclose.get(max([kd for kd in kdays if kd < d], default=None))   # 09:05 판정용 코스피 전일 종가
        k05 = kmin[d].get(time(9, 4)) or kmin[d].get(time(9, 5))
        uni = dm.execute("""SELECT d.code, d.close, d.high FROM daily_ohlcv d JOIN stocks s USING(code)
                            WHERE d.date=? AND d.value IS NOT NULL QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200""", [prev]).fetchall()
        pc = {c: (cl, hi) for c, cl, hi in uni}
        codes = list(pc)
        ph = ",".join("?" * len(codes))
        nopen = dict(dm.execute(f"SELECT code, open FROM daily_ohlcv WHERE date=? AND code IN ({ph})", [nxt, *codes]).fetchall())
        by = defaultdict(list)
        for c, ts, o, h, l, cl, v in m.execute(f"""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL'
                AND ts >= ? AND ts < ? AND code IN ({ph}) AND {done_filter('minute_ohlcv')} ORDER BY code, ts""",
                [datetime.combine(d, time(9, 0)), datetime.combine(d, time(15, 20)), *codes]).fetchall():
            by[c].append((ts.time(), o, h, l, cl, v))
        by = {c: b for c, b in by.items() if len(b) >= 60 and b[0][0] <= time(9, 1) and c in nopen and (c, d) not in BAD}
        if len(by) < 100:
            continue

        def med_at(T):
            v = []
            for c, bs in by.items():
                i = next((i for i, b in enumerate(bs) if b[0] >= T), None)
                if i:
                    v.append(bs[i - 1][4] / pc[c][0] - 1)
            return float(np.median(v))

        M05 = med_at(time(9, 5))
        K05z = (k05 / kp - 1) / x["sd20"] if (k05 and kp and x.get("sd20")) else np.nan
        U05 = (K05z >= 1) or (M05 >= 0.02)
        dayinfo[d] = dict(U10=U10, U05=bool(U05), M05=M05, K05z=K05z, M0=x["M0"], K1z=x["K1z"])
        if not (U10 or U05):
            continue
        flow = {c: (f, i) for c, f, i in iv.execute(
            f"SELECT code, foreign_, institution FROM investor_daily WHERE date=? AND code IN ({ph})", [prev, *codes]).fetchall()}
        for T in TIMES:
            cut = {c: next((i for i, b in enumerate(bs) if b[0] >= T), None) for c, bs in by.items()}
            cut = {c: i for c, i in cut.items() if i}
            cv = {c: sum(b[5] * (b[2] + b[3] + b[4]) / 3 for b in by[c][:i]) for c, i in cut.items()}
            rk = {c: r + 1 for r, c in enumerate(sorted(cv, key=lambda c: -cv[c]))}
            for c, i in cut.items():
                if rk[c] > 120:
                    continue
                bs = by[c]
                cl, hi = pc[c]
                last = bs[i - 1][4]
                e = bs[i][1]
                H = np.array([b[2] for b in bs[i:]])
                L = np.array([b[3] for b in bs[i:]])
                O = np.array([b[1] for b in bs[i:]])
                rows.append(dict(date=d, code=c, T=T, U10=U10, U05=bool(U05), chg=last / cl - 1, from_open=last / bs[0][1] - 1,
                                 gap=bs[0][1] / cl - 1, above=last > hi, vrank=rk[c], mcap=(shares.get(c) or 0) * cl,
                                 fr=flow.get(c, (None, None))[0], ins=flow.get(c, (None, None))[1], cval=cv[c],
                                 hi_so_far=max(b[2] for b in bs[:i]), ex=exits(H, L, O, e, nopen[c])))
    return rows, dayinfo


def _one(rows, feat):
    """events_15.py 의 1️⃣ 필터 그대로 (판정은 regime.py cls 규칙) → {(date, code): 수익률}."""
    from kiwoom_trading.backtest.playbook.build_regime import cls_of
    rows = [r for r in rows if all(abs(v) < 0.4 for v in r["ex"].values())]

    def cls_u(d):
        return d in feat and cls_of(feat[d]) == "U"
    return {(r["date"], r["code"]): r["ex"][(None, 0.04)] for r in rows
            if r["T"] == time(9, 10) and cls_u(r["date"]) and r["vrank"] <= 40 and r["from_open"] > 0
            and r["fr"] is not None and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0)}


def compare():
    o_rows, o_info = pickle.load(open(os.path.join(PB, "u_cands.pkl"), "rb"))
    n_rows, n_info = pickle.load(open(out("u_cands.pkl"), "rb"))
    print(f"\n[u_cands 전체] 보존본 {len(o_rows):,}줄 {len(o_info)}일 · 새로 {len(n_rows):,}줄 {len(n_info)}일")
    ok = {(r["date"], r["code"], r["T"]) for r in o_rows}
    nk = {(r["date"], r["code"], r["T"]) for r in n_rows}
    print(f"  (날짜, 종목, 시각) 같음 {len(ok & nk):,} · 보존본에만 {len(ok - nk)} · 새것에만 {len(nk - ok)}")
    on = {(r["date"], r["code"], r["T"]): r for r in o_rows}
    worst, nd = 0.0, 0
    for r in n_rows:
        o = on.get((r["date"], r["code"], r["T"]))
        if not o:
            continue
        for kx, v in r["ex"].items():
            dv = abs(v - o["ex"][kx])
            worst = max(worst, dv)
            nd += dv > 1e-12
        for f in ("chg", "from_open", "gap", "vrank", "mcap", "cval", "hi_so_far", "above", "fr", "ins"):
            if o[f] != r[f] and not (o[f] is None and r[f] is None):
                nd += 1
    print(f"  같은 줄의 값 차이: 매도 결과 최대 {worst:.3g}, 다른 칸 {nd}")
    same_info = sum(o_info[d] == n_info.get(d) or all(
        (o_info[d][k] == n_info[d][k]) or (isinstance(o_info[d][k], float) and np.isnan(o_info[d][k]) and np.isnan(n_info[d][k]))
        for k in o_info[d]) for d in o_info if d in n_info)
    print(f"  날 정보 같음 {same_info}/{len(o_info)}")
    # 1️⃣ 필터: 보존본 줄은 보존본 판정으로, 새 줄은 다시 만든 판정으로
    a = _one(o_rows, pickle.load(open(os.path.join(PB, "regime_feat.pkl"), "rb")))
    b = _one(n_rows, pickle.load(open(out("regime_feat.pkl"), "rb")))
    both = set(a) & set(b)
    print(f"\n[1️⃣ 필터 통과] 보존본 {len(a)}건 · 새로 {len(b)}건 · (date, code) 같음 {len(both)} "
          f"({len(both) / max(len(set(a) | set(b)), 1) * 100:.2f}%) · 보존본에만 {sorted(set(a) - set(b))[:10]} · 새것에만 {sorted(set(b) - set(a))[:10]}")
    diff = [abs(a[k] - b[k]) for k in both]
    print(f"  ex[(None, 0.04)] 차이 최대 {max(diff) if diff else 0:.3g}, 다른 건 {sum(x > 1e-12 for x in diff)} · "
          f"합계 수익률 보존본 {sum(a.values()):+.4f} / 새로 {sum(b.values()):+.4f}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--compare" not in sys.argv:
        t0 = _clock.time()
        rows, info = build()
        pickle.dump((rows, info), open(out("u_cands.pkl"), "wb"))
        print(f"u_cands: {len(rows):,}줄, {len(info)}일, 걸린 시간 {_clock.time() - t0:.0f}초")
    compare()


if __name__ == "__main__":
    main()
