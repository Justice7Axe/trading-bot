"""🧭 디앤서 종가 — 『실전 시황 트레이딩』 3장 종목 선정법으로 고른 종목을 정규장 종가 무렵 사서 다음 날 09:00 에 판다
(2026-10-25 사용자: "디앤서 매매 알고리즘의 매매는 이 방법대로 매매 종목을 선정", 스킬 danswer 1~9장).

책 체크리스트를 숫자로 바꾼 것 (15:15~15:18 첫 KRX 대금 상위 스냅샷):
- 대상: 주식 대금 10위 안 · 상승 · 상한가(+29.5%↑) 제외
- 전일 관심 (연속성): 전날 대금 30위 안
- 같은 섹터가 함께: 지금 대금 30위 안 +5%↑ 종목 중 같은 업종(stocks.sector) 다른 종목 1개↑
- 신고가 자리: 현재가 ≥ 250거래일 고가 × 0.95
- 추세 유지: 현재가 ≥ 통합 15분봉 종가 120개 평균 (책 '15분봉 120선')
- 수급: 장중 잠정치로 외국인·기관 둘 다 순매도면 뺌 (88쪽 '외국인이 산 종목은 종가배팅에 유리'). 양매수면 ★ 표시.
1년 백테스트 (정규장 종가 매수 → 다음 날 09:00 시가, 비용 0.25%, 스킬 danswer scripts/select_bt.py):
  357건 건당 +0.60% (앞 +0.30 / 뒤 +1.22), 합계 +215만(건당 100만), 최대 낙폭 31만 — 같은 대상 조건 없음 1,470건 +0.38%·낙폭 129만.
  양매수까지 170건 +0.85%·낙폭 14만. ⚠️ 백테스트 수급은 그날 확정치 → 장중 잠정치(정확도 약 70%)로는 덜 나올 수 있다.
매수는 정규장 시장가(모의 실주문), 손절·익절 없이 다음 날 09:00 매도 ('다음날' 방식).
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Iterable, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import _to_int
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import RankItem

KIND = "[디앤서] 종가 체크리스트"   # [디앤서] 접두사로 매매 기법을 바로 알 수 있게 (2026-10-25 사용자)
START, END = time(15, 15), time(15, 18)
TOP_N = 10
PREV_TOP = 30
PEER_TOP, PEER_MIN = 30, 0.05
HI_RATIO = 0.95
MA_BARS = 120
LIMIT_UP = 0.295


@dataclass
class DanswerContext:
    prev_top: set[str]            # 전날 대금 30위 안 주식
    hi250: dict[str, float]       # 전날까지 250거래일 고가
    sector: dict[str, str]


def load_danswer_context(conn, today: date) -> DanswerContext:
    prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [today]).fetchone()[0]
    top = {c for (c,) in conn.execute("""SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL
                                          QUALIFY rank() OVER (ORDER BY d.value DESC) <= ?""", [prev, PREV_TOP]).fetchall()}
    start = conn.execute("""SELECT min(date) FROM (SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ?
                            ORDER BY date DESC LIMIT 250)""", [today]).fetchone()[0]
    hi = {c: float(h) for c, h in conn.execute("SELECT code, max(high) FROM daily_ohlcv WHERE date >= ? AND date < ? GROUP BY code",
                                                [start, today]).fetchall() if h}
    sector = {c: s for c, s in conn.execute("SELECT code, sector FROM stocks WHERE sector IS NOT NULL").fetchall()}
    return DanswerContext(top, hi, sector)


def ma15(client, code: str) -> Optional[float]:
    """통합(KRX+NXT) 15분봉 종가 최근 120개 평균 (ka10080, 최신 → 과거 순)."""
    payload, _, _ = client._post("/api/dostk/chart", "ka10080", {"stk_cd": code + "_AL", "tic_scope": "15", "upd_stkpc_tp": "1"})
    closes = [abs(_to_int(x.get("cur_prc")) or 0) for x in (payload.get("stk_min_pole_chart_qry") or [])][:MA_BARS]
    closes = [c for c in closes if c]
    return sum(closes) / len(closes) if len(closes) >= 100 else None


class DanswerCloseWatcher:
    def __init__(self, market, client, ctx: Optional[DanswerContext], stock_codes: Iterable[str], done: bool = False,
                 notify: Optional[Callable[[str], object]] = None) -> None:
        self.market, self.client, self.ctx = market, client, ctx
        self.stocks = set(stock_codes)
        self.checked = done or ctx is None
        self.notify = notify
        self.info: dict[str, str] = {}      # 텔레그램 한 줄 요약
        self.why: list[str] = []            # 빠진 종목과 이유

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        if self.checked or not (START <= now.time() <= END):
            return []
        stocks = sorted((i for i in value_top if i.code in self.stocks and i.change_rate is not None and i.price), key=lambda i: i.rank)
        if len(stocks) < 50:
            return []
        self.checked = True
        ctx = self.ctx
        peers = [i for i in stocks[:PEER_TOP] if i.change_rate >= PEER_MIN]
        try:   # 장중 잠정치 (KRX, 하루 5~6번 갱신)
            fr, inst = self.market.investor_intraday("6"), self.market.investor_intraday("7")
        except Exception:
            logging.exception("디앤서 종가: 장중 외인·기관 잠정치 조회 실패 — 수급 조건 없이 판정")
            fr, inst = {}, {}
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out, why = [], []
        for i in stocks[:TOP_N]:
            if not 0 < i.change_rate < LIMIT_UP:
                continue
            sec = ctx.sector.get(i.code)
            mates = [p.name for p in peers if p.code != i.code and sec and ctx.sector.get(p.code) == sec]
            hi = ctx.hi250.get(i.code)
            miss = []
            if i.code not in ctx.prev_top:
                miss.append("전날 대금 30위 밖")
            if not mates:
                miss.append("같은 업종 +5% 종목 없음")
            if not hi or i.price < hi * HI_RATIO:
                miss.append(f"250일 고가의 {i.price / hi:.0%}" if hi else "250일 고가 없음")
            f, n = fr.get(i.code), inst.get(i.code)
            if f is not None and n is not None and f < 0 and n < 0:
                miss.append("외인·기관 둘 다 순매도")
            ma = None
            if not miss:
                try:
                    ma = ma15(self.client, i.code)
                except Exception:
                    logging.exception("디앤서 종가: 15분봉 조회 실패 %s", i.code)
                if ma is None or i.price < ma:
                    miss.append(f"15분봉 120선 {ma:,.0f} 아래" if ma else "15분봉 자료 부족")
            if miss:
                why.append(f"{i.name}({', '.join(miss)})")
                continue
            both = f is not None and n is not None and f > 0 and n > 0
            self.info[i.code] = (f"{'★양매수 · ' if both else ''}대금 {i.rank}위 {i.change_rate:+.1%} · 같은 업종 {', '.join(mates[:2])} · "
                                 f"250일 고가 {i.price / hi:.0%} · 15분봉 120선 위")
            flow = "자료 없음" if f is None or n is None else f"외인 {f / 1e8:+,.0f}억 · 기관 {n / 1e8:+,.0f}억"
            reason = (f"{'★양매수 ' if both else ''}대금 {i.rank}위 {i.change_rate:+.1%}, 전날도 대금 30위, 같은 업종 {', '.join(mates[:3])}, "
                      f"250일 고가의 {i.price / hi:.0%}, 15분봉 120선 {ma:,.0f} 위, 장중 잠정 {flow}. "
                      f"종가 무렵 매수 → 손절 없이 다음 날 09:00 매도 (1년 357건 +0.60%, 앞 +0.30 / 뒤 +1.22)")
            out.append((i.code, i.name, KIND, Signal(ts, KIND, float(i.price), float(i.price), 0.0, reason)))
        logging.info("디앤서 종가 %s: %s종목 %s / 빠짐: %s", f"{now:%H:%M}", len(out), ", ".join(n for _, n, _, _ in out), "; ".join(why))
        self.why = why
        if not out and self.notify:
            text = f"[디앤서] 🧭 종가 체크리스트 {now:%H:%M} — 오늘 해당 없음 (대금 10위 상승 {len(why)}종목 모두 미달)"
            for w in why[:10]:
                text += "\n  " + w
            self.notify(text)
        return out

    def format(self, now: datetime, found) -> str:
        lines = [f"[디앤서] 🧭 종가 체크리스트 {now:%H:%M} ({len(found)}건) — 알림만 (모의 매수 멈춤: 계좌 백테스트에서 손해, 보완 중)"]
        for code, name, _, s in found:
            lines.append(f"\n{name}({code}) {self.info.get(code, '')}\n  진입 {s.price:,.0f} / 손절 없음")
        if self.why:
            lines.append("\n빠짐: " + "; ".join(self.why[:6]))
        return "\n".join(lines)
