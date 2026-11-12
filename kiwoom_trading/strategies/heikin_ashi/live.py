"""🕯 하이킨아시 매매 — 트레이딩박스 '캔들 하나로 100달러를 220억으로 만든 트레이더 (더블 하이킨아시 매매법)'(2026-11-10 영상) 규칙
(2026-11-12 사용자 '둘다', 모의만). 영상은 코인 4시간봉 — 여기선 30분봉·일봉 두 가지로 옮김. 숫자는 영상 설정(n=10, 손익비 2.0, 20봉)을 그대로 쓴 가정, 검증 전.

색 (매끄럽게 한 하이킨아시 = '더블 하이킨아시'):
  so·sh·sl·sc = 시가·고가·저가·종가의 EMA10, HC = (so+sh+sl+sc)/4, HO 첫 봉 = (so+sc)/2, 그 뒤 HO = (앞 HO + 앞 HC)/2
  dO = EMA10(HO), dC = EMA10(HC) → dC > dO 면 주황(상승), 아니면 보라(하락). 봉이 60개 안 되면 판정하지 않음.
횡보 거르기 (보통 하이킨아시): 종가 (O+H+L+C)/4, 시가 (앞 시가 + 앞 종가)/2 (첫 봉 (O+C)/2), 고가·저가는 원래 봉과 HA 시가·종가 중 최고·최저.
  몸통 |종가−시가| ≤ 봉 길이(고가−저가) × 0.25 면 도지 — 최근 10봉(신호 봉 포함) 중 도지 5개↑ 면 안 삼.
매수 (롱만): 방금 끝난 봉 t 가 주황이고 t−1 이 보라 (색이 바뀜) → 그 판정 때 모의 매수. 기록 가격 = 봉 t 종가 (일봉은 15:15~15:19 지금가).
  손절 S = 봉 t 포함 최근 20봉 저가 중 최저, R = 매수가 − S. R ≤ 0 이거나 R/매수가 > 8% 면 안 삼.
매도 (paper 모드 'HA_D'·'HA_M'): 지금가가 S 에 닿으면 바로 손절 · 매수가 + 2R 에 닿으면 절반 익절(1주면 전부)
  · 다 끝난 봉이 보라면 남은 물량 전부 매도 (익절 전이어도 전부 — 색이 바뀌면 나감) · 15:19 정리 없이 밤을 넘김.
  t.stop = S, 익절선은 paper_trades.note 의 '익절선 N' (🪃 급락 반등과 같은 표시, 재시작해도 남음).
공통 선별 (📈 켈 수축과 같은 KellSelector): 대금 100억↑·주식 중 대금 100위 안, 전날 외인·기관 둘 다 순매도 뺌, 같은 네이버 테마 +4%↑ 2종목↑,
  상장 20거래일 안 뺌, 09:10 시장 판정 뒤·강한 하락장 날 아님 + 프로그램 순매수(program_intraday 10분 스냅샷) 최근 두 번이 줄지 않음
  (스냅샷이 두 번 안 되면 통과, 🪃 와 같은 규칙) · 🌀 무너지는 국면은 paper 가 뺌. 한 번 판정에 후보 최대 30종목.
30분봉 (KIND_M, 'HA_M'): 📈 켈 30분과 같은 30분봉(지난 10거래일 지역 DB + 오늘 키움 1분봉, 켈과 같은 캐시를 같이 씀).
  봉이 끝나고 1분 뒤 판정 — 보유 종목 색 판정(보라면 매도) → 매수 판정. 아침 09:00 에는 전날 마지막 봉 색으로 매도 판정.
일봉 (KIND_D, 'HA_D'): 15:15~15:19 한 번 — 📈 켈 일봉과 같은 일봉(9-14 뒤 daily_regular 정규장 값) + 오늘 KRX 시세 봉으로 판정.
  색 매도는 스캐너 시작 때 전 거래일까지 일봉 색이 보라면 09:00 매도. 손절·익절은 장중 지금가로.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.strategies.crash_rebound.live import load_program
from kiwoom_trading.strategies.kell_squeeze.live import (D_END, D_START, M_OPEN, MAX_VALUE_RANK, KellDailyContext, KellMinuteWatcher,
                                                         KellSelector, bar_index, ema, regime_gate)

KIND_D = "하이킨아시 일봉"
KIND_M = "하이킨아시 30분"
SOURCE = "하이킨아시"
N = 10                   # 더블 하이킨아시 EMA 길이
RR = 2.0                 # 첫 익절 = 매수가 + 2R
LB = 20                  # 손절 = 최근 20봉 최저가
MAX_RISK = 0.08          # R / 매수가 > 8% 면 안 삼
DOJI_BODY = 0.25         # 도지: 몸통 ≤ 봉 길이 × 0.25
CHOP_BARS, CHOP_MIN = 10, 5   # 최근 10봉 중 도지 5개↑ 면 횡보 → 안 삼
MIN_BARS = 60            # 판정에 필요한 최소 봉 수
TP_FRAC = 0.5            # 첫 익절 때 파는 비율
MAX_CANDS = 30           # 한 번 판정에 보는 후보 수 (API 부담)


# ---------------------------------------------------------------- 규칙 (순수 함수)
def smoothed_ha(bars: pd.DataFrame, n: int = N) -> pd.DataFrame:
    """bars(open·high·low·close, 오래된 순) → HO·HC·dO·dC·bull(주황) 칸."""
    g = bars.reset_index(drop=True)
    so, sh, sl, sc = (ema(g[k], n).to_numpy() for k in ("open", "high", "low", "close"))
    hc = (so + sh + sl + sc) / 4
    ho = np.empty_like(hc)
    if len(hc):
        ho[0] = (so[0] + sc[0]) / 2
        for i in range(1, len(hc)):
            ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    d_o, d_c = ema(pd.Series(ho), n).to_numpy(), ema(pd.Series(hc), n).to_numpy()
    return pd.DataFrame({"ho": ho, "hc": hc, "do": d_o, "dc": d_c, "bull": d_c > d_o})


def plain_ha(bars: pd.DataFrame) -> pd.DataFrame:
    """보통 하이킨아시 시가·고가·저가·종가 + 도지 여부."""
    g = bars.reset_index(drop=True)
    o, h, l, c = (g[k].astype(float).to_numpy() for k in ("open", "high", "low", "close"))
    hcl = (o + h + l + c) / 4
    hop = np.empty_like(hcl)
    if len(hcl):
        hop[0] = (o[0] + c[0]) / 2
        for i in range(1, len(hcl)):
            hop[i] = (hop[i - 1] + hcl[i - 1]) / 2
    hh = np.maximum.reduce([h, hop, hcl])
    hl = np.minimum.reduce([l, hop, hcl])
    doji = np.abs(hcl - hop) <= DOJI_BODY * (hh - hl)
    return pd.DataFrame({"open": hop, "high": hh, "low": hl, "close": hcl, "doji": doji})


def evaluate_last(bars: pd.DataFrame) -> tuple[Optional[str], Optional[dict]]:
    """마지막 봉 판정: 'buy' / 'chop'(횡보) / 'risk'(R 이상) / 'none'(색 안 바뀜). 봉이 60개 안 되면 (None, None)."""
    if len(bars) < MIN_BARS:
        return None, None
    g = bars.reset_index(drop=True)
    s = smoothed_ha(g)
    doji = int(plain_ha(g)["doji"].iloc[-CHOP_BARS:].sum())
    entry = float(g["close"].iloc[-1])
    stop = float(g["low"].astype(float).iloc[-LB:].min())
    r = entry - stop
    info = {"close": entry, "stop": stop, "R": r, "risk": r / entry if entry else float("nan"), "tp": entry + RR * r,
            "doji": doji, "dc": float(s["dc"].iloc[-1]), "do": float(s["do"].iloc[-1])}
    if not (bool(s["bull"].iloc[-1]) and not bool(s["bull"].iloc[-2])):
        return "none", info
    if doji >= CHOP_MIN:
        return "chop", info
    if r <= 0 or r / entry > MAX_RISK:
        return "risk", info
    return "buy", info


def color_exit(bars: pd.DataFrame, unit: str) -> Optional[str]:
    """다 끝난 마지막 봉이 보라면 매도 사유. 봉이 60개 안 되면 None (판정 안 함)."""
    if len(bars) < MIN_BARS:
        return None
    s = smoothed_ha(bars)
    if bool(s["bull"].iloc[-1]):
        return None
    return f"🕯 하이킨아시 보라 — {unit} 색이 하락(dC {s['dc'].iloc[-1]:,.0f} ≤ dO {s['do'].iloc[-1]:,.0f})으로 바뀜, 남은 물량 전부 매도"


def reason_text(info: dict, unit: str, when: str) -> str:
    return (f"🕯 하이킨아시({unit}) — 더블 하이킨아시(EMA{N}) 보라 → 주황으로 바뀜 ({when} 종가 {info['close']:,.0f}), "
            f"최근 {CHOP_BARS}봉 도지 {info['doji']}개(<{CHOP_MIN}) · 손절 {info['stop']:,.0f}({-info['risk']:+.1%}, {LB}봉 최저가) · "
            f"{info['tp']:,.0f}(+{RR:g}R) 에서 절반 익절 · 남은 물량은 봉이 보라로 바뀌면 매도")


def select(sel: KellSelector, value_top: list, program: dict[str, list], limit: int = MAX_CANDS) -> tuple[list, int]:
    """켈 공통 선별 + 프로그램 순매수 최근 두 번이 줄지 않음 → (후보 최대 limit, 프로그램으로 뺀 수)."""
    out, cut = [], 0
    for x in sel.pick(value_top, limit=MAX_VALUE_RANK):
        p = program.get(x.code) or []
        if len(p) >= 2 and p[0] < p[1]:
            cut += 1
            continue
        out.append(x)
        if len(out) >= limit:
            break
    return out, cut


def _program(store, day: date, value_top: list) -> dict[str, list]:
    try:
        return load_program(getattr(store, "conn", None), day, [x.code for x in value_top])
    except Exception:
        logging.exception("하이킨아시: 프로그램 매매 읽기 실패 — 프로그램 조건 없이 봄")
        return {}


def _signal(kind: str, ts: datetime, price: float, info: dict, reason: str) -> Signal:
    return Signal(ts=ts, kind=kind, price=price, level=round(info["tp"]), stop=info["stop"], reason=reason)


# ---------------------------------------------------------------- 일봉
class HaDailyContext(KellDailyContext):
    """📈 켈 일봉과 같은 일봉 자료 + 스캐너 시작 때 보유 종목 색 매도 판정."""

    def exits(self, held: dict[str, str]) -> dict[str, str]:   # type: ignore[override]
        """held = {거래 id: 코드} → {거래 id: 매도 사유} — 전 거래일 일봉 색이 보라면 09:00 매도."""
        out: dict[str, str] = {}
        hist = self.history(held.values())
        for tid, code in held.items():
            g = hist.get(code)
            if g is None or len(g) < MIN_BARS:
                logging.warning("하이킨아시 일봉 매도 판정 자료 부족 %s", code)
                continue
            why = color_exit(g, f"{g['date'].iloc[-1]:%m-%d} 일봉")
            if why:
                out[tid] = why + " — 시초 매도"
        return out


class HaDailyWatcher:
    """15:15~15:19 한 번: 선별 통과 종목(최대 30)의 일봉 + 오늘 KRX 시세 봉으로 판정 → 모의 매수 신호."""

    def __init__(self, ctx: HaDailyContext, selector: KellSelector, market, store=None, done: Iterable = (), regime=None) -> None:
        self.ctx, self.sel, self.market, self.store, self.regime = ctx, selector, market, store, regime
        self.done = set(done)
        self.fired = False

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if self.fired or not (D_START <= now.time() <= D_END):
            return []
        self.fired = True
        gate = regime_gate(self.regime, now)
        if gate:
            logging.info("하이킨아시 일봉: %s — 오늘 안 삼", gate)
            return []
        picks, cut = select(self.sel, value_top, _program(self.store, self.ctx.day, value_top))
        picks = [x for x in picks if x.code not in self.done]
        hist = self.ctx.history(x.code for x in picks)
        out, tally = [], {"chop": [], "risk": [], "short": []}
        naive = now.replace(tzinfo=None, second=0, microsecond=0)
        for x in picks:
            g = hist.get(x.code)
            if g is None or len(g) < MIN_BARS - 1:
                tally["short"].append(x.name)
                continue
            try:
                q = self.market.quote(x.code, integrated=False)
            except Exception:
                logging.warning("하이킨아시 일봉 시세 조회 실패 %s", x.code)
                continue
            if not q or not q.price:
                continue
            bars = pd.concat([g, pd.DataFrame([{"code": x.code, "date": self.ctx.day, "open": q.open, "high": q.high, "low": q.low,
                                                "close": q.price, "volume": q.volume}])], ignore_index=True)
            st, info = evaluate_last(bars)
            if st in ("chop", "risk"):
                tally[st].append(f"{x.name}" + (f" (R {info['risk']:.1%})" if st == "risk" else f" (도지 {info['doji']})"))
            if st != "buy":
                continue
            self.done.add(x.code)
            theme = self.sel.hot_theme(x.code, value_top)
            out.append((x.code, x.name, SOURCE, _signal(KIND_D, naive, float(q.price), info,
                                                        reason_text(info, "일봉", f"{now:%H:%M} 오늘")
                                                        + f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억" + (f" · 테마 {theme}" if theme else "")
                                                        + " — 색 매도는 다음 거래일부터 09:00 판정")))
        logging.info("하이킨아시 일봉 %s: 후보 %s종목(프로그램 줄어 뺌 %s) → 신호 %s %s · 횡보 %s · R 이상 %s · 일봉 부족 %s", f"{now:%H:%M}",
                     len(picks), cut, len(out), ", ".join(n for _, n, _, _ in out),
                     ", ".join(tally["chop"]) or "없음", ", ".join(tally["risk"]) or "없음", ", ".join(tally["short"]) or "없음")
        return out


# ---------------------------------------------------------------- 30분봉
class HaMinuteWatcher:
    """30분봉이 끝날 때마다: 보유 종목 색 판정(exits) → 선별 통과 종목(최대 30) 매수 판정.
    30분봉 자료는 📈 켈 30분 KellMinuteWatcher 의 지난날·오늘 캐시를 같이 씀 (src 를 주지 않으면 따로 하나 만듦).
    held() = [(거래 id, 코드)] — paper 가 HA_M 매도에 exits[거래 id] 를 씀."""

    def __init__(self, client, day: date, selector: KellSelector, src: Optional[KellMinuteWatcher] = None, store=None, regime=None,
                 held: Optional[Callable[[], list]] = None, done: Iterable = ()) -> None:
        self.day, self.sel, self.store, self.regime = day, selector, store, regime
        self.src = src if src is not None else KellMinuteWatcher(client, day, selector)
        self.held = held or (lambda: [])
        self.done = set(done)                      # (코드, 봉 끝 시각)
        self.exits: dict[str, str] = {}
        self.last_k: Optional[int] = None
        self.morning_done = False

    def _refresh_exits(self, k: Optional[int], label: str) -> None:
        held = self.held()
        self.src._ensure_hist([c for _, c in held])
        exits: dict[str, str] = {}
        for tid, code in held:
            try:
                s = self.src._series(code, k)
            except Exception:
                logging.warning("하이킨아시 30분봉 매도 판정 조회 실패 %s", code)
                continue
            why = color_exit(s, f"{pd.Timestamp(s['start'].iloc[-1]):%m-%d %H:%M} 30분봉") if len(s) else None
            if why:
                exits[tid] = why
        self.exits = exits
        if held:
            logging.info("하이킨아시 30분 매도 판정 %s: 보유 %s건 → 매도 %s", label, len(held), ", ".join(exits.values()) or "없음")

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if now.date() != self.day:
            return []
        k = bar_index(now)
        if k is None:
            if not self.morning_done and now.time() >= M_OPEN:
                self.morning_done = True          # 전날 마지막 봉 색으로 들고 넘어온 종목 매도 판정 (09:00)
                try:
                    self._refresh_exits(None, "전날 마지막 봉")
                except Exception:
                    logging.exception("하이킨아시 30분 아침 매도 판정 실패")
            return []
        if k == self.last_k:
            return []
        self.last_k = k
        self.morning_done = True
        end = datetime.combine(self.day, M_OPEN) + timedelta(minutes=30 * (k + 1))
        try:
            self._refresh_exits(k, f"{end:%H:%M}")
        except Exception:
            logging.exception("하이킨아시 30분 매도 판정 실패")
        gate = regime_gate(self.regime, now)
        if gate:
            logging.info("하이킨아시 30분 %s: %s — 안 삼", f"{end:%H:%M}", gate)
            return []
        picks, cut = select(self.sel, value_top, _program(self.store, self.day, value_top))
        picks = [x for x in picks if (x.code, end) not in self.done]
        self.src._ensure_hist([x.code for x in picks])
        out, tally = [], {"chop": [], "risk": [], "short": []}
        for x in picks:
            try:
                s = self.src._series(x.code, k)
            except Exception:
                logging.warning("하이킨아시 30분봉 오늘 1분봉 조회 실패 %s", x.code)
                continue
            if not len(s) or pd.Timestamp(s["start"].iloc[-1]) != end - timedelta(minutes=30):
                continue                              # 오늘 이 봉이 아직 없음 (거래 정지 등)
            st, info = evaluate_last(s)
            if st is None:
                tally["short"].append(x.name)
                continue
            if st in ("chop", "risk"):
                tally[st].append(f"{x.name}" + (f" (R {info['risk']:.1%})" if st == "risk" else f" (도지 {info['doji']})"))
            if st != "buy":
                continue
            self.done.add((x.code, end))
            theme = self.sel.hot_theme(x.code, value_top)
            out.append((x.code, x.name, SOURCE, _signal(KIND_M, end, info["close"], info,
                                                        reason_text(info, "30분봉", f"{end - timedelta(minutes=30):%H:%M}~{end:%H:%M} 봉")
                                                        + f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억" + (f" · 테마 {theme}" if theme else "")
                                                        + " — 30분봉 끝날 때마다 색 판정, 15:19 정리 없이 들고 감")))
        logging.info("하이킨아시 30분 %s 봉: 후보 %s종목(프로그램 줄어 뺌 %s) → 신호 %s %s · 횡보 %s · R 이상 %s · 봉 부족 %s", f"{end:%H:%M}",
                     len(picks), cut, len(out), ", ".join(n for _, n, _, _ in out),
                     ", ".join(tally["chop"]) or "없음", ", ".join(tally["risk"]) or "없음", ", ".join(tally["short"]) or "없음")
        return out
