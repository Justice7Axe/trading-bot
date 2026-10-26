"""🇺🇸 간밤 미국 지수 — 나스닥 종합(^IXIC)·다우(^DJI)·나스닥100(^NDX)·나스닥100 선물(NQ=F).

2026-10-27 사용자: "NDAQ, .IXIC, .DJI 모두 상승이면 국장도 상승 출발, 하락이면 하락 출발일 경우가 많다 → 코드·스킬·실전·가상 매매에 반영".
(NDAQ 는 나스닥 거래소 회사 주식이라 지수로는 나스닥100 ^NDX 와 선물 NQ=F 를 같이 본다.)

- 자료: Yahoo Finance chart API (키 없음). 미국 날짜 d 의 종가는 한국 d+1 새벽(05:00~06:00)에 확정.
- 한국 날짜 D 의 '간밤' = 미국 날짜 < D 인 마지막 거래일의 종가 등락(전날 종가 대비).
- us_daily(symbol, date, open, high, low, close) → data/index.duckdb (백테스트·분석용). 장중 실행은 fetch() 로 바로 받는다.

    python -m kiwoom_trading.common.us_market --backfill     # 5년 저장
    python -m kiwoom_trading.common.us_market                # 오늘 아침 간밤 요약 출력
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import requests

SYMBOLS = {"^IXIC": "나스닥", "^DJI": "다우", "^NDX": "나스닥100"}
FUTURE = ("NQ=F", "나스닥100 선물")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
NY = timezone(timedelta(hours=-5))   # 날짜만 쓰므로 서머타임 차이는 무시(장 마감 16:00 → 날짜 같음)


def _chart(symbol: str, rng: str = "10d", interval: str = "1d") -> list[tuple[date, float, float, float, float]]:
    r = requests.get(URL.format(symbol), params={"range": rng, "interval": interval},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for t, o, h, l, c in zip(res.get("timestamp") or [], q["open"], q["high"], q["low"], q["close"]):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, NY).date()
        out.append((d, o or c, h or c, l or c, c))
    return out


@dataclass
class Overnight:
    us_date: date
    changes: dict            # {이름: 등락률(비율)}
    future: Optional[float]  # 나스닥100 선물: 미국 종가 시점 대비 지금 등락(비율), 없으면 None

    @property
    def direction(self) -> str:
        """세 지수가 모두 + → '상승', 모두 − → '하락', 섞이면 '혼조'."""
        v = list(self.changes.values())
        if v and all(x > 0 for x in v):
            return "상승"
        if v and all(x < 0 for x in v):
            return "하락"
        return "혼조"

    @property
    def nasdaq(self) -> float:
        return self.changes.get("나스닥", 0.0)

    def text(self) -> str:
        parts = " · ".join(f"{k} {v * 100:+.2f}%" for k, v in self.changes.items())
        fut = f" · 선물(지금) {self.future * 100:+.2f}%" if self.future is not None else ""
        return f"🇺🇸 간밤 미국({self.us_date:%m-%d}) {self.direction}: {parts}{fut}"


def overnight_from_rows(rows_by_name: dict, kr_day: date) -> Optional[Overnight]:
    """rows_by_name = {이름: [(date, o, h, l, c), ...]} 에서 한국 날짜 kr_day 의 간밤 등락."""
    ch = {}
    us_date = None
    for name, rows in rows_by_name.items():
        rs = [r for r in sorted(rows) if r[0] < kr_day]
        if len(rs) < 2:
            continue
        ch[name] = rs[-1][4] / rs[-2][4] - 1
        us_date = rs[-1][0] if us_date is None else max(us_date, rs[-1][0])
    return Overnight(us_date, ch, None) if ch else None


def fetch(kr_day: Optional[date] = None) -> Optional[Overnight]:
    """지금 받아서 kr_day(기본 오늘) 아침의 간밤 미국 지수 등락. 실패하면 None."""
    kr_day = kr_day or date.today()
    try:
        rows = {name: _chart(sym) for sym, name in SYMBOLS.items()}
    except Exception:
        logging.exception("미국 지수 받기 실패")
        return None
    ov = overnight_from_rows(rows, kr_day)
    if ov is None:
        return None
    try:   # 선물: 지금 값 ÷ 전 거래일 정산 — 미국 장 마감 뒤 움직임까지 들어감
        f = _chart(FUTURE[0], rng="5d", interval="1d")
        if len(f) >= 2:
            ov.future = f[-1][4] / f[-2][4] - 1
    except Exception:
        logging.warning("나스닥 선물 받기 실패")
    return ov


def backfill(db_path: str, rng: str = "5y") -> int:
    import duckdb
    db = duckdb.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS us_daily(symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, PRIMARY KEY(symbol, date))")
    n = 0
    for sym in list(SYMBOLS) + [FUTURE[0]]:
        rows = _chart(sym, rng=rng)
        db.executemany("INSERT OR REPLACE INTO us_daily VALUES (?, ?, ?, ?, ?, ?)", [(sym, *r) for r in rows])
        n += len(rows)
    db.close()
    return n


def load_daily(conn) -> dict:
    """index.duckdb us_daily → {이름: [(date, o, h, l, c)]} (백테스트용)."""
    out = {}
    for sym, name in SYMBOLS.items():
        out[name] = conn.execute("SELECT date, open, high, low, close FROM us_daily WHERE symbol=? ORDER BY date", [sym]).fetchall()
    return out


def overnight_map(conn, kr_days) -> dict:
    """{한국 날짜: Overnight} — 백테스트에서 그날 아침 알 수 있던 값만."""
    rows = load_daily(conn)
    return {d: overnight_from_rows(rows, d) for d in kr_days}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()
    if args.backfill:
        from kiwoom_trading.ingestion.collectors.index_collector import INDEX_DB
        print("저장", backfill(INDEX_DB), "행")
    else:
        ov = fetch()
        print(ov.text() if ov else "받기 실패")
