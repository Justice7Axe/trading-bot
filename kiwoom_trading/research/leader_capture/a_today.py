"""A — 2026-10-28 주도 16종목 시각표 + 같은 조건에 걸린 다른 종목(가짜 후보) 비교, B(실제) — '추격 안 함' 건너뛴 신호의 결과,
C 보조 — 장 초 대금 상위 진입 종목이 그날 최종 대금 200위 안에 남는 비율(1분봉 자료 한계 재기).

자료: data/screener_snapshot.duckdb (rank_snapshots value_krx 1분마다 KRX 대금 상위 200, search_day 조회 순위, buy_signals, paper_trades …),
      data/leader_capture/bars_krx.pkl (fetch_today.py 로 받은 KRX 1분봉), data/daily_ohlcv.duckdb (전날 대금 순위·20일 평균 대금).
'처음 든 시각에 샀다면' = 그 스냅숏 가격에 매수 → 종가(15:30 정규장 마지막 봉), 장중 최대 상승 = 그 뒤 1분봉 고가 최대. 비용 0.25% 뺌.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_capture.a_today → data/leader_capture/a_today.txt
"""
import os, pickle, sys
from collections import defaultdict
from datetime import date, time

import duckdb
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(ROOT, "data", "leader_capture")
D = date(2026, 10, 28)
COST = 0.0025
GROUPS = [("로봇", [("460940", "피앤에스로보틱스"), ("030530", "원익홀딩스"), ("125490", "한라캐스트"), ("277810", "레인보우로보틱스")]),
          ("광통신", [("069540", "빛과전자"), ("072950", "빛샘전자"), ("010170", "대한광통신"), ("218410", "RFHIC")]),
          ("반도체", [("179880", "멜콘"), ("195870", "해성디에스"), ("059090", "미코"), ("003160", "디아이")]),
          ("보안", [("443670", "에스피소프트"), ("263860", "지니언스"), ("053800", "안랩"), ("356680", "엑스게이트")])]
