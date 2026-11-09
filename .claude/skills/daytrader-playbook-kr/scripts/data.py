"""데이터 로더. 1분봉 CSV -> 종목별/일자별 Day 객체.

CSV 필수 컬럼: datetime, symbol, open, high, low, close, volume
선택 컬럼  : value(거래대금), buy_volume, sell_volume(체결 주체 구분 거래량),
             vi(0/1, 해당 바가 VI 단일가 구간), catalyst(0/1, 재료 뉴스 확인 시점 이후 1),
             prev_close(수정주가 기준 전일 종가를 직접 제공할 때),
             rvol_base(같은 시각 누적거래량 기준값을 직접 제공할 때. 있으면 1분봉 이력 대신 사용)
일봉 CSV(선택, load_daily): date,symbol,open,high,low,close,volume[,value]
  주면 일봉 이력(hist)·전일 종가를 1분봉이 아니라 이 파일에서 만든다 (1분봉이 띄엄띄엄 있을 때 필수).
datetime 형식: "YYYY-MM-DD HH:MM[:SS]" (거래소 현지시간, 타임존 표기 없음)
바 라벨: 기본은 바 시작 시각. 데이터가 바 종료 시각 라벨이면 label="end" 로 로드.
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class Bar:
    t: dt.datetime
    o: float
    h: float
    l: float
    c: float
    v: float
    value: float = 0.0
    buy_v: float | None = None
    sell_v: float | None = None
    vi: int = 0
    catalyst: int = 0
    rvol_base: float | None = None


@dataclass
class DailyBar:
    date: dt.date
    o: float
    h: float
    l: float
    c: float
    v: float
    value: float


@dataclass
class Day:
    symbol: str
    date: dt.date
    bars: list  # 세션 내 연속매매 바만
    prev_close: float | None = None
    hist: list = field(default_factory=list)  # 이전 일봉(오래된 것 -> 최근)
    rvol_base: dict = field(default_factory=dict)  # "HH:MM" -> 직전 N일 같은 시각 누적거래량 평균
    prev_bars: list = field(default_factory=list)  # 직전 거래일 세션 바 (볼륨 프로파일용)
    daily: DailyBar | None = None  # 당일 일봉 (미래 정보! 전략에서 사용 금지, 리포트용)


def _f(row, key, default=None):
    v = row.get(key)
    if v is None or v == "":
        return default
    return float(v)


def parse_time(s: str) -> dt.time:
    h, m = s.split(":")[:2]
    return dt.time(int(h), int(m))


def load_bars(patterns, label: str = "start", bar_minutes: int = 1) -> dict:
    """여러 CSV(글롭 패턴 허용)를 읽어 {symbol: [Bar,...]} (시간순) 반환."""
    if isinstance(patterns, str):
        patterns = [patterns]
    files = []
    for p in patterns:
        files.extend(sorted(glob.glob(p)) or [p])
    out = defaultdict(list)
    shift = dt.timedelta(minutes=bar_minutes) if label == "end" else dt.timedelta(0)
    for fp in files:
        with open(fp, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                t = dt.datetime.fromisoformat(row["datetime"].strip()) - shift
                b = Bar(
                    t=t,
                    o=float(row["open"]), h=float(row["high"]), l=float(row["low"]), c=float(row["close"]),
                    v=float(row["volume"]),
                    value=_f(row, "value", 0.0) or 0.0,
                    buy_v=_f(row, "buy_volume"), sell_v=_f(row, "sell_volume"),
                    vi=int(_f(row, "vi", 0) or 0), catalyst=int(_f(row, "catalyst", 0) or 0),
                    rvol_base=_f(row, "rvol_base"),
                )
                if b.value == 0.0:
                    b.value = b.c * b.v
                pc = _f(row, "prev_close")
                if pc:
                    b.__dict__["prev_close"] = pc
                out[row["symbol"].strip()].append(b)
    for s in out:
        out[s].sort(key=lambda b: b.t)
    return dict(out)


def load_daily(path: str) -> dict:
    """일봉 CSV -> {symbol: [DailyBar,...]} (날짜순)."""
    out = defaultdict(list)
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            v = float(row["volume"])
            c = float(row["close"])
            out[row["symbol"].strip()].append(DailyBar(
                dt.date.fromisoformat(row["date"].strip()), float(row["open"]), float(row["high"]),
                float(row["low"]), c, v, _f(row, "value", 0.0) or c * v))
    for s in out:
        out[s].sort(key=lambda d: d.date)
    return dict(out)


def load_universe(path: str) -> set:
    """매매 대상 CSV(date,symbol) -> {(date, symbol)}. 그 날짜 장 시작 전에 알 수 있는 목록이어야 한다."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {(dt.date.fromisoformat(r["date"].strip()), r["symbol"].strip()) for r in csv.DictReader(f)}


