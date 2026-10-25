"""🧭 [디앤서] 14:30 주도주 종가 베팅 — 알림만 (2026-10-25 사용자 '권장안대로': 15:15 '종가 체크리스트'를 이것으로 바꿈).

책 근거 (『실전 시황 트레이딩』 4장 종가 베팅, 스킬 danswer 4-1·7-1):
- 주도주 종가 베팅은 "오후 2시부터 빠르게 들어가기도 한다" (p.142), 대상 = 실시간 조회 순위 당일 누적 10위 (p.104).
- 체크리스트 (p.142): 전일 종가 위 · 신고가 또는 라운드 피겨 같은 의미 있는 자리 · 프리·애프터마켓에서 거래되는 종목.
- ① 주도주 = 당일 고가 근처 + 신고가면 더 좋음 (p.117) → ★ 표시.
규칙 (14:30~14:35 첫 KRX 대금 상위 스냅샷):
  주식(우선주 제외) 대금 10위 · 등락 0 < r < +29.5% · NXT 거래 종목(ka10001 '_NX' 시세 있음)
  · (250일 신고가: 현재가 ≥ 전날까지 250거래일 고가  또는  라운드 피겨 1·2.5·5×10ⁿ 의 ±3%)
  ★ = 고가 근처(그날 정규장 (현재가−저가)/(고가−저가) ≥ 0.8) + 250일 신고가
1년 백테스트 (14:30 시점 누적 대금 10위 → 14:31 매수 → 다음 날 09:00, 비용 0.25%, 미래 정보 없음, 스킬 danswer scripts/t_closebet3.py):
  신고가 또는 라운드 398건 +0.96% ★ (앞 +0.64 / 뒤 +1.38) · 신고가 306건 +1.15% ★ · ★(고가 근처+신고가) 133건 +1.55% ★.
  다만 1천만 계좌에선 같은 종목을 6️⃣ 주도주 신고가가 장중에 먼저 사서 보탬이 작다(+55만, 낙폭 +1.2%p) → **매수 없이 알림만** 쌓아 본다.
250일 고가는 daily_ohlcv(2026-09-14 부터 애프터 고가 섞임) 대신, 있으면 data/daily_regular.duckdb 의 정규장 고가를 쓴다.
"""
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Iterable, Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.daily_backfill import _to_int
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import RankItem

KIND = "[디앤서] 14:30 주도주 종가"   # [디앤서] 접두사 (2026-10-25 사용자). 알림만 — paper_trader 가 건너뜀, 실계좌·10만 계좌 대상 아님
START, END = time(14, 30), time(14, 35)
TOP_N = 10
LIMIT_UP = 0.295
NEAR_HIGH = 0.8
ROUND = sorted({m * 10 ** k for k in range(2, 8) for m in (1, 2.5, 5)})
REGULAR_DB = os.path.join(PROJECT_ROOT, "data", "daily_regular.duckdb")
NXT_SWITCH = date(2026, 9, 14)


def near_round(p: float) -> Optional[float]:
    return next((x for x in ROUND if 0.97 <= p / x <= 1.03), None)


@dataclass
class DanswerContext:
    hi250: dict[str, float]       # 전날까지 250거래일 고가 (9-14 뒤는 정규장 고가로 바꿈)


def load_danswer_context(conn, today: date) -> DanswerContext:
    days = [d for (d,) in conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ? ORDER BY date DESC LIMIT 250",
                                       [today]).fetchall()]
    start = min(days)
    hi = {c: float(h) for c, h in conn.execute("""SELECT code, max(high) FROM daily_ohlcv WHERE date >= ? AND date < ? AND date < ?
                                                  GROUP BY code""", [start, today, NXT_SWITCH]).fetchall() if h}
    late = {}   # 9-14 이후: 정규장 고가 있으면 그것, 없으면 통합 고가
    for c, d, h in conn.execute("SELECT code, date, high FROM daily_ohlcv WHERE date >= ? AND date < ?", [max(start, NXT_SWITCH), today]).fetchall():
        late[(c, d)] = float(h)
    try:
        r = duckdb.connect(REGULAR_DB, read_only=True)
        try:
            for c, d, h in r.execute("SELECT code, date, high FROM daily_regular WHERE date >= ? AND date < ?", [max(start, NXT_SWITCH), today]).fetchall():
                if (c, d) in late: late[(c, d)] = float(h)
        finally:
            r.close()
    except Exception:
        logging.warning("디앤서 14:30: 정규장 일봉(daily_regular) 없음 — 9-14 뒤 고가는 통합 값 그대로")
    for (c, d), h in late.items():
        hi[c] = max(hi.get(c, 0.0), h)
    return DanswerContext(hi)


