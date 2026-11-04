"""🪜 애프터 정배열 — 전날 애프터장에서 오른 종목이 오늘 아침 1분봉 60선·120선 골든크로스 또는 정배열 우상향이면 모의 매수.

계기·결정 (2026-11-04 사용자): 한화솔루션 11-04 — 전날 애프터장 +2.3%, 10:39 1분봉 60선이 120선을 다시 위로 → 종가 +15%.
  사용자 '골든 크로스도 포함하고 더하여 120선 60선 정배열 우상향을 그리는 종목도 포함'. 모의 매매만 (실전 안 함).

후보 (스캐너 시작 때 한 번): 전 거래일 주식 대금 상위 100 (daily_ohlcv value, ETF·ETN·스팩·우선주 제외) 중
  전날 애프터 등락 ≥ +2% = 전날 통합(AL) 1분봉 마지막 봉(~19:59) 종가 ÷ 전날 15:30 이하 마지막 봉 종가 − 1.
  전날 1분봉은 data/minute_history.duckdb(밤 백필) 에서 읽고, 없으면 키움 ka10080 으로 받음.
신호 (09:30~10:40 봉, 매분): 통합(AL) 1분봉을 전날 08:00~20:00 + 오늘 08:00~방금 끝난 봉까지 이어 붙여 종가 60봉·120봉 평균.
  GC  = 60선이 120선 아래(직전 봉) → 위(이 봉), 종가 > 120선
  ALN = 정배열 우상향: 60선 > 120선, 60선·120선 모두 10봉 전보다 높음, 종가 > 60선
  둘 중 처음 맞는 봉에서 종목당 하루 한 번 신호 (09:30 첫 확인 때 이미 정배열 우상향이면 바로 신호).
매도 (paper '다음날' 방식): 익절 없음 · 손절 매수가 −3% · 못 닿으면 다음 날 09:00 시가.
돈: 🪜 전용 몫 300만·종목당 50만, 보유 한도(10칸) 예외, 몫을 넘으면 잔고 밖 가상. 시장 분위기(강한 하락장 등)로 막지 않음(백테스트는 모든 날).

1년 검증 (research/ma120_cross/align_bt.py, 전날 대금 상위 100·전날 애프터 ≥ 2%·09:30~10:40·−3% 손절·다음 날 09:00, 비용 0.25%):
  GC 만      171건 +1.02% (앞 +1.51 / 뒤 +0.76, 최고 10건 빼면 +0.17)
  ALN 만     385건 +0.63%
  GC + ALN   429건 / 139일 +0.78% (앞 +0.57 / 뒤 +0.92, 최근 3달 +0.34, 최고 10건 빼면 +0.32)  ← 이것을 씀
  애프터 ≥ 3% 이면 GC + ALN 184건 +1.10%.
  ⚠️ 수백 조합 중 고른 조건이라 ★ 아님 — 모의로 쌓아 보고 판단.
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Callable, Optional

import duckdb
import pandas as pd

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal

KIND = "애프터 정배열"
LABEL = "🪜 애프터 정배열"
TOP_N = 100                      # 전 거래일 주식 대금 상위
AFTER_MIN = 0.02                 # 전날 애프터 등락 ≥ +2%
FAST, SLOW, SLOPE = 60, 120, 10  # 60선 · 120선 · 10봉 전보다 높음
WIN_START, WIN_END = time(9, 30), time(10, 40)   # 신호 봉(1분봉 시각) 범위 — 백테스트와 같음
BUY_START, BUY_END = time(9, 31), time(10, 43)   # 감시 시간: 10:40 봉은 10:41 에 끝나므로 조금 여유
STALE_SEC = 180                  # 이보다 오래된 봉은 늦은 신호로 안 삼 (스캐너가 밀렸을 때)
STOP = 0.03                      # 손절 = 매수가 × (1 − 3%), 익절 없음
POOL, BUDGET = 3_000_000, 500_000
MH_PATH = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
SPAC_WORDS = ("스팩", "스펙", "기업인수목적")

Fetch = Callable[..., list]      # fetch_minute_bars(client, code, day, exchange) 와 같은 모양 (재현 때 바꿔 끼움)


@dataclass
class AlignPick:
    code: str
    name: str
    rank: int                    # 전날 주식 대금 순위
    after: float                 # 전날 애프터 등락
    prev_bars: list = field(default_factory=list, repr=False)   # 전날 08:00~20:00 통합 1분봉


def _prev_bars_db(mh_path: str, codes: list[str], prev: date) -> dict[str, list[dict]]:
    """minute_history 에서 전날 통합(AL) 1분봉. 못 읽으면(밤 백필이 잠금 등) 빈 dict → API 로 받음."""
    try:
        m = duckdb.connect(mh_path, read_only=True)
    except Exception as exc:
        logging.warning("애프터 정배열: minute_history 못 엶 (%s) — 전날 1분봉은 API 로", exc)
        return {}
    try:
        rows = m.execute("""SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv
                            WHERE exchange = 'AL' AND code IN (SELECT unnest(?)) AND ts >= ? AND ts < ? + INTERVAL 1 DAY
                              AND ts::time BETWEEN '08:00' AND '20:00' ORDER BY code, ts""", [codes, prev, prev]).fetchall()
    finally:
        m.close()
    out: dict[str, list[dict]] = {}
    for code, ts, o, h, l, c, v in rows:
        out.setdefault(code, []).append({"code": code, "exchange": "AL", "ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v or 0})
    return out


def _after_gain(bars: list[dict]) -> Optional[float]:
    """전날 애프터 등락 = 마지막 봉 종가 ÷ 15:30 이하 마지막 봉 종가 − 1."""
    reg = [b for b in bars if b["ts"].time() <= time(15, 30)]
    if not reg or not reg[-1]["close"] or not bars[-1]["close"]:
        return None
    return float(bars[-1]["close"]) / float(reg[-1]["close"]) - 1


def load_picks(conn, client, today: date, mh_path: str = MH_PATH, fetch: Fetch = fetch_minute_bars) -> list[AlignPick]:
    """오늘 감시할 🪜 후보. conn = daily_ohlcv.duckdb (read_only)."""
    prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code = '005930' AND date < ?", [today]).fetchone()[0]
    if prev is None:
        return []
    rows = conn.execute("""SELECT d.code, s.name FROM daily_ohlcv d JOIN stocks s USING(code)
                           WHERE d.date = ? AND d.value IS NOT NULL ORDER BY d.value DESC""", [prev]).fetchall()
    top = [(c, n) for c, n in rows if c[-1] not in "579K" and not any(w in (n or "") for w in SPAC_WORDS)][:TOP_N]
    have = _prev_bars_db(mh_path, [c for c, _ in top], prev)
    out, from_api = [], 0
    for rank, (code, name) in enumerate(top, 1):
        bars = have.get(code)
        if not bars:
            try:
                bars = [b for b in fetch(client, code, prev, "AL") if time(8, 0) <= b["ts"].time() <= time(20, 0)]
                from_api += 1
            except Exception:
                logging.warning("애프터 정배열: %s 전날 1분봉 조회 실패", code)
                continue
        bars = [b for b in bars if b.get("close")]
        after = _after_gain(bars) if bars else None
        if after is None or after < AFTER_MIN:
            continue
        out.append(AlignPick(code, name, rank, after, bars))
    logging.info("애프터 정배열: 전날 %s 대금 상위 %s 중 애프터 +%.0f%%↑ %s종목 (전날 1분봉 DB %s · API %s)",
                 prev, len(top), AFTER_MIN * 100, len(out), len(have), from_api)
    return out


def scan(bars: list[dict], today: date, since: Optional[datetime] = None) -> list[tuple[dict, str, float, float]]:
    """이어 붙인 1분봉에서 오늘 09:30~10:40 봉 중 since 뒤에 GC·ALN 이 맞는 봉 전부 → [(봉, 'GC'|'ALN', 60선, 120선)].
    계산은 research/ma120_cross/align_bt.py 와 같다 (pandas rolling, 값이 모자란 봉은 비교가 거짓)."""
    if len(bars) < SLOW:
        return []
    close = pd.Series([float(b["close"]) for b in bars])
    m60, m120 = close.rolling(FAST).mean(), close.rolling(SLOW).mean()
    up = m60 > m120
    gc = up & ~up.shift(fill_value=True) & (close > m120)
    aln = up & (m60 > m60.shift(SLOPE)) & (m120 > m120.shift(SLOPE)) & (close > m60)
    out = []
    for k, b in enumerate(bars):
        ts = b["ts"]
        if ts.date() != today or not (WIN_START <= ts.time() <= WIN_END) or (since is not None and ts <= since) or pd.isna(m120[k]):
            continue
        if gc[k] or aln[k]:
            out.append((b, "GC" if gc[k] else "ALN", float(m60[k]), float(m120[k])))
    return out


class AfterAlignWatcher:
    """매분: 후보마다 통합 1분봉(전날 + 오늘)을 이어 60선·120선을 보고, GC·정배열 우상향이 처음 맞으면 매수 신호 (종목당 하루 한 번)."""

    def __init__(self, client, today: date, picks: list[AlignPick], done: set = frozenset(), fetch: Fetch = fetch_minute_bars) -> None:
        self.client, self.today, self.picks, self.fetch = client, today, picks, fetch
        self.done = set(done)
        self.seen: dict[str, datetime] = {}     # 종목별 마지막으로 본 봉 시각
        self.last: dict[str, datetime] = {}     # 종목별 마지막으로 확인한 분

    def check(self, now: datetime, value_top=None) -> list:
        if not (BUY_START <= now.time() <= BUY_END) or not self.picks:
            return []
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for p in self.picks:
            if p.code in self.done or self.last.get(p.code) == minute:
                continue
            self.last[p.code] = minute
            try:
                today = [b for b in self.fetch(self.client, p.code, self.today, "AL")
                         if time(8, 0) <= b["ts"].time() and b["ts"] < minute and b.get("close")]
            except Exception:
                logging.warning("애프터 정배열: %s 오늘 1분봉 조회 실패", p.code)
                continue
            if not today:
                continue
            hits = scan(p.prev_bars + today, self.today, self.seen.get(p.code))
            self.seen[p.code] = today[-1]["ts"]
            hit = next((h for h in hits if (minute - h[0]["ts"]).total_seconds() <= STALE_SEC), None)
            if hits and hit is None:
                logging.info("애프터 정배열: %s %s 봉 신호는 늦어서 안 삼 (지금 %s)", p.name, hits[0][0]["ts"].strftime("%H:%M"), f"{minute:%H:%M}")
            if hit is None:
                continue
            x, how, m60, m120 = hit
            price = float(x["close"])
            self.done.add(p.code)
            what = "GC — 60선이 120선을 위로 뚫음" if how == "GC" else "ALN — 60선 > 120선 정배열, 둘 다 10봉 전보다 높음"
            reason = (f"{LABEL} — {what} · 전날 애프터 {p.after:+.1%} (전날 대금 {p.rank}위) · "
                      f"{x['ts']:%H:%M} 봉 종가 {price:,.0f} / 60선 {m60:,.0f} / 120선 {m120:,.0f}. "
                      f"익절 없음 / 손절 매수가 −{STOP:.0%}, 못 닿으면 다음 날 09:00 "
                      f"(1년 GC+ALN 429건 +0.78%, ★ 아님 — 모의로 확인)")
            out.append((p.code, p.name, LABEL, Signal(minute, KIND, price, m60, price * (1 - STOP), reason)))
        if out:
            logging.info("애프터 정배열 신호: %s", ", ".join(f"{n} {s.price:,.0f}" for _, n, _, s in out))
        return out
