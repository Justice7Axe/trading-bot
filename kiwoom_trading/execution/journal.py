"""📓 매매일지 (2026-11-06 사용자 '항상 각 매매에 대한 매매일지를 작성하고 있지?' → '매매일지를 보고 복기하면서 매매 전략을 개선해야 돼').

표 기록(real_trades·paper_trades·ledger_trades·buy_signals)과 장중 로그를 모아 하루 서술형 일지를 만든다.
  1. 머리말: 09:10 시장 분위기 판정 · 코스피·코스닥 등락 · 간밤 미국
  2. 🔴 실전 매매 한 건씩: 포착 이유 · 매수/매도 · 손익 · 규칙대로였나 · 1분봉 차트(data/journal/YYYYMMDD/<code>.png)
  3. 실전 못 산 신호: 이유 + 그날 종가(또는 다음 날 시가) → 놓친 기회인지 피한 손실인지
  4. 🟢 모의 · 🟣 가상: 매매별 묶음 요약 + 눈에 띄는 것
  5. 📝 복기 칸: 손절·직접 매도(규칙대로였으면)·손절선 1% 안 접근·놓친 +5%·연속 손실
출력: docs/journal/YYYY-MM-DD.md (문서 문체), 텔레그램은 짧은 요약 + 실전 차트 사진.
주간: --week → docs/journal/week-YYYY-Www.md.

    python -m kiwoom_trading.execution.journal [YYYYMMDD] [--send] [--db PATH]
    python -m kiwoom_trading.execution.journal --week [YYYYMMDD] [--send]
    python -m kiwoom_trading.execution.journal --since 20261016 [--until 20261105]   # 여러 날 파일만
"""
import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT

DATA = os.path.join(PROJECT_ROOT, "data")
DOCS = os.path.join(PROJECT_ROOT, "docs", "journal")
CHARTS = os.path.join(DATA, "journal")
SCREENER_DB = os.path.join(DATA, "screener.duckdb")
SNAPSHOT_DB = os.path.join(DATA, "screener_snapshot.duckdb")
REAL_START = date(2026, 10, 26)
PAPER_COST = 0.0025
NEAR_STOP = 0.01          # 손절선까지 1% 안으로 다가가면 표시
BIG_MOVE = 0.05           # 모의·가상 눈에 띄는 것 / 놓친 신호 +5%
REG_OPEN, REG_CLOSE = time(9, 0), time(15, 30)

# 매매 이름 (번호 옆에 항상 이름 — CLAUDE.md 3장). 실전은 real.PLAYS 를 그대로 쓰고, 나머지는 여기서 채운다.
KIND_LABEL = {
    "주도주 신고가": "6️⃣ 주도주 신고가", "저항 돌파": "2️⃣ 저항 돌파", "약세장 인버스": "5️⃣ 약세장 인버스",
    "📕 상한가 풀림": "📕 홍인기 상한가 풀림", "상승장 장 초": "1️⃣ 상승장 장 초", "시가 탈환": "🔁 시가 탈환",
    "카페 테마 대장": "☕ 카페 테마 대장", "역행 강세 종가": "4️⃣ 역행 강세 종가", "[디앤서] 종가 재돌파": "🌙 종가 재돌파",
    "주도주 추세": "7️⃣ 주도주 추세", "막힌 고점 돌파": "3️⃣ 막힌 고점 돌파", "주도주 모양": "🎯 주도주 모양",
    "돌파 후 눌림": "🎯 돌파 후 눌림", "눌림 돌파": "🎯 눌림 돌파", "지지 반등": "🎯 지지 반등", "대형주 수급": "🎯 대형주 수급",
    "장 초 공통점": "🧭 장 초 공통점", "[디앤서] 14:30 주도주 종가": "🧭 디앤서 14:30 주도주 종가", "인버스 갭": "인버스 갭",
    "햄버거": "🍔 햄버거", "애프터 정배열": "🪜 애프터 정배열", "중심선": "📍 중심선",
}
PLAY_RULE: dict[str, tuple[Optional[float], Optional[float]]] = {}   # 종류 → (익절, 손절)
try:
    from kiwoom_trading.execution import real as _R
    for _k, (_lb, _tp, _sl) in _R.PLAYS.items():
        KIND_LABEL[_k] = _lb
        PLAY_RULE[_k] = (_tp, _sl)
except Exception:   # 실전 모듈을 못 불러와도 일지는 만든다
    logging.exception("real.PLAYS 불러오기 실패 — 기본 이름표 사용")
LABEL_KIND = {v: k for k, v in KIND_LABEL.items()}
NEXT_OPEN_KINDS = ("역행 강세 종가", "[디앤서] 종가 재돌파")   # 결과를 다음 날 시가로 보는 매매 (종가·애프터 매수)
BOOK_LABEL = {"카페 대장": "☕ 카페 테마 대장 (가상 장부)", "수급 확인": "📕 홍인기 상한가 풀림 (수급 확인)",
              "수급 없이": "📕 홍인기 상한가 풀림 (수급 없이)", "전황 11시": "📘 전황 11시", "10만 원": "💰 10만 원 계좌"}

# 페이지 끝 약어 풀이 (API·IP·DB·URL·HTTP 제외) — 본문에 처음 나온 순서대로
ABBR = {
    "KRX": "Korea Exchange, 한국거래소 정규장 시세",
    "NXT": "Nextrade, 대체거래소 (프리장·애프터장)",
    "AL": "통합 시세 (KRX + NXT)",
    "ETF": "Exchange Traded Fund, 상장지수펀드",
    "PNG": "Portable Network Graphics, 그림 파일 형식",
    "R": "Risk, 한 번 매매에서 감수한 손실 폭 대비 배수",
    "VWAP": "Volume Weighted Average Price, 거래량 가중 평균 가격",
}


def label(kind: Optional[str]) -> str:
    return KIND_LABEL.get(kind or "", kind or "?")


def book_label(book: str) -> str:
    if book in BOOK_LABEL:
        return BOOK_LABEL[book]
    if book.startswith("일정 "):
        return "📅 " + book
    if book in ("돌파·대장", "돌파", "강한 쪽", "애프터 급락"):
        return f"📕 홍인기 상따 밖 · {book}"
    return book


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _won(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:+,.0f}원"


def _px(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:,.0f}"


