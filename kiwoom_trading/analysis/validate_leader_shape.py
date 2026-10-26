"""🎯 주도주 모양(screener/leader_shape.py) 1년 검증 — data/minute_history.duckdb (통합 AL 1분봉).

표본 (선택 편향 없이):
- 날짜 D 에는 **전날(D-1) 전 종목 대금 순위 상위 N(기본 200)** 종목만 쓴다.
- minute_history 의 D 종목에는 'D 의 대금 상위 200' 도 섞여 있다. 장 마감 뒤에야 아는 목록이라 쓰면 결과가 부푼다.
- 장중 대금 순위: 표본 종목 안에서 매분 누적 대금(가격 × 거래량)으로 직접 매긴다.
  실전은 KRX 전 종목 순위라, 전날 상위 밖에서 새로 뜬 종목은 이 검증에 없다.

판정·매도: 실전과 같은 함수(leader_shape.features / failed / stop_price), 09:30~10:30 매분, 종목당 첫 통과 → 다음 봉 시가 매수.
매도 비교: 반반(+2% 절반, 나머지 손절·15:19) / 15:19 보유(손절 없음) / 15:19 보유(−3% 손절). 비용 0.25%.
시장 상태: 판정 시각에 표본 종목 중 시가 위에 있는 비율(넓게 오르는 날인지)로 나눠 본다.

    .venv\\Scripts\\python.exe -m kiwoom_trading.analysis.validate_leader_shape [--top 200] [--since 2025-10-15]
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
from kiwoom_trading.strategies.leader_shape.live import LeaderShapeConfig, big_red_exit, failed, features, stop_price

COST = 0.0025


def _copy(path: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), f"vls_{os.getpid()}_" + os.path.basename(path))
    shutil.copy(path, dst)
    return dst


def simulate(bars: list[dict], k: int, stop: float, mode: str) -> tuple[float, str]:
    """bars[k] 시가 매수 → (수익률, 사유). mode: '차트'(큰 음봉, 실전) | '반반' | '보유' | '보유3'"""
    buy = bars[k]["open"]
    if mode == "보유3":
        stop = buy * 0.97
    elif mode == "보유":
        stop = 0
    half = None
    buy_ts = bars[k]["ts"]
    for j in range(k, len(bars)):
        b = bars[j]
        if b["low"] <= stop:
            px = min(b["open"], stop)
            return ((half or px) + px) / 2 / buy - 1 - COST if mode == "반반" else px / buy - 1 - COST, "손절"
        if mode == "반반" and half is None and b["high"] >= buy * 1.02:
            half = max(b["open"], buy * 1.02)
        if mode == "차트" and j + 1 < len(bars) and big_red_exit(bars[:j + 1], buy_ts):
            return bars[j + 1]["open"] / buy - 1 - COST, "큰 음봉"
    last = bars[-1]["close"]
    return ((half or last) + last) / 2 / buy - 1 - COST if mode == "반반" else last / buy - 1 - COST, "마감"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--since", default="2025-10-15")
    ap.add_argument("--db", default="", help="1분봉 DB 경로 (백필이 실행 중이면 원본이 잠겨 있으니 복사본을 지정)")
    a = ap.parse_args()
    cfg = LeaderShapeConfig()
    m = duckdb.connect(a.db or _copy(os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")), read_only=True)
    dm = duckdb.connect(_copy(os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")), read_only=True)
    days = [r[0] for r in m.execute("SELECT DISTINCT ts::date FROM minute_ohlcv WHERE ts::date >= ? ORDER BY 1",
                                    [date.fromisoformat(a.since)]).fetchall()]
    all_days = [r[0] for r in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    names = dict(dm.execute("SELECT code, name FROM stocks").fetchall())
    trades = []
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
        cum = {}
        for code, bars in by.items():
            acc, ts, cs = 0.0, [], []
            for b in bars:
                acc += b["volume"] * (b["high"] + b["low"] + b["close"]) / 3
                ts.append(b["ts"]); cs.append(acc)
            cum[code] = (ts, cs)

        def cum_at(code: str, t: datetime) -> float:
            ts, cs = cum[code]
            j = bisect.bisect_left(ts, t) - 1
            return cs[j] if j >= 0 else 0.0

        tsl = {c: [b["ts"] for b in bars] for c, bars in by.items()}
        minutes = sorted({b["ts"] for bars in by.values() for b in bars if cfg.start <= b["ts"].time() <= cfg.end})
        done: set[str] = set()
        for t in minutes:
            vals = sorted(((cum_at(c, t), c) for c in by), reverse=True)
            rank = {c: i + 1 for i, (_, c) in enumerate(vals)}
            above_open = None
            for code, bars in by.items():
                if code in done or rank[code] > cfg.max_rank:
                    continue
                k = bisect.bisect_left(tsl[code], t)
                if k >= len(bars):
                    continue
                f = features(bars[:k], universe[code])
                if f is None or failed(f, rank[code], cfg):
                    continue
                done.add(code)
                if above_open is None:
                    ups = [1 for c2, b2 in by.items() if (j := bisect.bisect_left(tsl[c2], t)) > 0 and b2[j - 1]["close"] > b2[0]["open"]]
                    above_open = len(ups) / len(by)
                stop = stop_price(f["price"], f["low10"], cfg)
                row = dict(date=d, code=code, name=names.get(code, code), t=bars[k]["ts"].time(), rank=rank[code],
                           breadth=above_open, chg=f["chg"])
                for mode in ("차트", "반반", "보유", "보유3"):
                    row[mode] = simulate(bars, k, stop, mode)[0]
                trades.append(row)
    if not trades:
        print("매매 없음")
        return
    half = days[len(days) // 2]

    def show(label: str, xs: list[dict]) -> None:
        if not xs:
            print(f"  {label:28} 0건")
            return
        parts = []
        for mode in ("차트", "반반", "보유", "보유3"):
            r = sorted(x[mode] for x in xs)
            n = len(r)
            tr = r[n // 20:n - n // 20] or r
            f = [x[mode] for x in xs if x["date"] < half]
            b = [x[mode] for x in xs if x["date"] >= half]
            parts.append(f"{mode} {sum(r) / n:+.2%}(양끝뺀 {sum(tr) / len(tr):+.2%}, 승 {sum(1 for v in r if v > 0) / n:.0%}, "
                         f"앞 {sum(f) / max(len(f), 1):+.2%} 뒤 {sum(b) / max(len(b), 1):+.2%})")
        print(f"  {label:28} {len(xs):4}건 {len({x['date'] for x in xs}):3}일 | " + " | ".join(parts))

    print(f"주도주 모양 검증 {days[0]}~{days[-1]} ({len(days)}일), 전날 대금 상위 {a.top}, 앞/뒤 나눔 {half}")
    show("전체", trades)
    for lo, hi in ((0, 0.4), (0.4, 0.6), (0.6, 1.01)):
        show(f"판정 때 표본 {lo:.0%}~{min(hi, 1):.0%} 가 시가 위", [x for x in trades if lo <= x["breadth"] < hi])
    for lo, hi in ((0, 30), (30, 60), (60, 101)):
        show(f"장중 대금 순위 {lo + 1}~{hi - 1 if hi > 100 else hi}위", [x for x in trades if lo < x["rank"] <= hi])
    for lo, hi in ((time(9, 30), time(9, 45)), (time(9, 45), time(10, 0)), (time(10, 0), time(10, 31))):
        show(f"매수 {lo:%H:%M}~{hi:%H:%M}", [x for x in trades if lo <= x["t"] < hi])
    per_day = defaultdict(list)
    for x in trades:
        per_day[x["date"]].append(x["반반"])
    print(f"  하루 평균 {len(trades) / len(per_day):.1f}건, 반반 기준 플러스인 날 {sum(1 for v in per_day.values() if sum(v) > 0)}/{len(per_day)}")


if __name__ == "__main__":
    main()
