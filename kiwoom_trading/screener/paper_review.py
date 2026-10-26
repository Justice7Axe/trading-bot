"""모의투자 하루 복기 — 실제 체결 + 한도로 못 산 신호를 같은 규칙으로 가상 매매해 비교하고 누적한다 (2026-10-20 사용자 요청).

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.paper_review               # 마지막 거래일 복기 (콘솔)
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.paper_review --date 20261019

가상 매매 (paper_trader 와 같은 규칙):
- 신호 봉 다음 1분봉 시가에 매수. 시가가 신호가보다 +1% 넘게 높으면 '추격 안 함'.
- 정규장 신호는 KRX 1분봉, 프리·애프터장 신호는 통합(AL) 1분봉. 정리 시각 15:19 (가상 08:49 / 19:50).
- 매도: 기본 = 신호 손절가 / 추적 = −5%, +5% 뒤 고점 −3% / 목표 = +2% 익절·−2% 손절(햄버거는 전저점 손절) /
  차트 = 큰 음봉(leader_shape.big_red_exit) / 눌림 = 5분선 아래 큰 음봉(pullback_breakout.exit_reason), 손절가 공통.
- 손절가는 1분봉 저가로 판정한다(실전은 15초마다 현재가). 비용 0.25%.
1분봉은 20:00 업데이트가 저장한 감시 종목 1분봉(daily_ohlcv.duckdb minute_ohlcv, 모의투자 종목 포함)을 쓴다.
09:15 시장 분위기(대금 상위 200 중앙 전일 대비)도 함께 기록한다. 1년 분석: +1.5%↑ 면 강한 상승장 정밀도 73%,
그러나 그 뒤 종가까지는 평균 −0.2% 안팎이고 대형주 +2% 매매는 분위기와 상관없이 −0.2~−0.4% → 아직 분위기별 매매 방식 근거 없음, 쌓아서 본다.
품질 필터에 걸린 🎯 신호(buy_signals.alerted = false)도 기본 매도로 가상 매매해 status='filtered' 로 쌓는다.
10-19 검증: 실제 체결 23건을 거의 같게 재현 (예: 삼성바이오로직스 실제 +2.46% / 가상 +2.30%).
"""
import argparse
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.screener.contra_close import KIND as CONTRA_KIND
from kiwoom_trading.screener.closing_rebreak import KIND as REBREAK_KIND
from kiwoom_trading.screener.danswer_close import KIND as DANSWER_KIND
from kiwoom_trading.screener.resistance_retest import RETEST_KIND
from kiwoom_trading.screener.regime_plays import BLOCK_KIND, NEWHIGH_KIND, UP_KIND
from kiwoom_trading.screener.trend_hold import KIND as TREND_KIND
from kiwoom_trading.screener.inverse_gap import WEAK_KIND
from kiwoom_trading.screener.hamburger_watch import KIND as BURGER_KIND
from kiwoom_trading.screener.leader_shape import big_red_exit
from kiwoom_trading.execution.paper import COST, KIND_LIMIT, MAX_CHASE, MAX_POSITIONS, STRONG_STOP, TRAIL_GAP, TRAIL_START
from kiwoom_trading.screener.pullback_breakout import exit_reason as pullback_exit
from kiwoom_trading.screener.store import ScreenerStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_review (
    date      DATE,
    id        VARCHAR,
    code      VARCHAR,
    name      VARCHAR,
    kind      VARCHAR,
    mode      VARCHAR,
    status    VARCHAR,     -- 실제 기록 상태 (closed / skipped ...)
    skip_why  VARCHAR,
    virtual   BOOLEAN,     -- 프리·애프터장
    signal_ts TIMESTAMP,
    buy_ts    TIMESTAMP,
    sell_ts   TIMESTAMP,
    actual    DOUBLE,      -- 실제 수익률 (비용 뺌)
    sim       DOUBLE,      -- 가상 매매 수익률 (비용 뺌)
    sim_why   VARCHAR,
    PRIMARY KEY (date, id)
);
"""


def _bars(conn, code: str, day: date, exchange: str) -> list[dict]:
    return [dict(ts=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in conn.execute(
        "SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code = ? AND exchange = ? AND ts::DATE = ? ORDER BY ts",
        [code, exchange, day]).fetchall()]


def simulate(bars: list[dict], signal_ts: datetime, signal_price: float, stop: float, mode: str,
             end: time, chart_exit: bool, keep_stop: bool = False) -> Optional[dict]:
    """신호 하나를 가상 매매. 반환: {ret, why, buy_ts, sell_ts} 또는 None(봉 없음)."""
    k0 = next((i for i, b in enumerate(bars) if b["ts"] > signal_ts and b["ts"].time() <= end), None)
    if k0 is None:
        return None
    buy, buy_ts = bars[k0]["open"], bars[k0]["ts"]
    if signal_price and buy > signal_price * (1 + MAX_CHASE):
        return dict(ret=None, why="추격 안 함", buy_ts=None, sell_ts=None)
    if mode == "추적":
        stop = buy * (1 - STRONG_STOP)
    elif mode == "목표" and not keep_stop:    # 🎯 대형주 수급 −2% (🍔 햄버거는 신호의 전저점 손절을 그대로)
        stop = buy * 0.98
    peak = buy
    last = bars[k0]
    for j in range(k0, len(bars)):
        b = bars[j]
        if b["ts"].time() > end:
            break
        last = b
        if stop and b["low"] <= stop:
            trailing = mode == "추적" and stop > buy * (1 - STRONG_STOP) + 1e-9
            return dict(ret=min(b["open"], stop) / buy - 1 - COST, why="고점 대비 -3%" if trailing else "손절", buy_ts=buy_ts, sell_ts=b["ts"])
        if mode == "목표" and b["high"] >= buy * 1.02:
            return dict(ret=max(0.02, b["open"] / buy - 1) - COST, why="목표 +2%", buy_ts=buy_ts, sell_ts=b["ts"])
        peak = max(peak, b["high"])
        if mode == "추적" and peak >= buy * (1 + TRAIL_START):
            stop = max(stop, peak * (1 - TRAIL_GAP))
        if chart_exit and mode in ("차트", "눌림") and j + 1 < len(bars) and bars[j + 1]["ts"].time() <= end:
            why = pullback_exit(bars[:j + 1], buy_ts) if mode == "눌림" else big_red_exit(bars[:j + 1], buy_ts)
            if why:
                return dict(ret=bars[j + 1]["open"] / buy - 1 - COST, why="큰 음봉", buy_ts=buy_ts, sell_ts=bars[j + 1]["ts"])
    return dict(ret=last["close"] / buy - 1 - COST, why="시간 정리", buy_ts=buy_ts, sell_ts=last["ts"])


def filter_category(why: Optional[str]) -> str:
    why = why or ""
    return ("하락 차트(시가 아래)" if "시가" in why and "아래" in why else "깊은 눌림" if "깊은 눌림" in why
            else "박스 짧음" if "박스" in why else "깨진 지지선" if "깨졌던" in why else "허용 시간 밖" if "시간" in why
            else "같은 자리 손절 반복" if "손절" in why else "기타")


def review(store: ScreenerStore, day: date, daily_path: str = DEFAULT_DB_PATH) -> int:
    """그날 모의투자 신호 전부를 가상 매매해 paper_review 에 저장. 반환: 저장 건수."""
    conn = store.conn
    conn.execute(SCHEMA)
    trades = conn.execute("""SELECT id, code, name, kind, mode, status, note, signal_ts, signal_price, stop, virtual,
                                    buy_price, sell_price FROM paper_trades WHERE date = ? ORDER BY signal_ts""", [day]).fetchall()
    d = duckdb.connect(daily_path, read_only=True)
    cache: dict = {}
    rows = []
    try:
        for tid, code, name, kind, mode, status, note, sig_ts, sig_price, stop, virtual, bp, sp in trades:
            if sig_ts is None or kind in (CONTRA_KIND, RETEST_KIND, UP_KIND, BLOCK_KIND, NEWHIGH_KIND, TREND_KIND, WEAK_KIND, REBREAK_KIND, DANSWER_KIND):   # 다음 날 09:00 에 파는 신호('다음날' 매도)는 당일 가상 매매에서 뺀다
                continue
            ext = virtual or not (time(9, 0) <= sig_ts.time() < time(15, 30))
            ex = "AL" if ext else "KRX"
            if (code, ex) not in cache:
                cache[(code, ex)] = _bars(d, code, day, ex)
            end = (time(8, 49) if sig_ts.time() < time(9, 0) else time(19, 50)) if ext else time(15, 19)
            s = simulate(cache[(code, ex)], sig_ts, sig_price, stop or 0, mode, end, chart_exit=not ext,
                         keep_stop=kind == BURGER_KIND and bool(stop)) or {}
            actual = sp / bp - 1 - COST if status == "closed" and bp and sp else None
            why = note if status == "skipped" else None
            rows.append((day, tid, code, name, kind, mode, status, why, bool(ext), sig_ts, s.get("buy_ts"), s.get("sell_ts"),
                         actual, s.get("ret"), s.get("why")))
        # 품질 필터에 걸려 모의투자로 넘어가지 않은 🎯 신호도 '기본' 매도(신호 손절가·15:19)로 가상 매매 (status='filtered')
        for code, name, ts, kind, price, stop, why in conn.execute(
                "SELECT code, name, ts, kind, price, stop, reject_reason FROM buy_signals WHERE date = ? AND NOT alerted ORDER BY ts", [day]).fetchall():
            ext = not (time(9, 0) <= ts.time() < time(15, 30))
            ex = "AL" if ext else "KRX"
            if (code, ex) not in cache:
                cache[(code, ex)] = _bars(d, code, day, ex)
            sim = simulate(cache[(code, ex)], ts, price, stop or 0, "기본", time(19, 50) if ext else time(15, 19), False) or {}
            rows.append((day, f"F-{ts:%H%M%S}-{code}-{kind}", code, name, kind, "기본", "filtered", filter_category(why), bool(ext), ts,
                         sim.get("buy_ts"), sim.get("sell_ts"), None, sim.get("ret"), sim.get("why")))
    finally:
        d.close()
    conn.execute("DELETE FROM paper_review WHERE date = ?", [day])
    if rows:
        conn.executemany("INSERT INTO paper_review VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    logging.info("모의투자 복기 %s: %s건", day, len(rows))
    return len(rows)


REGIME_STRONG = 0.015   # 09:15 대금 상위 200 중앙 전일 대비 +1.5%↑ → 강한 상승장 판정 (1년: 정밀도 73%, 강한 상승장 63% 포착)


_STOCKS: set = set()


def morning_regime(store: ScreenerStore, day: date, at: time = time(9, 15), daily_path: str = DEFAULT_DB_PATH) -> Optional[float]:
    """그날 at 시각 직후 KRX 대금 상위 200 스냅샷(스캐너가 매분 저장) 중 주식만의 전일 대비 등락 중앙값.
    ETF(인버스·레버리지 포함)를 빼야 한다: 10-16 09:30 전체 +1.5% / 주식만 +2.5%."""
    if not _STOCKS:
        d = duckdb.connect(daily_path, read_only=True)
        try:
            _STOCKS.update(r[0] for r in d.execute("SELECT code FROM stocks").fetchall())
        finally:
            d.close()
    ts = store.conn.execute("SELECT min(ts) FROM rank_snapshots WHERE date = ? AND source = 'value_krx' AND ts::TIME >= ?",
                            [day, at]).fetchone()[0]
    if ts is None:
        return None
    xs = sorted(r[1] for r in store.conn.execute("SELECT code, change_rate FROM rank_snapshots WHERE ts = ? AND source = 'value_krx'",
                                                 [ts]).fetchall() if r[0] in _STOCKS and r[1] is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def regime_label(x: float) -> str:
    return "강한 상승장" if x >= REGIME_STRONG else "상승" if x >= 0.005 else "보합" if x > -0.005 else "하락" if x > -REGIME_STRONG else "강한 하락장"


def _portfolio(rows: list, limit: int, kind_limit: dict) -> tuple[int, float, Counter]:
    """정규장 가상 매매를 신호 시각 순으로 담는다 (같은 종목 동시 보유 금지, 건당 100만 원)."""
    held, pnl, kinds = [], 0.0, Counter()
    for code, kind, buy_ts, sell_ts, ret in sorted(rows, key=lambda r: r[2]):
        held = [h for h in held if h[2] > buy_ts]
        if len(held) >= limit or any(h[0] == code for h in held):
            continue
        cap = kind_limit.get(kind)
        if cap is not None and sum(1 for h in held if h[1] == kind) >= cap:
            continue
        held.append((code, kind, sell_ts))
        pnl += ret * 1_000_000
        kinds[kind] += 1
    return sum(kinds.values()), pnl, kinds


def build_review(store: ScreenerStore, day: date, daily_path: str = DEFAULT_DB_PATH) -> str:
    conn = store.conn
    conn.execute(SCHEMA)
    rows = conn.execute("""SELECT code, kind, status, skip_why, virtual, actual, sim, sim_why, buy_ts, sell_ts
                           FROM paper_review WHERE date = ? AND status <> 'filtered'""", [day]).fetchall()
    filtered = conn.execute("SELECT skip_why, sim FROM paper_review WHERE date = ? AND status = 'filtered' AND sim IS NOT NULL", [day]).fetchall()
    if not rows:
        return f"🔁 {day:%m-%d} 모의투자 복기: 신호 없음"
    d = duckdb.connect(daily_path, read_only=True)
    try:
        mkt = d.execute("""WITH r AS (SELECT code, date, close, value, lag(close) OVER (PARTITION BY code ORDER BY date) pc FROM daily_ohlcv
                                      WHERE date <= ? AND date >= ?::DATE - 10)
                           SELECT median(close / pc - 1), avg((close > pc)::INT) FROM r
                           WHERE date = ? AND code IN (SELECT code FROM daily_ohlcv WHERE date = ? ORDER BY value DESC LIMIT 200)""",
                        [day, day, day, day]).fetchone()
    finally:
        d.close()
    pct = lambda xs: f"{sum(xs) / len(xs):+.2%}" if xs else "-"
    win = lambda xs: f"{sum(1 for x in xs if x > 0) / len(xs):.0%}" if xs else "-"
    closed = [r[5] for r in rows if r[2] == "closed" and r[5] is not None]
    limited = [r for r in rows if r[2] == "skipped" and r[3] and ("최대" in r[3] or "동시" in r[3])]
    lim_sim = [r[6] for r in limited if r[6] is not None]
    lines = [f"🔁 {day:%m-%d} 모의투자 복기 — 한도로 못 산 신호까지 같은 규칙으로 가상 매매 (비용 0.25% 뺌)"]
    regime = morning_regime(store, day)
    if mkt and mkt[0] is not None:
        lines.append(f"시장: 대금 상위 200 중앙 {mkt[0]:+.1%}, {mkt[1]:.0%} 상승"
                     + (f" | 09:15 분위기: 중앙 {regime:+.1%} → {regime_label(regime)}" if regime is not None else ""))
    lines.append(f"실제 체결 {len(closed)}건 {pct(closed)} (승률 {win(closed)}) | 한도로 건너뜀 {len(limited)}건 → 가상 {pct(lim_sim)} (승률 {win(lim_sim)})")
    down = [r[6] for r in rows if r[2] == "skipped" and r[3] and "강한 하락장" in r[3] and r[6] is not None]
    if down:
        lines.append(f"🧯 강한 하락장이라 안 산 신호 {len(down)}건 → 가상 {pct(down)} (승률 {win(down)}) — 플러스면 보수적 매매가 손해, 마이너스면 손실을 막은 것")
    notup = [r[6] for r in rows if r[2] == "skipped" and r[3] and "강한 상승장 아님" in r[3] and r[6] is not None]
    if notup:
        lines.append(f"📈 강한 상승장이 아니라 안 산 차트 신호 {len(notup)}건 → 가상 {pct(notup)} (승률 {win(notup)}) — 마이너스면 규칙이 손실을 막은 것")
    if filtered:
        fg = defaultdict(list)
        for why, sim in filtered:
            fg[why].append(sim)
        fs = [x for _, x in filtered]
        lines.append(f"품질 필터에 걸린 신호 {len(fs)}건 → 가상 {pct(fs)} (승률 {win(fs)}): "
                     + " · ".join(f"{k} {len(v)}건 {pct(v)}" for k, v in sorted(fg.items(), key=lambda x: -len(x[1]))))
    by = defaultdict(list)
    for r in rows:
        if r[6] is not None:
            by[r[1]].append(r[6])
    lines.append("신호 종류별 (전체 가상): " + " · ".join(f"{k} {len(v)}건 {pct(v)}" for k, v in sorted(by.items(), key=lambda x: -len(x[1]))))
    reg = [(r[0], r[1], r[8], r[9], r[6]) for r in rows if r[6] is not None and not r[4] and r[8] and r[9]]
    if reg:
        parts = []
        for label, lim, kl in ((f"지금 규칙({MAX_POSITIONS}종목)", MAX_POSITIONS, KIND_LIMIT), (f"{MAX_POSITIONS * 2}종목", MAX_POSITIONS * 2, KIND_LIMIT),
                               ("무제한", 10 ** 6, {})):
            n, pnl, _ = _portfolio(reg, lim, kl)
            parts.append(f"{label} {n}건 {pnl / 1e4:+,.0f}만 원")
        lines.append("보유 한도별 (정규장, 건당 100만 원): " + " / ".join(parts))
    # 누적
    days = conn.execute("SELECT count(DISTINCT date) FROM paper_review").fetchone()[0]
    acc = conn.execute("""SELECT kind, count(*), avg(sim), avg((sim > 0)::INT) FROM paper_review WHERE sim IS NOT NULL AND status <> 'filtered'
                          GROUP BY kind ORDER BY count(*) DESC""").fetchall()
    facc = conn.execute("""SELECT count(*), avg(sim), count(DISTINCT date) FROM paper_review WHERE sim IS NOT NULL AND status = 'filtered'""").fetchone()
    lines.append(f"누적 {days}일 (가상 매매 기준): " + " · ".join(f"{k} {n}건 {a:+.2%} 승률 {w:.0%}" for k, n, a, w in acc))
    if facc and facc[0]:
        lines.append(f"누적 품질 필터 탈락 {facc[0]}건 {facc[1]:+.2%} ({facc[2]}일) — 필터가 거르는 신호가 통과 신호보다 나쁜지 확인용")
    by_regime = defaultdict(list)
    for (dd,) in conn.execute("SELECT DISTINCT date FROM paper_review").fetchall():
        rg = morning_regime(store, dd)
        if rg is None:
            continue
        by_regime[regime_label(rg)] += [r[0] for r in conn.execute(
            "SELECT sim FROM paper_review WHERE date = ? AND sim IS NOT NULL AND status <> 'filtered'", [dd]).fetchall()]
    if by_regime:
        lines.append("누적 09:15 분위기별 (가상 매매): " + " · ".join(f"{k} {len(v)}건 {pct(v)}" for k, v in by_regime.items()))
    lines.append("⚠️ 하루 결과는 시장 분위기에 크게 좌우된다. 신호 규칙 판단은 누적과 1년 검증으로 한다.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="모의투자 하루 복기 (한도로 못 산 신호 가상 매매 포함)")
    parser.add_argument("--date", help="YYYYMMDD (없으면 모의투자 마지막 날)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = ScreenerStore()
    try:
        day = (datetime.strptime(args.date, "%Y%m%d").date() if args.date else
               store.conn.execute("SELECT max(date) FROM paper_trades").fetchone()[0])
        review(store, day)
        print(build_review(store, day))
    finally:
        store.close()


if __name__ == "__main__":
    main()