# ------------------------------------------------------------------ 자료 연결
class Ctx:
    """읽기 전용 연결 묶음. 없는 파일·잠긴 파일은 None (그 항목만 빠짐)."""

    def __init__(self, db: Optional[str] = None) -> None:
        self.scr = self._open_screener(db)
        self.daily = self._open(os.path.join(DATA, "daily_ohlcv.duckdb"))
        self.hist = self._open(os.path.join(DATA, "minute_history.duckdb"))
        self.reg = self._open(os.path.join(DATA, "daily_regular.duckdb"))
        self.idx = self._open(os.path.join(DATA, "index.duckdb"))
        self._days: Optional[list[date]] = None

    @staticmethod
    def _open(path: str):
        if not os.path.exists(path):
            return None
        try:
            return duckdb.connect(path, read_only=True)
        except Exception as exc:
            logging.warning("일지: %s 못 엶 — %s", os.path.basename(path), exc)
            return None

    def _open_screener(self, db: Optional[str]):
        for p in ([db] if db else [SCREENER_DB, SNAPSHOT_DB]):   # 본 DB 가 잠겨 있으면 스캐너 사본
            c = self._open(p)
            if c is not None:
                self.scr_path = p
                return c
        raise RuntimeError("screener DB 를 열 수 없음")

    def close(self) -> None:
        for c in (self.scr, self.daily, self.hist, self.reg, self.idx):
            try:
                c and c.close()
            except Exception:
                pass

    def q(self, conn, sql: str, args=()) -> list:
        if conn is None:
            return []
        try:
            return conn.execute(sql, list(args)).fetchall()
        except Exception as exc:
            logging.debug("일지 조회 실패: %s — %s", sql[:80], exc)
            return []

    # 거래일 -----------------------------------------------------------
    def trading_days(self) -> list[date]:
        if self._days is None:
            ds = {r[0] for r in self.q(self.idx, "SELECT DISTINCT date FROM idx_daily WHERE code = '001'")}
            ds |= {r[0] for r in self.q(self.scr, "SELECT DISTINCT date FROM rank_snapshots WHERE date >= '2026-10-01'")}
            self._days = sorted(ds)
        return self._days

    def next_day(self, d: date) -> Optional[date]:
        later = [x for x in self.trading_days() if x > d]
        return later[0] if later else None

    def prev_days(self, d: date, n: int) -> list[date]:
        return [x for x in self.trading_days() if x <= d][-n:]

    # 1분봉 -----------------------------------------------------------
    def bars(self, code: str, d: date, prefer: str = "KRX") -> tuple[str, list]:
        """(거래소, [(ts, o, h, l, c, v)]). 감시 종목 1분봉(KRX → AL) → 1분봉 백필(AL)."""
        order = [prefer, "AL" if prefer == "KRX" else "KRX"]
        for ex in order:
            rows = self.q(self.daily, "SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code = ? AND exchange = ? "
                                      "AND ts >= ? AND ts < ? ORDER BY ts", [code, ex, d, d + timedelta(days=1)])
            if rows:
                return ex, rows
        rows = self.q(self.hist, "SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code = ? AND exchange = 'AL' "
                                 "AND ts >= ? AND ts < ? ORDER BY ts", [code, d, d + timedelta(days=1)])
        return ("AL", rows) if rows else ("", [])

    def close_on(self, code: str, d: date) -> tuple[Optional[float], str]:
        """그날 정규장 종가 (15:30 까지 마지막 1분봉 → 정규장 일봉 → 통합 일봉)."""
        ex, rows = self.bars(code, d)
        reg = [r for r in rows if r[0].time() <= REG_CLOSE]
        if reg:
            return float(reg[-1][4]), f"{ex} 1분봉"
        r = self.q(self.reg, "SELECT close FROM daily_regular WHERE code = ? AND date = ?", [code, d])
        if r and r[0][0]:
            return float(r[0][0]), "정규장 일봉"
        r = self.q(self.daily, "SELECT close FROM daily_ohlcv WHERE code = ? AND date = ?", [code, d])
        if r and r[0][0]:
            return float(r[0][0]), "통합 일봉(애프터 포함)"
        return None, ""

    def open_on(self, code: str, d: date) -> Optional[float]:
        """그날 09:00 정규장 시가."""
        _, rows = self.bars(code, d)
        reg = [r for r in rows if r[0].time() >= REG_OPEN]
        if reg:
            return float(reg[0][1])
        r = self.q(self.reg, "SELECT open FROM daily_regular WHERE code = ? AND date = ?", [code, d])
        return float(r[0][0]) if r and r[0][0] else None


# ------------------------------------------------------------------ 자료 모으기
@dataclass
class RealItem:
    code: str
    name: str
    kind: str
    qty: int
    buy_ts: Optional[datetime]
    buy_price: Optional[float]
    sell_ts: Optional[datetime]
    sell_price: Optional[float]
    reason: str
    pnl: Optional[float]
    status: str
    signal: str = ""
    role: str = ""            # 그날 산 것 / 그날 판 것 / 들고 있음
    flag: str = ""            # 규칙대로였나
    eval_close: Optional[float] = None
    later: str = ""
    near_stop: str = ""
    rule_alt: str = ""
    rule_alt_pnl: Optional[float] = None
    chart: str = ""

    @property
    def ret(self) -> Optional[float]:
        if self.pnl is not None and self.buy_price and self.qty:
            return self.pnl / (self.buy_price * self.qty)
        return None


@dataclass
class Missed:
    code: str
    name: str
    kind: str
    ts: str
    why: str
    signal: str = ""
    sig_price: Optional[float] = None
    out_price: Optional[float] = None
    out_basis: str = ""

    @property
    def ret(self) -> Optional[float]:
        return self.out_price / self.sig_price - 1 if self.out_price and self.sig_price else None


@dataclass
class Group:
    section: str              # 🟢 모의 / 🟣 가상
    name: str
    n: int = 0
    wins: int = 0
    pnl: float = 0.0
    held: int = 0
    notes: list = field(default_factory=list)


@dataclass
class DayJournal:
    day: date
    market: list = field(default_factory=list)
    regime: str = ""
    real: list = field(default_factory=list)
    real_failed: list = field(default_factory=list)
    missed: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    review: list = field(default_factory=list)
    streaks: list = field(default_factory=list)
    has_data: bool = False


def _log_lines(d: date) -> list[str]:
    p = os.path.join(DATA, "logs", f"screener_{d:%Y%m%d}.log")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.readlines()


