"""🎯 눌림 돌파(screener/pullback_breakout.py) 검증 — data/minute_history.duckdb (통합 AL 1분봉).

표본 (선택 편향 없이, validate_leader_shape 와 같다):
- 날짜 D 에는 **전날(D-1) 전 종목 대금 순위 상위 N(기본 200)** 종목만 쓴다.
- 장중 대금 순위: 표본 종목 안에서 신호 봉까지의 누적 대금으로 직접 매긴다 (실전은 KRX 전 종목 순위).
- 실전은 KRX 1분봉, 여기는 통합(AL) 1분봉이라 봉 모양이 조금 다를 수 있다.

매수·매도: 실전과 같은 scan() — 신호 다음 봉 시가 매수, 큰 음봉 다음 봉 시가 / 손절가 / 15:19 종가 매도, 종목당 하루 3번.
비교: 같은 매수 자리에서 15:19 까지 보유. 비용 0.25%.

    .venv\\Scripts\\python.exe -m kiwoom_trading.analysis.validate_pullback_breakout [--top 200] [--since 2025-10-15] [--db 복사본]
"""
import argparse
import bisect
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import date, datetime, time

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.strategies.pullback_breakout.live import PullbackConfig, scan

COST = 0.0025


def _copy(path: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), f"vpb_{os.getpid()}_" + os.path.basename(path))
    shutil.copy(path, dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--since", default="2025-10-15")
    ap.add_argument("--db", default="", help="1분봉 DB 경로 (백필이 실행 중이면 원본이 잠겨 있으니 복사본을 지정)")
    a = ap.parse_args()
    cfg = PullbackConfig()
    m = duckdb.connect(a.db or _copy(os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")), read_only=True)
    dm = duckdb.connect(_copy(os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")), read_only=True)
    days = [r[0] for r in m.execute("SELECT DISTINCT ts::date FROM minute_ohlcv WHERE ts::date >= ? ORDER BY 1",
                                    [date.fromisoformat(a.since)]).fetchall()]
    all_days = [r[0] for r in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    names = dict(dm.execute("SELECT code, name FROM stocks").fetchall())
    trades = []
    used_days = []
    for d in days:
        prev_day = max(x for x in all_days if x < d)
        universe = {c: pc for c, pc in dm.execute(
            "SELECT code, close FROM (SELECT code, close, rank() OVER (ORDER BY value DESC) rk FROM daily_ohlcv "
            "WHERE date = ? AND value > 0) WHERE rk <= ?", [prev_day, a.top]).fetchall()}
        by = defaultdict(list)
        for r in m.execute("SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE ts::date = ? "
                           "AND ts::time BETWEEN TIME '09:00' AND TIME '15:19' ORDER BY code, ts", [d]).fetchall():
            if r[0] in universe:
                by[r[0]].append(dict(ts=r[1], open=r[2], high=r[3], low=r[4], close=r[5], volume=r[6]))
        if len(by) < 50:
            continue
        used_days.append(d)
        cum = {}
        for code, bars in by.items():
            acc, ts, cs = 0.0, [], []
            for b in bars:
                acc += b["volume"] * b["close"]
                ts.append(b["ts"]); cs.append(acc)
            cum[code] = (ts, cs)

        def cum_at(code: str, t: datetime) -> float:      # t 봉까지 (그 봉 포함) 누적 대금
            ts, cs = cum[code]
            j = bisect.bisect_right(ts, t) - 1
            return cs[j] if j >= 0 else 0.0

        rank_cache: dict[datetime, list[float]] = {}

        def rank_of(code: str, t: datetime) -> int:
            if t not in rank_cache:
                rank_cache[t] = sorted((cum_at(c, t) for c in by), reverse=True)
            mine = cum_at(code, t)
            return sum(1 for v in rank_cache[t] if v > mine) + 1

        for code, bars in by.items():
            rk: dict[datetime, int] = {}

            def rank_ok(t: datetime, code=code, rk=rk) -> bool:
                rk[t] = rank_of(code, t)
                return rk[t] <= cfg.max_rank

            entries, _ = scan(bars, universe[code], cfg, rank_ok)
            bars_f = [b for b in bars if time(9, 0) <= b["ts"].time() <= cfg.exit_at]
            for n, e in enumerate(entries, 1):
                if e["buy"] is None:
                    continue
                buy = bars_f[e["buy"]]["open"]
                if e["sell"] is None:
                    px, why = bars_f[-1]["close"], "마감"
                elif e["why"] == "손절":
                    px, why = min(bars_f[e["sell"]]["open"], e["stop"]), "손절"
                else:
                    px, why = bars_f[e["sell"]]["open"], "큰 음봉"
                sig_ts = bars_f[e["sig"]]["ts"]
                trades.append(dict(date=d, code=code, name=names.get(code, code), t=sig_ts.time(), n=n,
                                   rank=rk.get(sig_ts, 0), why=why,
                                   hold_min=((bars_f[e["sell"]]["ts"] if e["sell"] is not None else bars_f[-1]["ts"])
                                             - bars_f[e["buy"]]["ts"]).total_seconds() / 60,
                                   rule=px / buy - 1 - COST, keep=bars_f[-1]["close"] / buy - 1 - COST))
    if not trades:
        print("매매 없음")
        return
    half = used_days[len(used_days) // 2]

    def show(label: str, xs: list[dict]) -> None:
        if not xs:
            print(f"  {label:22} 0건")
            return
        parts = []
        for mode, name in (("rule", "규칙 매도"), ("keep", "15:19 보유")):
            r = sorted(x[mode] for x in xs)
            n = len(r)
            tr = r[n // 20:n - n // 20] or r
            f = [x[mode] for x in xs if x["date"] < half]
            b = [x[mode] for x in xs if x["date"] >= half]
            parts.append(f"{name} {sum(r) / n:+.2%}(양끝뺀 {sum(tr) / len(tr):+.2%}, 승 {sum(1 for v in r if v > 0) / n:.0%}, "
                         f"앞 {sum(f) / max(len(f), 1):+.2%} 뒤 {sum(b) / max(len(b), 1):+.2%})")
        print(f"  {label:22} {len(xs):5}건 {len({x['date'] for x in xs}):3}일 | " + " | ".join(parts))

    print(f"눌림 돌파 검증 {used_days[0]}~{used_days[-1]} ({len(used_days)}일), 전날 대금 상위 {a.top}, 앞/뒤 나눔 {half}")
    show("전체", trades)
    for k in (1, 2, 3):
        show(f"그날 {k}번째 매수", [x for x in trades if x["n"] == k])
    for w in ("큰 음봉", "손절", "마감"):
        xs = [x for x in trades if x["why"] == w]
        show(f"매도 사유 {w}", xs)
    for lo, hi in ((0, 30), (30, 60), (60, 100)):
        show(f"대금 순위 {lo + 1}~{hi}위", [x for x in trades if lo < x["rank"] <= hi])
    for lo, hi in ((time(9, 3), time(9, 30)), (time(9, 30), time(10, 30)), (time(10, 30), time(12, 0)), (time(12, 0), time(14, 31))):
        show(f"신호 {lo:%H:%M}~{hi:%H:%M}", [x for x in trades if lo <= x["t"] < hi])
    per_day = defaultdict(list)
    for x in trades:
        per_day[x["date"]].append(x["rule"])
    hm = sorted(x["hold_min"] for x in trades)
    print(f"  하루 평균 {len(trades) / len(per_day):.1f}건, 보유 시간 중앙값 {hm[len(hm) // 2]:.0f}분, "
          f"규칙 매도 기준 플러스인 날 {sum(1 for v in per_day.values() if sum(v) > 0)}/{len(per_day)}")


if __name__ == "__main__":
    main()
