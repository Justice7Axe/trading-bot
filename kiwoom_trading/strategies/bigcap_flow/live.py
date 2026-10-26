"""🎯 대형주 수급 — 전날 시총 상위 100 중 장중 외국인 잠정치가 순매수인 종목을 09:15~10:00 에 사서 +2% 에 판다 (2026-10-19 사용자 결정, 실험용).

배경 (스크래치 bigcap_oc.py / bigcap_tp.py, 시총 상위 100, 1년):
- 시가 전·장 초 가격, 일봉 위치·이평, 1분봉 이평, 전날까지 수급은 '+2% 먼저 닿기'를 가르지 못한다 (구분력 0.42~0.61, 처음 보는 기간에서 모두 손실).
- 당일 외국인·기관 수급만 크게 가른다 (장 마감 확정치: 둘 다 순매수 → 시가→종가 +2.25%, 80% 상승). 장중 잠정치로 얼마나 남는지는 아직 모른다.
  → 아래 규칙을 결과를 보기 전에 고정하고, 매일 20:00 에 대형주 전체를 평가해 쌓는다 (evaluate / summary).

매수 규칙 (고정, 2026-10-19):
- 대상: 전날 시총(종가 × 상장주식수) 상위 100
- 09:15~10:00 사이 외국인 장중 잠정치가 새로 들어올 때마다 (첫 값은 09:20~09:30 무렵):
  외국인 순매수 ≥ 그 시각 KRX 누적 대금의 5% 이고, 현재가 > 시가 → 매수 (종목당 하루 1번, 비율 큰 순서로 하루 3종목까지)
- 10-14~10-16 시험(사흘): 규칙 통과 하루 13.7건, +2% 먼저 49%, 평균 +0.15% (대형주 전체 −0.44%) — 표본 부족
매도: +2% 에 전부 매도, 손절 −2%, 남으면 15:19 정리 (모의투자 mode='목표')
"""
import argparse
import bisect
import logging
import os
import sys
from datetime import date, datetime, time, timedelta
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import KiwoomMarket, RankItem
from kiwoom_trading.screener.store import ScreenerStore

KIND = "대형주 수급"
TOP_CAP = 100
START, END = time(9, 15), time(10, 0)
MIN_FOREIGN_RATIO = 0.05      # 외국인 잠정 순매수 ÷ KRX 누적 대금
TARGET = 0.02                 # +2% 매도
STOP = 0.02                   # −2% 손절
COST = 0.0025
MAX_PER_DAY = 3               # 모의투자 동시 보유 한도를 다른 신호와 나눠 쓰도록 하루 3종목까지 (검증은 20:00 평가가 대형주 전체로 한다)
MIN_DAYS = 15


def big_caps(day: date, db_path: str = DEFAULT_DB_PATH, top: int = TOP_CAP) -> dict[str, tuple[str, float]]:
    """day 전 거래일 시총 상위 N: 코드 → (이름, 전일 종가)."""
    conn = duckdb.connect(db_path, read_only=True)
    try:
        return {c: (n, pc) for c, n, pc in conn.execute("""
            WITH p AS (SELECT max(date) d FROM daily_ohlcv WHERE date < ?)
            SELECT o.code, s.name, o.close FROM daily_ohlcv o JOIN stocks s USING (code), p
            WHERE o.date = p.d AND s.listed_shares > 0 AND o.close > 0
            ORDER BY o.close * s.listed_shares DESC LIMIT ?""", [day, top]).fetchall()}
    finally:
        conn.close()


