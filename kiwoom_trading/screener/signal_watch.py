"""감시 종목 1분봉 → 매수 신호 (지지 반등 / 돌파 후 눌림) → 텔레그램.

감시 목록 = 전일 장 마감 후 '다음 거래일 관심 종목' + 최근 20거래일 '쉬어 가는 주도주'(이탈 제외)
          + 오늘 장중 포착 종목 + 조기 트리거(조회 급등 / 대금 가속 / 프리마켓 주목 / 조기 주도주, early_watch.py) — 실시간 추가.
신호는 품질 필터(intraday_signals.reject_reason: 시가 아래·깨진 지지선·짧은 박스·손절 후 반복·시간·깊은 눌림)를 통과한 것만 알림.
걸린 신호도 사유와 함께 buy_signals.reject_reason 에 저장.
매 주기 감시 종목의 당일 1분봉(KRX+NXT 통합)을 받아 detect_signals 로 판정한다.
진행 중인 현재 분의 봉은 제외하고, 마감된 봉으로만 판단한다.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.early_watch import active_rest_leaders, usual_value
from kiwoom_trading.screener.intraday_signals import QualityConfig, Signal, SignalConfig, detect_signals, reject_reason
from kiwoom_trading.screener.store import ScreenerStore


ALERT_WINDOW = timedelta(minutes=5)   # 재시작 시 과거 신호를 한꺼번에 보내지 않도록 최근 신호만 알림
STRONG_FLOW = 5.0                      # 최근 5분 대금이 같은 시간대 평소의 5배↑ → 손절·청산 안내
STRONG_FLOW_GUIDE = ("⚡ 돈이 많이 붙은 신호 — 손절 -5%, +5% 도달 후 고점 대비 -3% 따라 올리기 권장 (당일 정리)\n"
                     "    (1년 검증: 평소 5배↑ 신호는 이 방식이 지금보다 앞·뒤 기간 모두 나음, 아직 수익 확정은 아님)")


class SignalWatcher:
    def __init__(self, client: KiwoomDailyClient, store: ScreenerStore, today: date, config: SignalConfig | None = None,
                 prev_close: dict[str, float] | None = None, quality: QualityConfig | None = None,
                 avg_value: dict[str, float] | None = None) -> None:
        self.client = client
        self.store = store
        self.today = today
        self.config = config or SignalConfig()
        self.quality = quality or QualityConfig()
        self.prev_close = prev_close or {}            # 전일 종가 (돌파선이 전일 종가 위인지 판정)
        self.avg_value = avg_value or {}              # 20일 평균 거래대금 (신호 시점 돈이 붙은 정도 계산)
        self.flow: dict[tuple[str, datetime], tuple[float, Optional[float]]] = {}   # (종목, 신호 시각) → (최근 5분 대금, 평소 대비 배수)
        self.passed = store.passed_signals(today)     # 종목 → 오늘 통과한 신호 (손절 후 반복 금지 판정)
        self.watch: dict[str, tuple[str, str]] = {
            code: (name, "전일 관심") for code, name in store.previous_daily_watchlist(today).items()
        }
        for code, (name, k) in active_rest_leaders(store, today).items():   # 쉬는 날 이후 최대 20거래일 감시
            self.watch.setdefault(code, (name, f"쉬는 주도주 D+{k}"))
        for code, name in store.intraday_watchlist(today).items():
            self.watch.setdefault(code, (name, "장중 포착"))
        for code, (name, source) in store.watch_adds(today).items():
            self.watch.setdefault(code, (name, source))
        self.seen = store.signal_keys(today)
        logging.info("매수 신호 감시 시작: %s종목 %s", len(self.watch), ", ".join(n for n, _ in self.watch.values()))

    def add(self, code: str, name: str, source: str = "장중 포착", reason: str = "", ts: datetime | None = None) -> bool:
        """새로 추가되면 True. 조기 트리거(장중 포착 외)는 재시작해도 유지되도록 저장."""
        if code in self.watch:
            return False
        self.watch[code] = (name, source)
        if source != "장중 포착":
            self.store.save_watch_add(self.today, ts or datetime.now(), code, name, source, reason)
        logging.info("감시 추가: %s(%s) [%s] %s", name, code, source, reason)
        return True

    def check(self, now: datetime) -> list[tuple[str, str, str, Signal]]:
        """새로 발생한 신호 목록 [(code, name, source, signal)] — 알림 대상(최근 5분)만 반환, 전부 저장."""
        minute_start = now.replace(second=0, microsecond=0, tzinfo=None)
        fresh = []
        for code, (name, source) in list(self.watch.items()):
            try:
                bars = [b for b in fetch_minute_bars(self.client, code, self.today, "AL") if b["ts"] < minute_start]
            except Exception as exc:
                logging.warning("1분봉 조회 실패 %s: %s", code, exc)
                continue
            for s in detect_signals(bars, self.config):     # 시간순
                key = (code, s.ts, s.kind)
                if key in self.seen:
                    continue
                self.seen.add(key)
                earlier = self.passed.setdefault(code, [])
                reject = reject_reason(bars, s, earlier, self.quality, prev_close=self.prev_close.get(code))
                if reject is None:
                    earlier.append(s)
                alert = reject is None and s.ts >= minute_start - ALERT_WINDOW
                self.store.save_signal(self.today, code, name, s, source, alert, reject)
                if reject:
                    logging.info("신호 제외 %s %s %s: %s", name, s.kind, f"{s.ts:%H:%M}", reject)
                if alert:
                    self.flow[(code, s.ts)] = signal_flow(bars, s, self.avg_value.get(code))
                    fresh.append((code, name, source, s))
        return fresh


def signal_flow(bars: list[dict], s: Signal, avg_value_20: Optional[float]) -> tuple[float, Optional[float]]:
    """신호 시점 최근 5분 정규장 거래대금(원)과 같은 시간대 평소 대비 배수(20일 평균 × 시간대 비중)."""
    reg = [b for b in bars if time(9, 0) <= b["ts"].time() and b["ts"] <= s.ts]
    v5 = float(sum(b["close"] * b["volume"] for b in reg[-5:]))
    usual = usual_value(avg_value_20, s.ts.time(), 5) if avg_value_20 else 0
    return v5, (v5 / usual if usual else None)


def format_signals(now: datetime, items: list[tuple[str, str, str, Signal]],
                   flow: Optional[dict[tuple[str, datetime], tuple[float, Optional[float]]]] = None) -> str:
    lines = [f"🎯 매수 신호 {now:%H:%M} ({len(items)}건) — 관찰용 (1년 검증상 아직 비용을 넘는 수익 규칙 없음)"]
    for code, name, source, s in items:
        after = " · 애프터마켓(NXT) — 모의투자는 가상 체결" if s.ts.time() >= time(15, 30) else ""
        lines.append(
            f"\n{name}({code}) [{s.kind}] {s.ts:%H:%M}봉{after}\n"
            f"  진입 {s.price:,.0f} / 손절 {s.stop:,.0f} ({s.stop / s.price - 1:+.1%}) — {source}\n"
            f"  {s.reason}"
        )
        v5, mult = (flow or {}).get((code, s.ts), (None, None))
        if v5 is not None:
            lines.append(f"  돈: 최근 5분 {v5 / 1e8:,.0f}억" + (f" = 이 시간대 평소의 {mult:,.1f}배" if mult is not None else ""))
            if mult is not None and mult >= STRONG_FLOW:
                lines.append("  " + STRONG_FLOW_GUIDE)
    return "\n".join(lines)