def build_days(bars_by_symbol: dict, inst, hist_days: int = 60, rvol_days: int = 20, daily: dict | None = None,
               universe: set | None = None):
    """종목별로 Day 객체를 시간순으로 생성한다. 각 Day 에는 '그날 장 시작 전까지' 알 수 있는 정보만 담는다.

    daily: load_daily 결과. 주면 hist·전일 종가를 일봉에서 만든다 (당일 이전 일봉만).
    universe: load_universe 결과. 주면 그 (날짜, 종목)만 Day 로 내보낸다 (이력 계산에는 나머지 날도 쓴다).
    """
    s_start, s_end = parse_time(inst.session_start), parse_time(inst.session_end)
    days_out = []
    for sym, bars in bars_by_symbol.items():
        by_date = defaultdict(list)
        for b in bars:
            by_date[b.t.date()].append(b)
        hist: deque = deque(maxlen=hist_days)
        cum_hist: deque = deque(maxlen=rvol_days)
        prev_session: list = []
        for d in sorted(by_date):
            all_bars = by_date[d]
            sess = [b for b in all_bars if s_start <= b.t.time() < s_end]
            today = DailyBar(d, all_bars[0].o, max(b.h for b in all_bars), min(b.l for b in all_bars),
                             all_bars[-1].c, sum(b.v for b in all_bars), sum(b.value for b in all_bars))
            explicit_pc = all_bars[0].__dict__.get("prev_close")
            if daily is not None:
                dh = [x for x in daily.get(sym, []) if x.date < d][-hist_days:]
                prev_close = explicit_pc or (dh[-1].c if dh else None)
            else:
                dh = list(hist)
                prev_close = explicit_pc or (hist[-1].c if hist else None)
            base = {}
            if sess and sess[0].rvol_base is not None:
                base = {b.t.strftime("%H:%M"): b.rvol_base for b in sess if b.rvol_base}
            elif cum_hist:
                acc = defaultdict(list)
                for m in cum_hist:
                    for k, v in m.items():
                        acc[k].append(v)
                base = {k: sum(v) / len(v) for k, v in acc.items()}
            if sess and (universe is None or (d, sym) in universe):
                days_out.append(Day(sym, d, sess, prev_close, dh, base, prev_session, today))
            cum, m = 0.0, {}
            for b in sess:
                cum += b.v
                m[b.t.strftime("%H:%M")] = cum
            if m:
                cum_hist.append(m)
            hist.append(today)
            prev_session = sess
    days_out.sort(key=lambda d: (d.date, d.symbol))
    return days_out


def resample(bars: list, minutes: int, anchor: dt.time) -> list:
    """세션 시작(anchor) 기준 N분봉으로 묶는다. 라벨은 버킷 시작 시각."""
    if minutes <= 1:
        return list(bars)
    out: list = []
    cur_key = None
    for b in bars:
        mins = (b.t.hour * 60 + b.t.minute) - (anchor.hour * 60 + anchor.minute)
        k = mins // minutes
        if k != cur_key:
            start = dt.datetime.combine(b.t.date(), anchor) + dt.timedelta(minutes=k * minutes)
            out.append(Bar(start, b.o, b.h, b.l, b.c, b.v, b.value,
                           b.buy_v, b.sell_v, b.vi, b.catalyst))
            cur_key = k
        else:
            x = out[-1]
            x.h, x.l, x.c = max(x.h, b.h), min(x.l, b.l), b.c
            x.v += b.v
            x.value += b.value
            if b.buy_v is not None:
                x.buy_v = (x.buy_v or 0) + b.buy_v
            if b.sell_v is not None:
                x.sell_v = (x.sell_v or 0) + b.sell_v
            x.vi = max(x.vi, b.vi)
            x.catalyst = max(x.catalyst, b.catalyst)
    return out