class BigcapFlowWatcher:
    """스캐너가 저장한 외국인 잠정치(investor_intraday)가 새로 들어오면 대형주를 판정 → 신호 (종목당 하루 1번)."""

    def __init__(self, market: KiwoomMarket, store: ScreenerStore, today: date,
                 caps: Optional[dict[str, tuple[str, float]]] = None, done: Optional[set[str]] = None) -> None:
        self.market = market
        self.store = store
        self.today = today
        self.caps = caps if caps is not None else big_caps(today)
        self.done: set[str] = set(done or ())
        self.last_snapshot: Optional[datetime] = None

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        if not (START <= now.time() <= END):
            return []
        ts = self.store.conn.execute("SELECT max(ts) FROM investor_intraday WHERE date = ? AND investor = 'foreign'",
                                     [self.today]).fetchone()[0]
        if ts is None or ts == self.last_snapshot:
            return []
        self.last_snapshot = ts
        flows = dict(self.store.conn.execute(
            "SELECT code, net_amount FROM investor_intraday WHERE date = ? AND investor = 'foreign' AND ts = ?", [self.today, ts]).fetchall())
        values = {i.code: i.trade_value for i in value_top if i.trade_value}
        out, seen = [], []
        # 외국인 순매수 비율이 큰 종목부터 (모의투자 동시 보유 한도)
        cands = sorted(((flows[c] / values[c], c) for c in self.caps if flows.get(c) and values.get(c)), reverse=True)
        for ratio, code in cands:
            name = self.caps[code][0]
            amt, val = flows[code], values[code]
            if code in self.done or ratio < MIN_FOREIGN_RATIO or len(self.done) >= MAX_PER_DAY:
                continue
            q = self.market.quote(code, integrated=False)
            if not q:
                continue
            seen.append(f"{name} {amt / val:+.0%}")
            if q.price <= q.open:
                continue
            self.done.add(code)
            sig_ts = now.replace(second=0, microsecond=0, tzinfo=None)
            reason = (f"외국인 잠정 {amt / 1e8:+,.0f}억 = 누적 대금의 {amt / val:+.0%} ({ts:%H:%M} 기록) · 시가 대비 {q.price / q.open - 1:+.1%} "
                      f"— 매도: +{TARGET:.0%} 익절 / −{STOP:.0%} 손절, 남으면 15:19")
            out.append((code, name, KIND, Signal(sig_ts, KIND, float(q.price), float(q.open), float(q.price * (1 - STOP)), reason)))
        logging.info("대형주 수급 판정 (외국인 잠정 %s): 순매수 5%%↑ %s → 시가 위 통과 %s", f"{ts:%H:%M}",
                     ", ".join(seen) or "없음", ", ".join(n for _, n, _, _ in out) or "없음")
        return out


# ---------------------------------------------------------------- 매일 20:00 누적 검증 (대형주 전체)
SCHEMA = """
CREATE TABLE IF NOT EXISTS bigcap_flow_eval (
    date        DATE,
    code        VARCHAR,
    name        VARCHAR,
    snap_ts     TIMESTAMP,   -- 09:15~10:00 첫 외국인 잠정치 시각
    foreign_amt BIGINT,
    krx_value   BIGINT,      -- 그 시각 KRX 누적 대금 (rank_snapshots)
    ratio       DOUBLE,      -- foreign_amt / krx_value
    above_open  BOOLEAN,
    inst_amt    BIGINT,      -- 10:00 까지 마지막 기관 잠정치 (참고)
    buy_price   DOUBLE,      -- 잠정치 다음 분 봉 시가 (통합 1분봉)
    hit_first   VARCHAR,     -- 'tp' | 'sl' | 'none'
    ret         DOUBLE,      -- +2%/−2%/15:19, 비용 전
    mfe         DOUBLE,
    rule        BOOLEAN,     -- 고정 규칙 통과 (ratio ≥ 5% & 시가 위)
    PRIMARY KEY (date, code)
);
"""


def _outcome(bars: list[dict], buy_ts: datetime) -> Optional[tuple[float, str, float, float]]:
    post = [b for b in bars if buy_ts <= b["ts"] and b["ts"].time() <= time(15, 19)]
    if not post:
        return None
    buy = post[0]["open"]
    mfe = max(b["high"] for b in post) / buy - 1
    for b in post:
        if b["low"] <= buy * (1 - STOP):
            return buy, "sl", -STOP if b["open"] > buy * (1 - STOP) else b["open"] / buy - 1, mfe
        if b["high"] >= buy * (1 + TARGET):
            return buy, "tp", TARGET if b["open"] < buy * (1 + TARGET) else b["open"] / buy - 1, mfe
    return buy, "none", post[-1]["close"] / buy - 1, mfe


