"""🧯 강한 하락장 장 초 판정 → 보수적 매매 (2026-10-20 사용자: 강한 하락장일 때는 아주 보수적으로, 때로는 매매하지 않는 게 낫다).

판정: 09:10 과 09:20 두 번 (각 시각 뒤 5분 안 첫 스냅샷), KRX 대금 상위 200 중 주식만(ETF·인버스 제외)의
      전일 대비 등락 중앙값 ≤ −1.5% 이면 그날 '강한 하락장' (그날 끝까지 유지).
      1년: 09:10 만 → 39일 정밀도 74% 포착 50% / 09:10 또는 09:20 → 46일 정밀도 72% 포착 57% (추가 7일 종가 중앙 −2.5%)
           / 09:30 까지 더하면 50일 정밀도 66% 로 떨어진다.
      ⚠️ 매분 판정으로 하면 10-19(09:29 −1.5%, 종가 +1.3% 반등일)를 잘못 판정한다 → 정해진 두 시점만.
근거 (스크래치 regime_early.py / regime_signals.py, 1년 246일, 전날 대금 상위 200):
- 09:10 중앙 ≤ −1.5% → 그날 종가 중앙 −1.5%↓ 강한 하락장 정밀도 74%, 강한 하락장 58일 중 50% 포착 (판정일 종가 중앙 −3.6%).
- 판정된 날 차트 신호가 더 나쁘다: 주도주 모양 −0.72% (다른 날 −0.36%), 눌림 돌파 −0.46% (−0.34%), 앞·뒤 기간 모두.
- 대형주 09:30 +2% 매매는 판정일에도 −0.24% 로 다른 날(−0.29%)보다 나쁘지 않다 (장 초 빠진 대형주 반등 경향).
보수적 매매 (paper_trader 가 적용):
- 차트·박스 신호(주도주 모양, 눌림 돌파, 장 초 공통점, 지지 반등, 돌파 후 눌림) 새 매수 안 함 — 알림과 기록만 (복기에서 가상 매매로 검증)
- 🎯 대형주 수급은 하루 1종목까지
- 하루 손실 한도 −3% → −1.5%
- 이미 산 종목은 원래 매도 규칙 그대로

📈 강한 상승장 판정 (2026-10-23 사용자 B안: 차트 신호 3종은 강한 상승장에만 산다):
      같은 두 시점에 중앙값 ≥ +2% 이면 그날 '강한 상승장' (그날 끝까지 유지).
      그날만 지지 반등·돌파 후 눌림·주도주 모양을 실제 주문으로 산다. 다른 날은 알림·기록만 (복기에서 가상 매매로 검증).
근거: 모의매매 5거래일(10-16~22) 이 셋 85건 −0.8% 안팎으로 손실 대부분. 1년: 09:10 중앙 ≥ +2% 22일에
      주도주 모양 +0.25% vs 다른 날 −0.52% (스크래치 regime_up.py).
⚠️ 10-19 처럼 약하게 출발해 크게 오른 날은 못 잡는다 (09:10 −1.49%). 10-21 은 +2.7% 출발 뒤 밀린 예외.

📐 기준 다시 정함 (2026-10-25 사용자: 외부 자료로 상승장·하락장 기준을 다시 정하라):
      외부 관례 = 고점 −10% 조정 / −20% 약세장, 200일선, ADR(시장 폭), 사이드카·서킷브레이커.
      2026 은 코스피 일간 변동성이 2.4% → 3.7% 로 커져 고정 % 기준은 시기마다 뜻이 달라진다.
      → 그날 분위기에 '코스피 09:10 전일 대비 ÷ 최근 20거래일 일간 등락 표준편차(σ)' 를 더한다.
  강한 상승장 = 코스피 ≥ +1σ 또는 중앙값 ≥ +2% / 강한 하락장 = 코스피 ≤ −1σ 또는 중앙값 ≤ −1.5%
  큰 흐름(전날 종가): 코스피 52주 고점 대비 −10% 안 = 상승 추세, −10~−20% = 조정, −20% 이하 = 약세장.
      조정·약세장이면 보통 날(강한 상승장 아님) 새 매수를 쉰다 (paper_trader).
근거 (스크래치 regime_cmp.py / regime_combo.py, 1년 249일, 새 기본 매도 = 익절/즉시 손절/둘 다 아니면 다음날 시가):
- 코스피 ≥ +1σ 또는 중앙 ≥ +2% 42일: 09:10 대금 상위 10 +0.75%, 아무 종목 +0.50%, 막힌 고점 +0.67% (앞·뒤 모두 +).
  지금 기준(중앙 ≥ +2%) 23일은 +0.63 / +0.98 / +0.93%. 코스피 σ 만 30일은 09:10 대금 상위 10 +1.24% (0.8σ +0.84, 1.2σ +1.98, 단조).
- 코스피 ≤ −1σ 또는 중앙 ≤ −1.5% 48일: 막힌 고점 −0.92% (지금 41일 −0.79%) → 손실 날을 더 잘 거름.
- 보통 날 & 고점 −10% 안 103일: 막힌 고점 +0.44% / 보통 날 & 조정·약세장 69일: 세 전략 모두 −0.5~−0.7%.
- 200일선은 1년 내내 위라 구분 못 함, 오른 종목 비율(시장 폭)은 가장 약했다.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Iterable, Optional

from kiwoom_trading.screener.market_data import RankItem

CHECKS = (time(9, 10), time(9, 20))   # 각 시각부터 5분 안 첫 스냅샷에서 한 번씩
WINDOW_MIN = 5
STRONG_DOWN = -0.015
STRONG_UP = 0.02
INDEX_CODE = "001"                    # 코스피 종합
SIGMA_UP, SIGMA_DOWN = 1.0, -1.0      # 코스피 09:10 등락 ÷ 20일 변동성
SD_DAYS = 20
HIGH_DAYS = 250                       # 52주
CORRECTION, BEAR = -0.10, -0.20       # 52주 고점 대비
UP_ONLY_KINDS = ("지지 반등", "돌파 후 눌림", "주도주 모양")   # 강한 상승장에만 실제 주문
CONSERVATIVE_LOSS_LIMIT = 0.015
BIGCAP_MAX_WHEN_DOWN = 1


@dataclass
class IndexContext:
    """전날 종가까지의 코스피: 20일 일간 변동성(σ), 52주 고점 대비 → 큰 흐름."""
    prev_close: float
    sd20: float
    dd52: float          # 전날 종가 ÷ 52주 고가 − 1

    @property
    def trend(self) -> str:
        return "상승 추세" if self.dd52 > CORRECTION else "조정" if self.dd52 > BEAR else "약세장"


def _num(x) -> float:
    return abs(float(str(x).replace(",", "") or 0)) / 100      # 지수는 100배 정수, 부호 붙어 옴


def load_index_context(client, today: date) -> Optional[IndexContext]:
    """ka20006 업종일봉 — 오늘 봉은 빼고 전날까지로 계산."""
    payload, _, _ = client._post("/api/dostk/chart", "ka20006", {"inds_cd": INDEX_CODE, "base_dt": f"{today:%Y%m%d}"})
    rows = [r for r in payload.get("inds_dt_pole_qry") or [] if r.get("dt", "") < f"{today:%Y%m%d}"]   # 최신 먼저
    closes = [_num(r["cur_prc"]) for r in rows]
    if len(closes) < SD_DAYS + 1:
        return None
    rets = [closes[i] / closes[i + 1] - 1 for i in range(SD_DAYS)]
    mean = sum(rets) / len(rets)
    sd = (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5
    hi = max(_num(r["high_pric"]) for r in rows[:HIGH_DAYS])
    return IndexContext(prev_close=closes[0], sd20=sd, dd52=closes[0] / hi - 1)


def fetch_index_now(client, today: date) -> Optional[float]:
    """ka20005 업종분봉 1분 — 가장 최근 봉 현재가 (오늘 것만)."""
    payload, _, _ = client._post("/api/dostk/chart", "ka20005", {"inds_cd": INDEX_CODE, "tic_scope": "1"})
    rows = payload.get("inds_min_pole_qry") or []
    if not rows or not str(rows[0].get("cntr_tm", "")).startswith(f"{today:%Y%m%d}"):
        return None
    return _num(rows[0]["cur_prc"])


class MarketRegime:
    def __init__(self, stock_codes: Iterable[str], notify: Optional[Callable[[str], None]] = None,
                 store=None, today: Optional[date] = None, client=None) -> None:
        self.stocks = set(stock_codes)
        self.notify = notify or (lambda text: None)
        self.store, self.today, self.client = store, today, client
        self.strong_down = False
        self.strong_up = False
        self.last_median: Optional[float] = None
        self.last_z: Optional[float] = None
        self.decided_at: Optional[datetime] = None
        self.done: set[time] = set()
        self.index: Optional[IndexContext] = None
        if client is not None and today is not None:
            try:
                self.index = load_index_context(client, today)
            except Exception:
                logging.exception("코스피 일봉 조회 실패 — 오늘은 대금 상위 중앙값만으로 판정")
        if self.index:
            logging.info("코스피 큰 흐름: %s (전날 %.2f, 52주 고점 대비 %+.1f%%, 20일 변동성 %.2f%%)", self.index.trend,
                         self.index.prev_close, self.index.dd52 * 100, self.index.sd20 * 100)
        if store is not None and today is not None:     # 장중에 다시 켜도 그날 판정 유지
            row = store.conn.execute("SELECT regime, decided_at, median FROM market_regime WHERE date = ?", [today]).fetchone()
            if row:
                self.strong_down, self.strong_up = row[0] == "강한 하락장", row[0] == "강한 상승장"
                self.decided_at, self.last_median = row[1], row[2]
                logging.info("시장 분위기 판정 불러옴: %s (%s, 중앙 %+.2f%%)", row[0], f"{row[1]:%H:%M}", row[2] * 100)

    @property
    def trend_weak(self) -> bool:
        """코스피가 52주 고점 대비 −10% 밖(조정·약세장) — 보통 날 새 매수를 쉰다."""
        return self.index is not None and self.index.dd52 <= CORRECTION

    def day_label(self, now: Optional[datetime] = None) -> str:
        """알림 끝에 붙이는 오늘 시장 상황 (2026-10-25 사용자 '알림에 표시 붙이기').
        강한 상승장 / 상승 흐름 보통 날 / 하락 흐름 보통 날 / 강한 하락장, 09:10 전엔 '판정 전'."""
        flow = ("하락 흐름" if self.trend_weak else "상승 흐름") if self.index else None
        where = f"코스피 52주 고점 대비 {self.index.dd52:+.0%}" if self.index else "큰 흐름 모름"
        if self.strong_up:
            day = "강한 상승장"
        elif self.strong_down:
            day = "강한 하락장"
        elif CHECKS[0] in self.done:
            day = f"{flow} 보통 날" if flow else "보통 날"
            if CHECKS[-1] not in self.done:
                day += f" ({CHECKS[-1]:%H:%M} 재판정 전)"
        else:
            day = f"판정 전 ({CHECKS[0]:%H:%M}) · {flow}" if flow else f"판정 전 ({CHECKS[0]:%H:%M})"
        return f"📍 오늘 시장: {day} · {where}"

    def trend_text(self) -> str:
        if not self.index:
            return "큰 흐름 모름(코스피 일봉 없음)"
        return f"코스피 {self.index.trend} (52주 고점 대비 {self.index.dd52:+.1%})"

    def _save(self, regime: str, now: datetime, med: float, kospi: Optional[float], z: Optional[float]) -> None:
        if self.store is not None and self.today is not None:
            self.store.conn.execute(
                "INSERT OR REPLACE INTO market_regime (date, regime, decided_at, median, kospi_chg, kospi_z, trend) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [self.today, regime, now.replace(tzinfo=None), med, kospi, z, self.index.trend if self.index else None])

    def _kospi(self, now: datetime) -> tuple[Optional[float], Optional[float]]:
        if self.client is None or not self.index or self.index.sd20 <= 0:
            return None, None
        try:
            px = fetch_index_now(self.client, now.date())
        except Exception:
            logging.exception("코스피 분봉 조회 실패 — 중앙값만으로 판정")
            return None, None
        if px is None:
            return None, None
        chg = px / self.index.prev_close - 1
        return chg, chg / self.index.sd20

    def update(self, now: datetime, value_top: list[RankItem]) -> None:
        if self.strong_down or self.strong_up:
            return
        mins = now.hour * 60 + now.minute
        due = [c for c in CHECKS if c not in self.done and c.hour * 60 + c.minute <= mins < c.hour * 60 + c.minute + WINDOW_MIN]
        if not due:
            return
        xs = sorted(i.change_rate for i in value_top if i.code in self.stocks and i.change_rate is not None)
        if len(xs) < 50:
            return
        self.done.update(due)
        n = len(xs)
        med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
        kospi, z = self._kospi(now)
        self.last_median, self.last_z = med, z
        down = med <= STRONG_DOWN or (z is not None and z <= SIGMA_DOWN)
        up = not down and (med >= STRONG_UP or (z is not None and z >= SIGMA_UP))
        why = (f"대금 상위 주식 {n}종목 중앙 {med:+.1%}"
               + (f", 코스피 {kospi:+.1%} = 20일 변동성의 {z:+.2f}배" if z is not None else ", 코스피 값 없음"))
        logging.info("시장 분위기 판정 %s: %s → %s (%s)", f"{now:%H:%M}", why,
                     "강한 하락장" if down else "강한 상승장" if up else "보통", self.trend_text())
        if up:
            self.strong_up, self.decided_at = True, now
            self._save("강한 상승장", now, med, kospi, z)
            self.notify(f"📈 강한 상승장 판정 {now:%H:%M} — {why}\n"
                        f"(기준: 코스피 ≥ +{SIGMA_UP:.0f}σ 또는 중앙 ≥ {STRONG_UP:+.1%}) · {self.trend_text()}\n"
                        f"오늘은 차트 신호({'·'.join(UP_ONLY_KINDS)})도 모의 매수합니다. 강한 상승장이 아닌 날은 알림·기록만.")
        elif down:
            self.strong_down, self.decided_at = True, now
            self._save("강한 하락장", now, med, kospi, z)
            self.notify(f"🧯 강한 하락장 판정 {now:%H:%M} — {why}\n"
                        f"(기준: 코스피 ≤ {SIGMA_DOWN:.0f}σ 또는 중앙 ≤ {STRONG_DOWN:+.1%}) · {self.trend_text()}\n"
                        f"오늘은 보수적으로: 차트 신호(주도주 모양·눌림 돌파·장 초 공통점·지지 반등·돌파 후 눌림)는 새로 사지 않고 알림만, "
                        f"대형주 수급은 {BIGCAP_MAX_WHEN_DOWN}종목까지, 하루 손실 한도 −{CONSERVATIVE_LOSS_LIMIT:.1%}. 보유 종목은 원래 매도 규칙대로.")
        elif CHECKS[-1] in self.done and self.trend_weak:
            self.notify(f"🌫️ 하락 흐름 보통 날 — {self.trend_text()}. 오늘은 🎯 저항 돌파·🎯 약세장 인버스만 모의 매수합니다 (인버스 갭·가상 매매 포함).\n"
                        f"마지막 판정 {now:%H:%M}: {why}. (1년: 하락 흐름 보통 날은 다른 롱 전략 모두 −0.5~−0.7%)")
