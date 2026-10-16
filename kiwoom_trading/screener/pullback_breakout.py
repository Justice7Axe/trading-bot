"""🎯 눌림 돌파 — 사용자가 1분봉에 직접 표시한 매수·매도 자리를 규칙으로 옮겼다 (2026-10-17).

기준 표시 (10-16):
- 에이피알: 매수 09:07 봉(첫 고점 318,500 종가 돌파) → 매도 09:15 큰 음봉(337,000 → 328,500, 5분선 아래)
- 삼성바이오로직스: 매수 09:24 봉(첫 고점 1,273,000 돌파) → 매도 09:36 음봉(5분선 아래, 몸통 직전 5봉 평균의 2.2배)
  - 09:18 긴 아래꼬리(1,216,000)는 눌림으로 보지 않는다 → 눌림 깊이는 몸통(시가·종가 중 낮은 값)으로 잰다.

매수 (마감된 KRX 1분봉, 다음 확인 때 시장가):
1. 09:00 이후 고점이 시가보다 +2% 이상
2. 그 뒤 음봉이 섞인 눌림: 몸통 저점이 고점보다 0.7% 이상 낮고, VWAP(그날 평균 단가) −1% 안
3. 양봉이 VWAP·5분선 위에서 그 고점을 종가로 돌파, 그 봉 대금 ≥ 눌림 구간 평균 대금
4. 전일 대비 +2% 이상, 그 시점 대금 100위 안, 09:03~14:30
5. 판 뒤 새 고점·눌림이 생기면 다시 산다 (종목당 하루 3번까지)

매도:
- 음봉이 5분선 아래로 마감하고 몸통 ≥ 직전 5봉 평균 몸통 × 2 → 다음 확인 때 매도
- 손절 = 눌림 몸통 저점 −0.5% (매수가 대비 최대 −5%), 남으면 15:19 정리

10-16 확인: 에이피알 09:08 → 09:16 +2.88%, 삼성바이오로직스 09:25 → 09:37 +1.47% (두 표시 자리와 같다).
10-13~10-16 대금 100위 안 전체: 하루 10~60건, 평균 −0.2 ~ −1.1% (아직 수익 근거 없음, 사용자 표시를 더 받아 다듬는 중).
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

from kiwoom_trading.ingestion.collectors.daily_backfill import KiwoomDailyClient
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.market_data import RankItem

KIND = "눌림 돌파"


@dataclass(frozen=True)
class PullbackConfig:
    min_rise: float = 0.02          # 고점 ≥ 시가 × 1.02
    min_pull: float = 0.007         # 눌림 몸통 저점 ≤ 고점 × (1 − 0.7%)
    vwap_tol: float = 0.01          # 눌림 몸통 저점 ≥ VWAP × (1 − 1%)
    min_chg: float = 0.02           # 매수 봉 종가 ≥ 전일 종가 × 1.02
    max_rank: int = 100
    start: time = time(9, 3)
    last_entry: time = time(14, 30)
    exit_at: time = time(15, 19)
    max_trades: int = 3
    stop_buf: float = 0.005
    stop_max: float = 0.05
    body_mult: float = 2.0          # 매도 음봉 몸통 ≥ 직전 5봉 평균 × 2
    body_n: int = 5
    prefilter_change: float = 0.01  # 1분봉을 받기 전 순위 데이터 등락률 하한 (매수 조건 +2% 의 여유)
    recheck_minutes: int = 3        # 눌림이 진행 중이 아닌 종목은 3분에 한 번만 1분봉을 받는다
    max_fetch: int = 40             # 1분에 받는 1분봉 종목 수 상한 (눌림 진행 종목 먼저)


def _vwap(bars: list[dict[str, Any]]) -> list[float]:
    pv = v = 0.0
    out = []
    for b in bars:
        tp = (b["high"] + b["low"] + b["close"]) / 3
        pv += tp * b["volume"]
        v += b["volume"]
        out.append(pv / v if v else tp)
    return out


def _ma5(cl: list[float], j: int) -> float:
    return sum(cl[max(0, j - 4):j + 1]) / min(5, j + 1)


def exit_bar(bars: list[dict[str, Any]], j: int, cfg: Optional[PullbackConfig] = None) -> bool:
    """bars[j] 가 매도 음봉인가: 5분선 아래 마감 + 몸통 ≥ 직전 5봉 평균 × 2."""
    cfg = cfg or PullbackConfig()
    b = bars[j]
    if b["close"] >= b["open"]:
        return False
    cl = [x["close"] for x in bars[:j + 1]]
    if b["close"] >= _ma5(cl, j):
        return False
    prior = bars[max(0, j - cfg.body_n):j]
    if not prior:
        return False
    avg_body = sum(abs(x["close"] - x["open"]) for x in prior) / len(prior)
    return avg_body > 0 and (b["open"] - b["close"]) >= avg_body * cfg.body_mult


def exit_reason(bars: list[dict[str, Any]], buy_ts: datetime, cfg: Optional[PullbackConfig] = None) -> Optional[str]:
    """실전 매도 판정: 매수 뒤 마지막 마감 봉이 매도 음봉이면 사유."""
    if not bars or bars[-1]["ts"] <= buy_ts:
        return None
    j = len(bars) - 1
    if exit_bar(bars, j, cfg):
        b = bars[j]
        return f"큰 음봉 {b['ts']:%H:%M} (5분선 아래, {b['open']:,}→{b['close']:,})"
    return None


def scan(bars: list[dict[str, Any]], prev_close: float, cfg: Optional[PullbackConfig] = None,
         rank_ok: Optional[Callable[[datetime], bool]] = None) -> tuple[list[dict], bool]:
    """그날 1분봉(마감 봉만, 시간순)으로 매매를 처음부터 다시 따라간다 (인과적).

    반환: ([{"sig": 신호 봉 index, "buy": 매수 봉 index, "sell": 매도 봉 index|None, "why", "stop", "high"}], 지금 눌림 진행 중인지)
    매도는 같은 규칙으로 시뮬레이션해 다음 매수 가능 시점을 정한다(실전 매도는 모의투자가 따로 판정).
    """
    cfg = cfg or PullbackConfig()
    bars = [b for b in bars if time(9, 0) <= b["ts"].time() <= cfg.exit_at]
    out: list[dict] = []
    if len(bars) < 5 or not prev_close:
        return out, False
    o = bars[0]["open"]
    cl = [b["close"] for b in bars]
    vw = _vwap(bars)
    hi = hi_i = pull_low = pull_i = None
    i = 0
    while i < len(bars) and len(out) < cfg.max_trades:
        b = bars[i]
        t = b["ts"].time()
        if hi_i is not None and i > hi_i:
            body_low = min(b["open"], b["close"])
            if pull_low is None or body_low < pull_low:
                pull_low, pull_i = body_low, i
        armed = (hi is not None and hi >= o * (1 + cfg.min_rise) and pull_low is not None
                 and pull_low <= hi * (1 - cfg.min_pull) and pull_low >= vw[pull_i] * (1 - cfg.vwap_tol)
                 and any(x["close"] < x["open"] for x in bars[hi_i + 1:i + 1]))
        if (armed and cfg.start <= t <= cfg.last_entry and b["close"] > b["open"] and b["close"] > hi
                and b["close"] > vw[i] and b["close"] > _ma5(cl, i) and b["close"] >= prev_close * (1 + cfg.min_chg)
                and (rank_ok is None or rank_ok(b["ts"]))):
            seg = bars[hi_i + 1:i]
            avg_val = sum(x["close"] * x["volume"] for x in seg) / len(seg) if seg else 0
            if b["close"] * b["volume"] >= avg_val:
                entry = {"sig": i, "buy": i + 1 if i + 1 < len(bars) else None, "sell": None, "why": "",
                         "stop": pull_low * (1 - cfg.stop_buf), "high": hi}
                out.append(entry)
                if entry["buy"] is None:          # 마지막 봉이 신호 → 실전에서 지금 사는 자리
                    return out, False
                k = entry["buy"]
                entry["stop"] = max(bars[k]["open"] * (1 - cfg.stop_max), entry["stop"])
                for j in range(k, len(bars)):
                    if bars[j]["low"] <= entry["stop"]:
                        entry["sell"], entry["why"] = j, "손절"
                        break
                    if j + 1 < len(bars) and exit_bar(bars, j, cfg):
                        entry["sell"], entry["why"] = j + 1, "큰 음봉"
                        break
                if entry["sell"] is None:
                    return out, False             # 아직 들고 있는 중
                i = entry["sell"]
                hi, hi_i, pull_low, pull_i = bars[i]["high"], i, None, None
                i += 1
                continue
        if hi is None or b["high"] > hi:
            hi, hi_i, pull_low, pull_i = b["high"], i, None, None
        i += 1
    return out, bool(hi is not None and pull_low is not None and hi >= o * (1 + cfg.min_rise))


class PullbackWatcher:
    """대금 100위 안·+1%↑ 종목의 KRX 1분봉으로 눌림 돌파 판정 → 마지막 마감 봉이 신호면 알림 (종목·봉당 1번)."""

    def __init__(self, client: KiwoomDailyClient, today: date, prev_close: dict[str, float],
                 config: Optional[PullbackConfig] = None, seen: Optional[set[tuple[str, datetime]]] = None) -> None:
        self.client = client
        self.today = today
        self.prev_close = prev_close
        self.config = config or PullbackConfig()
        self.seen: set[tuple[str, datetime]] = set(seen or ())
        self.last_check: dict[str, datetime] = {}
        self.cache: dict[str, list] = {}               # 같은 분에 받은 KRX 1분봉 (주도주 모양·눌림 돌파가 함께 씀, run_once 가 매분 비움)
        self.armed: set[str] = set()

    def _bars(self, code: str) -> list:
        if code not in self.cache:
            self.cache[code] = fetch_minute_bars(self.client, code, self.today, "KRX")
        return self.cache[code]

    def check(self, now: datetime, value_top: list[RankItem]) -> list[tuple[str, str, str, Signal]]:
        cfg = self.config
        # 14:30 봉은 14:31 에 마감되므로 1분 여유
        if not (cfg.start <= now.time() <= (datetime.combine(self.today, cfg.last_entry) + timedelta(minutes=1)).time()):
            return []
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        cands = []
        for item in value_top:
            if item.rank > cfg.max_rank or item.change_rate is None or item.change_rate < cfg.prefilter_change:
                continue
            if item.code not in self.prev_close:
                continue
            last = self.last_check.get(item.code)
            due = last is None or (item.code in self.armed and last < minute) or \
                (minute - last).total_seconds() >= cfg.recheck_minutes * 60
            if due:
                cands.append((0 if item.code in self.armed else 1, last or datetime.min, item))
        cands.sort(key=lambda x: (x[0], x[1]))
        out = []
        for _, _, item in cands[:cfg.max_fetch]:
            self.last_check[item.code] = minute
            try:
                bars = [b for b in self._bars(item.code) if b["ts"] < minute]
            except Exception as exc:
                logging.warning("눌림 돌파 1분봉 조회 실패 %s: %s", item.code, exc)
                continue
            entries, armed = scan(bars, self.prev_close[item.code], cfg)
            if armed:
                self.armed.add(item.code)
            else:
                self.armed.discard(item.code)
            if not entries or entries[-1]["buy"] is not None:
                continue
            e = entries[-1]
            regular = [b for b in bars if b["ts"].time() >= time(9, 0)]
            sig_bar = regular[e["sig"]]
            key = (item.code, sig_bar["ts"])
            if key in self.seen:      # scan 은 마지막 마감 봉이 신호일 때만 매수 None 으로 돌려준다 → 늘 방금 나온 신호
                continue
            self.seen.add(key)
            price = float(sig_bar["close"])
            stop = max(price * (1 - cfg.stop_max), e["stop"])
            reason = (f"대금 {item.rank}위 · 고점 {e['high']:,.0f} 돌파 · 눌림 저점 {e['stop'] / (1 - cfg.stop_buf):,.0f} · "
                      f"오늘 {len(entries)}번째 — 매도: 5분선 아래 큰 음봉(몸통 직전 5봉 평균 2배) 또는 손절, 남으면 15:19")
            out.append((item.code, item.name, KIND, Signal(sig_bar["ts"], KIND, price, float(e["high"]), float(stop), reason)))
        return out