def evaluate(store: ScreenerStore, client, day: date, daily_path: str = DEFAULT_DB_PATH) -> int:
    conn = store.conn
    conn.execute(SCHEMA)
    snap = conn.execute("""SELECT min(ts) FROM investor_intraday WHERE date = ? AND investor = 'foreign'
                           AND ts::TIME BETWEEN ? AND ?""", [day, START, END]).fetchone()[0]
    if snap is None:
        logging.info("대형주 수급 평가 %s: 09:15~10:00 외국인 잠정치 없음", day)
        return 0
    flows = dict(conn.execute("SELECT code, net_amount FROM investor_intraday WHERE date = ? AND investor = 'foreign' AND ts = ?",
                              [day, snap]).fetchall())
    inst_ts = conn.execute("""SELECT max(ts) FROM investor_intraday WHERE date = ? AND investor = 'institution'
                              AND ts::TIME <= ?""", [day, END]).fetchone()[0]
    inst = dict(conn.execute("SELECT code, net_amount FROM investor_intraday WHERE date = ? AND investor = 'institution' AND ts = ?",
                             [day, inst_ts]).fetchall()) if inst_ts else {}
    rank_ts = conn.execute("SELECT max(ts) FROM rank_snapshots WHERE date = ? AND source = 'value_krx' AND ts <= ?",
                           [day, snap]).fetchone()[0]
    ranks = {c: v for c, v in conn.execute("SELECT code, trade_value FROM rank_snapshots WHERE source = 'value_krx' AND ts = ?",
                                           [rank_ts]).fetchall()} if rank_ts else {}
    buy_ts = snap.replace(second=0, microsecond=0) + timedelta(minutes=1)
    conn.execute("DELETE FROM bigcap_flow_eval WHERE date = ?", [day])
    n = 0
    for code, (name, _) in big_caps(day, daily_path).items():
        try:
            bars = fetch_minute_bars(client, code, day, "AL")
        except Exception as exc:
            logging.warning("대형주 수급 평가 1분봉 실패 %s: %s", code, exc)
            continue
        regular = [b for b in bars if b["ts"].time() >= time(9, 0)]
        res = _outcome(regular, buy_ts)
        if not regular or res is None:
            continue
        buy, hit, ret, mfe = res
        i = bisect.bisect_left([b["ts"] for b in regular], buy_ts) - 1
        above = i >= 0 and regular[i]["close"] > regular[0]["open"]
        amt, val = flows.get(code, 0), ranks.get(code)
        ratio = amt / val if val else None
        conn.execute("INSERT INTO bigcap_flow_eval VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            day, code, name, snap, amt, val, ratio, above, inst.get(code), buy, hit, ret, mfe,
            bool(ratio is not None and ratio >= MIN_FOREIGN_RATIO and above)])
        n += 1
    logging.info("대형주 수급 평가 %s: %s종목 (외국인 잠정 %s)", day, n, f"{snap:%H:%M}")
    return n


def summary(store: ScreenerStore) -> str:
    conn = store.conn
    conn.execute(SCHEMA)
    days = conn.execute("SELECT count(DISTINCT date) FROM bigcap_flow_eval").fetchone()[0]
    if not days:
        return "🎯 대형주 수급 누적 검증: 아직 평가된 날 없음"

    def row(where: str, label: str) -> str:
        n, tp, avg, hit2 = conn.execute(f"""SELECT count(*), avg((hit_first = 'tp')::INT), avg(ret), avg((mfe >= {TARGET})::INT)
                                            FROM bigcap_flow_eval WHERE {where}""").fetchone()
        if not n:
            return f"  {label}: 0건"
        return f"  {label}: {n}건 (하루 {n / days:.1f}) · +2% 먼저 {tp:.0%} · 평균 {avg - COST:+.2%}(비용 뺌) · 장중 +2% 닿음 {hit2:.0%}"

    lines = [f"🎯 대형주 수급 누적 검증 (시총 상위 100, 첫 외국인 잠정치 다음 분 매수 → +2%/−2%/15:19) — {days}일"
             + (f" (표본 부족, {MIN_DAYS}일↑ 필요)" if days < MIN_DAYS else "")]
    lines.append(row("rule", "규칙 통과 (외국인 5%↑ & 시가 위)"))
    lines.append(row("ratio >= 0.05", "외국인 5%↑"))
    lines.append(row("ratio > 0 AND ratio < 0.05", "외국인 0~5%"))
    lines.append(row("ratio <= 0", "외국인 순매도"))
    lines.append(row("ratio >= 0.05 AND inst_amt > 0", "외국인 5%↑ & 10:00 기관 순매수"))
    lines.append(row("true", "대형주 전체"))
    return "\n".join(lines)


def main() -> None:
    from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
    parser = argparse.ArgumentParser(description="대형주 수급(장중 외국인 잠정치) 누적 검증")
    parser.add_argument("--date", help="YYYYMMDD (없으면 잠정치가 쌓인 모든 날)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = ScreenerStore()
    client = build_client()
    try:
        days = ([datetime.strptime(args.date, "%Y%m%d").date()] if args.date else
                [r[0] for r in store.conn.execute("SELECT DISTINCT date FROM investor_intraday ORDER BY 1").fetchall()])
        for d in days:
            evaluate(store, client, d)
        print(summary(store))
    finally:
        store.close()


if __name__ == "__main__":
    main()
