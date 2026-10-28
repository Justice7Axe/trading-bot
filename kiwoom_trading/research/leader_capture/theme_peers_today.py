"""보조 — 2026-10-28 장 초 상한가 대장(에스피소프트 09:13, 피앤에스로보틱스 09:21)이 나온 순간, 같은 네이버 테마 종목을 샀다면?
(놓친 8종목 중 보안·로봇 종목은 대금 순위로는 늦게 잡혔다 → '대장 상한가 → 같은 테마 짝꿍' 으로 더 일찍 잡을 수 있었나 하루 확인. 1년 검증 아님)

테마 = data/naver_groups.duckdb kind='theme' (지금 목록 — 과거 검증에 쓰면 미래 정보 섞임, 오늘 하루라 근사로만).
매수 = 대장이 그날 최고가(상한가) 처음 닿은 봉의 다음 봉 시가 (KRX 1분봉), 결과 = 종가까지 / 그 뒤 최대. 비용 0.25%.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_capture.theme_peers_today → data/leader_capture/theme_peers_today.txt
"""
import os, pickle, shutil, sys, tempfile
from datetime import date, time

import duckdb
import numpy as np

from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(ROOT, "data", "leader_capture")
PKL = os.path.join(OUT, "bars_krx.pkl")
D = date(2026, 10, 28)
LEADERS = {"443670": "에스피소프트", "460940": "피앤에스로보틱스"}
F = open(os.path.join(OUT, "theme_peers_today.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = os.path.join(tempfile.gettempdir(), "lc_ng.duckdb"); shutil.copy(os.path.join(ROOT, "data", "naver_groups.duckdb"), p)
    ng = duckdb.connect(p, read_only=True)
    dm = duckdb.connect(os.path.join(ROOT, "data", "daily_ohlcv.duckdb"), read_only=True)
    names = dict(dm.execute("SELECT code, name FROM stocks").fetchall())
    prevd = dm.execute("SELECT max(date) FROM daily_ohlcv WHERE date < ?", [D]).fetchone()[0]
    pclose = dict(dm.execute("SELECT code, close FROM daily_ohlcv WHERE date=?", [prevd]).fetchall())
    prank = {c: i + 1 for i, (c,) in enumerate(dm.execute("SELECT code FROM daily_ohlcv d JOIN stocks USING(code) WHERE date=? AND value>0 ORDER BY value DESC", [prevd]).fetchall())}
    BARS = pickle.load(open(PKL, "rb"))
    cl = None
    nd = ng.execute("SELECT max(date) FROM naver_groups WHERE kind='테마'").fetchone()[0]
    say("주의: 전날 종가는 일봉(9-14 부터 통합 20:00 값) → '등락' 은 근사. 결과(종가까지·최대)는 같은 날 1분봉끼리라 정확.")
    for L, ln in LEADERS.items():
        b = [x for x in BARS[(L, D)] if time(9, 0) <= x[0].time() <= time(15, 30)]
        top = max(x[2] for x in b)   # 일봉 전날 종가는 통합(20:00) 값이라 +29.5% 로 못 찾을 수 있음 → 그날 최고가 처음 닿은 봉
        tL = b[next(i for i, x in enumerate(b) if x[2] >= top)][0]
        themes = ng.execute("SELECT DISTINCT no, name FROM naver_groups WHERE kind='테마' AND date=? AND code=?", [nd, L]).fetchall()
        say(f"\n[{ln}] 상한가 {tL:%H:%M} — 네이버 테마 {len(themes)}개")
        for no, tn in themes:
            peers = sorted({c for (c,) in ng.execute("SELECT DISTINCT code FROM naver_groups WHERE kind='테마' AND date=? AND no=?", [nd, no]).fetchall()} - {L})
            for c in peers:
                if (c, D) not in BARS:
                    cl = cl or build_client()
                    try:
                        BARS[(c, D)] = [(x["ts"], x["open"], x["high"], x["low"], x["close"], x["volume"]) for x in fetch_minute_bars(cl, c, D, "KRX")]
                    except Exception as e:
                        say(f"  {c} 받기 실패 {e}"); continue
            pickle.dump(BARS, open(PKL, "wb"))
            rows = []
            for c in peers:
                pb = [x for x in BARS.get((c, D), []) if time(9, 0) <= x[0].time() <= time(15, 30)]
                j = next((i for i, x in enumerate(pb) if x[0] > tL), None)
                if j is None or c not in pclose or not j:
                    continue
                buy = pb[j][1]; ch = pb[j - 1][4] / pclose[c] - 1
                if ch >= 0.28:
                    continue
                r = pb[-1][4] / buy - 1 - 0.0025; mx = max(x[2] for x in pb[j:]) / buy - 1
                rows.append((c, ch, r, mx))
            if not rows:
                continue
            rows.sort(key=lambda x: -x[2])
            say(f"  테마 '{tn}' {len(rows)}종목: 평균 종가까지 {np.mean([x[2] for x in rows]):+.1%}, +5%↑ {sum(x[2] >= 0.05 for x in rows)}개, 손실 {sum(x[2] < 0 for x in rows)}개")
            for c, ch, r, mx in rows[:6]:
                say(f"     {names.get(c, c)[:10]:10s} 전날 {prank.get(c, 9999):4d}위 | 그때 등락 {ch:+5.1%} → 종가까지 {r:+5.1%} 최대 {mx:+5.1%}")
            if len(rows) > 6:
                say(f"     … 맨 아래 {names.get(rows[-1][0], rows[-1][0])[:10]} {rows[-1][2]:+.1%}")
            # 그때 가장 많이 오른 (대장 다음) 종목 1개만 샀다면 / 그때 +0~10% 중 전날 대금 가장 큰 것
            sec = max(rows, key=lambda x: x[1])
            mid = [x for x in rows if 0 <= x[1] < 0.10]
            midb = min(mid, key=lambda x: prank.get(x[0], 9999)) if mid else None
            say(f"     그때 2등(가장 많이 오른) {names.get(sec[0])} {sec[2]:+.1%}" + (f" / 그때 +0~10% 중 전날 대금 1등 {names.get(midb[0])} {midb[2]:+.1%}" if midb else ""))
    F.close()


if __name__ == "__main__":
    main()
