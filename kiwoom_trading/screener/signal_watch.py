"""감시 종목 1분봉 → 매수 신호 (지지 반등 / 돌파 후 눌림) → 텔레그램.

감시 목록 = 전일 장 마감 후 '다음 거래일 관심 종목' + 최근 20거래일 '쉬어 가는 주도주'(이탈 제외)
          + 오늘 장중 포착 종목 + 조기 트리거(조회 급등 / 대금 가속 / 프리마켓 주목 / 조기 주도주, early_watch.py) — 실시간 추가.
신호는 품질 필터(intraday_signals.reject_reason: 시가 아래·깨진 지지선·짧은 박스·손절 후 반복·시간·깊은 눌림)를 통과한 것만 알림.
걸린 신호도 사유와 함께 buy_signals.reject_reason 에 저장.
매 주기 감시 종목의 당일 1분봉(KRX+NXT 통합)을 받아 detect_signals 로 판정한다.
진행 중인 현재 분의 봉은 제외하고, 마감된 봉으로만 판단한다.
"""
import logging
from datetime import date, datetime, timedelta

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.early_watch import active_rest_leaders
from kiwoom_trading.screener.intraday_signals import QualityConfig, Signal, SignalConfig, detect_signals, reject_reason
from kiwoom_trading.screener.store import ScreenerStore


ALERT_WINDOW = timedelta(minutes=5)   # 재시작 시 과거 신호를 한꺼번에 보내지 않도록 최근 신호만 알림


class SignalWatcher:
    def __init__(self, client: KiwoomDailyClient, store: ScreenerStore, today: date, config: SignalConfig | None = None,
                 prev_close: dict[str, float] | None = None, quality: QualityConfig | None = None) -> None:
        self.client = client
        self.store = store
        self.today = today
        self.config = config or SignalConfig()
        self.quality = quality or QualityConfig()
        self.prev_close = prev_close or {}            # 전일 종가 (알림 표시용)
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
                reject = reject_reason(bars, s, earlier, self.quality)
                if reject is None:
                    earlier.append(s)
                alert = reject is None and s.ts >= minute_start - ALERT_WINDOW
                self.store.save_signal(self.today, code, name, s, source, alert, reject)
                if reject:
                    logging.info("신호 제외 %s %s %s: %s", name, s.kind, f"{s.ts:%H:%M}", reject)
                if alert:
                    fresh.append((code, name, source, s))
        return fresh


def format_signals(now: datetime, items: list[tuple[str, str, str, Signal]]) -> str:
    lines = [f"🎯 매수 신호 {now:%H:%M} ({len(items)}건) — 관찰용 (근거 필터 후에도 1년 백테스트 손익분기 부근, 진입 방식 개선 전)"]
    for code, name, source, s in items:
        lines.append(
            f"\n{name}({code}) [{s.kind}] {s.ts:%H:%M}봉\n"
            f"  진입 {s.price:,.0f} / 손절 {s.stop:,.0f} ({s.stop / s.price - 1:+.1%}) — {source}\n"
            f"  {s.reason}"
        )
    return "\n".join(lines)