TARGETS = {c: n for _, g in GROUPS for c, n in g}
F = open(os.path.join(OUT, "a_today.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def hm(ts):
    return ts.strftime("%H:%M") if ts else "  -  "


def pct(x, f="+.0%"):
    return format(x, f) if x is not None else "-"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = duckdb.connect(os.path.join(ROOT, "data", "screener_snapshot.duckdb"), read_only=True)
    dm = duckdb.connect(os.path.join(ROOT, "data", "daily_ohlcv.duckdb"), read_only=True)
    BARS = pickle.load(open(os.path.join(OUT, "bars_krx.pkl"), "rb"))
    stocks = {c: n for c, n in dm.execute("SELECT code, name FROM stocks").fetchall()}

    def ok(c):
        return c in stocks and c[-1] not in "579K" and "스팩" not in stocks[c]

    cal = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]

    def prev_rank(d):
        p = max(x for x in cal if x < d)
        rows = dm.execute("SELECT d.code, d.value FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date=? AND d.value>0 "
                          "ORDER BY d.value DESC", [p]).fetchall()
        return {c: i + 1 for i, (c, _) in enumerate(rows)}, p

    PR, pday = prev_rank(D)
    avg20 = dict(dm.execute("""SELECT code, avg(value) FROM (SELECT code, value, row_number() OVER (PARTITION BY code ORDER BY date DESC) rn
                               FROM daily_ohlcv WHERE date < ?) WHERE rn <= 20 GROUP BY 1""", [D]).fetchall())

    def reg(c, d=D):
        return [x for x in BARS.get((c, d), []) if time(9, 0) <= x[0].time() <= time(15, 30)]

    def close_of(c, d=D):
        b = reg(c, d)
        return b[-1][4] if b else None

    def after_max(c, ts, d=D):
        b = [x for x in reg(c, d) if x[0] >= ts.replace(second=0, microsecond=0)]
        return max(x[2] for x in b) if b else None

    snaps = s.execute("SELECT ts, source, rank, code, change_rate, price, trade_value FROM rank_snapshots WHERE date=? ORDER BY ts", [D]).fetchall()
    vk = [r for r in snaps if r[1] == "value_krx" and r[0].time() >= time(9, 0)]
    first = defaultdict(dict)   # code -> {N: (ts, price, chg, rank)}
    for ts, src, rk, c, chg, px, tv in vk:
        for N in (200, 40, 20):
            if rk <= N and N not in first[c]:
                first[c][N] = (ts, px, chg, rk)
    for ts, src, rk, c, chg, px, tv in snaps:
        if src == "search_day" and rk <= 20 and "S20" not in first[c] and ts.time() >= time(8, 0):
            first[c]["S20"] = (ts, px, chg, rk)
    at = {}
    for T in (time(9, 5), time(9, 10)):
        tsT = min({r[0] for r in vk if r[0].time() >= T})
        at[T] = {r[3]: (r[2], r[4], r[6]) for r in vk if r[0] == tsT}
    sig = defaultdict(list)
    for c, ts, kind in s.execute("SELECT code, ts, kind FROM buy_signals WHERE date=? ORDER BY ts", [D]).fetchall():
        sig[c].append((ts, kind))
    alert = defaultdict(list)
    for q in ("SELECT code, ts, 'early:' || source FROM early_alerts WHERE date=?",
              "SELECT code, ts, 'watch:' || source FROM watch_adds WHERE date=?",
              "SELECT code, ts, 'theme:' || label FROM theme_alerts WHERE date=?",
              "SELECT code, ts, 'surge:' || label FROM surge_groups WHERE date=?"):
        for c, ts, k in s.execute(q, [D]).fetchall():
            alert[c].append((ts, k))
    trades = defaultdict(list)
    for c, kind, st, bts, bp, sts, sp, note in s.execute(
            "SELECT code, kind, status, buy_ts, buy_price, sell_ts, sell_price, note FROM paper_trades WHERE date=? ORDER BY signal_ts", [D]).fetchall():
        trades[c].append((kind, st, bts, bp, sts, sp, (note or "")[:40]))

    # ------------------------------------------------------------ A. 시각표
    say(f"A. 2026-10-28 주도 16종목 시각표 (전날 = {pday}, 전날 순위는 일봉 대금 전 종목 / 장중은 KRX 대금 상위 200 스냅숏 1분마다)")
    say("열: 전날순위 | 200위 처음(시각 등락) | 40위 처음 | 20위 처음 | 조회20 처음 | 09:05 순위/등락 | 09:10 순위/등락 | 첫 매수신호 | 첫 포착알림 | 고가시각(고가등락) | 종가등락")
    rows16 = []
    for gname, g in GROUPS:
        say(f"\n[{gname}]")
        for c, n in g:
            b = reg(c)
            pc = None
            f = first.get(c, {})
            for N in (200, 40, 20, "S20"):   # 전일 종가 = 스냅숏 가격 ÷ (1+등락)
                if N in f and f[N][1] and f[N][2] is not None:
                    pc = f[N][1] / (1 + f[N][2]); break
            if pc is None:
                r = dm.execute("SELECT close FROM daily_ohlcv WHERE code=? AND date=?", [c, pday]).fetchone()
                pc = r and r[0]
            hi = max(b, key=lambda x: x[2]) if b else None
            cl = b[-1][4] if b else None

            def cell(N):
                return f"{hm(f[N][0])} {f[N][2]:+.0%}" if N in f else "   -      "
            a5 = at[time(9, 5)].get(c); a10 = at[time(9, 10)].get(c)
            sg = sig.get(c, [])
            al = sorted(alert.get(c, []))
            s5 = f"{a5[0]}위 {a5[1]:+.0%}" if a5 else "200밖"
            s10 = f"{a10[0]}위 {a10[1]:+.0%}" if a10 else "200밖"
            sgs = f"{hm(sg[0][0])} {sg[0][1]}" if sg else "없음"
            als = f"{hm(al[0][0])} {al[0][1][:24]}" if al else "없음"
            his = f"{hm(hi[0])} {hi[2] / pc - 1:+.0%}" if hi and pc else "-"
            say(f" {n[:8]:8s} 전날 {PR.get(c, 9999):4d}위 | 200 {cell(200)} | 40 {cell(40)} | 20 {cell(20)} | 조회 {cell('S20')} | "
                f"09:05 {s5:9s} | 09:10 {s10:9s} | 신호 {sgs:14s} | 알림 {als:30s} | 고가 {his} | 종가 {pct(cl / pc - 1 if cl and pc else None, '+.1%')}")
            for t in trades.get(c, []):
                say(f"      모의: {t[0]} {t[1]} 매수 {hm(t[2])} {t[3] or ''} 매도 {hm(t[4])} {t[5] or ''} {t[6]}")
            rows16.append((c, n, f, pc, cl))

    say("\n'처음 든 시각에 샀다면' (스냅숏 가격 매수, 비용 0.25%): 종목 시각 종가까지/그 뒤 장중 최대 상승")
    for N, nm in ((200, "대금 200위"), (40, "대금 40위"), (20, "대금 20위"), ("S20", "조회 20위")):
        parts, rr = [], []
        for c, n, f, pc, cl in rows16:
            if N in f and cl and f[N][1]:
                px = f[N][1]; mx = after_max(c, f[N][0])
                parts.append(f"{n[:5]} {hm(f[N][0])} {cl / px - 1 - COST:+.0%}/{(mx / px - 1) if mx else 0:+.0%}")
                rr.append(cl / px - 1 - COST)
        say(f" {nm} ({len(rr)}종목, 종가까지 평균 {np.mean(rr):+.1%}): " + " · ".join(parts))

    # ------------------------------------------------------------ 가짜 후보
    say("\n" + "=" * 110)
    say("같은 조건에 처음 걸린 종목 전체 (09:00~10:30 에 처음 든 것, 주식만·우선주·스팩 제외) — 16종목 vs 나머지")
    say("수익 = 처음 든 스냅숏 가격 매수 → 종가 (비용 뺌), 최대 = 그 뒤 장중 고가")
    say("=" * 110)

    def fmt(L):
        if not L:
            return "0개"
        r = [x[3] for x in L]
        return (f"{len(L):3d}개 종가까지 평균 {np.mean(r):+.1%} 중앙 {np.median(r):+.1%} +5%↑ {np.mean([x >= 0.05 for x in r]):.0%} "
                f"손실 {np.mean([x < 0 for x in r]):.0%} 최대상승 평균 {np.mean([x[4] for x in L]):+.1%}")
    for N, nm in ((200, "대금 200위"), (40, "대금 40위"), (20, "대금 20위"), ("S20", "조회 20위")):
        for outside, on in ((None, "전체"), (True, "전날 200위 밖만")):
            res = []
            for c, f in first.items():
                if N not in f or not ok(c):
                    continue
                ts, px, chg, rk = f[N]
                if not (time(9, 0) <= ts.time() <= time(10, 30)) or not px:
                    continue
                if outside and PR.get(c, 9999) <= 200:
                    continue
                cl = close_of(c); mx = after_max(c, ts)
                if not cl or not mx:
                    continue
                res.append((c, ts, chg, cl / px - 1 - COST, mx / px - 1))
            if not res:
                continue
            tg = [r for r in res if r[0] in TARGETS]; ot = [r for r in res if r[0] not in TARGETS]
            say(f"\n {nm} · {on}: 처음 든 종목 {len(res)}개 (16종목 중 {len(tg)}개)")
            say(f"   16종목  {fmt(tg)}")
            say(f"   나머지  {fmt(ot)}")
            for lo, hi in ((-1, 0.05), (0.05, 0.10), (0.10, 1)):
                L = [r for r in res if lo <= (r[2] or 0) < hi]
                if L:
                    say(f"     진입 때 등락 {lo:+.0%}~{hi:+.0%}: {fmt(L)} (16종목 {sum(r[0] in TARGETS for r in L)})")

    # ------------------------------------------------------------ B 실제. 추격 안 함
    say("\n" + "=" * 110)
    say("B(실제). '추격 안 함' 으로 건너뛴 모의 신호 전부 (snapshot 10-12 ~ 10-28) — KRX 1분봉")
    say("건너뛸 때 현재가에 샀다면 → 그날 종가, 장중 최대, −4% 손절 닿았나, 1️⃣식(−4%·다음 날 09:00 시가)")
    say("=" * 110)
    sdays = sorted({d for (d,) in s.execute("SELECT DISTINCT date FROM rank_snapshots").fetchall()})
    nxt = {d: sdays[i + 1] for i, d in enumerate(sdays[:-1])}
    rets = []
    for d, c, n, kind, sts, spx, note in s.execute("SELECT date, code, name, kind, signal_ts, signal_price, note FROM paper_trades "
                                                   "WHERE note LIKE '%추격%' ORDER BY date, signal_ts").fetchall():
        try:
            now = float(note.split("현재가 ")[1].split("원")[0].replace(",", ""))
        except Exception:
            now = None
        b = reg(c, d)
        if not b:
            say(f" {d} {n} 1분봉 없음"); continue
        cl = b[-1][4]
        after = [x for x in b if x[0] > sts]
        buy = now or spx
        stop_hit = next((x for x in after if x[3] <= buy * 0.96), None)
        no = None
        if d in nxt:
            nb = [x for x in BARS.get((c, nxt[d]), []) if x[0].time() >= time(9, 0)]
            no = nb[0][1] if nb else None
        r4 = (-0.04 - COST) if stop_hit else ((no / buy - 1 - COST) if no else None)
        mx = max(x[2] for x in after) if after else buy
        r4s = f"{r4:+.1%}" if r4 is not None else "다음날 아직"
        say(f" {d} {sts:%H:%M} {n[:8]:8s} [{kind}] 신호가 {spx:,.0f} 현재가 {buy:,.0f} ({buy / spx - 1:+.1%}) | 종가 {cl:,.0f}: 신호가 대비 {cl / spx - 1:+.1%}, "
            f"현재가 대비 {cl / buy - 1:+.1%} | 그 뒤 최대 {mx / buy - 1:+.1%} | −4% {'닿음 ' + hm(stop_hit[0]) if stop_hit else '안 닿음'} | 1️⃣식 {r4s}")
        rets.append((d, cl / buy - 1 - COST, r4))
    r4v = [r[2] for r in rets if r[2] is not None]
    say(f" → 현재가에 샀다면 종가까지 평균 {np.mean([r[1] for r in rets]):+.2%} ({len(rets)}건, 종가 + {sum(r[1] > 0 for r in rets)}건); "
        f"−4%·다음 날 09:00 확정 {len(r4v)}건 평균 {np.mean(r4v) if r4v else 0:+.2%} 합계 {sum(r4v):+.1%}")

    # ------------------------------------------------------------ C 보조. 자료 한계 재기
    say("\n" + "=" * 110)
    say("C 한계 재기 — 전날 200위 밖 종목이 09:01~09:30 에 KRX 대금 상위 N 에 처음 들었고 그때 등락 +5%↑ → 그날 마지막 스냅숏에도 200위 안에 남았나")
    say("(minute_history 는 그날 최종 대금 200위 안 종목만 있음 → 남지 못한 비율만큼 C 백테스트에서 빠진다. KRX 순위 vs 일봉 통합 대금이라 근사)")
    say("=" * 110)
    for N in (20, 40, 100):
        tot = kept = 0
        lost = []
        for d in sdays:
            try:
                pr, _ = prev_rank(d)
            except ValueError:
                continue
            rs = s.execute("SELECT ts, rank, code, change_rate, price FROM rank_snapshots WHERE date=? AND source='value_krx' "
                           "AND ts::time BETWEEN '09:00' AND '15:35' ORDER BY ts", [d]).fetchall()
            if not rs:
                continue
            lastts = max(r[0] for r in rs)
            final = {r[2] for r in rs if r[0] == lastts}
            seen = set()
            for ts, rk, c, chg, px in rs:
                if ts.time() < time(9, 1) or ts.time() > time(9, 30) or rk > N or c in seen or not ok(c):
                    continue
                seen.add(c)
                if pr.get(c, 9999) <= 200 or (chg or 0) < 0.05:
                    continue
                tot += 1; kept += c in final
                if c not in final:
                    lost.append(f"{d:%m-%d} {stocks.get(c, c)[:6]}")
        say(f" 상위 {N:3d} 진입 & +5%↑: {tot}건 중 마지막까지 200위 안 {kept}건 ({kept / max(tot, 1):.0%}) — 빠지는 예: {', '.join(lost[:6])}")
    say("\n오늘 16종목의 C 조건 값 (09:30 까지 KRX 대금 상위 40 에 처음 든 때, 그때 누적 대금 ÷ 20일 평균 하루 대금(통합), 등락):")
    for c, n in TARGETS.items():
        hit = None
        for ts, src, rk, cc, chg, px, tv in vk:
            if cc == c and rk <= 40 and ts.time() <= time(9, 30):
                hit = (ts, rk, chg, (tv or 0) / (avg20.get(c) or 1e18)); break
        say(f"  {n[:8]:8s} 전날 {PR.get(c, 9999):4d}위 → " + (f"{hm(hit[0])} {hit[1]}위 등락 {hit[2]:+.1%} 누적대금 {hit[3]:.2f}배" if hit else "09:30 까지 40위 안 못 듦"))
    F.close()


if __name__ == "__main__":
    main()
