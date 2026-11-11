"""🌀 프랙탈 사이클 — 불장단타왕 '차트로 국장 씹어 먹는 80억 트레이더의 코스피 관점'(2026-11-11 영상) 규칙 (2026-11-11 사용자 '3' = 둘 다).

영상 요지: 큰 상승 뒤 고점을 찍은 종목은 같은 순서로 무너진다 — 매물대에서 옆으로 비빔 → 내려오는 일봉 50일선을 기다림
→ 50일선에 닿으면 한 번 더 크게 빠짐 → 상승 출발점으로 돌아감. 바닥은 오래 옆으로 기고(거래량 터짐), 이평선이 내려와 봉과 만나고,
봉이 일봉 VWMA100 위에 올라타 그 선을 밟을 때. 손절·익절·보유 기간은 영상에 없어 아래 매도는 사용자에게 보낸 예시(C) 그대로.

일봉 (전 거래일까지, daily_ohlcv — 9-14 뒤는 daily_regular 정규장 값이 있으면 그것), MA50 = 종가 50일 단순평균,
VWMA100 = Σ(종가×거래량)/Σ거래량 100일.
A. 무너지는 국면 (실전·모의 모든 매수에서 제외):
   큰 상승 = 최근 120일 고가 H ≥ 그 앞 250일(120~370일 전) 최저가 P × 2,
   종가 < H × 0.7, MA50 < 20일 전 MA50, 종가 < MA50 < VWMA100.
B. 바닥 매수 (모의만, 다음 날 09:00):
   최근 120일 중 A 인 날 ≥ 60, 최근 40일 (최고가−최저가)/종가 ≤ 25%, 그 40일 안 거래량 ≥ 20일 평균 × 2 인 날 ≥ 2,
   |MA50 − 종가|/종가 ≤ 3%, |VWMA100 − 종가|/종가 ≤ 5%, 최근 3일 종가 > VWMA100,
   마지막 날 저가 ≤ VWMA100 × 1.01 이고 종가 > VWMA100 (선을 밟음).
C. 매도: 전 거래일 종가 < VWMA100 이면 09:00 매도 (손절·익절·15:19 정리 없음).
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.screener.intraday_signals import Signal

KIND = "프랙탈 바닥"
REGULAR_DB = os.path.join(PROJECT_ROOT, "data", "daily_regular.duckdb")
RISE, DROP_FROM_H = 2.0, 0.7
A_MIN_DAYS, BOX_DAYS, BOX_WIDTH, VOL_MULT, VOL_DAYS = 60, 40, 0.25, 2.0, 2
MA_NEAR, VW_NEAR, ABOVE_DAYS, TOUCH = 0.03, 0.05, 3, 0.01
BUY_START, BUY_END = time(9, 0), time(9, 30)
MIN_VALUE = 1e9          # 전날 대금 10억↑만 (체결 가능성)


def _load(day: date, db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    conn = duckdb.connect(db_path, read_only=True)
    try:
        df = conn.execute("""SELECT d.code, d.date, d.high, d.low, d.close, d.volume, d.value, s.name FROM daily_ohlcv d
                             JOIN stocks s USING(code) WHERE d.date < ? AND d.date >= ? - INTERVAL 560 DAY""", [day, day]).df()
    finally:
        conn.close()
    try:   # 9-14 뒤 daily_ohlcv 종가는 20:00 애프터 종가 → 정규장 값이 있으면 덮어씀
        rc = duckdb.connect(REGULAR_DB, read_only=True)
        reg = rc.execute("SELECT code, date, high, low, close, volume FROM daily_regular WHERE date < ?", [day]).df()
        rc.close()
        if len(reg):
            df = df.merge(reg, on=["code", "date"], how="left", suffixes=("", "_r"))
            for c in ("high", "low", "close", "volume"):
                df[c] = df[f"{c}_r"].fillna(df[c])
            df = df.drop(columns=[f"{c}_r" for c in ("high", "low", "close", "volume")])
    except Exception:
        logging.exception("프랙탈: daily_regular 읽기 실패 — daily_ohlcv 값만 씀")
    return df.sort_values(["code", "date"])


def _features(g: pd.DataFrame) -> pd.DataFrame:
    c, v = g["close"].astype(float), g["volume"].astype(float)
    g = g.copy()
    g["ma50"] = c.rolling(50).mean()
    g["vwma"] = (c * v).rolling(100).sum() / v.rolling(100).sum()
    h120 = g["high"].rolling(120).max()
    p_before = g["low"].shift(120).rolling(250, min_periods=120).min()
    g["A"] = ((h120 >= p_before * RISE) & (c < h120 * DROP_FROM_H) & (g["ma50"] < g["ma50"].shift(20))
              & (c < g["ma50"]) & (g["ma50"] < g["vwma"]))
    g["a_days"] = g["A"].astype(int).rolling(120).sum()
    width = (g["high"].rolling(BOX_DAYS).max() - g["low"].rolling(BOX_DAYS).min()) / c
    big = (v >= v.rolling(20).mean() * VOL_MULT).astype(int).rolling(BOX_DAYS).sum()
    above = (c > g["vwma"]).astype(int).rolling(ABOVE_DAYS).sum()
    g["B"] = ((g["a_days"] >= A_MIN_DAYS) & (width <= BOX_WIDTH) & (big >= VOL_DAYS)
              & ((g["ma50"] - c).abs() / c <= MA_NEAR) & ((g["vwma"] - c).abs() / c <= VW_NEAR)
              & (above >= ABOVE_DAYS) & (g["low"] <= g["vwma"] * (1 + TOUCH)) & (c > g["vwma"]))
    return g


class FractalContext:
    """스캐너 시작 때 한 번: A(무너지는 국면) 종목, B(바닥 매수) 후보, VWMA100 이탈 종목."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH) -> None:
        self.day = day
        df = _load(day, db_path)
        last = []
        for code, g in df.groupby("code", sort=False):
            if len(g) < 120:
                continue
            last.append(_features(g).iloc[-1])
        t = pd.DataFrame(last)
        self.collapse: dict[str, str] = {}
        self.picks: list[tuple[str, str, float, float]] = []
        self.below_vwma: set[str] = set()
        if t.empty:
            return
        for r in t.itertuples():
            if bool(r.A):
                self.collapse[r.code] = (f"🌀 무너지는 국면 — 큰 상승 뒤 고점 −30% 아래·50일선 하락·종가 {r.close:,.0f} < 50일선 "
                                         f"{r.ma50:,.0f} < VWMA100 {r.vwma:,.0f} ({r.date:%m-%d})")
            if bool(r.B) and (r.value or 0) >= MIN_VALUE:
                self.picks.append((r.code, r.name, float(r.close), float(r.vwma)))
            if not np.isnan(r.vwma) and r.close < r.vwma:
                self.below_vwma.add(r.code)
        logging.info("프랙탈: 무너지는 국면 %s종목 (매수 제외), 바닥 매수 후보 %s종목 %s", len(self.collapse), len(self.picks),
                     ", ".join(n for _, n, _, _ in self.picks))

    def skip_reason(self, code: str) -> Optional[str]:
        return self.collapse.get(code)


class FractalWatcher:
    """09:00~09:30 첫 확인 때 B 후보를 모의 매수 신호로 (하루 한 번)."""

    def __init__(self, ctx: FractalContext, done: set) -> None:
        self.ctx = ctx
        self.done = set(done)

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if not (BUY_START <= now.time() <= BUY_END):
            return []
        out = []
        for code, name, close, vwma in self.ctx.picks:
            if code in self.done:
                continue
            self.done.add(code)
            out.append((code, name, "프랙탈", Signal(ts=now.replace(tzinfo=None, second=0, microsecond=0), kind=KIND, price=close,
                                                     level=vwma, stop=None,
                                                     reason=f"🌀 바닥 매수 — 오래 옆으로 긴 뒤 이평선이 내려와 만나고 일봉 VWMA100 {vwma:,.0f} 을 밟음 "
                                                            f"(전날 종가 {close:,.0f}) · 손절·익절 없이 종가가 VWMA100 아래로 마감한 다음 날 09:00 매도")))
        return out
