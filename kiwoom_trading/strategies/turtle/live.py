"""🐢 터틀 돌파 — 리처드 데니스 '터틀 매매법' (손절봇 영상 2026-11-14, 2026-11-15 사용자 '모두 추천값', 모의만).
정리 문서: docs/lectures/turtle_richard_dennis.md (3-2 ①~⑮ 모두 ★). 백테스트 안 함 — 숫자는 영상·원문 규칙과 사용자 선택 그대로.

선 (전 거래일까지 정규장 일봉으로, 종목이 처음 대상이 될 때 한 번 — 스캐너가 매일 아침 새로 켜지므로 '장 시작 때 전날 기준으로 다시 계산'):
  20일·55일 최고가 = 오늘을 뺀 직전 20·55거래일 정규장 고가의 최고값 · 10일·20일 최저가 = 직전 10·20거래일 정규장 저가의 최저값.
  N = 진짜 폭(True Range: max(고가−저가, |고가−전일 종가|, |저가−전일 종가|))의 직전 20일 단순 평균.
      원문 규칙서는 첫 값만 단순 평균이고 그 뒤로는 (19 × 전날 N + 오늘 TR) ÷ 20 으로 이어 가지만, 여기서는 매일 단순 20일 평균으로 함 (사용자 확정).
  일봉: 2026-09-14 전은 data/daily_ohlcv.duckdb, 9-14 부터는 data/daily_regular.duckdb(정규장)를 이어 붙임. 9-14 뒤 daily_ohlcv 는
    08:00~20:00 통합 값이라 가격으로는 쓰지 않고 '그 종목이 거래된 날 목록'으로만 씀. daily_regular 에 빠진 날(그날 대금 상위 약 500 밖)은
    minute_history.duckdb 통합(AL) 1분봉 → 앞서 받아 둔 파일 캐시(data/turtle_regular_fill.json) → 키움 통합 1분봉(그날 하루치, 한 확인에 최대 FETCH_BUDGET 번)
    순서로 09:00~15:30 봉(30개↑)을 모아 정규장 일봉으로 채움 (daily_regular 를 만드는 방식과 같음, 받은 값은 파일 캐시에 남겨 다음 날 다시 안 받음).
  수정주가·액면분할로 가격이 튀는 종목 — 이어 붙인 일봉에서 전일 종가 대비 고가·저가·종가가 ±31%(가격 제한폭 30% + 여유) 넘게 벗어난 날이 있거나,
    오늘 기준가가 어제 정규장 종가와 15% 넘게 다르면 그날 빼고 로그.
직전 20일 신호 이김/짐 (실제로 샀든 안 샀든 일봉으로): 직전 약 HIST_ROWS 거래일을 앞에서부터 '20일 돌파에 사서 −2N 손절 또는 10일 최저가 이탈에 파는'
  가상 매매로 따라감 (가상으로 들고 있는 동안 나온 돌파는 새 신호로 안 셈). 산 값 = max(그날 시가, 돌파선), 산 다음 날부터 판정,
  판 값 = min(그날 시가, 닿은 선) — 같은 날 둘 다 닿으면 손절이 먼저라고 봄 (일봉으로는 순서를 몰라 보수적으로, 문서 ③ A).
  마지막 가상 매매가 10일 최저가 이탈로 이익 매도 → '이김' → 오늘 20일 돌파는 건너뜀. −2N 손절이 먼저거나 이탈 매도가 손실 → '짐'.
  아직 안 끝났으면 어제 종가가 산 값보다 위면 '이김(진행 중)', 아니면 '짐(진행 중)'. 앞선 신호가 없으면 건너뛰지 않음.
종목 범위: 📏 변동성 돌파와 같은 KellSelector.pick(theme=False) — 지금 대금 100억↑ & 주식(ETF·ETN·우선주·스팩 뺌) 중 대금 100위 안,
  전날 외인·기관 둘 다 순매도 뺌, 상장 20거래일 안 뺌. ☕ 카페 종목 제한·🌀 무너지는 국면은 paper 공통 관문, 시장 분위기 관문은 안 거름(문서 ⑬ A).
매수 (09:00~15:19, 지금가 = 스캐너가 매분 받는 KRX 대금 순위 현재가 — 1분 안에 찍고 내려온 돌파는 놓쳐도 됨):
  지금가 > 55일 최고가 → 55일 돌파 매수 (건너뛰기와 상관없이) / 지금가 > 20일 최고가 & 직전 신호가 이기지 않음 → 20일 돌파 매수.
  직전 신호가 이겼으면 20일 돌파는 건너뜀(로그) — 55일 돌파는 그 뒤로도 계속 봄. 선마다 하루 한 번.
  신호가 = 돌파선 → paper 추격 제한이 '돌파선 +1% 넘으면 안 삼'. 처음 보는 종목은 시세를 한 번 조회해 오늘 고가가 이미 돌파선을 넘었는데 지금가가 아래면
  '이미 닿았다 내려옴', 지금가가 돌파선 +1% 넘게 위면 '늦게 봄' 으로 그 선은 그날 끝. 돌파선 ≥ 오늘 상한가면 안 삼.
산 뒤 (paper 모드 'TURTLE', 15초마다 KRX 시세, 09:00~15:19 판정):
  손절선 = 마지막에 산 값 − 2N (추가 매수 때마다 올림, paper_trades.stop) — 지금가 ≤ 손절선이면 전부 매도.
  지금가 < 10일 최저가(55일 진입은 20일 최저가) 면 전부 매도. 추가 매수: 지금가 ≥ 마지막 산 값 + ½N 이면 1단위 더 (최대 4단위, 정규장만).
  익절 없음 · 15:19 정리 없음 · 보유 기간 제한 없음. N 은 처음 산 날 값을 그대로 씀(note '🐢 진입 20일 · N …').
  🧷 R1(계획 한 줄)·R7(오후 크기 제한)만, R2~R6 은 안 함 — 모드 'TURTLE' 은 hold_manage.HOLD_MODES 에 없음.
크기·한도: 1단위 = min(5만 원어치 × 계좌 축소 배수, 계좌 1% ÷ N 수량) — 1주가 더 비싸면 1주 (문서 ⑦ C, 100만 계좌에선 사실상 5만 원어치). 🧾 이 매매의 가상 계좌(100만)가 시작보다 10% 빠질 때마다 20% 줄임
  (90만 → 0.8배, 81만 → 0.64배 …, 끝난 매매 손익 기준 = 🧾 잔고와 같은 기준). 키움 모의도 같은 배수 + 기존 모의 금액 규칙(Nada 축소·보유 10종목·주문 가능 금액).
  한 종목 4단위, 같은 네이버 업종(data/naver_groups.duckdb '업종') 합계 6단위 — 업종을 모르는 종목은 그 종목 하나를 한 묶음으로 봄. 하락 쪽(인버스)은 안 함.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.strategies.kell_squeeze.live import MAX_VALUE_RANK, KellSelector

KIND = "터틀 돌파"
LABEL = "🐢 터틀 돌파"
FAST, SLOW = 20, 55                  # 20일·55일 최고가 돌파
EXIT_DAYS = {FAST: 10, SLOW: 20}     # 매도선: 20일 진입 → 10일 최저가, 55일 진입 → 20일 최저가
N_DAYS = 20                          # N = 직전 20일 진짜 폭 평균
STOP_N, ADD_N = 2.0, 0.5             # 손절 = 마지막 산 값 − 2N, 추가 = 마지막 산 값 + ½N
UNIT_WON = 50_000                    # 1단위 금액 (상한)
RISK = 0.01                          # 1단위 = 계좌 1% ÷ N 수량과 5만 원어치 중 작은 쪽
MAX_UNITS = 4                        # 한 종목 최대 단위
SECTOR_UNITS = 6                     # 같은 업종 합계 최대 단위
DD_STEP, DD_CUT = 0.10, 0.20         # 계좌 −10% 마다 단위 금액 −20%
JUMP = 0.31                          # 전일 종가 대비 ±31% 넘게 벗어나면 수정주가 튐으로 봄
BASE_GAP = 0.15                      # 오늘 기준가가 어제 정규장 종가와 15% 넘게 다르면 권리락·액면 변경 의심
HIST_ROWS = 160                      # 직전 신호 되짚기·선 계산에 쓰는 일봉 수
MIN_ROWS = SLOW + 1                  # 55일 최고가 + 진짜 폭(전일 종가) 에 필요한 최소 일봉 수
BUY_START, BUY_END = time(9, 0), time(15, 19)
CHASE = 0.01                         # 처음 볼 때 돌파선 +1% 넘게 이미 올라가 있으면 늦게 본 것 (paper MAX_CHASE 와 같은 값)
QUOTE_BUDGET = 30                    # 한 번 확인에 처음 보는 종목 시세 조회 수
FETCH_BUDGET = 20                    # 한 번 확인에 빈 날을 키움 1분봉으로 채우는 수
LOG_EVERY = 10
NXT_SWITCH = date(2026, 9, 14)       # 이날부터 daily_ohlcv 는 통합 값 → 정규장은 daily_regular
REG_OPEN, REG_CLOSE = time(9, 0), time(15, 30)
MIN_BARS = 30                        # 1분봉으로 정규장 일봉을 만들 때 최소 봉 수 (daily_regular 와 같음)
REGULAR_DB = os.path.join(PROJECT_ROOT, "data", "daily_regular.duckdb")
MINUTE_DB = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
NAVER_DB = os.path.join(PROJECT_ROOT, "data", "naver_groups.duckdb")
FILL_CACHE = os.path.join(PROJECT_ROOT, "data", "turtle_regular_fill.json")
ENTRY_TAG = "🐢 진입 "               # note: '🐢 진입 20일 · N 1,234.5 · 돌파선 56,700'
ADD_TAG = "🐢 추가 "                 # note: '🐢 추가 2단위 11-16 10:31 1주 × 57,300'

Bar = tuple  # (date, open, high, low, close)


# ---------------------------------------------------------------- 규칙 (순수 함수)
def true_ranges(bars: list[Bar]) -> list[float]:
    """봉마다 진짜 폭. 첫 봉은 전일 종가가 없어 고가−저가."""
    out = []
    for k, (_, _, h, l, c) in enumerate(bars):
        if k == 0:
            out.append(h - l)
        else:
            pc = bars[k - 1][4]
            out.append(max(h - l, abs(h - pc), abs(l - pc)))
    return out


def lines(bars: list[Bar]) -> Optional[dict]:
    """bars(오래된 순, 어제까지) → 오늘 쓸 선. 일봉이 MIN_ROWS 보다 적으면 None.
    N 은 직전 20일 진짜 폭의 단순 평균 (원문의 (19×전N+TR)/20 부드러운 평균 대신 — 사용자 확정)."""
    if len(bars) < MIN_ROWS:
        return None
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    tr = true_ranges(bars)
    return {"hi20": max(h[-FAST:]), "hi55": max(h[-SLOW:]), "lo10": min(l[-EXIT_DAYS[FAST]:]), "lo20": min(l[-EXIT_DAYS[SLOW]:]),
            "n": sum(tr[-N_DAYS:]) / N_DAYS, "close": bars[-1][4], "last": bars[-1][0]}


def prev_signal(bars: list[Bar]) -> Optional[dict]:
    """직전 20일 돌파 신호를 터틀 규칙대로 따라간 결과 (실제 매수와 무관). 신호가 없으면 None.
    {date, entry, n, stop, exit, exit_date, how, result} — result: '이김'·'짐'·'이김(진행 중)'·'짐(진행 중)'."""
    o = [b[1] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    tr = true_ranges(bars)
    pos, last = None, None
    for d in range(N_DAYS + 1, len(bars)):
        if pos is None:
            line = max(h[d - FAST:d])
            if h[d] > line:
                n = sum(tr[d - N_DAYS:d]) / N_DAYS
                entry = max(o[d], line)
                pos = {"date": bars[d][0], "entry": entry, "n": n, "stop": entry - STOP_N * n}
            continue
        lo = min(l[d - EXIT_DAYS[FAST]:d])
        hit = [(lv, how) for lv, how, ok in ((pos["stop"], "손절", l[d] <= pos["stop"]), (lo, "10일 최저가 이탈", l[d] < lo)) if ok]
        if not hit:
            continue
        lv, how = hit[0]                                       # 둘 다 닿으면 손절 먼저 (보수적, 문서 ③ A)
        px = min(o[d], lv)
        last = {**pos, "exit": px, "exit_date": bars[d][0], "how": how,
                "result": "이김" if how != "손절" and px > pos["entry"] else "짐"}
        pos = None
    if pos is not None:
        return {**pos, "exit": None, "exit_date": None, "how": "진행 중",
                "result": "이김(진행 중)" if bars[-1][4] > pos["entry"] else "짐(진행 중)"}
    return last


def is_win(prev: Optional[dict]) -> bool:
    return bool(prev) and prev["result"].startswith("이김")


def price_jump(bars: list[Bar]) -> Optional[str]:
    """전일 종가 대비 고가·저가·종가가 ±31% 넘게 벗어난 날(수정주가·액면분할 섞임 의심) → 설명, 없으면 None."""
    for k in range(1, len(bars)):
        d, _, h, l, c = bars[k]
        pc = bars[k - 1][4]
        if pc and (h / pc > 1 + JUMP or l / pc < 1 - JUMP or abs(c / pc - 1) > JUMP):
            return f"{d:%m-%d} 가격 튐 (전일 종가 {pc:,.0f} → 고가 {h:,.0f}·저가 {l:,.0f}·종가 {c:,.0f}, 수정주가·액면분할 의심)"
    return None


def first_look(price: float, day_high: float, line: float) -> Optional[str]:
    """처음 조회한 종목: 이미 지나간 돌파면 이유, 아니면 None (None 이고 price > line 이면 지금 신호)."""
    if price <= line < day_high:
        return "이미 닿았다 내려옴"
    if price > line * (1 + CHASE):
        return "늦게 봄(이미 넘어감)"
    return None


def shrink(balance: float, start: float) -> tuple[float, int]:
    """계좌 축소 → (단위 금액 배수, 단계). 시작보다 10% 빠질 때마다 20% 줄임 (100만 → 90만 0.8배, 81만 0.64배 …)."""
    if balance >= start:
        return 1.0, 0
    steps = 30 if balance <= 0 else int(math.floor(math.log(balance / start) / math.log(1 - DD_STEP) + 1e-9))
    return (1 - DD_CUT) ** steps, steps


def unit_qty(price: float, budget: float, n: Optional[float] = None, balance: Optional[float] = None) -> int:
    """1단위 수량 = min(budget 안에서 살 수 있는 만큼, 계좌 1% ÷ N) — 문서 ⑦ C. 둘 중 하나라도 1주가 안 되면 1주.
    100만 계좌의 1% 는 1만 원이라 N 이 값의 20% 를 넘는 아주 거친 종목에서만 계좌 1% 쪽이 작음 → 사실상 5만 원어치."""
    if not price:
        return 0
    q = int(budget // price)
    if n and balance:
        q = min(q, int(balance * RISK // n))
    return max(1, q)


def stop_line(last_price: float, n: float) -> float:
    return float(last_price) - STOP_N * n


def add_line(last_price: float, n: float) -> float:
    return float(last_price) + ADD_N * n


def entry_of(source: str) -> int:
    """신호 source '🐢 터틀 돌파 55일' → 55 (없으면 20)."""
    m = re.search(r"(\d+)일", source or "")
    return int(m.group(1)) if m and int(m.group(1)) in EXIT_DAYS else FAST


def entry_tag(entry: int, n: float, line: float) -> str:
    return f"{ENTRY_TAG}{entry}일 · N {n:,.1f} · 돌파선 {line:,.0f}"


def add_tag(units: int, now: datetime, qty: int, price: float) -> str:
    return f"{ADD_TAG}{units}단위 {now:%m-%d %H:%M} {qty}주 × {price:,.0f}"


def parse(note: str, buy_price: Optional[float]) -> dict:
    """note → {entry: 20|55, n: N|None, units: 지금 단위 수, last: 마지막 산 값}. 재시작해도 note 에서 다시 읽음."""
    m = re.search(re.escape(ENTRY_TAG) + r"(\d+)일 · N ([\d,.]+)", note or "")
    adds = re.findall(re.escape(ADD_TAG) + r"(\d+)단위 \S+ \S+ (\d+)주 × ([\d,]+)", note or "")
    last = float(adds[-1][2].replace(",", "")) if adds else (float(buy_price) if buy_price else None)
    return {"entry": int(m.group(1)) if m else FAST, "n": float(m.group(2).replace(",", "")) if m else None,
            "units": 1 + len(adds), "last": last}


def exit_line(info: Optional[dict], entry: int) -> Optional[float]:
    if not info:
        return None
    return info["lo10"] if entry == FAST else info["lo20"]


def plan_text(entry: int, line: float, n: float, exit_px: Optional[float]) -> str:
    """매수 알림·R1 계획에 쓰는 규칙 설명 (진입 종류·N·손절선·매도선)."""
    ed = EXIT_DAYS.get(entry, 10)
    return (f"{LABEL} {entry}일 돌파 — 돌파선 {line:,.0f} · N {n:,.0f} · 손절 = 마지막 산 값 − 2N(지금 약 {stop_line(line, n):,.0f}, 더 살 때마다 올림) · "
            f"매도: 지금가가 {ed}일 최저가" + (f" {exit_px:,.0f}원" if exit_px else "") + " 아래로 내려오면 전부(선은 매일 아침 다시 계산) · "
            f"추가: 마지막 산 값 + ½N({ADD_N * n:,.0f}원)마다 1단위, 최대 {MAX_UNITS}단위 · 익절 없음 · 15:19 정리·보유 기간 제한 없음")


# ---------------------------------------------------------------- 자료
def load_sectors(naver_db: str = NAVER_DB) -> dict[str, str]:
    """네이버 업종 최신 목록 → {종목코드: 업종 이름} (DB 가 잠겨 있으면 임시 복사본으로 읽음)."""
    path = naver_db
    try:
        conn = duckdb.connect(naver_db, read_only=True)
    except Exception:
        path = os.path.join(tempfile.gettempdir(), f"turtle_{os.getpid()}_naver_groups.duckdb")
        shutil.copy(naver_db, path)
        conn = duckdb.connect(path, read_only=True)
    try:
        rows = conn.execute("""SELECT code, name FROM naver_groups WHERE kind = '업종'
                               AND date = (SELECT max(date) FROM naver_groups WHERE kind = '업종')""").fetchall()
    finally:
        conn.close()
    return {c: n for c, n in rows}


def _bars_from_minutes(bars: list[dict]) -> Optional[tuple]:
    """키움 1분봉(하루치) → 정규장 (시가, 고가, 저가, 종가). 09:00~15:30 봉이 30개 안 되면 None."""
    reg = [b for b in bars if REG_OPEN <= b["ts"].time() <= REG_CLOSE and b["high"] and b["low"] and b["close"]]
    if len(reg) < MIN_BARS:
        return None
    return (float(reg[0]["open"] or reg[0]["close"]), float(max(b["high"] for b in reg)), float(min(b["low"] for b in reg)), float(reg[-1]["close"]))


class TurtleContext:
    """종목별 선(20·55일 최고가, 10·20일 최저가, N, 직전 신호 결과)과 업종. prepare() 로 필요한 종목만 그때 계산해 하루 동안 둠."""

    def __init__(self, day: date, db_path: str = DEFAULT_DB_PATH, regular_db: str = REGULAR_DB, minute_db: str = MINUTE_DB,
                 naver_db: str = NAVER_DB, cache_path: Optional[str] = FILL_CACHE, sectors: Optional[dict] = None) -> None:
        self.day, self.db_path, self.regular_db, self.minute_db, self.cache_path = day, db_path, regular_db, minute_db, cache_path
        self.info: dict[str, dict] = {}            # 코드 → 선 (계산 끝)
        self.bad: dict[str, str] = {}              # 코드 → 오늘 못 쓰는 이유
        self.rows: dict[str, dict[date, tuple]] = {}   # 코드 → {날짜: (시가, 고가, 저가, 종가)} (빈 날 채우는 중)
        self.missing: dict[str, list[date]] = {}   # 코드 → 아직 못 채운 9-14 뒤 빈 날
        self.fetched = 0                           # 키움 1분봉으로 채운 날 수 (오늘 누적)
        self.filled_local = 0                      # minute_history·파일 캐시로 채운 날 수
        self.cache: dict[str, Optional[list]] = {}
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                logging.exception("터틀: 정규장 빈 날 캐시 읽기 실패 — 새로 만듦")
        if sectors is not None:
            self.sectors = sectors
        else:
            try:
                self.sectors = load_sectors(naver_db)
            except Exception:
                logging.exception("터틀: 네이버 업종 읽기 실패 — 업종 한도는 종목 하나씩으로 봄")
                self.sectors = {}
        logging.info("터틀 준비 %s: 업종 %s종목, 정규장 빈 날 캐시 %s건", day, len(self.sectors), len(self.cache))

    # ------------------------------------------------------------ 조회
    def line(self, code: str) -> Optional[dict]:
        return self.info.get(code)

    def exit_line(self, code: str, entry: int) -> Optional[float]:
        return exit_line(self.info.get(code), entry)

    def sector(self, code: str) -> str:
        return self.sectors.get(code) or f"종목 {code}"

    # ------------------------------------------------------------ 계산
    def prepare(self, codes: Iterable[str], budget: int = FETCH_BUDGET, client=None) -> int:
        """codes 중 아직 선이 없는 종목을 계산. 빈 날은 키움 1분봉으로 최대 budget 번 채움 → 쓴 조회 수."""
        todo = [c for c in dict.fromkeys(codes) if c not in self.info and c not in self.bad]
        new = [c for c in todo if c not in self.rows]
        if new:
            self._load(new)
        used = 0
        dirty = False
        for c in todo:
            miss = self.missing.get(c, [])
            while miss and used < budget and client is not None:
                d = miss[0]
                try:
                    from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
                    ohlc = _bars_from_minutes(fetch_minute_bars(client, c, d, "AL"))
                except Exception:
                    logging.warning("터틀: %s %s 1분봉 조회 실패 — 다음 확인 때 다시", c, d)
                    used = budget
                    break
                used += 1
                self.fetched += 1
                miss.pop(0)
                self.cache[f"{c}|{d:%Y-%m-%d}"] = list(ohlc) if ohlc else None
                dirty = True
                if ohlc:
                    self.rows[c][d] = ohlc
            if miss:
                if client is None:
                    self.bad[c] = f"9-14 뒤 정규장 일봉 빈 날 {len(miss)}일 (채울 방법 없음)"
                continue
            self._finish(c)
        if dirty:
            self._save_cache()
        return used

    def _load(self, codes: list[str]) -> None:
        ph = ",".join("?" * len(codes))
        start = self.day - timedelta(days=int(HIST_ROWS * 1.6) + 30)
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            old = conn.execute(f"""SELECT code, date, open, high, low, close FROM daily_ohlcv WHERE code IN ({ph}) AND date >= ? AND date < ?
                                   AND open > 0 AND high > 0 AND low > 0 AND close > 0""", [*codes, start, min(self.day, NXT_SWITCH)]).fetchall()
            traded = conn.execute(f"SELECT code, date FROM daily_ohlcv WHERE code IN ({ph}) AND date >= ? AND date < ? AND coalesce(volume, 1) > 0",
                                  [*codes, NXT_SWITCH, self.day]).fetchall()
        finally:
            conn.close()
        reg = []
        if self.day > NXT_SWITCH:
            try:
                rc = duckdb.connect(self.regular_db, read_only=True)
                try:
                    reg = rc.execute(f"""SELECT code, date, open, high, low, close FROM daily_regular WHERE code IN ({ph}) AND date >= ? AND date < ?
                                         AND open > 0 AND high > 0 AND low > 0 AND close > 0""", [*codes, NXT_SWITCH, self.day]).fetchall()
                finally:
                    rc.close()
            except Exception:
                logging.exception("터틀: daily_regular 읽기 실패 — 빈 날을 1분봉으로 채움")
        for c in codes:
            self.rows[c] = {}
        for c, d, o, h, l, cl in old + reg:
            self.rows[c][d] = (float(o), float(h), float(l), float(cl))
        want: dict[str, list[date]] = {}
        for c, d in traded:
            if d not in self.rows[c]:
                want.setdefault(c, []).append(d)
        # 빈 날: 파일 캐시 → minute_history
        for c, ds in want.items():
            rest = []
            for d in sorted(ds):
                key = f"{c}|{d:%Y-%m-%d}"
                if key in self.cache:
                    if self.cache[key]:
                        self.rows[c][d] = tuple(self.cache[key])
                    self.filled_local += 1
                else:
                    rest.append(d)
            want[c] = rest
        need = {c: ds for c, ds in want.items() if ds}
        if need and os.path.exists(self.minute_db):
            try:
                mc = duckdb.connect(self.minute_db, read_only=True)
                try:
                    lo = min(min(ds) for ds in need.values())
                    q = ",".join("?" * len(need))
                    got = mc.execute(f"""SELECT code, CAST(ts AS DATE) d, arg_min(open, ts), max(high), min(low), arg_max(close, ts), count(*)
                                         FROM minute_ohlcv WHERE exchange = 'AL' AND code IN ({q}) AND ts >= ? AND ts < ?
                                         AND CAST(ts AS TIME) BETWEEN TIME '09:00' AND TIME '15:30' GROUP BY code, d""",
                                     [*need, datetime.combine(lo, time(0)), datetime.combine(self.day, time(0))]).fetchall()
                finally:
                    mc.close()
                for c, d, o, h, l, cl, nb in got:
                    if d in need.get(c, ()) and nb >= MIN_BARS and h and l and cl:
                        self.rows[c][d] = (float(o or cl), float(h), float(l), float(cl))
                        need[c].remove(d)
                        self.filled_local += 1
            except Exception:
                logging.exception("터틀: minute_history 읽기 실패 — 빈 날을 키움 1분봉으로 채움")
        for c in codes:
            ds = sorted(need.get(c, []))
            # 오래된 빈 날부터 채우되, 선 계산에 쓰는 범위(최근 HIST_ROWS) 밖은 안 채움
            self.missing[c] = ds

    def _finish(self, c: str) -> None:
        rows = self.rows.pop(c, {})
        self.missing.pop(c, None)
        bars = [(d, *v) for d, v in sorted(rows.items())][-HIST_ROWS:]
        jump = price_jump(bars)
        if jump:
            self.bad[c] = jump
            logging.info("터틀: %s 오늘 뺌 — %s", c, jump)
            return
        v = lines(bars)
        if v is None:
            self.bad[c] = f"정규장 일봉 {len(bars)}개 (55일 선에 {MIN_ROWS}개 필요)"
            return
        prev = prev_signal(bars)
        v.update(prev=prev, prev_win=is_win(prev), rows=len(bars))
        self.info[c] = v

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except Exception:
            logging.exception("터틀: 정규장 빈 날 캐시 저장 실패")


def prev_text(prev: Optional[dict]) -> str:
    if not prev:
        return "직전 20일 신호 없음"
    if prev["exit"] is None:
        return f"직전 20일 신호 {prev['date']:%m-%d}(산 값 {prev['entry']:,.0f}) {prev['result']}"
    return (f"직전 20일 신호 {prev['date']:%m-%d}(산 값 {prev['entry']:,.0f}) → {prev['exit_date']:%m-%d} {prev['how']} {prev['exit']:,.0f} "
            f"({prev['exit'] / prev['entry'] - 1:+.1%}) {prev['result']}")


# ---------------------------------------------------------------- 감시
class TurtleWatcher:
    """매분: 선별 통과 종목의 선(일봉으로 하루 한 번 계산)과 대금 순위 현재가를 비교 → 20일·55일 첫 돌파면 모의 매수 신호.
    1분봉은 받지 않음 (빈 날 채우기 제외) — 추가 조회는 처음 보는 종목 시세 한 번."""

    def __init__(self, market, selector: KellSelector, ctx: TurtleContext, done: Iterable = (), held: Optional[Callable[[], Iterable[str]]] = None,
                 stats: Optional[Callable[[], str]] = None, budget: int = QUOTE_BUDGET, fetch_budget: int = FETCH_BUDGET) -> None:
        self.market, self.sel, self.ctx = market, selector, ctx
        self.day = ctx.day
        self.held, self.stats = held, stats
        self.done20: set[str] = set(done)          # 20일 선 오늘 끝 (신호·건너뜀·늦게 봄)
        self.done55: set[str] = set(done)          # 55일 선 오늘 끝
        self.seen: set[str] = set()                # 처음 보는 종목 시세 조회 끝
        self.upper: dict[str, Optional[int]] = {}
        self.late: dict[tuple[str, int], str] = {}
        self.skipped: dict[str, str] = {}          # 20일 돌파 건너뜀 (직전 신호 이김)
        self.counts = {FAST: 0, SLOW: 0}
        self.budget, self.fetch_budget = budget, fetch_budget

    def check(self, now: datetime, value_top) -> list[tuple[str, str, str, Signal]]:
        if now.date() != self.day or not (BUY_START <= now.time() < BUY_END):
            return []
        held = set(self.held() or ()) if self.held else set()
        picks = list(self.sel.pick(value_top, limit=MAX_VALUE_RANK, theme=False))
        used = 0
        try:
            used = self.ctx.prepare([x.code for x in picks] + sorted(held), self.fetch_budget, getattr(self.market, "client", None))
        except Exception:
            logging.exception("터틀: 선 계산 실패")
        naive = now.replace(tzinfo=None, second=0, microsecond=0)
        budget, out = self.budget, []
        for x in picks:
            c = x.code
            v = self.ctx.info.get(c)
            if v is None or (c in self.done20 and c in self.done55):   # 들고 있는 종목도 신호는 냄 — 키움 모의·🧾 계좌가 각자 '이미 보유 중'으로 거름
                continue
            if c not in self.seen:
                if budget <= 0:
                    continue
                budget -= 1
                try:
                    q = self.market.quote(c, integrated=False)
                except Exception:
                    logging.warning("터틀 시세 조회 실패 %s", c)
                    continue
                if not q or not q.price or not getattr(q, "volume", 1):
                    continue
                self.seen.add(c)
                base = getattr(q, "base_price", None)
                if base and v["close"] and abs(base / v["close"] - 1) > BASE_GAP:
                    why = f"오늘 기준가 {base:,} ≠ 어제 정규장 종가 {v['close']:,.0f} (권리락·액면 변경 의심)"
                    self.ctx.bad[c] = why
                    self.done20.add(c)
                    self.done55.add(c)
                    logging.info("터틀: %s(%s) 오늘 뺌 — %s", x.name, c, why)
                    continue
                self.upper[c] = getattr(q, "upper", None)
                price, high = float(q.price), max(float(getattr(q, "high", 0) or 0), float(x.price or 0))
                for lt, done in ((SLOW, self.done55), (FAST, self.done20)):
                    why = first_look(price, high, v[f"hi{lt}"])
                    if why and c not in done:
                        done.add(c)
                        self.late[(c, lt)] = why
            else:
                price = float(x.price or 0)
            if not price:
                continue
            if c not in self.done55 and price > v["hi55"]:
                lt = SLOW
            elif c not in self.done20 and price > v["hi20"]:
                lt = FAST
            else:
                continue
            line = v[f"hi{lt}"]
            up = self.upper.get(c)
            if up and line >= up:
                (self.done55 if lt == SLOW else self.done20).add(c)
                self.late[(c, lt)] = "돌파선 ≥ 상한가"
                continue
            if lt == FAST and v["prev_win"]:
                self.done20.add(c)
                self.skipped[c] = prev_text(v["prev"])
                logging.info("터틀 20일 돌파 건너뜀 %s(%s) — 지금가 %s > 20일 최고가 %s · %s (55일 최고가 %s 는 계속 봄)",
                             x.name, c, f"{price:,.0f}", f"{line:,.0f}", self.skipped[c], f"{v['hi55']:,.0f}")
                continue
            self.done20.add(c)
            if lt == SLOW:
                self.done55.add(c)
            self.counts[lt] += 1
            n = v["n"]
            ex = exit_line(v, lt)
            reason = (f"{LABEL} {lt}일 돌파 — 지금가 {price:,.0f}원 > {lt}일 최고가 {line:,.0f}원 (어제까지 정규장 고가) · N {n:,.0f}원({n / line:.1%}) · "
                      f"손절 {stop_line(line, n):,.0f}(산 값 − 2N) · 매도선 {EXIT_DAYS[lt]}일 최저가 {ex:,.0f} · 추가 +½N {ADD_N * n:,.0f}원마다 최대 {MAX_UNITS}단위 · "
                      + ("55일 돌파는 건너뛰기 상관없이 삼 · " if lt == SLOW else "") + prev_text(v["prev"])
                      + f" · 대금 {(x.trade_value or 0) / 1e8:,.0f}억 · 업종 {self.ctx.sector(c)}")
            out.append((c, x.name, f"{LABEL} {lt}일", Signal(ts=naive, kind=KIND, price=line, level=line, stop=stop_line(line, n), reason=reason)))
        if out or now.minute % LOG_EVERY == 0:
            bad: dict[str, int] = {}
            for why in self.ctx.bad.values():
                key = "가격 튐" if "튐" in why else "기준가 다름" if "기준가" in why else "일봉 부족" if "일봉" in why and "필요" in why else "빈 날" if "빈 날" in why else why
                bad[key] = bad.get(key, 0) + 1
            late: dict[str, int] = {}
            for why in self.late.values():
                late[why] = late.get(why, 0) + 1
            extra = ""
            if self.stats is not None:
                try:
                    extra = self.stats()
                except Exception:
                    logging.exception("터틀 통계 실패")
            logging.info("터틀 %s: 대상 %s종목 · 20일 돌파 %s(건너뜀 %s) · 55일 돌파 %s · %s · 선 계산 %s종목(빈 날 채움: 1분봉 조회 이번 %s·누적 %s, 지역 자료 %s) · 못 씀 %s · 늦게 봄 %s%s",
                         f"{now:%H:%M}", len(picks), self.counts[FAST], len(self.skipped), self.counts[SLOW], extra or "추가 매수 0 · 매도 0",
                         len(self.ctx.info), used, self.ctx.fetched, self.ctx.filled_local,
                         ", ".join(f"{k} {n}" for k, n in bad.items()) or "없음", ", ".join(f"{k} {n}" for k, n in late.items()) or "없음",
                         (" · 신호 " + ", ".join(f"{nm} {src.split()[-1]} {s.level:,.0f}" for _, nm, src, s in out)) if out else "")
        return out


def trade_stats(trades: Iterable, day: date) -> tuple[int, int]:
    """오늘 🐢 추가 매수 수·매도 수 (로그 한 줄용)."""
    adds = sells = 0
    tag = f"단위 {day:%m-%d} "
    for t in trades:
        if t.kind != KIND:
            continue
        adds += (t.note or "").count(tag)
        if t.status in ("closed", "selling") and t.sell_ts and t.sell_ts.date() == day:
            sells += 1
    return adds, sells
