"""🍔 불개미 2026-10-28(수) 주도주 매매일지·관점 VOD 전략 백테스트 (2026-11-22).

영상 규칙 정리: docs/wiki/bulgaemi/bulgaemi_1028_strategy.md (보고서), docs/wiki/bulgaemi/hamburger.md 9장.
실전·모의 코드는 바꾸지 않음 — 이 파일은 백테스트용 규칙 함수와 실행기만 담음.

비교
  (a) H4  지금 햄버거 모의 규칙 (전날 대금 상위 40 · 기준봉 · 위치 0~+3% · 익절 2% · 전저점 손절)
  (b) V   영상 전략 그대로 (rules 는 아래 VideoParams / video_day)
  (c) V + 영웅문 조건식 1차 필터 (햄버거1 · 햄버거2 · 불개미검증, data/condition_filter/hits.duckdb) — 신호 봉 시각까지 그날 조건에 걸린 종목만

공통 원칙 (backtest-rules)
  - 대상은 그 시각까지 아는 값으로만 고름: 전날 대금 순위·전날까지 일봉, 장중 값은 그 봉까지 누적.
  - 1분봉은 통합(AL) 원가격, 대금 = 거래량 × (고+저+종)/3. 전일 종가는 전날 1분봉 정규장 마지막 종가 (9-14 통합 일봉 함정 회피).
  - 매도: 익절가 닿으면 그 가격, 손절가 닿으면 즉시(같은 봉이면 손절 먼저), 둘 다 아니면 다음 날 09:00 시가. 종가 매도 없음. 비용 0.25%.

    python -m kiwoom_trading.backtest.bulgaemi_1028_bt                 # 전 기간 (a)(b)(c) + 보고서 숫자
    python -m kiwoom_trading.backtest.bulgaemi_1028_bt --day 2026-10-28  # 그날 신호만 (재현율 확인)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Optional

import duckdb
import numpy as np

from kiwoom_trading.common.krx import upper_limit
from kiwoom_trading.strategies.hamburger.rules import (BurgerParams, adj_value, bar_value, pick_reference_days,
                                                          reference_bar, simulate_day, with_params)

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "bulgaemi_1028")
COST = 0.0025
NXT_SWITCH = date(2026, 9, 14)


def _open(name: str):
    """DB 를 읽기 전용으로 엶. 다른 작업이 쓰는 중이면 임시 폴더로 복사해서 엶."""
    src = os.path.join(DATA, name)
    try:
        return duckdb.connect(src, read_only=True)
    except Exception:
        dst = os.path.join(tempfile.gettempdir(), "bg1028_" + name)
        if not os.path.exists(dst):
            shutil.copy(src, dst)
        return duckdb.connect(dst, read_only=True)


# ====================================================================== 자료
class Store:
    def __init__(self) -> None:
        self.mh = _open("minute_history.duckdb")
        self.dm = _open("daily_ohlcv.duckdb")
        self.ix = _open("index.duckdb")
        self.names = dict(self.dm.execute("SELECT code, name FROM stocks").fetchall())
        self.shares = dict(self.dm.execute("SELECT code, listed_shares FROM stocks WHERE listed_shares > 0").fetchall())
        self.cal = [r[0] for r in self.mh.execute("SELECT DISTINCT ts::date d FROM minute_ohlcv ORDER BY 1").fetchall()]
        self.dcal = [r[0] for r in self.dm.execute(
            "SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date >= DATE '2024-09-01' ORDER BY 1").fetchall()]
        self._daily: dict[str, list[dict]] = {}
        self._day: dict[date, dict[str, list[dict]]] = {}
        self._extra: dict[tuple[str, date], list[dict]] = {}
        try:
            self.cache = _open("hamburger_minute_cache.duckdb")
        except Exception:
            self.cache = None

    # ---- 일봉
    def daily(self, code: str) -> list[dict]:
        if code not in self._daily:
            self._daily[code] = [dict(zip(("date", "open", "high", "low", "close", "value"), r)) for r in self.dm.execute(
                "SELECT date, open, high, low, close, value FROM daily_ohlcv WHERE code=? AND date >= DATE '2025-03-01' ORDER BY date",
                [code]).fetchall()]
        return self._daily[code]

    def prev_cal(self, d: date) -> Optional[date]:
        xs = [x for x in self.dcal if x < d]
        return xs[-1] if xs else None

    def top_value(self, day: date, n: int) -> list[str]:
        """day 의 일봉 거래대금 상위 n (보통주). day 는 매매일의 전날로 넘겨야 미래 정보가 아님."""
        return [r[0] for r in self.dm.execute(
            """SELECT d.code FROM daily_ohlcv d JOIN stocks s USING (code) WHERE d.date = ? AND d.value IS NOT NULL
               AND s.name NOT LIKE '%우' AND s.name NOT SIMILAR TO '.*(KODEX|TIGER|ETN|인버스|레버리지|RISE|ACE|SOL|PLUS|KBSTAR|HANARO|KOSEF|ARIRANG).*'
               ORDER BY d.value DESC LIMIT ?""", [day, n]).fetchall()]

    # ---- 1분봉
    def day_bars(self, d: date) -> dict[str, list[dict]]:
        """그날 minute_history 통합 1분봉 전부 {code: [bar]} (08:00~20:00). 하루씩만 캐시."""
        if d not in self._day:
            self._day = {}
            got = defaultdict(list)
            for c, ts, o, h, l, cl, v in self.mh.execute(
                    "SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL' AND ts >= ? AND ts < ? ORDER BY code, ts",
                    [datetime.combine(d, time(0)), datetime.combine(d + timedelta(days=1), time(0))]).fetchall():
                if v and v > 0:
                    got[c].append({"ts": ts, "open": o, "high": h, "low": l, "close": cl, "volume": v})
            self._day[d] = dict(got)
        return self._day[d]

    def bars(self, code: str, d: date) -> list[dict]:
        if d in self._day:
            return self._day[d].get(code, [])
        key = (code, d)
        if key not in self._extra:
            rows = self.mh.execute("SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE exchange='AL' AND code=? AND ts >= ? AND ts < ? ORDER BY ts",
                                   [code, datetime.combine(d, time(0)), datetime.combine(d + timedelta(days=1), time(0))]).fetchall()
            if not rows and self.cache is not None:
                rows = self.cache.execute("SELECT ts, open, high, low, close, volume FROM bars WHERE code=? AND day=? ORDER BY ts", [code, d]).fetchall()
            if len(self._extra) > 20000:
                self._extra.clear()
            self._extra[key] = [{"ts": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows if r[5]]
        return self._extra[key]

    def _load_lastclose(self) -> None:
        self._lc = {}
        for c, d, cl in self.mh.execute(
                """SELECT code, ts::date, arg_max(close, ts) FROM minute_ohlcv WHERE exchange='AL' AND volume > 0
                   AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '15:30' GROUP BY 1, 2 HAVING max(CAST(ts AS TIME)) >= TIME '15:19'""").fetchall():
            self._lc[(c, d)] = float(cl)

    def prev_close(self, code: str, d: date) -> Optional[float]:
        """전일 정규장 종가: 전날 1분봉 15:19 이후 마지막 정규장 봉 → (9-14 전) 일봉 종가."""
        if not hasattr(self, "_lc"):
            self._load_lastclose()
        pd = self.prev_cal(d)
        if pd is None:
            return None
        if (code, pd) in self._lc:
            return self._lc[(code, pd)]
        if pd < NXT_SWITCH:
            r = next((x for x in self.daily(code) if x["date"] == pd), None)
            return float(r["close"]) if r else None
        return None


def regular(bars: list[dict]) -> list[dict]:
    return [b for b in bars if time(9, 0) <= b["ts"].time() <= time(15, 30)]


# ====================================================================== 시장 분위기 (U / N+ / N- / D, regime.py 와 같은 기준)
def build_regime(st: Store) -> dict[date, dict]:
    """09:10 판정. K1z = 코스피 09:09 마지막 값 전일 대비 ÷ 20일 등락 표준편차, M0 = 전날 대금 상위 200 의 09:09 종가 전일 대비 중앙값,
    dd52 = 전날 코스피 종가 ÷ 직전 250일 최고 종가 − 1. U: K1z ≥ 1 또는 M0 ≥ 2% / D: K1z ≤ −1 또는 M0 ≤ −1.5% / 나머지 dd52 > −10% 면 N+, 아니면 N-."""
    path = os.path.join(OUT, "regime.pkl")
    if os.path.exists(path):
        got = pickle.load(open(path, "rb"))
        if set(st.cal) <= set(got):
            return got
    kd = dict(st.ix.execute("SELECT date, close FROM idx_daily WHERE code='001' ORDER BY date").fetchall())
    kdays = sorted(kd)
    k909 = {}
    for ts, cl in st.ix.execute("SELECT ts, close FROM idx_min WHERE code='001' AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '09:09' ORDER BY ts").fetchall():
        k909[ts.date()] = cl
    out = {}
    for d in st.cal:
        if d not in kd:
            continue
        i = kdays.index(d)
        if i < 251:
            continue
        pc = kd[kdays[i - 1]]
        rets = [kd[kdays[j]] / kd[kdays[j - 1]] - 1 for j in range(i - 20, i)]
        sd = float(np.std(rets))
        k1 = (k909[d] / pc - 1) if d in k909 else None
        dd52 = pc / max(kd[kdays[j]] for j in range(i - 251, i)) - 1
        pdd = st.prev_cal(d)
        codes = st.top_value(pdd, 200) if pdd else []
        bars = st.day_bars(d)
        chg = []
        for c in codes:
            b = [x for x in bars.get(c, []) if time(9, 0) <= x["ts"].time() < time(9, 10)]
            pcl = st.prev_close(c, d)
            if b and pcl and b[0]["ts"].time() <= time(9, 1):
                chg.append(b[-1]["close"] / pcl - 1)
        m0 = float(np.median(chg)) if len(chg) >= 30 else None
        k1z = k1 / sd if (k1 is not None and sd) else None
        if k1z is None or m0 is None:
            reg = None
        elif k1z <= -1 or m0 <= -0.015:
            reg = "D"
        elif k1z >= 1 or m0 >= 0.02:
            reg = "U"
        else:
            reg = "N+" if dd52 > -0.10 else "N-"
        out[d] = dict(K1=k1, K1z=k1z, M0=m0, dd52=dd52, reg=reg)
    os.makedirs(OUT, exist_ok=True)
    pickle.dump(out, open(path, "wb"))
    return out


# ====================================================================== 공통: 매도 처리
def exit_trade(st: Store, code: str, d: date, bars: list[dict], j: int, px: float, stop: float, tp: Optional[float],
               last_bar: time = time(15, 30)) -> tuple[float, datetime, str]:
    """bars[j] 봉부터 보유. 손절 먼저, 익절, 둘 다 아니면 다음 날 09:00 시가 (없으면 그날 마지막 정규장 종가, 표시)."""
    for b in bars[j:]:
        if b["ts"].time() > last_bar:
            break
        if b["low"] <= stop:
            return min(stop, b["open"]), b["ts"], "손절"
        if tp and b["high"] >= tp:
            return max(tp, b["open"]), b["ts"], "익절"
    nd = next((x for x in st.cal if x > d), None)
    if nd:
        nb = [x for x in st.bars(code, nd) if time(9, 0) <= x["ts"].time() <= time(9, 5)]
        if nb:
            o = nb[0]["open"]
            # 받은 날 사이 가격 기준이 바뀐 경우(분할 등) 버림
            if abs(o / px - 1) < 0.35:
                return o, nb[0]["ts"], "다음 날 09:00"
    r = regular(bars)
    return (r[-1]["close"] if r else px), (r[-1]["ts"] if r else bars[-1]["ts"]), "자료 없음(종가)"


@dataclass
class Trade:
    tag: str
    d: date
    code: str
    name: str
    sig_ts: datetime
    entry_ts: datetime
    entry: float
    exit_ts: datetime
    exit: float
    reason: str
    ret: float
    reg: Optional[str] = None
    info: dict = field(default_factory=dict)


# ====================================================================== (a) H4 기준선
H4 = with_params(BurgerParams(), tp=0.02, tp_large=0.02)
H4_TOP = 40


def run_h4_day(st: Store, d: date, reg: Optional[str]) -> list[Trade]:
    """지금 햄버거 모의(H4)와 같은 선정·판정. 매도만 공통 규칙(15:19 정리 대신 다음 날 09:00)으로 다시 계산."""
    pd = st.prev_cal(d)
    if pd is None:
        return []
    out = []
    p = replace(H4, exit_at=time(15, 30))
    for code in st.top_value(pd, H4_TOP):
        rows = st.daily(code)
        if len([r for r in rows if r["date"] < d]) < 25:
            continue
        cands, today_env = pick_reference_days(rows, d, H4)
        refs = []
        for c in cands[:H4.max_refs]:
            rb = reference_bar(st.bars(code, c["date"]), c["prev_close"], H4)
            if rb:
                refs.append((c, rb))
        if not refs:
            continue
        best, ref = max(refs, key=lambda x: x[1]["value"])
        mult = H4.env_mult if (today_env and not best["env_burst"]) else 1.0
        bars = st.bars(code, d)
        pc = st.prev_close(code, d)
        if not bars or not pc:
            continue
        r = simulate_day(bars, pc, ref["value"], best["high_pct"], mult, p, False)
        if r.get("status") != "traded":
            continue
        pos = r["burger"]["pct"]
        if not (0 < pos <= 0.03):
            continue
        e = r["entry"]
        j = next(i for i, b in enumerate(bars) if b["ts"] == e["ts"])
        if bars[j]["low"] <= e["stop"]:            # 체결 봉에서 손절가까지 밀림 (보수적, rules.simulate_day 와 같음)
            px, ts, why = e["stop"], e["ts"], "손절"
        else:
            px, ts, why = exit_trade(st, code, d, bars, j + 1, e["price"], e["stop"], e["tp"])
        out.append(Trade("H4", d, code, st.names.get(code, code), r["breakout"]["ts"], e["ts"], e["price"], ts, px, why,
                         px / e["price"] - 1 - COST, reg, {"ref": f"{best['date']} {ref['ts']:%H:%M} {ref['value'] / 1e8:.0f}억", "pos": pos}))
    return out


# ====================================================================== (b) 영상 전략 (2026-10-28 VOD)
@dataclass(frozen=True)
class VideoParams:
    """영상에서 뽑은 숫자 규칙. 영상에 숫자가 없는 칸은 '정의값' (docs/wiki/bulgaemi/bulgaemi_1028_strategy.md 2장 표)."""
    min_cap: float = 1_500e8        # 시총(전일 종가 기준): 영상 '1조 넘는 종목 위주, 2천억 초반(멜콘·엠에스바이오)은 비중 작게' → 1,500억 이상 (정의값)
    rank_n: int = 100               # 황금키 '대금 상위 4% 이상 상승 종목' → 그 시각 누적 대금 순위 100 안 (실시간 검색기로 찾으니 넓게, 순위 수는 정의값)
    min_day_pct: float = 0.04       # 4% 이상 상승 (영상 화면 황금키 제목)
    mult: float = 1.3               # 햄버거 = 기준봉 × 1.3 이상 (영상: 엠에스바이오 1.04배 '부족', 대한광통신 1.45배·네오셈 1.5배 '됨' 사이 → 정의값)
    min_bar_value: float = 10e8     # 1분 대금 10억 이상 (티에프이 '10억 정도 터지면 올라갈 여건')
    nxt_lift: float = 1 / 3         # 프리장 1분 대금 ≥ 기준봉 × 1/3 이면 15분 규칙 사라짐 (영상 '햄버거의 30~50%')
    wait_min: int = 15              # 9시 15분 규칙 (5일 안 상한가 종목은 생략, 영상)
    kki_room: float = 0.03          # 끼까지 남은 폭 ≥ 3%p (영상 '낮은 구간·끼 남음', 익절 폭 3% 와 맞춤 → 정의값)
    chase: float = 0.01             # 다음 봉 시가가 햄버거 봉 종가 +1% 넘으면 안 삼 (정의값)
    entry: str = "break"            # 'break' 돌파 다음 봉 시가 / 'pull' 햄버거 봉 몸통 절반 지정가 (30분 안)
    pull_wait: int = 30
    tp_up: float = 0.03             # 익절: 보통·상승장 3% (영상 '원래 3% 볼 종목은 3%')
    tp_down: float = 0.02           # 약세장·하락장 2% (영상 '2, 3%만 만족')
    stop_min: float = 0.02          # 손절: 햄버거 봉 저가 −0.5%, 매수가 대비 2~3% 사이로 자름 (영상 '손절 2, 3%')
    stop_max: float = 0.03
    last_entry: time = time(14, 30)  # 정의값 (H4 와 같음)
    skip_regs: tuple = ()           # 쉬는 시장 분위기 (영상 그대로는 없음)
    news_x: float = 0.0             # >0 이면 기준 × news_x 이상 갑자기 터진 봉(뉴스빵 근사)에선 안 사고 5분 뒤 다시 터지는 돌파 햄버거를 기다림
                                    # (영상 멜콘 10:23 93억 → 10:44 50억, 엠에스바이오 10:51 → 10:54. 뉴스 자료가 없어 크기로만 근사, 시험용)


V0 = VideoParams()


def _limit_up_recent(rows: list[dict], d: date, n: int = 5) -> bool:
    """d 전 n거래일 안에 종가 +29% 이상(상한가)이 있었나 (영상 '5일상')."""
    prev = [r for r in rows if r["date"] < d][-(n + 1):]
    return any(prev[i - 1]["close"] and prev[i]["close"] / prev[i - 1]["close"] - 1 >= 0.29 for i in range(1, len(prev)))


def video_reference(st: Store, code: str, d: date, ref_cache: dict) -> Optional[dict]:
    """기준봉·끼. 상장 25거래일 안 종목은 상장 둘째 날부터 앞선 날(첫날 포함) 중 고가 등락률 8% 이상인 날로 (영상 '첫날 캔들이 기준')."""
    key = (code, d)
    if key in ref_cache:
        return ref_cache[key]
    rows = st.daily(code)
    prev = [r for r in rows if r["date"] < d]
    out = None
    new = len(prev) < 25 and bool(rows) and rows[0]["date"] >= date(2025, 6, 2)     # 신규 상장 (일봉 시작 = 상장일)
    if prev and (len(prev) >= 25 or new):
        # 영상: '고점 찍고 많이 내려온 날보다 당장 많이 오른 날' → 최근 20거래일 중 고가 +8%↑ 양봉인 가장 가까운 날 하나 (빅웨이브 10-26, 안랩 10-27,
        # 원익홀딩스 10-26, 대한광통신 10-21, 엠에스바이오 10-26). 강의 기준일의 '대금 2배'·전날 환경 맞추기는 이 영상에 없어서 뺌.
        def base_of(i):                                   # 상장 첫날은 시가 대비 (영상 '시가 대비 24%')
            return prev[i - 1]["close"] if i else (prev[0]["open"] if new else None)
        lo = max(0, len(prev) - 20)
        pick = None
        for i in range(len(prev) - 1, lo - 1, -1):
            r, b0 = prev[i], base_of(i)
            if not b0 or r["close"] <= r["open"] and not (new and i == 0) or r["high"] / b0 - 1 < 0.08:
                continue
            if i >= 2 and prev[i - 2]["close"] and prev[i - 1]["close"] / prev[i - 2]["close"] - 1 >= 0.29:
                continue                                   # 상한가 다음 날은 기준일로 안 씀 (강의)
            pick = (r, b0)
            break
        if pick:
            rb = reference_bar(st.bars(code, pick[0]["date"]), pick[1], H4)
            if rb:
                # 끼 = 최근 60거래일(상장 뒤 전부) 하루 최고 고가 등락률 (영상: 원익홀딩스 '과거 상한가', 디아이 '10/1 14%·9/21 15%')
                kk = [prev[i]["high"] / base_of(i) - 1 for i in range(max(0, len(prev) - 60), len(prev)) if base_of(i)]
                out = {"value": rb["value"], "ts": rb["ts"], "kki": max(kk), "ref_date": pick[0]["date"], "new": new}
    ref_cache[key] = out
    return out


def intraday_rank(day: dict[str, list[dict]], prev_close: dict[str, float]) -> tuple[list[time], dict[str, np.ndarray], dict[str, np.ndarray]]:
    """09:00~15:30 분마다 누적 정규장 대금 순위·등락률. 반환 (분 목록, {code: 순위 배열}, {code: 등락률 배열})."""
    grid = [time(9 + (m // 60), m % 60) for m in range(0, 391)]
    gi = {t: i for i, t in enumerate(grid)}
    codes = [c for c in day if prev_close.get(c)]
    cum = np.zeros((len(codes), len(grid)))
    pct = np.full((len(codes), len(grid)), np.nan)
    for k, c in enumerate(codes):
        for b in day[c]:
            i = gi.get(b["ts"].time().replace(second=0))
            if i is None:
                continue
            cum[k, i] += bar_value(b)
            pct[k, i] = b["close"] / prev_close[c] - 1
        cum[k] = np.cumsum(cum[k])
        # 등락률은 마지막 거래 값을 이어 씀
        last = np.nan
        for i in range(len(grid)):
            if np.isnan(pct[k, i]):
                pct[k, i] = last
            else:
                last = pct[k, i]
    order = (-cum).argsort(axis=0).argsort(axis=0) + 1 if codes else np.zeros((0, len(grid)))
    return grid, {c: order[k] for k, c in enumerate(codes)}, {c: pct[k] for k, c in enumerate(codes)}


_CTX: dict = {}


def video_day(st: Store, d: date, reg: Optional[str], p: VideoParams = V0, ref_cache: Optional[dict] = None,
              cond_first: Optional[dict] = None) -> tuple[list[Trade], list[dict]]:
    """영상 전략 하루. cond_first = {code: 첫 조건 걸린 봉 시각} 이면 그 시각 이후 신호만 (조건식 1차 필터).
    반환 (매매, 신호 목록 — 재현율 확인용)."""
    if ref_cache is None:
        ref_cache = {}
    if reg in p.skip_regs:
        return [], []
    day = st.day_bars(d)
    if _CTX.get("d") != d:
        pcs = {c: st.prev_close(c, d) for c in day}
        pcs = {c: v for c, v in pcs.items() if v}
        _CTX.clear()
        _CTX.update(d=d, pcs=pcs, r=intraday_rank(day, pcs))
    pcs = _CTX["pcs"]
    grid, rank, pct = _CTX["r"]
    gi = {t: i for i, t in enumerate(grid)}
    trades, sigs = [], []
    for code, bars in day.items():
        pc = pcs.get(code)
        nm = st.names.get(code, "")
        if not pc or code not in rank or not nm or nm.endswith("우") or any(x in nm for x in ("KODEX", "TIGER", "ETN", "인버스", "레버리지", "RISE", "ACE ", "SOL ", "PLUS ", "KBSTAR", "HANARO")):
            continue
        sh = st.shares.get(code)
        if not sh or sh * pc < p.min_cap:
            continue
        rk = rank[code]
        # 그 시각 대금 순위 30 안에 한 번도 못 든 종목은 바로 넘김 (빠르게)
        if rk[:gi[p.last_entry] + 1].min() > p.rank_n:
            continue
        ref = video_reference(st, code, d, ref_cache)
        if not ref or ref["value"] <= 0:
            continue
        rows = st.daily(code)
        lu5 = _limit_up_recent(rows, d)
        thr = max(ref["value"] * p.mult, 0)
        pre = [b for b in bars if b["ts"].time() < time(9, 0)]
        nxt_lift = any(bar_value(b) >= ref["value"] * p.nxt_lift for b in pre)
        gate = time(9, 0) if (lu5 or nxt_lift) else time(9, p.wait_min)
        run_high = max((b["high"] for b in pre), default=None)
        news_ts = None
        for j, b in enumerate(bars):
            t = b["ts"].time()
            if t < time(9, 0):
                continue
            prev_high = run_high
            run_high = b["high"] if run_high is None else max(run_high, b["high"])
            if t > p.last_entry:
                break
            if t < gate or b["close"] <= b["open"]:
                continue
            v = adj_value(b)
            if v < thr or bar_value(b) < p.min_bar_value:
                continue
            if prev_high is not None and b["high"] <= prev_high:
                continue                                   # 고점 돌파가 아님
            i = gi.get(t.replace(second=0))
            if i is None or rk[i] > p.rank_n or not (pct[code][i] >= p.min_day_pct):
                continue
            bpct = b["close"] / pc - 1
            if ref["kki"] - bpct < p.kki_room:
                continue                                   # 끼를 거의 다 씀 (높은 구간)
            if p.news_x:
                if news_ts is None and v >= ref["value"] * p.news_x:
                    news_ts = b["ts"]
                    continue
                if news_ts is not None and b["ts"] < news_ts + timedelta(minutes=5):
                    continue
            if cond_first is not None:
                ft = cond_first.get(code)
                if ft is None or ft > b["ts"]:
                    continue
            sig = {"code": code, "name": nm, "ts": b["ts"], "value": bar_value(b), "adj": v, "ref": ref["value"],
                   "x": v / ref["value"], "pct": bpct, "kki": ref["kki"], "rank": int(rk[i]), "ref_date": ref["ref_date"]}
            sigs.append(sig)
            # 매수
            if p.entry == "break":
                if j + 1 >= len(bars):
                    break
                nb = bars[j + 1]
                if nb["ts"].time() > time(15, 19) or nb["open"] > b["close"] * (1 + p.chase):
                    break                                  # 놓친 돌파는 쫓지 않음 (영상)
                k, px = j + 1, float(nb["open"])
            else:
                lim = (b["open"] + b["close"]) / 2
                k = next((x for x in range(j + 1, len(bars)) if bars[x]["ts"] <= b["ts"] + timedelta(minutes=p.pull_wait)
                          and bars[x]["ts"].time() <= p.last_entry and bars[x]["low"] <= lim), None)
                if k is None:
                    break
                px = float(min(lim, bars[k]["open"]))
            stop = min(px * (1 - p.stop_min), max(px * (1 - p.stop_max), b["low"] * 0.995))
            tp = px * (1 + (p.tp_down if reg in ("N-", "D") else p.tp_up))
            if p.entry == "pull" and bars[k]["low"] <= stop:       # 지정가 체결 봉에서 손절가까지 밀림
                ex, ets, why = stop, bars[k]["ts"], "손절"
            elif p.entry == "pull":
                ex, ets, why = exit_trade(st, code, d, bars, k + 1, px, stop, tp)
            else:
                ex, ets, why = exit_trade(st, code, d, bars, k, px, stop, tp)
            trades.append(Trade("V", d, code, nm, b["ts"], bars[k]["ts"], px, ets, float(ex), why, float(ex) / px - 1 - COST, reg,
                                {**sig, "stop": stop, "tp": tp}))
            break                                          # 종목당 하루 한 번
    return trades, sigs


def cond_first_hits(d: date, cond: str) -> dict:
    """data/condition_filter/hits.duckdb 에서 그날 조건(h1/h2/bg)에 처음 걸린 봉 시각 {code: ts}."""
    global _HITS
    if "_HITS" not in globals() or _HITS is None:
        _HITS = _open(os.path.join("condition_filter", "hits.duckdb"))
    return dict(_HITS.execute(f"SELECT code, min(ts) FROM hits WHERE d = ? AND {cond} GROUP BY 1", [d]).fetchall())


_HITS = None


# ====================================================================== 평가
def stats(ts: list[Trade]) -> dict:
    """건수·승률·합계(건당 100만 원 기준, 만 원)·건당 평균·손익비·PF·최대 낙폭·앞뒤 절반·최고 10건 뺀 합·최고 5일 뺀 합·★."""
    n = len(ts)
    if n == 0:
        return {"n": 0}
    r = np.array([t.ret for t in ts])
    win, loss = r[r > 0], r[r <= 0]
    days = sorted({t.d for t in ts})
    half = days[len(days) // 2]
    a = [t.ret for t in ts if t.d < half]
    b = [t.ret for t in ts if t.d >= half]
    byday = defaultdict(float)
    for t in ts:
        byday[t.d] += t.ret
    eq = np.cumsum([byday[d] for d in sorted(byday)])
    mdd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    top5d = sorted(byday.values(), reverse=True)
    srt = np.sort(r)[::-1]
    out = dict(n=n, days=len(byday), win=float((r > 0).mean()), sum=float(r.sum()), mean=float(r.mean()),
               payoff=float(win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else None,
               pf=float(win.sum() / -loss.sum()) if len(loss) and loss.sum() < 0 else None, mdd=mdd,
               a=float(np.mean(a)) if a else None, b=float(np.mean(b)) if b else None, na=len(a), nb=len(b),
               ex10=float(srt[10:].sum()), ex5d=float(sum(top5d[5:])))
    out["star"] = bool(n >= 15 and out["a"] is not None and out["b"] is not None and out["a"] > 0 and out["b"] > 0 and out["ex5d"] > 0)
    return out


def by_key(ts: list[Trade], key) -> dict:
    g = defaultdict(list)
    for t in ts:
        g[key(t)].append(t)
    return {k: stats(v) for k, v in sorted(g.items(), key=lambda x: str(x[0]))}


def account_sim(ts: list[Trade], capital: float, slots: int = 3) -> dict:
    """계좌 시뮬: 시작 금액, 동시 보유 최대 slots 종목, 한 종목 = 그때 평가 금액 ÷ slots (현금 안에서), 주식 수는 내림.
    1주도 못 사면 '돈 부족'으로 건너뜀. 같은 시각엔 파는 것 먼저. 비용 0.25% (산 금액 기준)."""
    ev = []
    for i, t in enumerate(ts):
        ev.append((t.entry_ts, 1, i))
        ev.append((t.exit_ts, 2 if t.exit_ts <= t.entry_ts else 0, i))   # 산 봉에서 바로 판 매매는 산 다음에 처리
    ev.sort()
    cash, held, curve, skipped, done = capital, {}, [], 0, 0
    for ts_, kind, i in ev:
        t = ts[i]
        if kind in (0, 2):
            if i in held:
                q = held.pop(i)
                cash += q * t.exit - q * t.entry * COST
                done += 1
        else:
            if len(held) >= slots:
                skipped += 1
                continue
            equity = cash + sum(q * ts[j].entry for j, q in held.items())
            alloc = min(cash, equity / slots)
            q = int(alloc // t.entry)
            if q <= 0:
                skipped += 1
                continue
            cash -= q * t.entry
            held[i] = q
        curve.append(cash + sum(q * ts[j].entry for j, q in held.items()))
    final = cash + sum(q * ts[j].exit for j, q in held.items())
    arr = np.array([capital] + curve + [final])
    mdd = float(((np.maximum.accumulate(arr) - arr) / np.maximum.accumulate(arr)).max())
    return dict(final=final, ret=final / capital - 1, mdd=mdd, done=done, skipped=skipped)


def fill_check(st: Store, ts: list[Trade], size: float = 1e6) -> dict:
    """체결 가능성: 매수 봉이 상한가에 붙어 있었나(고가 = 저가 = 상한가), 매수 봉 대금이 1억(100만 원의 100배) 미만인가, 매수 봉 대금 중앙값,
    다음 봉 시가 대비 호가 2칸 미끄러지면 건당 평균이 얼마나 줄어드나."""
    from kiwoom_trading.common.krx import tick_size
    locked = thin = 0
    vals, slip = [], []
    for t in ts:
        b = next((x for x in st.bars(t.code, t.d) if x["ts"] == t.entry_ts), None)
        pc = st.prev_close(t.code, t.d)
        slip.append(2 * tick_size(t.entry) / t.entry)
        if b is None:
            continue
        vals.append(bar_value(b))
        if pc and b["high"] == b["low"] and b["high"] >= upper_limit(pc):
            locked += 1
        if bar_value(b) < size * 100:
            thin += 1
    return dict(n=len(ts), locked=locked, thin=thin, med_value=float(np.median(vals)) if vals else None,
                slip2=float(np.mean(slip)) if slip else None)


# ====================================================================== 실행
VARIANTS = {
    "V": V0,                                                     # (b) 영상 전략 그대로
    "V·눌림 매수": replace(V0, entry="pull"),
    "V·배수 2.0": replace(V0, mult=2.0),
    "V·대금 30위": replace(V0, rank_n=30),
    "V·시총 1조": replace(V0, min_cap=1e12),
    "V·익절 늘 3%": replace(V0, tp_down=0.03),
    "V·하락장·약세장 쉼": replace(V0, skip_regs=("D", "N-")),
    "V·뉴스빵 기다림(4배)": replace(V0, news_x=4.0),
}
CONDS = {"햄버거1": "h1", "햄버거2": "h2", "불개미검증": "bg"}

# 2026-10-27·28 영상 속 종목·시각 (재현율 확인). (날짜, 코드, 이름, 영상 시각, 영상 판정)
VIDEO_TARGETS = [
    ("2026-10-27", "179880", "멜콘", "09:08~09:22", "해볼 만했음 (장 초 고점 돌파 상따)"),
    ("2026-10-27", "425420", "티에프이", "09:00~", "실제 매매 +1.7%"),
    ("2026-10-27", "253590", "네오셈", "10:15", "실제 매매 본전 (−0.7%)"),
    ("2026-10-27", "0013Y0", "엠에스바이오", "10:51~11:26", "실제 매매 +600만 (손절 뒤 재매수)"),
    ("2026-10-28", "003160", "디아이", "09:00", "9시 땡 매수는 잘함, 14~15% 뒤 눌림은 위험"),
    ("2026-10-28", "0035S0", "빅웨이브로보틱스", "09:09~09:16", "해볼 만했음"),
    ("2026-10-28", "030530", "원익홀딩스", "09:30", "해볼 만했음 (놓침)"),
    ("2026-10-28", "053800", "안랩", "11:05", "해볼 만했음 (안 함)"),
    ("2026-10-28", "010170", "대한광통신", "10:32", "해볼 만했음 (안 함)"),
    ("2026-10-28", "005930", "삼성전자", "09:0x", "해볼 만했음 (빈집털이 일봉)"),
    ("2026-10-28", "064400", "LG씨엔에스", "10:21", "실제 매매 수수료 손절"),
    ("2026-10-28", "179880", "멜콘", "10:23 / 10:44", "실제 매매 주력 (+약 2천만 평가)"),
    ("2026-10-28", "222800", "심텍", "—", "위험 (프로그램 −400억)"),
    ("2026-10-28", "353200", "대덕전자", "—", "위험 (프로그램 −250억)"),
    ("2026-10-28", "007810", "코리아써키트", "10:20", "위험 (프로그램 −80억)"),
]


def summarize(name: str, ts: list[Trade], st: Store) -> dict:
    s = stats(ts)
    s["name"] = name
    if not ts:
        return s
    s["month"] = {k: (v["n"], v["sum"]) for k, v in by_key(ts, lambda t: t.d.strftime("%Y-%m")).items()}
    s["reg"] = {str(k): {kk: v.get(kk) for kk in ("n", "mean", "sum", "win")} for k, v in by_key(ts, lambda t: t.reg).items()}
    s["why"] = {k: v["n"] for k, v in by_key(ts, lambda t: t.reason).items()}
    s["acc100k"] = account_sim(ts, 1e5, slots=1)        # 10만 원은 한 번에 한 종목 (작은 돈은 나누면 못 사는 종목이 많음)
    s["acc1m"] = account_sim(ts, 1e6, slots=3)
    # 최근 석 달 (2026-08-20~)
    rec = [t for t in ts if t.d >= date(2026, 8, 20)]
    s["recent"] = stats(rec)
    s["acc100k_recent"] = account_sim(rec, 1e5, slots=1) if rec else None
    s["acc1m_recent"] = account_sim(rec, 1e6, slots=3) if rec else None
    s["fill"] = fill_check(st, ts)
    return s


def run_all(days: Optional[list[date]] = None) -> dict:
    st = Store()
    reg = build_regime(st)
    days = days or st.cal[:-1]                      # 마지막 날은 다음 날 09:00 이 없어 뺌
    res: dict[str, list[Trade]] = defaultdict(list)
    sigs: dict[str, list[dict]] = defaultdict(list)
    ref_cache: dict = {}
    for i, d in enumerate(days):
        rg = reg.get(d, {}).get("reg")
        res["H4"] += run_h4_day(st, d, rg)
        for name, p in VARIANTS.items():
            tr, sg = video_day(st, d, rg, p, ref_cache)
            res[name] += tr
            if name == "V":
                sigs["V"] += [dict(s, d=d) for s in sg]
        for cname, ck in CONDS.items():
            cf = cond_first_hits(d, ck)
            tr, sg = video_day(st, d, rg, V0, ref_cache, cond_first=cf)
            res[f"V+{cname}"] += tr
            sigs[f"V+{cname}"] += [dict(s, d=d) for s in sg]
        if i % 20 == 0:
            print(f"{i}/{len(days)} {d} " + " ".join(f"{k} {len(v)}" for k, v in res.items()), flush=True)
    os.makedirs(OUT, exist_ok=True)
    pickle.dump({"trades": dict(res), "sigs": dict(sigs), "reg": reg}, open(os.path.join(OUT, "result.pkl"), "wb"))
    summ = {k: summarize(k, v, st) for k, v in res.items()}
    json.dump(summ, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    return {"trades": dict(res), "sigs": dict(sigs), "summary": summ}


def recall(res: dict) -> list[dict]:
    """영상 종목·날을 V(그리고 조건식 필터)가 신호로 잡았나."""
    out = []
    for d, code, name, vt, verdict in VIDEO_TARGETS:
        dd = date.fromisoformat(d)
        row = {"d": d, "code": code, "name": name, "video_time": vt, "verdict": verdict}
        for key in ["V", "V+햄버거1", "V+햄버거2", "V+불개미검증"]:
            s = [x for x in res["sigs"].get(key, []) if x["d"] == dd and x["code"] == code]
            t = [x for x in res["trades"].get(key, []) if x.d == dd and x.code == code]
            row[key] = (f"{s[0]['ts']:%H:%M} ×{s[0]['x']:.1f}" + (f" → {t[0].reason} {t[0].ret:+.1%}" if t else "")) if s else "—"
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="")
    ap.add_argument("--report", action="store_true", help="저장된 result.pkl 로 요약만 다시 계산")
    a = ap.parse_args()
    if a.report:
        res = pickle.load(open(os.path.join(OUT, "result.pkl"), "rb"))
        st = Store()
        res["summary"] = {k: summarize(k, v, st) for k, v in res["trades"].items()}
        json.dump(res["summary"], open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        json.dump(recall(res), open(os.path.join(OUT, "recall.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for k, s in res["summary"].items():
            if s.get("n"):
                print(f"{'★' if s['star'] else ' '} {k:22s} {s['n']:5d}건 건당 {s['mean']:+.2%} 합계 {s['sum'] * 100:+7.0f}만 | 10만(1칸) {s['acc100k']['final']:,.0f} "
                      f"({s['acc100k']['done']}건) 100만(3칸) {s['acc1m']['final']:,.0f} ({s['acc1m']['done']}건) 낙폭 {s['acc1m']['mdd']:.0%}")
        return
    if a.day:
        st = Store()
        reg = build_regime(st)
        d = date.fromisoformat(a.day)
        tr, sg = video_day(st, d, reg.get(d, {}).get("reg"))
        for s in sg:
            print(f"신호 {s['ts']:%H:%M} {s['name']}({s['code']}) {s['value'] / 1e8:.0f}억 기준 {s['ref'] / 1e8:.0f}억 ×{s['x']:.1f} 위치 {s['pct']:+.1%} 끼 {s['kki']:.0%} 순위 {s['rank']}")
        for t in tr:
            print(f"매매 {t.name} {t.entry_ts:%H:%M} {t.entry:,.0f} → {t.reason} {t.exit_ts:%m-%d %H:%M} {t.exit:,.0f} = {t.ret:+.2%}")
        return
    res = run_all()
    for k, s in res["summary"].items():
        if s.get("n"):
            print(f"{'★' if s['star'] else ' '} {k:22s} {s['n']:5d}건 승률 {s['win']:.0%} 건당 {s['mean']:+.2%} 합계 {s['sum'] * 100:+7.0f}만 손익비 {s['payoff'] or 0:.2f} "
                  f"PF {s['pf'] or 0:.2f} 낙폭 {s['mdd'] * 100:.0f}만 | 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%} | 최고10건 빼면 {s['ex10'] * 100:+.0f}만 최고5일 빼면 {s['ex5d'] * 100:+.0f}만 "
                  f"| 10만 계좌 {s['acc100k']['final']:,.0f} 100만 {s['acc1m']['final']:,.0f}")
    for r in recall(res):
        print(r)
    json.dump(recall(res), open(os.path.join(OUT, "recall.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    # 모듈 이름으로 다시 불러 실행 → result.pkl 의 Trade 가 '__main__.Trade' 가 아니라 이 모듈 경로로 저장됨 (다른 스크립트에서 바로 읽힘)
    from kiwoom_trading.backtest.bulgaemi_1028_bt import main as _main
    _main()