def _market(ctx: Ctx, d: date, logs: list[str]) -> tuple[str, list[str]]:
    out = []
    trend = ""
    for ln in logs:
        m = re.search(r"코스피 큰 흐름: (\S+) \(.*?52주 고점 대비 ([-+0-9.]+%)", ln)
        if m:
            trend = f"{m.group(1)} (52주 고점 대비 {m.group(2)})"
            break
    row = ctx.q(ctx.scr, "SELECT regime, decided_at, median, kospi_chg, kospi_z, trend FROM market_regime WHERE date = ?", [d])
    regime = ""
    if row:
        rg, at, med, kc, z, tr = row[0]
        regime = rg
        detail = f"대금 상위 주식 중앙 {_pct(med)}" + (f", 코스피 {_pct(kc)} (20일 변동성의 {z:+.2f}배)" if kc is not None and z is not None else "")
        out.append(f"시장 분위기 판정: **{rg}** ({at:%H:%M} 판정) — {detail}" + (f" · 큰 흐름 {tr}" if tr else ""))
    else:
        judged = [ln for ln in logs if "시장 분위기 판정 " in ln and "→" in ln]
        if judged:
            ln = judged[-1]
            m = re.search(r"판정 (\d\d:\d\d): (.+?) → (\S+)", ln)
            if m:
                res = m.group(3)
                weak = any(k in trend for k in ("약세장", "조정"))
                regime = res if res != "보통" else ("하락 흐름 보통 날" if weak else "상승 흐름 보통 날" if trend else "보통 날")
                detail = m.group(2).replace("대금 상위 주식 ", "대금 상위 ").replace(" = 20일 변동성의 ", " (20일 변동성의 ")
                detail = re.sub(r"(-?[0-9.]+배)$", r"\1)", detail) if "(20일" in detail else detail
                out.append(f"시장 분위기 판정: **{regime}** ({m.group(1)} 판정) — {detail}" + (f" · 큰 흐름 코스피 {trend}" if trend else ""))
        elif d < date(2026, 10, 20):
            out.append("시장 분위기 판정: 기록 없음 (판정 기능 시작 전)")
        else:
            out.append("시장 분위기 판정: 기록 없음")
    # 코스피·코스닥 그날 등락
    parts = []
    for code, nm in (("001", "코스피"), ("101", "코스닥")):
        r = ctx.q(ctx.idx, "SELECT close FROM idx_daily WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT 2", [code, d])
        r_day = ctx.q(ctx.idx, "SELECT 1 FROM idx_daily WHERE code = ? AND date = ?", [code, d])
        if len(r) == 2 and r_day:
            parts.append(f"{nm} {r[0][0]:,.2f} ({r[0][0] / r[1][0] - 1:+.2%})")
    if parts:
        out.append("지수 마감: " + " · ".join(parts))
    us = ctx.q(ctx.scr, "SELECT us_date, direction, nasdaq, dow, ndx FROM us_overnight WHERE date = ?", [d])
    if us:
        ud, dr, nq, dw, ndx = us[0]
        out.append(f"간밤 미국({ud:%m-%d}): {dr} — 나스닥 {_pct(nq)} · 다우 {_pct(dw)} · 나스닥100 {_pct(ndx)}")
    return regime, out


def _signal_reason(ctx: Ctx, d: date, code: str, kind: str, before: Optional[datetime]) -> tuple[str, Optional[float]]:
    rows = ctx.q(ctx.scr, "SELECT ts, price, reason FROM buy_signals WHERE date = ? AND code = ? AND kind = ? ORDER BY ts", [d, code, kind])
    if before:
        rows = [r for r in rows if r[0] <= before + timedelta(minutes=2)] or rows
    if rows:
        return (rows[0][2] or "").split("\n")[0].strip(), rows[0][1]
    if kind == "📕 상한가 풀림":   # 실전 📕 는 가상 장부(수급 없이)가 살 때 넘어온다
        r = ctx.q(ctx.scr, "SELECT plan, note, buy_price FROM ledger_trades WHERE date = ? AND code = ? AND book = '수급 없이'", [d, code])
        if r:
            text = " · ".join(x for x in r[0][:2] if x and not str(x).lstrip().startswith("{"))   # plan 은 매도 계획 JSON — 빼고 note 만
            return text[:200], r[0][2]
    return "", None


def _rule_flag(reason: str) -> str:
    r = reason or ""
    if "직접 매도" in r or "사용자" in r:
        return "⚠️ 직접 매도"
    if "손절" in r:
        return "손절 (규칙대로)"
    if "익절" in r:
        return "익절 (규칙대로)"
    if "시초" in r or "09:00" in r or "20일선" in r:
        return "규칙대로 (다음 날 시초 매도)"
    return r or "—"


def _stop_take(kind: str, buy: float) -> tuple[Optional[float], Optional[float]]:
    tp, sl = PLAY_RULE.get(kind, (None, None))
    return (buy * (1 + tp) if tp else None), (buy * (1 - sl) if sl else None)


def _rule_alternative(ctx: Ctx, it: RealItem) -> None:
    """직접 매도 뒤 규칙대로 들고 있었으면: 그날 남은 1분봉에서 손절(먼저)·익절 → 아니면 다음 날 09:00 시가."""
    if not it.sell_ts or not it.buy_price:
        return
    tpx, spx = _stop_take(it.kind, it.buy_price)
    d = it.sell_ts.date()
    _, rows = ctx.bars(it.code, d, "KRX")
    rest = [r for r in rows if it.sell_ts < r[0] + timedelta(minutes=1) and r[0].time() <= REG_CLOSE]
    exit_px, why = None, ""
    for ts, o, h, l, c, v in rest:
        if spx and l <= spx:
            exit_px, why = (min(o, spx) if o < spx else spx), f"{ts:%H:%M} 손절선 {spx:,.0f} 닿음"
            break
        if tpx and h >= tpx:
            exit_px, why = (max(o, tpx) if o > tpx else tpx), f"{ts:%H:%M} 익절가 {tpx:,.0f} 닿음"
            break
    if exit_px is None:
        nd = ctx.next_day(d)
        nx = ctx.open_on(it.code, nd) if nd else None
        if nx:
            exit_px, why = nx, f"손절·익절 안 닿아 {nd:%m-%d} 09:00 시가"
        else:
            cl, _ = ctx.close_on(it.code, d)
            if cl:
                it.rule_alt = (f"규칙대로였으면: 손절·익절 안 닿고 다음 날 09:00 매도 예정 — 다음 날 시가 자료 아직 없음, "
                               f"그날 종가 {cl:,.0f} 기준 {_pct(cl / it.buy_price - 1)}")
            return
    cost = it.buy_price * it.qty * (0.0005 if it.code == "123310" else PAPER_COST)
    alt_pnl = (exit_px - it.buy_price) * it.qty - cost
    it.rule_alt_pnl = alt_pnl
    diff = alt_pnl - (it.pnl or 0)
    it.rule_alt = (f"규칙대로였으면: {why} {exit_px:,.0f} → {_pct(alt_pnl / (it.buy_price * it.qty))} ({_won(alt_pnl)}, 비용 포함) · "
                   f"직접 매도와 차이 {_won(diff)} ({'직접 매도가 나았음' if diff < 0 else '규칙대로가 나았음' if diff > 0 else '같음'})")