def is_nxt(client, code: str) -> bool:
    """NXT 거래 종목인지 (ka10001 '_NX' 시세가 있으면)."""
    try:
        payload, _, _ = client._post("/api/dostk/stkinfo", "ka10001", {"stk_cd": code + "_NX"})
        return bool(_to_int(payload.get("cur_prc")))
    except Exception:
        return False


class DanswerCloseWatcher:
    def __init__(self, market, client, ctx: Optional[DanswerContext], stock_codes: Iterable[str], done: bool = False,
                 notify: Optional[Callable[[str], object]] = None) -> None:
        self.market, self.client, self.ctx = market, client, ctx
        self.stocks = set(stock_codes)
        self.checked = done or ctx is None
        self.notify = notify
        self.info: dict[str, str] = {}
        self.why: list[str] = []

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        if self.checked or not (START <= now.time() <= END):
            return []
        stocks = sorted((i for i in value_top if i.code in self.stocks and i.code[-1] not in "579K" and i.change_rate is not None and i.price),
                        key=lambda i: i.rank)
        if len(stocks) < 50:
            return []
        self.checked = True
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out, why = [], []
        for i in stocks[:TOP_N]:
            if not 0 < i.change_rate < LIMIT_UP:
                why.append(f"{i.name}({i.change_rate:+.1%})"); continue
            if not is_nxt(self.client, i.code):
                why.append(f"{i.name}(정규장만 거래)"); continue
            hi = self.ctx.hi250.get(i.code)
            newhi = bool(hi) and i.price >= hi
            rf = near_round(i.price)
            if not (newhi or rf):
                why.append(f"{i.name}(250일 고가의 {i.price / hi:.0%}, 라운드 피겨 아님)" if hi else f"{i.name}(250일 고가 없음)"); continue
            pos = None
            try:
                q = self.market.quote(i.code, integrated=False)      # KRX 정규장 고·저
                if q and q.high > q.low: pos = (i.price - q.low) / (q.high - q.low)
            except Exception:
                logging.warning("디앤서 14:30: 시세 조회 실패 %s", i.code)
            star = newhi and pos is not None and pos >= NEAR_HIGH
            where = "250일 신고가" if newhi else f"라운드 피겨 {rf:,.0f} ±3%"
            self.info[i.code] = (f"{'★주도주 · ' if star else ''}대금 {i.rank}위 {i.change_rate:+.1%} · {where}"
                                 + (f" · 고가 근처 {pos:.0%}" if pos is not None else ""))
            reason = (f"{'★' if star else ''}14:30 대금 {i.rank}위 {i.change_rate:+.1%}, {where}, NXT 거래. 알림만 — 산다면 14:31 매수 → 다음 날 09:00 "
                      f"(1년 신고가·라운드 398건 +0.96%, ★ 133건 +1.55%)")
            out.append((i.code, i.name, KIND, Signal(ts, KIND, float(i.price), float(i.price), 0.0, reason)))
        logging.info("디앤서 14:30 %s: %s종목 %s / 빠짐: %s", f"{now:%H:%M}", len(out), ", ".join(n for _, n, _, _ in out), "; ".join(why))
        self.why = why
        if not out and self.notify:
            self.notify(f"[디앤서] 🧭 14:30 주도주 종가 — 오늘 해당 없음 (대금 10위 중 조건 맞는 종목 없음)\n  " + "; ".join(why[:10]))
        return out

    def format(self, now: datetime, found) -> str:
        lines = [f"[디앤서] 🧭 14:30 주도주 종가 {now:%H:%M} ({len(found)}건) — 알림만 (매수 안 함). 1년: 14:31 매수 → 다음 날 09:00 건당 +0.96%"]
        for code, name, _, s in found:
            lines.append(f"\n{name}({code}) {self.info.get(code, '')}\n  지금 {s.price:,.0f}")
        if self.why:
            lines.append("\n빠짐: " + "; ".join(self.why[:6]))
        return "\n".join(lines)