def _near_stop(ctx: Ctx, it: RealItem, d: date) -> None:
    if not it.buy_price or "손절" in (it.reason or ""):
        return
    _, spx = _stop_take(it.kind, it.buy_price)
    if not spx:
        return
    _, rows = ctx.bars(it.code, d, "KRX")
    start = it.buy_ts if it.buy_ts and it.buy_ts.date() == d else datetime.combine(d, REG_OPEN)
    end = it.sell_ts if it.sell_ts and it.sell_ts.date() == d else datetime.combine(d, REG_CLOSE)
    lows = [r[3] for r in rows if start <= r[0] + timedelta(minutes=1) and r[0] <= end and r[0].time() <= REG_CLOSE]
    if lows and min(lows) <= spx * (1 + NEAR_STOP):
        lo = min(lows)
        it.near_stop = f"손절선 {spx:,.0f} 에 1% 안으로 다가감 (최저 {lo:,.0f}, 손절선 대비 {lo / spx - 1:+.1%}) — 살아남음"


def _chart(ctx: Ctx, it: RealItem, d: date) -> str:
    """그날 1분봉 + 매수▲·매도▼·손절선 → data/journal/YYYYMMDD/<code>.png."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception:
        logging.warning("matplotlib 없음 — 차트 건너뜀")
        return ""
    in_reg = all(ts is None or ts.date() != d or REG_OPEN <= ts.time() <= REG_CLOSE for ts in (it.buy_ts, it.sell_ts))
    ex, rows = ctx.bars(it.code, d, "KRX" if in_reg else "AL")
    if in_reg:
        rows = [r for r in rows if REG_OPEN <= r[0].time() <= time(15, 35)] or rows
    if not rows:
        return ""
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax, axv) = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [4, 1]})
    xs = list(range(len(rows)))
    w = 0.6
    for x, (ts, o, h, l, c, v) in zip(xs, rows):
        col = "#d62728" if c >= o else "#1f5fbf"
        ax.vlines(x, l, h, color=col, linewidth=0.6)
        ax.add_patch(Rectangle((x - w / 2, min(o, c)), w, max(abs(c - o), 1e-9), color=col, linewidth=0))
        axv.bar(x, v, width=w, color=col)
    ts_list = [r[0] for r in rows]

    def xpos(ts: datetime) -> Optional[int]:
        if ts is None or ts.date() != d:
            return None
        for i, t in enumerate(ts_list):
            if t + timedelta(minutes=1) > ts:
                return i
        return len(ts_list) - 1

    if it.buy_price:
        ax.axhline(it.buy_price, color="#555", linestyle=":", linewidth=0.9, label=f"매수가 {it.buy_price:,.0f}")
        tpx, spx = _stop_take(it.kind, it.buy_price)
        if spx:
            ax.axhline(spx, color="#1f5fbf", linestyle="--", linewidth=0.9, label=f"손절선 {spx:,.0f}")
        if tpx:
            ax.axhline(tpx, color="#d62728", linestyle="--", linewidth=0.9, label=f"익절가 {tpx:,.0f}")
    bx = xpos(it.buy_ts)
    if bx is not None and it.buy_price:
        ax.scatter([bx], [it.buy_price], marker="^", s=140, color="#00a000", zorder=5, label=f"매수 {it.buy_ts:%H:%M}")
    sx = xpos(it.sell_ts)
    if sx is not None and it.sell_price:
        ax.scatter([sx], [it.sell_price], marker="v", s=140, color="#ff7f0e", zorder=5, label=f"매도 {it.sell_ts:%H:%M}")
    step = max(1, len(xs) // 12)
    axv.set_xticks(xs[::step])
    axv.set_xticklabels([t.strftime("%H:%M") for t in ts_list[::step]], fontsize=8)
    res = f" → 매도 {it.sell_price:,.0f} ({_pct(it.ret)})" if it.sell_price and it.sell_ts and it.sell_ts.date() == d else ""
    plain_label = re.sub(r"(\d)️?⃣", r"\g<1>번", label(it.kind))   # 숫자 이모지 → N번
    plain_label = re.sub(r"[^\w\s가-힣·()+\-%.,]", "", plain_label).strip()   # 이모지는 글꼴이 깨져서 뺌
    ax.set_title(f"{d:%m-%d} {it.name}({it.code}) {plain_label} · 매수 {_px(it.buy_price)}{res} · {ex} 1분봉", fontsize=11)
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    axv.grid(alpha=0.2)
    out_dir = os.path.join(CHARTS, f"{d:%Y%m%d}")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{it.code}.png")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def _real(ctx: Ctx, d: date, charts: bool) -> tuple[list[RealItem], list[str]]:
    rows = ctx.q(ctx.scr, """SELECT code, coalesce(name, code), kind, qty, buy_ts, buy_price, sell_ts, sell_price, coalesce(reason, ''), pnl, status, date
                             FROM real_trades
                             WHERE status <> 'failed' AND (date = ? OR sell_ts::date = ? OR (date < ? AND (sell_ts IS NULL OR sell_ts::date > ?)))
                             ORDER BY coalesce(buy_ts, sell_ts)""", [d, d, d, d])
    failed = [f"{r[1]} [{label(r[2])}] {r[3]}주 미체결 취소" for r in
              ctx.q(ctx.scr, "SELECT coalesce(name, code), kind, qty FROM real_trades WHERE status = 'failed' AND date = ?", [d])]
    items = []
    for code, nm, kind, qty, bts, bp, sts, sp, why, pnl, st, bdate in rows:
        it = RealItem(code, nm, kind or "", qty or 0, bts, bp, sts, sp, why, pnl, st)
        sold_today = bool(sts and sts.date() == d)
        it.role = ("그날 사고 그날 팜" if bdate == d and sold_today else "그날 판 것 (전에 산 것)" if sold_today
                   else "그날 사서 들고 넘김" if bdate == d else "들고 있음")
        it.signal, _ = _signal_reason(ctx, bdate, code, it.kind, bts)
        if sold_today:
            it.flag = _rule_flag(why)
        else:
            it.flag = "보유 중"
            cl, _ = ctx.close_on(code, d)
            it.eval_close = cl
            if sts and sts.date() > d and sp:   # 일지를 나중에 만들면 그 뒤 결과도 적는다
                it.later = f"이후 {sts:%m-%d %H:%M} {sp:,.0f} 매도 ({why}) → {_pct(it.ret)} {_won(pnl)}"
        if sold_today and "직접 매도" in it.flag:
            _rule_alternative(ctx, it)
        _near_stop(ctx, it, d)
        if charts:
            try:
                it.chart = _chart(ctx, it, d)
            except Exception:
                logging.exception("일지 차트 실패 %s", code)
        items.append(it)
    return items, failed


_ITEM = re.compile(r"^(.+?)\(([0-9A-Z]{6})\) \[(.+?) (\d\d:\d\d)\]\s*(.*)$")


def _missed(ctx: Ctx, d: date, logs: list[str], bought: set[str]) -> list[Missed]:
    """로그의 '실전 안 삼'(엄격 선정 등 규칙상 대상 아님)·'실전 못 삼'(예수금·추격·하루 1종목 등)."""
    names = {n: c for c, n in ctx.q(ctx.scr, "SELECT DISTINCT code, name FROM buy_signals WHERE date = ?", [d]) if n}
    out: dict[tuple, Missed] = {}
    for ln in logs:
        m = re.search(r"실전 안 삼 (.+?) \[(.+?)\]: (.+)$", ln)
        if m:
            nm, lb, why = m.group(1), m.group(2), m.group(3).strip()
            code = names.get(nm) or next((c for (c,) in ctx.q(ctx.daily, "SELECT code FROM stocks WHERE name = ? LIMIT 1", [nm])), "")
            kind = LABEL_KIND.get(lb, lb)
            key = (code or nm, kind)
            if key not in out:
                ts = ln[11:16]
                out[key] = Missed(code, nm, kind, ts, why.replace("엄격 선정 — ", "엄격 선정: "))
            continue
        m = re.search(r"실전 못 삼 (.*?): (.+)$", ln)
        if not m:
            continue
        head = m.group(1).strip()
        for part in re.split(r"; (?=[^;]{1,40}?\([0-9A-Z]{6}\) \[)", m.group(2).strip()):
            mi = _ITEM.match(part.strip())
            if not mi:
                continue
            nm, code, lb, ts, rest = mi.groups()
            why, _, sig = rest.partition("포착:")
            why = why.strip(" ·") or head
            kind = LABEL_KIND.get(lb, lb)
            key = (code, kind)
            if key not in out:
                out[key] = Missed(code, nm, kind, ts, why, sig.strip()[:150])
    res = []
    for (code, kind), x in out.items():
        if x.code and x.code in bought:
            continue
        if x.code:
            sig, px = _signal_reason(ctx, d, x.code, kind, None)
            x.signal = x.signal or sig[:150]
            x.sig_price = px
            if kind in NEXT_OPEN_KINDS:
                nd = ctx.next_day(d)
                x.out_price = ctx.open_on(x.code, nd) if nd else None
                x.out_basis = f"{nd:%m-%d} 시가" if nd and x.out_price else ""
            else:
                x.out_price, src = ctx.close_on(x.code, d)
                x.out_basis = "그날 종가" if x.out_price else ""
        res.append(x)
    res.sort(key=lambda x: (x.ts, x.name))
    return res


def _paper_net(qty, bp, sp, part_qty, part_price) -> Optional[float]:
    if not bp or not sp or not qty:
        return None
    part = min(part_qty or 0, qty)
    gain = (sp - bp) * (qty - part) + ((part_price or sp) - bp) * part
    return gain - bp * qty * PAPER_COST


def _groups(ctx: Ctx, d: date) -> list[Group]:
    gs: dict[tuple, Group] = {}

    def g(section: str, name: str) -> Group:
        return gs.setdefault((section, name), Group(section, name))

    for nm, kind, qty, bp, sp, sts, why, virt, ovf, pq, pp, bdate in ctx.q(ctx.scr, """
            SELECT name, kind, qty, buy_price, sell_price, sell_ts, coalesce(sell_reason, ''), virtual, overflow, part_qty, part_price, date
            FROM paper_trades WHERE buy_price IS NOT NULL AND status <> 'skipped' AND status <> 'failed'
              AND (sell_ts::date = ? OR (date = ? AND (sell_ts IS NULL OR sell_ts::date > ?)))""", [d, d, d]):
        sec = "🟣 가상" if (virt or ovf) else "🟢 모의"
        name = label(kind) + (" (잔고 밖)" if ovf else " (NXT 가상 체결)" if virt else "")
        grp = g(sec, name)
        if sts and sts.date() == d:
            pnl = _paper_net(qty, bp, sp, pq, pp)
            if pnl is None:
                continue
            grp.n += 1
            grp.wins += pnl > 0
            grp.pnl += pnl
            r = sp / bp - 1 - PAPER_COST
            if abs(r) >= BIG_MOVE or "직접" in why or "사용자" in why:
                grp.notes.append(f"{nm} {bp:,.0f} → {sp:,.0f} {_pct(r)} ({_won(pnl)}) — {why}" + (" · 전날 산 것" if bdate != d else ""))
        else:
            grp.held += 1
    for book, nm, bp, sp, sts, why, pnl, bdate in ctx.q(ctx.scr, """
            SELECT book, name, buy_price, sell_price, sell_ts, coalesce(reason, ''), pnl, date FROM ledger_trades
            WHERE buy_price IS NOT NULL AND (sell_ts::date = ? OR (date = ? AND (sell_ts IS NULL OR sell_ts::date > ?)))""", [d, d, d]):
        grp = g("🟣 가상", book_label(book or "?"))
        if sts and sts.date() == d and pnl is not None:
            grp.n += 1
            grp.wins += pnl > 0
            grp.pnl += pnl
            r = sp / bp - 1 if sp and bp else None
            if r is not None and abs(r) >= BIG_MOVE:
                grp.notes.append(f"{nm} {bp:,.0f} → {sp:,.0f} {_pct(r)} ({_won(pnl)}) — {why}" + (" · 전에 산 것" if bdate != d else ""))
        else:
            grp.held += 1
    return sorted(gs.values(), key=lambda x: (x.section, -abs(x.pnl)))


def _streaks(ctx: Ctx, d: date) -> list[str]:
    """최근 5거래일 같은 매매 연속 손실 (실전 2번↑, 모의 3번↑)."""
    days = ctx.prev_days(d, 5)
    if not days:
        return []
    out = []
    lo, hi = days[0], d + timedelta(days=1)
    real = defaultdict(list)
    for kind, pnl, ts in ctx.q(ctx.scr, "SELECT kind, pnl, sell_ts FROM real_trades WHERE status = 'closed' AND pnl IS NOT NULL "
                                        "AND sell_ts >= ? AND sell_ts < ? ORDER BY sell_ts", [lo, hi]):
        real[kind].append(pnl)
    paper = defaultdict(list)
    for kind, qty, bp, sp, pq, pp in ctx.q(ctx.scr, "SELECT kind, qty, buy_price, sell_price, part_qty, part_price FROM paper_trades "
                                                    "WHERE status = 'closed' AND NOT coalesce(virtual, false) AND NOT coalesce(overflow, false) "
                                                    "AND sell_ts >= ? AND sell_ts < ? ORDER BY sell_ts", [lo, hi]):
        p = _paper_net(qty, bp, sp, pq, pp)
        if p is not None:
            paper[kind].append(p)
    for src, book, need in (("🔴 실전", real, 2), ("🟢 모의", paper, 3)):
        for kind, xs in book.items():
            n = 0
            for p in reversed(xs):
                if p > 0:
                    break
                n += 1
            if n >= need:
                out.append(f"{src} {label(kind)}: 최근 5거래일 마지막 {n}건 연속 손실 (합 {_won(sum(xs[-n:]))})")
    return out


def collect(ctx: Ctx, d: date, charts: bool = True) -> DayJournal:
    j = DayJournal(d)
    logs = _log_lines(d)
    j.regime, j.market = _market(ctx, d, logs)
    if d >= REAL_START:
        j.real, j.real_failed = _real(ctx, d, charts)
        bought = {it.code for it in j.real if it.buy_ts and it.buy_ts.date() == d}
        j.missed = _missed(ctx, d, logs, bought)
    j.groups = _groups(ctx, d)
    j.streaks = _streaks(ctx, d)
    # 복기 칸
    rv = []
    for it in j.real:
        tag = f"{it.name} [{label(it.kind)}]"
        if it.flag.startswith("손절"):
            rv.append(f"손절: {tag} {_pct(it.ret)} {_won(it.pnl)} — 매수 때 시장 '{j.regime or '판정 없음'}', 포착 이유가 맞았는지 차트로 확인할 것")
        if "직접 매도" in it.flag:
            rv.append(f"⚠️ 직접 매도: {tag} {it.reason} → {_pct(it.ret)} {_won(it.pnl)}. " + (it.rule_alt or "규칙대로였으면: 계산할 1분봉 없음"))
        if it.near_stop:
            rv.append(f"손절선 근처: {tag} {it.near_stop}")
    for x in j.missed:
        if x.ret is not None and x.ret >= BIG_MOVE:
            rv.append(f"놓친 +5%↑: {x.name} [{label(x.kind)}] 신호가 {_px(x.sig_price)} → {x.out_basis} {_px(x.out_price)} ({_pct(x.ret)}) — 못 산 이유: {x.why}")
    rv += [f"연속 손실: {s}" for s in j.streaks]
    j.review = rv
    j.has_data = bool(logs or j.real or j.groups or ctx.q(ctx.scr, "SELECT 1 FROM buy_signals WHERE date = ? LIMIT 1", [d])
                      or ctx.q(ctx.scr, "SELECT 1 FROM paper_trades WHERE date = ? LIMIT 1", [d]))
    return j


# ------------------------------------------------------------------ 문서 (문체 '~임/~됨/~함')
def _abbr_footer(text: str) -> str:
    found = []
    for ab in ABBR:
        m = re.search(rf"(?<![A-Za-z]){re.escape(ab)}(?![A-Za-z])", text)
        if m:
            found.append((m.start(), ab))
    if not found:
        return ""
    found.sort()
    return "\n\n---\n약어 풀이\n" + "\n".join(f"- {ab}: {ABBR[ab]}" for _, ab in found) + "\n"


def render_md(j: DayJournal) -> str:
    d = j.day
    L = [f"# 📓 매매일지 {d:%Y-%m-%d} ({'월화수목금토일'[d.weekday()]})", ""]
    L += ["## 시장", ""] + [f"- {x}" for x in j.market] + [""]

    L += ["## 🔴 실전 매매", ""]
    if d < REAL_START:
        L += ["- 실전 매매 시작(2026-10-26) 전이라 없음.", ""]
    elif not j.real:
        L += ["- 오늘 실전 매매 없음.", ""]
    for it in j.real:
        L.append(f"### {label(it.kind)} · {it.name} ({it.code}) — {it.role}")
        if it.signal:
            L.append(f"- 포착 이유: {it.signal}")
        L.append(f"- 매수: {it.buy_ts:%m-%d %H:%M} · {_px(it.buy_price)}원 × {it.qty}주" if it.buy_ts else f"- 매수: {_px(it.buy_price)}원 × {it.qty}주")
        if it.flag == "보유 중":
            if it.eval_close and it.buy_price:
                ev = (it.eval_close - it.buy_price) * it.qty
                L.append(f"- 보유 중: 그날 종가 {it.eval_close:,.0f} 기준 평가 {_pct(it.eval_close / it.buy_price - 1)} ({_won(ev)}, 비용 빼기 전)")
            else:
                L.append("- 보유 중: 그날 종가 자료 없음")
            if it.later:
                L.append(f"- {it.later}")
        else:
            L.append(f"- 매도: {it.sell_ts:%m-%d %H:%M} · {_px(it.sell_price)}원 · 이유: {it.reason}")
            L.append(f"- 손익: {_won(it.pnl)} ({_pct(it.ret)}, 비용 포함)")
            L.append(f"- 규칙대로였나: {it.flag}")
        if it.rule_alt:
            L.append(f"- {it.rule_alt}")
        if it.near_stop:
            L.append(f"- {it.near_stop}")
        if it.chart:
            rel = os.path.relpath(it.chart, DOCS).replace("\\", "/")
            L.append(f"- 1분봉 차트(PNG): `{os.path.relpath(it.chart, PROJECT_ROOT)}`")
            L.append(f"\n![{it.name}]({rel})")
        else:
            L.append("- 1분봉 차트: 1분봉 자료 없음")
        L.append("")
    if j.real:
        closed = [it for it in j.real if it.flag != "보유 중" and it.pnl is not None]
        if closed:
            L += [f"오늘 실현 손익 합계 {_won(sum(it.pnl for it in closed))} ({len(closed)}건, 이긴 매매 {sum(1 for it in closed if it.pnl > 0)}건)임.", ""]
    for f in j.real_failed:
        L.append(f"- {f}")

    if d >= REAL_START:
        L += ["## ⏭ 실전 못 산 신호", ""]
        if not j.missed:
            L += ["- 없음.", ""]
        else:
            L += ["| 시각 | 종목 | 매매 | 못 산 이유 | 신호가 | 결과 | 판정 |", "|---|---|---|---|---|---|---|"]
            for x in j.missed:
                r = x.ret
                verdict = "—" if r is None else ("놓친 기회" if r > 0.005 else "피한 손실" if r < -0.005 else "비슷함")
                L.append(f"| {x.ts} | {x.name} | {label(x.kind)} | {x.why[:70]} | {_px(x.sig_price)} | "
                         f"{(x.out_basis + ' ' + _px(x.out_price) + ' (' + _pct(r) + ')') if r is not None else '자료 없음'} | {verdict} |")
            got = [x.ret for x in j.missed if x.ret is not None]
            if got:
                L += ["", f"결과를 아는 {len(got)}건 평균 {_pct(sum(got) / len(got))} (신호가 대비, 비용 빼기 전)임."]
            L.append("")

    L += ["## 🟢 모의 · 🟣 가상", ""]
    if not j.groups:
        L += ["- 그날 끝난 모의·가상 매매 없음.", ""]
    else:
        L += ["| 구분 | 매매 | 끝난 건수 | 이긴 수 | 손익 합 | 들고 넘김 |", "|---|---|---|---|---|---|"]
        for g in j.groups:
            L.append(f"| {g.section} | {g.name} | {g.n} | {g.wins} | {_won(g.pnl) if g.n else '—'} | {g.held or ''} |")
        notes = [(g, n) for g in j.groups for n in g.notes]
        if notes:
            L += ["", "눈에 띄는 것 (±5% 이상·직접 매도):"]
            L += [f"- {g.section} {g.name}: {n}" for g, n in notes]
        L.append("")

    L += ["## 📝 복기 칸", ""]
    L += [f"- {x}" for x in j.review] if j.review else ["- 자동으로 잡힌 복기 거리 없음."]
    L += ["", "> 이 칸은 자동 표시임. 왜 그렇게 됐는지와 배운 점·개선 후보는 복기 노트(docs/journal/review-YYYY-MM-DD.md)에 씀."]
    body = "\n".join(L)
    return body + _abbr_footer(body)


def render_tg(j: DayJournal) -> str:
    d = j.day
    L = [f"📓 {d:%m-%d} 매매일지"]
    mk = [x.replace("**", "") for x in j.market]
    rest = [x.split(": ", 1)[1] if x.startswith("지수 마감") else x.replace(": ", " ", 1) for x in mk[1:]]
    L.append("📍 " + (j.regime or "시장 판정 없음") + (" · " + " · ".join(rest) if rest else ""))
    if d >= REAL_START:
        closed = [it for it in j.real if it.flag != "보유 중" and it.pnl is not None]
        if not j.real:
            L.append("🔴 오늘 실전 매매 없음")
        else:
            L.append(f"🔴 실전 {len(j.real)}건 · 실현 {_won(sum(it.pnl for it in closed)) if closed else '없음'}")
            for it in j.real:
                head = "⚠️" if "직접" in it.flag else "✅" if (it.pnl or 0) > 0 and it.flag != "보유 중" else "📦" if it.flag == "보유 중" else "❌"
                if it.flag == "보유 중":
                    ev = f" 종가 {_px(it.eval_close)} ({_pct(it.eval_close / it.buy_price - 1)})" if it.eval_close and it.buy_price else ""
                    L.append(f"  {head} {it.name} [{label(it.kind)}] {_px(it.buy_price)} 보유{ev}")
                else:
                    L.append(f"  {head} {it.name} [{label(it.kind)}] {_px(it.buy_price)} → {_px(it.sell_price)} {_pct(it.ret)} {_won(it.pnl)} — {it.reason}")
                if it.rule_alt:
                    L.append("     " + it.rule_alt.split(" · 직접")[0])
        if j.missed:
            big = sorted(j.missed, key=lambda x: -(x.ret if x.ret is not None else -9))
            L.append(f"⏭ 실전 못 산 신호 {len(j.missed)}건" + (" (위 3건)" if len(j.missed) > 3 else ""))
            for x in big[:3]:
                res = f"{x.out_basis} {_pct(x.ret)}" if x.ret is not None else "결과 자료 없음"
                L.append(f"  · {x.name} [{label(x.kind)}] {x.why[:40]} → {res}")
    else:
        L.append("🔴 실전 시작 전")
    for sec in ("🟢 모의", "🟣 가상"):
        gs = [g for g in j.groups if g.section == sec and g.n]
        if gs:
            L.append(f"{sec} {sum(g.n for g in gs)}건 · 이긴 {sum(g.wins for g in gs)} · {_won(sum(g.pnl for g in gs))}  "
                     + " / ".join(f"{g.name} {g.n}건 {_won(g.pnl)}" for g in gs[:4]))
    if j.review:
        L.append("📝 복기: " + str(len(j.review)) + "건")
        L += [f"  · {x[:150]}" for x in j.review[:6]]
    L.append(f"전체: docs/journal/{d:%Y-%m-%d}.md")
    return "\n".join(L)


def write_day(ctx: Ctx, d: date, charts: bool = True) -> tuple[Optional[str], DayJournal]:
    j = collect(ctx, d, charts)
    if not j.has_data:
        return None, j
    os.makedirs(DOCS, exist_ok=True)
    path = os.path.join(DOCS, f"{d:%Y-%m-%d}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_md(j))
    return path, j


# ------------------------------------------------------------------ 주간
def week_days(ctx: Ctx, end: date) -> list[date]:
    mon = end - timedelta(days=end.weekday())
    return [x for x in ctx.trading_days() if mon <= x <= end] or [mon + timedelta(days=i) for i in range((end - mon).days + 1) if i < 5]


def render_week(js: list[DayJournal]) -> tuple[str, str, str]:
    """(md, 텔레그램, 파일 이름)."""
    end = js[-1].day
    y, w, _ = end.isocalendar()
    real = defaultdict(lambda: [0, 0, 0.0])
    paper = defaultdict(lambda: [0, 0, 0.0])
    issues = defaultdict(list)
    day_rows = []
    for j in js:
        closed = [it for it in j.real if it.flag != "보유 중" and it.pnl is not None]
        for it in closed:
            r = real[label(it.kind)]
            r[0] += 1; r[1] += it.pnl > 0; r[2] += it.pnl
        for g in j.groups:
            if g.n:
                r = paper[(g.section, g.name)]
                r[0] += g.n; r[1] += g.wins; r[2] += g.pnl
        for it in j.real:
            if "직접" in it.flag:
                issues["⚠️ 직접 매도"].append(f"{j.day:%m-%d} {it.name} [{label(it.kind)}] {_won(it.pnl)}"
                                            + (f" (규칙대로였으면 {_won(it.rule_alt_pnl)})" if it.rule_alt_pnl is not None else ""))
            if it.flag.startswith("손절"):
                issues["손절"].append(f"{j.day:%m-%d} {it.name} [{label(it.kind)}] {_won(it.pnl)}")
            if it.near_stop:
                issues["손절선 1% 안 접근"].append(f"{j.day:%m-%d} {it.name} [{label(it.kind)}]")
        for x in j.missed:
            if x.ret is not None and x.ret >= BIG_MOVE:
                issues["놓친 +5%↑ 신호"].append(f"{j.day:%m-%d} {x.name} [{label(x.kind)}] {_pct(x.ret)} — {x.why[:40]}")
        for s in j.streaks:
            issues["연속 손실"].append(f"{j.day:%m-%d} {s}")
        miss_known = [x.ret for x in j.missed if x.ret is not None]
        day_rows.append((j.day, j.regime or "—", len(closed), sum(it.pnl for it in closed), len(j.missed),
                         sum(miss_known) / len(miss_known) if miss_known else None, sum(g.pnl for g in j.groups if g.section == "🟢 모의")))
    L = [f"# 📓 주간 매매일지 {y}-W{w:02d} ({js[0].day:%m-%d} ~ {end:%m-%d})", "", "## 날마다", "",
         "| 날짜 | 시장 | 실전 건수 | 실전 손익 | 못 산 신호 | 못 산 신호 평균 | 🟢 모의 손익 |", "|---|---|---|---|---|---|---|"]
    for d, rg, n, p, nm, mr, pp in day_rows:
        L.append(f"| [{d:%m-%d}]({d:%Y-%m-%d}.md) | {rg} | {n} | {_won(p) if n else '—'} | {nm} | {_pct(mr)} | {_won(pp)} |")
    L += ["", "## 🔴 실전 매매별 성적", ""]
    if real:
        L += ["| 매매 | 건수 | 이긴 수 | 손익 합 |", "|---|---|---|---|"]
        L += [f"| {k} | {v[0]} | {v[1]} | {_won(v[2])} |" for k, v in sorted(real.items(), key=lambda kv: kv[1][2])]
        tot = sum(v[2] for v in real.values())
        L += ["", f"주간 실전 실현 손익 합계 {_won(tot)} ({sum(v[0] for v in real.values())}건)임."]
    else:
        L.append("- 이번 주 끝난 실전 매매 없음.")
    L += ["", "## 🟢 모의 · 🟣 가상 매매별 성적", ""]
    if paper:
        L += ["| 구분 | 매매 | 건수 | 이긴 수 | 손익 합 |", "|---|---|---|---|---|"]
        L += [f"| {k[0]} | {k[1]} | {v[0]} | {v[1]} | {_won(v[2])} |" for k, v in sorted(paper.items(), key=lambda kv: (kv[0][0], kv[1][2]))]
    else:
        L.append("- 없음.")
    L += ["", "## 반복 문제", ""]
    if issues:
        L += ["| 문제 | 횟수 | 사례 |", "|---|---|---|"]
        for k, v in issues.items():
            L.append(f"| {k} | {len(v)} | {'<br>'.join(v[:6])} |")
    else:
        L.append("- 자동으로 잡힌 반복 문제 없음.")
    L += ["", "> 반복 문제는 하루 사례로 규칙을 바꾸지 않고, 1년 검증·10만 계좌 시뮬로 판단함 (스킬 trade-journal)."]
    body = "\n".join(L)
    md = body + _abbr_footer(body)
    T = [f"📓 주간 매매일지 {y}-W{w:02d} ({js[0].day:%m-%d}~{end:%m-%d})"]
    if real:
        T.append(f"🔴 실전 {sum(v[0] for v in real.values())}건 · {_won(sum(v[2] for v in real.values()))}")
        T += [f"  {k}: {v[0]}건 이긴 {v[1]} · {_won(v[2])}" for k, v in sorted(real.items(), key=lambda kv: kv[1][2])]
    else:
        T.append("🔴 실전 끝난 매매 없음")
    for sec in ("🟢 모의", "🟣 가상"):
        xs = [(k[1], v) for k, v in paper.items() if k[0] == sec]
        if xs:
            T.append(f"{sec} {sum(v[0] for _, v in xs)}건 · {_won(sum(v[2] for _, v in xs))}")
    if issues:
        T.append("반복 문제: " + " · ".join(f"{k} {len(v)}" for k, v in issues.items()))
    T.append(f"전체: docs/journal/week-{y}-W{w:02d}.md")
    return md, "\n".join(T), f"week-{y}-W{w:02d}.md"


def write_week(ctx: Ctx, end: date, charts: bool = False) -> tuple[Optional[str], str]:
    js = [j for j in (collect(ctx, d, charts) for d in week_days(ctx, end)) if j.has_data]
    if not js:
        return None, ""
    md, tg, fname = render_week(js)
    os.makedirs(DOCS, exist_ok=True)
    path = os.path.join(DOCS, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path, tg


# ------------------------------------------------------------------ 전송·진입점
def send(j: DayJournal, text: str) -> None:
    from kiwoom_trading.common.telegram import send_telegram_message, send_telegram_photo
    send_telegram_message(text)
    for it in j.real:
        if it.chart:
            send_telegram_photo(it.chart, f"📓 {j.day:%m-%d} {it.name} [{label(it.kind)}] {_pct(it.ret) if it.flag != '보유 중' else '보유 중'}")


def run_daily(d: date, send_tg: bool = True, db: Optional[str] = None, week: Optional[bool] = None) -> Optional[str]:
    """20:00 일일 업데이트가 부름: 일지 쓰기·전송, 금요일(또는 week=True)엔 주간도."""
    ctx = Ctx(db)
    try:
        path, j = write_day(ctx, d)
        text = render_tg(j)
        logging.info("📓 매매일지: %s", path or "자료 없음")
        if send_tg:
            send(j, text)   # 매매가 없는 날도 시장 판정·못 산 신호는 보냄
        if week if week is not None else d.weekday() == 4:
            wpath, wtext = write_week(ctx, d)
            logging.info("📓 주간 매매일지: %s", wpath)
            if wpath and send_tg:
                from kiwoom_trading.common.telegram import send_telegram_message
                send_telegram_message(wtext)
        return path
    finally:
        ctx.close()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="📓 매매일지")
    ap.add_argument("day", nargs="?", default="", help="YYYYMMDD (기본: 오늘)")
    ap.add_argument("--send", action="store_true", help="텔레그램 전송")
    ap.add_argument("--db", default=None, help="screener DB (기본: 본 DB, 잠겨 있으면 screener_snapshot.duckdb)")
    ap.add_argument("--week", action="store_true", help="그 주 월~지정일 주간 묶음")
    ap.add_argument("--since", default="", help="YYYYMMDD 부터 여러 날 파일만 (전송 안 함)")
    ap.add_argument("--until", default="", help="--since 끝 날 (기본: 오늘)")
    ap.add_argument("--no-chart", action="store_true")
    a = ap.parse_args()
    p = lambda s: datetime.strptime(s, "%Y%m%d").date()
    d = p(a.day) if a.day else date.today()
    ctx = Ctx(a.db)
    print(f"(screener DB: {os.path.basename(ctx.scr_path)})")
    try:
        if a.since:
            lo, hi = p(a.since), (p(a.until) if a.until else date.today())
            days = [x for x in ctx.trading_days() if lo <= x <= hi]
            made, skipped = [], []
            for x in days:
                path, _ = write_day(ctx, x, not a.no_chart)
                (made if path else skipped).append(x)
            weeks = sorted({x - timedelta(days=x.weekday()) + timedelta(days=4) for x in made})
            for wend in weeks:
                wpath, _ = write_week(ctx, min(wend, hi))
                print("주간:", wpath)
            print("만든 일지:", ", ".join(f"{x:%m-%d}" for x in made) or "없음")
            print("자료 없어 건너뜀:", ", ".join(f"{x:%m-%d}" for x in skipped) or "없음")
            return
        if a.week:
            wpath, wtext = write_week(ctx, d)
            print(wpath); print(wtext)
            if a.send and wpath:
                from kiwoom_trading.common.telegram import send_telegram_message
                send_telegram_message(wtext)
            return
        path, j = write_day(ctx, d, not a.no_chart)
        text = render_tg(j)
        print(path or "자료 없음")
        print(text)
        if a.send:
            send(j, text)
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
