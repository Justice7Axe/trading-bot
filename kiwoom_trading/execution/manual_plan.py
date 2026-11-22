"""🧪 수동 실전 계획 실행기 — 사용자가 직접 지시한 일회성 실전 매매 (2026-11-22 사용자, 첫 계획 = 11-23 수동 인버스 3분할).

사용자 원문: "실전 매매로 내일 아침에 장이 시작되면 바로 인버스 매수 해줘. 보유 금액의 1/3 만큼, 그리고 눌림에 다시 1/3,
그리고 돌파가 나오면 다시 1/3 매수 해줘."

- 계획 파일: kiwoom_trading/execution/manual_plans/<id>.json (저장소에 넣음) 또는 data/manual_plans/<id>.json (git 제외, 같은 이름이면 이쪽이 먼저).
  상태 파일: 늘 data/manual_plans/<id>.state.json (git 제외).
  스캐너(run_intraday)가 시작될 때 계획 날짜 = 오늘인 파일이 있으면 그 계획을 사고팔고,
  계획 날짜가 지났어도 상태 파일에 아직 안 판 보유가 있으면 이어서 손절·다음 날 09:00 매도만 한다.
- 전역 스위치 KIWOOM_REAL_TRADING=off(2026-11-15 '당분간 실전 중지')와 상관없이 이 계획만 돈다 (사용자 직접 지시).
  real_auto_stop(자동 멈춤)·REAL_ON 목록·엄격 선정·🌀 무너지는 국면·☕ 카페 종목 제한 같은 기존 실전 관문은 적용하지 않음.
  텔레그램 '실전 쉼'(real_pause) 이면 새 매수만 멈춤 (손절·매도는 계속). 계획 파일 "enabled": false 도 새 매수만 멈춤.
- 규칙 (inverse_split3):
  기준 금액 = 계획일 08:55~09:00 사이(늦게 켜지면 첫 매수 직전) 실계좌 주문 가능 금액 전체(RealClient.cash()), 1회분 = 기준 ÷ 3.
  1차: 09:00 정규장 첫 체결 시세(KRX 거래량 > 0)를 보면 바로 1/3.
  2차(눌림): 1차 체결 뒤 현재가가 1차 체결가 × (1 − 0.5%) 이하로 내려간 적이 있고, 그 뒤(다음 봉부터) 1분봉이 직전 1분봉 종가보다 높게 마감하면 1/3.
  3차(돌파): 2차 체결 뒤 끝난 1분봉 종가가 그날 그 봉 전까지 정규장 고점을 넘으면 남은 금액(기준 − 1·2차 체결 금액, 주문 가능 금액 안에서).
  14:30 뒤에는 새로 안 삼 (못 산 차수는 그냥 안 삼). 1주도 못 사면 건너뛰고 알림.
  손절: 보유 평균 체결가 −2% 에 닿으면 즉시 전량 시장가 매도 (계획일·다음 날 장중 09:00~15:20). 익절 없음.
  손절 안 걸리면 계획일 15:19 정리 안 하고 들고 넘어가 exit_date 09:00 첫 확인 때 전량 시장가 매도.
- 주문 방식은 실전과 같음: 현재가 +1% 지정가(호가 올림, 상한가로 자름), 2분 안에 다 안 채워지면 남은 수량 취소.
- 안전장치: 같은 차수는 상태 파일로 한 번만 주문 (주문 직전 'sending' 저장 → 재시작 때 'sending' 이면 다시 보내지 않고 '확인 필요' 알림),
  계획 종목만 주문(RealClient.allowed = {종목}, ALLOWED_CODES 밖이면 계획 무시), 주문 실패·미체결은 로그+알림 뒤 1분 지나 한 번만 다시,
  팔 수량 = 계좌 보유 − 계획 시작 전 보유(baseline), 계좌 보유보다 많이 팔지 않음.
- 기록: real_trades 에 차수마다 한 줄 (kind = '수동 인버스 3분할', id = YYYYMMDD-종목-차수), 매도는 한 주문으로 모든 차수를 같이 닫음.
  RealTrader 는 이 kind 를 관리하지 않음 (real.actives 에서 뺌).

시험: .venv\\Scripts\\python.exe tests\\test_manual_plan.py (가짜 클라이언트·시세, 실주문 없음)
"""
import glob
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.common.krx import upper_limit
from kiwoom_trading.execution.real import MANUAL_KIND, PLAYS, SCHEMA, tick_up

STATE_DIR = os.path.join(PROJECT_ROOT, "data", "manual_plans")      # 상태 파일 (git 제외) — 계획 파일을 여기 직접 둬도 됨 (같은 id 면 여기 것이 먼저)
PLAN_DIRS = (STATE_DIR, os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_plans"))   # 저장소에 넣은 계획 파일


def state_path_for(plan_path: str, state_dir: str = STATE_DIR) -> str:
    return os.path.join(state_dir, os.path.basename(plan_path)[:-5] + ".state.json")
LABEL = PLAYS[MANUAL_KIND][0]            # '🧪 수동 인버스 3분할'
ALLOWED_CODES = {"114800"}               # KODEX 인버스 — 이 밖의 종목 계획은 무시 (사용자 지시 종목만)
OPEN, STOP_END = time(9, 0), time(15, 20)
BASE_FROM = time(8, 55)
TICK_GAP_SEC = 4                         # 5초 on_tick + 1분 run_once 에서 불려도 4초에 한 번만
RETRY_GAP_SEC = 60
FRESH_SEC = 150                          # 신호 봉이 끝난 지 2분 30초 넘었으면 (스캐너가 바빠 늦게 봄) 그 봉으로는 안 삼
SELL_RETRY_NOTE_EVERY = 5


def _t(text: Optional[str], default: time) -> time:
    if not text:
        return default
    h, m = (int(x) for x in str(text).split(":")[:2])
    return time(h, m)


def _iso(ts: Optional[datetime]) -> Optional[str]:
    return ts.isoformat(timespec="seconds") if ts else None


def _dt(text: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(text) if text else None


def _minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def _done_bars(bars: list, now: datetime) -> list:
    """정규장(09:00~) 끝난 1분봉만 (ts = 봉 시작)."""
    return [b for b in bars if b.get("close") and b["ts"].time() >= OPEN and b["ts"] + timedelta(minutes=1) <= now]


def find_dip(bars: list, fill_ts: datetime, threshold: float, now: datetime) -> Optional[datetime]:
    """1차 체결 뒤(체결한 봉의 다음 봉부터) 저가가 threshold 이하인 첫 봉의 시작 시각."""
    start = _minute(fill_ts) + timedelta(minutes=1)
    for b in _done_bars(bars, now):
        if b["ts"] >= start and b["low"] and b["low"] <= threshold:
            return b["ts"]
    return None


def rebound_bar(bars: list, dip_ts: datetime, now: datetime, fresh_sec: int = FRESH_SEC) -> Optional[dict]:
    """눌림(dip_ts 가 든 봉) 다음 봉부터, 직전 봉 종가보다 높게 마감한 봉 중 가장 최근 것 — 끝난 지 fresh_sec 안이면."""
    done = _done_bars(bars, now)
    start = _minute(dip_ts) + timedelta(minutes=1)
    hit = None
    for prev, b in zip(done, done[1:]):
        if b["ts"] >= start and b["close"] > prev["close"]:
            hit = b
    if hit and (now - (hit["ts"] + timedelta(minutes=1))).total_seconds() <= fresh_sec:
        return hit
    return None


def breakout_bar(bars: list, after_ts: datetime, now: datetime, fresh_sec: int = FRESH_SEC) -> Optional[dict]:
    """after_ts(2차 체결) 뒤에 끝난 봉 중 종가가 그날 그 봉 전까지 정규장 고점보다 높은 가장 최근 봉 — 끝난 지 fresh_sec 안이면."""
    done = _done_bars(bars, now)
    hit, high = None, None
    for b in done:
        if high is not None and b["ts"] + timedelta(minutes=1) > after_ts and b["close"] > high:
            hit = (b, high)
        high = max(high or 0, b["high"] or 0)
    if hit and (now - (hit[0]["ts"] + timedelta(minutes=1))).total_seconds() <= fresh_sec:
        return {**hit[0], "prior_high": hit[1]}
    return None


def _manual_paused(conn, day: date) -> bool:
    """텔레그램 '실전 쉼'만 봄 (실전 자동 멈춤 real_auto_stop 은 이 계획에 적용하지 않음 — 사용자 직접 지시)."""
    try:
        r = conn.execute("SELECT paused FROM real_pause WHERE date = ?", [day]).fetchone()
    except Exception:
        return False
    return bool(r and r[0])


class ManualPlanRunner:
    def __init__(self, plan: dict, path: str, client, market, conn, today: date,
                 notify: Optional[Callable[[str], Any]] = None, bars_fn: Optional[Callable[[str, date], list]] = None,
                 pause_fn: Optional[Callable[[], bool]] = None, now: Optional[datetime] = None, state_dir: str = STATE_DIR) -> None:
        self.plan, self.path = plan, path
        self.state_path = state_path_for(path, state_dir)
        self.client, self.market, self.conn, self.today = client, market, conn, today
        self.notify = notify or (lambda text: None)
        self.code, self.name = str(plan["code"]), str(plan.get("name") or plan["code"])
        self.day = date.fromisoformat(plan["date"])
        self.exit_day = date.fromisoformat(plan["exit_date"])
        self.parts = int(plan.get("parts", 3))
        self.dip = float(plan.get("dip_pct", 0.005))
        self.stop = float(plan.get("stop_pct", 0.02))
        self.limit_up = float(plan.get("limit_up", 0.01))
        self.fill_wait = int(plan.get("fill_wait_sec", 120))
        self.buy_until = _t(plan.get("buy_until"), time(14, 30))
        self.exit_at = _t(plan.get("exit_time"), OPEN)
        self.bars_fn = bars_fn
        self.pause_fn = pause_fn or (lambda: _manual_paused(self.conn, self.today))
        self._bars_cache: tuple[str, list] = ("", [])
        self._last_tick: Optional[datetime] = None
        self._err_notes = 0
        if hasattr(self.client, "allowed"):
            self.client.allowed = {self.code}          # 이 계획 종목만 주문
        self.conn.execute(SCHEMA)
        self.st = self._load_state()
        now = (now or datetime.now()).replace(tzinfo=None)
        for n, t in self.st["tranches"].items():   # 주문 보내다 꺼졌으면 다시 보내지 않음
            if t["status"] == "sending":
                t["status"] = "unknown"
                self._save()
                self.notify(f"⚠️ {LABEL} {n}차 주문을 보내는 중에 스캐너가 꺼졌던 기록 — 다시 주문하지 않음, 키움에서 주문·체결 직접 확인 필요")
        if self.today == self.day and self.st.get("base_cash") is None:
            self._capture_base(now, final=False)    # 07:50 카드용 임시 기준 금액

    # ------------------------------------------------------------ 상태 파일
    def _load_state(self) -> dict:
        if os.path.exists(self.state_path):
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        return {"plan_id": self.plan.get("id"), "base_cash": None, "base_final": False, "base_ts": None, "baseline_qty": None,
                "dip_ts": None, "tranches": {str(n): {"status": "pending", "attempts": 0} for n in range(1, self.parts + 1)},
                "exit": {"status": "none", "fails": 0}, "done": False}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------ 보기
    def tr(self, n: int) -> dict:
        return self.st["tranches"][str(n)]

    def held_parts(self) -> list[tuple[int, dict]]:
        return [(int(n), t) for n, t in self.st["tranches"].items() if t["status"] == "open" and t.get("fill_qty")]

    def open_qty(self) -> int:
        return sum(t["fill_qty"] for _, t in self.held_parts())

    def avg_price(self) -> Optional[float]:
        q = self.open_qty()
        return sum(t["fill_qty"] * t["fill_price"] for _, t in self.held_parts()) / q if q else None

    def card_line(self) -> str:
        if self.today == self.day:
            base = self.st.get("base_cash")
            return (f"🧪 오늘 실전: 수동 인버스 3분할 계획 있음 (기준 금액 {base:,.0f}원 · {self.name} {self.code} · 1회 약 {base // self.parts:,.0f}원) "
                    f"— 09:00 1/3, 눌림 1/3, 돌파 1/3 · 손절 평균가 −{self.stop:.0%} · 익절 없음 · {self.exit_day:%m-%d} 09:00 매도. 전역 실전은 계속 중지"
                    if base is not None else f"🧪 오늘 실전: 수동 인버스 3분할 계획 있음 ({self.name} {self.code}, 기준 금액은 09:00 직전 다시 읽음)")
        q, avg = self.open_qty(), self.avg_price()
        return (f"🧪 오늘 실전: 수동 인버스 3분할 보유 {self.name} {q}주 (평균 {avg:,.0f}원) — 09:00 전량 매도" if q
                else f"🧪 오늘 실전: 수동 인버스 3분할 마무리 확인 ({self.name})")

    def has_position(self) -> bool:
        return not self.st.get("done") and (self.open_qty() > 0 or any(t["status"] in ("ordered", "unknown") for t in self.st["tranches"].values()))

    # ------------------------------------------------------------ 한 번 확인
    def tick(self, now: datetime) -> None:
        now = now.replace(tzinfo=None)
        if self.st.get("done"):
            return
        if self._last_tick and (now - self._last_tick).total_seconds() < TICK_GAP_SEC:
            return
        self._last_tick = now
        try:
            self._tick(now)
        except Exception as exc:
            logging.exception("%s 확인 실패", LABEL)
            self._err_notes += 1
            if self._err_notes in (1, 10, 50):
                self.notify(f"⚠️ {LABEL} 확인 실패 — {exc}"[:400])

    def _tick(self, now: datetime) -> None:
        tm = now.time()
        if self.today < self.day:
            return
        self._check_orders(now)
        if self.st["exit"]["status"] == "selling":
            self._check_sell(now)
            return
        if self.st["exit"]["status"] == "pending":     # 매도하기로 했는데 주문이 실패한 상태 — 값이 돌아와도 다시 사지 않고 매도만 다시
            if OPEN <= tm < STOP_END:
                self._exit(now, self.st["exit"]["reason"])
            return
        if self.today == self.day:
            if tm >= BASE_FROM and not self.st.get("base_final") and self.tr(1)["status"] == "pending":
                self._capture_base(now, final=True)
            if BASE_FROM <= tm < OPEN:   # 장 전 KRX 거래량 (쉬는 날·장 전엔 지난 거래일 값이 그대로 보임) — 09:00 뒤 이 값과 달라져야 첫 체결로 봄
                q = self.market.quote(self.code, integrated=False)
                if q is not None and self.st.get("preopen_volume") != getattr(q, "volume", 0):
                    self.st["preopen_volume"] = getattr(q, "volume", 0)
                    self._save()
            if not (OPEN <= tm < STOP_END):
                return
            if self._stop_check(now):
                return
            self._buy_step(now)
            return
        # 계획 다음 날부터: exit_day 09:00 전량 매도 (못 팔면 1분마다 다시), 그 전 날짜는 손절만
        if not (OPEN <= tm < STOP_END):
            return
        for n, t in self.st["tranches"].items():   # 전날 주문이 체결 확인 없이 남았으면 (그날 조회 안 됨) 확인 필요로
            if t["status"] == "ordered":
                t["status"] = "unknown"
                self._save()
        if self.today >= self.exit_day and tm >= self.exit_at:
            self._exit(now, "다음 날 09:00 시초 매도 (손절 안 걸리고 들고 넘김)")
        else:
            self._stop_check(now)

    # ------------------------------------------------------------ 기준 금액
    def _capture_base(self, now: datetime, final: bool) -> None:
        try:
            cash = int(self.client.cash())
            held = int(self.client.holding_qty(self.code))
        except Exception as exc:
            logging.exception("%s 기준 금액 조회 실패", LABEL)
            if final and self.st.get("base_cash") is not None and now.time() >= OPEN:
                self.st["base_final"] = True     # 09:00 넘었는데도 못 읽으면 07:50 값으로
                self._save()
            elif final and not self.st.get("base_fail_noted"):
                self.st["base_fail_noted"] = True
                self._save()
                self.notify(f"⚠️ {LABEL} 기준 금액 조회 실패 — {exc}"[:300] + " (다음 확인 때 다시 읽음)")
            return
        self.st.update(base_cash=cash, base_ts=_iso(now), base_final=final, baseline_qty=held)
        self._save()
        logging.info("%s 기준 금액 %s원 (%s), 계획 전 보유 %s주", LABEL, f"{cash:,}", "확정" if final else "임시", held)

    # ------------------------------------------------------------ 매수
    def _bars(self, now: datetime) -> list:
        key = now.strftime("%H%M")
        if self._bars_cache[0] != key:
            if self.bars_fn is not None:
                bars = self.bars_fn(self.code, self.today)
            else:
                from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
                bars = fetch_minute_bars(self.market.client, self.code, self.today, "KRX")
            self._bars_cache = (key, bars)
        return self._bars_cache[1]

    def _buy_step(self, now: datetime) -> None:
        tm = now.time()
        trs = self.st["tranches"]
        if any(t["status"] in ("ordered", "sending") for t in trs.values()):
            return                                   # 체결 확인 전에는 다음 차수 안 봄
        if tm >= self.buy_until or not self.plan.get("enabled", True):
            return
        if self.pause_fn():
            if not self.st.get("pause_logged"):
                logging.info("%s: 실전 쉼이라 새 매수 안 함 (손절·매도는 계속)", LABEL)
                self.st["pause_logged"] = True
                self._save()
            return
        for n in range(1, self.parts + 1):           # 다시 시도할 차수 (1분 뒤 한 번)
            t = self.tr(n)
            if t["status"] == "retry":
                if (now - _dt(t["last_fail_ts"])).total_seconds() >= RETRY_GAP_SEC:
                    self._order(n, now, t.get("signal_price"), (t.get("why") or "") + " · 다시 주문")
                return
        t1, t2, t3 = self.tr(1), self.tr(2), self.tr(3) if self.parts >= 3 else {"status": "n/a"}
        if t1["status"] == "pending":
            if self.st.get("base_cash") is None or not self.st.get("base_final"):
                return                               # 기준 금액을 아직 못 읽음 — 읽힐 때까지 기다림 (매 확인 때 다시 읽음)
            q = self.market.quote(self.code, integrated=False)
            pre = self.st.get("preopen_volume")
            vol = getattr(q, "volume", 0) if q else 0
            if q and q.price and vol > 0 and (pre is None or vol != pre):   # 정규장 첫 체결이 난 뒤 (장 전 거래량과 달라짐)
                self._order(1, now, float(q.price), f"09:00 정규장 시작 첫 체결 시세 {q.price:,.0f}원 확인")
            return
        if t1["status"] != "open":
            return                                   # 1차가 안 됐으면 (건너뜀·포기·확인 필요) 2·3차 없음
        if t2["status"] == "pending":
            p1 = float(t1["fill_price"])
            thr = p1 * (1 - self.dip)
            dip = _dt(self.st.get("dip_ts"))
            if dip is None:
                q = self.market.quote(self.code, integrated=False)
                fill_ts = _dt(t1["fill_ts"])
                if q and q.price and q.price <= thr:
                    dip = now
                else:
                    dip = find_dip(self._bars(now), fill_ts, thr, now)
                if dip is not None:
                    self.st["dip_ts"] = _iso(dip)
                    self._save()
                    logging.info("%s 눌림 확인 %s (1차 체결가 %s × %.1f%% = %s 이하)", LABEL, dip, f"{p1:,.0f}", (1 - self.dip) * 100, f"{thr:,.0f}")
                return
            b = rebound_bar(self._bars(now), dip, now)
            if b:
                self._order(2, now, float(b["close"]),
                            f"눌림 — 1차 체결가 {p1:,.0f}원 −{self.dip:.1%}({thr:,.0f}원) 아래로 내려간 뒤 {b['ts']:%H:%M} 1분봉이 직전 봉 종가보다 높게 마감 ({b['close']:,.0f}원)")
            return
        if t2["status"] != "open" or t3["status"] != "pending":
            return
        b = breakout_bar(self._bars(now), _dt(t2["fill_ts"]), now)
        if b:
            self._order(3, now, float(b["close"]),
                        f"돌파 — {b['ts']:%H:%M} 1분봉 종가 {b['close']:,.0f}원이 오늘 그 전까지 고점 {b['prior_high']:,.0f}원 위로 마감")

    def _order(self, n: int, now: datetime, signal_price: Optional[float], why: str) -> None:
        t = self.tr(n)
        q = self.market.quote(self.code, integrated=False)
        if not q or not q.price:
            logging.info("%s %s차: 시세 없음 — 다음 확인 때", LABEL, n)
            return
        price = float(q.price)
        limit = tick_up(price * (1 + self.limit_up))
        base = float(getattr(q, "base_price", 0) or 0)
        cap = upper_limit(base) if base else 0
        if cap and limit > cap:
            limit = cap
        b = int(self.st.get("base_cash") or 0)
        spent = sum(self.tr(k).get("fill_qty", 0) * self.tr(k).get("fill_price", 0) for k in range(1, n) if self.tr(k)["status"] == "open")
        budget = b // self.parts if n < self.parts else max(0, b - spent)
        cash = int(self.client.cash())
        qty = int(min(budget, cash) // limit)
        if qty < 1:
            t.update(status="skipped", why=why, note=f"1회분 {budget:,.0f}원 · 주문 가능 {cash:,.0f}원 < 1주 지정가 {limit:,}원")
            self._save()
            self.notify(f"⏭ {LABEL} {n}차 건너뜀 — 1주도 못 삼 ({t['note']})")
            logging.info("%s %s차 건너뜀: %s", LABEL, n, t["note"])
            return
        attempt = int(t.get("attempts", 0)) + 1
        t.update(status="sending", attempts=attempt, signal_price=signal_price, why=why)
        self._save()                                  # 주문 직전 저장 — 꺼졌다 켜져도 같은 차수 두 번 주문 안 함
        ask1, bid1 = self._book()
        try:
            try:
                no = self.client.limit_buy(self.code, qty, limit)
            except RuntimeError as exc:               # '[2000](855056:매수증거금이 부족합니다. 46주 매수가능)'
                m = re.search(r"(\d+)주 매수가능", str(exc))
                if not m or not 0 < int(m.group(1)) < qty:
                    raise
                qty = int(m.group(1))
                no = self.client.limit_buy(self.code, qty, limit)
        except Exception as exc:
            logging.exception("%s %s차 주문 실패", LABEL, n)
            self._fail(n, now, f"주문 실패 — {exc}")
            return
        tid = f"{self.day:%Y%m%d}-{self.code}-{n}" + ("" if attempt == 1 else "b")
        t.update(status="ordered", order_no=no, qty=qty, limit=limit, price=price, order_ts=_iso(now), tid=tid)
        self._save()
        self.conn.execute("""INSERT OR REPLACE INTO real_trades (id, date, code, name, kind, qty, buy_order_no, buy_ts, buy_price, status, note,
                                                                 signal_price, order_price, ask1, bid1)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ordered', ?, ?, ?, ?, ?)""",
                          [tid, self.day, self.code, self.name, MANUAL_KIND, qty, no, now, price,
                           f"{n}차 · {why} · 사용자 직접 지시 일회성 계획 (손절 평균가 −{self.stop:.0%}, 익절 없음, {self.exit_day:%m-%d} 09:00 매도)",
                           signal_price, float(limit), ask1, bid1])
        self.notify(f"🔴 실전 매수 주문 [{LABEL} {n}차] {self.name}({self.code}) {qty}주 × 약 {price:,.0f}원 = {qty * price:,.0f}원 "
                    f"(지정가 {limit:,}원, 주문 {no})\n  {why}")
        logging.info("%s %s차 매수 주문 %s주 지정가 %s (주문 %s)", LABEL, n, qty, limit, no)

    def _fail(self, n: int, now: datetime, msg: str) -> None:
        t = self.tr(n)
        again = int(t.get("attempts", 0)) < 2 and now.time() < self.buy_until
        t.update(status="retry" if again else "gave_up", last_fail_ts=_iso(now), note=msg[:200])
        self._save()
        self.notify(f"⚠️ {LABEL} {n}차 {msg}"[:300] + (" — 1분 뒤 한 번 다시 주문" if again else " — 이 차수는 안 삼"))

    def _book(self) -> tuple[Optional[float], Optional[float]]:
        fn = getattr(self.client, "best_quote", None)
        if fn is None:
            return None, None
        try:
            return fn(self.code)
        except Exception:
            logging.warning("%s 호가 조회 실패 (체결 차이 기록만 빠짐)", LABEL)
            return None, None

    # ------------------------------------------------------------ 체결 확인
    def _check_orders(self, now: datetime, force_cancel: bool = False) -> None:
        for n in range(1, self.parts + 1):
            t = self.tr(n)
            if t["status"] != "ordered" or _dt(t["order_ts"]).date() != self.today:
                continue
            got, px = self.client.fill_info(t["order_no"], self.code)
            waited = (now - _dt(t["order_ts"])).total_seconds()
            if got < t["qty"] and (waited >= self.fill_wait or force_cancel):
                try:
                    self.client.cancel(t["order_no"], self.code)
                except Exception:
                    logging.exception("%s %s차 남은 수량 취소 실패", LABEL, n)
                got, px = self.client.fill_info(t["order_no"], self.code)
                if not got:
                    self.conn.execute("UPDATE real_trades SET status = 'failed', note = coalesce(note, '') || ? WHERE id = ?",
                                      [f" · 지정가 {self.fill_wait // 60}분 미체결 → 취소", t["tid"]])
                    if force_cancel:
                        t.update(status="gave_up", note="손절·매도 때 미체결 취소")
                        self._save()
                    else:
                        self._fail(n, now, f"지정가 {t['limit']:,}원 {self.fill_wait // 60}분 안에 체결 안 됨 → 취소")
                    continue
                if got < t["qty"]:
                    self.notify(f"🔴 {LABEL} {n}차 일부만 체결 {got}/{t['qty']}주 — 남은 수량 취소")
            elif got < t["qty"] or not px:
                continue
            t.update(status="open", fill_qty=int(got), fill_price=float(px), fill_ts=_iso(now))
            self._save()
            self.conn.execute("UPDATE real_trades SET qty = ?, buy_price = ?, fill_price = ?, peak = ?, status = 'open' WHERE id = ?",
                              [int(got), float(px), float(px), float(px), t["tid"]])
            avg = self.avg_price()
            self.notify(f"🔴 실전 매수 체결 [{LABEL} {n}차] {self.name} {got}주 × {px:,.0f}원 — 합계 {self.open_qty()}주 평균 {avg:,.0f}원 · "
                        f"손절 {avg * (1 - self.stop):,.0f}원 · 익절 없음 · {self.exit_day:%m-%d} 09:00 매도")
            logging.info("%s %s차 체결 %s주 × %s", LABEL, n, got, px)

    # ------------------------------------------------------------ 손절·매도
    def _stop_check(self, now: datetime) -> bool:
        avg = self.avg_price()
        if not avg:
            return False
        q = self.market.quote(self.code, integrated=False)
        if not q or not q.price:
            return False
        if float(q.price) <= avg * (1 - self.stop):
            self._exit(now, f"손절 −{self.stop:.0%} (평균 {avg:,.0f}원 → 지금 {q.price:,.0f}원)", float(q.price))
            return True
        return False

    def _exit(self, now: datetime, reason: str, sig_px: Optional[float] = None) -> None:
        ex = self.st["exit"]
        if ex.get("last_fail_ts") and (now - _dt(ex["last_fail_ts"])).total_seconds() < RETRY_GAP_SEC:
            return
        if ex.get("status") != "pending":
            ex.update(status="pending", reason=reason)   # 한 번 매도하기로 하면 되돌리지 않음 (새 매수 없음)
            self._save()
        self._check_orders(now, force_cancel=True)    # 아직 안 채워진 매수 주문은 취소하고 체결분만
        held = int(self.client.holding_qty(self.code))
        base = self.st.get("baseline_qty")
        qty = min(held, max(0, held - int(base))) if base is not None else min(held, self.open_qty())
        if qty < 1:
            self.st["done"] = True
            self._save()
            if self.open_qty():
                self.notify(f"⚠️ {LABEL} 매도 못 함 — 계좌 매도 가능 {held}주 (계획 전 {base}주), 기록상 {self.open_qty()}주 · 직접 확인 필요")
            logging.info("%s 팔 수량 없음 (계좌 %s주, 계획 전 %s주) — 끝", LABEL, held, base)
            return
        if sig_px is None:
            try:
                q = self.market.quote(self.code, integrated=False)
                sig_px = float(q.price) if q and q.price else None
            except Exception:
                sig_px = None
        sask, sbid = self._book()
        try:
            no = self.client.market_order("sell", self.code, qty)
        except Exception as exc:
            logging.exception("%s 매도 주문 실패", LABEL)
            ex["fails"] = int(ex.get("fails", 0)) + 1
            ex["last_fail_ts"] = _iso(now)
            self._save()
            if ex["fails"] == 1 or ex["fails"] % SELL_RETRY_NOTE_EVERY == 0:
                self.notify(f"⚠️ {LABEL} 매도 주문 실패 {ex['fails']}번째 ({reason}) — {exc}"[:300] + " · 1분마다 다시 시도")
            return
        ex.update(status="selling", order_no=no, qty=qty, reason=reason, ts=_iso(now), signal_price=sig_px)
        self._save()
        for _, t in self.held_parts():
            self.conn.execute("""UPDATE real_trades SET status = 'selling', sell_order_no = ?, sell_ts = ?, reason = ?, sell_signal_price = ?,
                                 sell_order_price = NULL, sell_ask1 = ?, sell_bid1 = ? WHERE id = ?""",
                              [no, now, reason, sig_px, sask, sbid, t["tid"]])
        self.notify(f"🔴 실전 매도 주문 [{LABEL}] {self.name}({self.code}) {qty}주 시장가 — {reason} (주문 {no})")
        logging.info("%s 매도 주문 %s주 %s (주문 %s)", LABEL, qty, reason, no)

    def _check_sell(self, now: datetime) -> None:
        ex = self.st["exit"]
        got, px = self.client.fill_info(ex["order_no"], self.code)
        if not px or got < ex["qty"]:
            return
        from kiwoom_trading.execution.real import _cost
        total = 0.0
        for _, t in self.held_parts():
            pnl = t["fill_qty"] * (px - t["fill_price"]) - t["fill_qty"] * t["fill_price"] * _cost(self.code)
            total += pnl
            t["status"] = "closed"
            t["sell_price"], t["pnl"] = float(px), pnl
            self.conn.execute("UPDATE real_trades SET sell_price = ?, pnl = ?, status = 'closed' WHERE id = ?", [float(px), pnl, t["tid"]])
        ex.update(status="closed", price=float(px), pnl=total, filled_ts=_iso(now))
        self.st["done"] = True
        self._save()
        self.notify(f"🔴 실전 매도 체결 [{LABEL}] {self.name} {ex['qty']}주 × {px:,.0f}원 — {total:+,.0f}원 ({ex['reason']})")
        logging.info("%s 매도 체결 %s주 × %s, 손익 %s", LABEL, ex["qty"], px, total)


# ------------------------------------------------------------ 스캐너가 부르는 곳
def plan_files(plan_dirs=PLAN_DIRS) -> list[str]:
    """계획 파일 (상태 파일 제외). 같은 이름이 여러 폴더에 있으면 앞 폴더(data/manual_plans) 것만."""
    seen, out = set(), []
    for d in ([plan_dirs] if isinstance(plan_dirs, str) else plan_dirs):
        for p in sorted(glob.glob(os.path.join(d, "*.json"))):
            name = os.path.basename(p)
            if p.endswith(".state.json") or name in seen:
                continue
            seen.add(name)
            out.append(p)
    return out


def load_runners(today: date, market, conn, notify=None, client_factory: Optional[Callable[[], Any]] = None,
                 plan_dir=PLAN_DIRS, now: Optional[datetime] = None, state_dir: str = STATE_DIR, **kw) -> list[ManualPlanRunner]:
    """오늘 날짜 계획 + 날짜는 지났지만 아직 안 판 계획만 실행기로. 해당 계획이 없으면 실계좌 클라이언트도 안 만듦."""
    picks = []
    for path in plan_files(plan_dir):
        try:
            with open(path, encoding="utf-8") as f:
                plan = json.load(f)
            if plan.get("type") != "inverse_split3":
                logging.warning("수동 계획 %s: 모르는 종류 %s — 무시", os.path.basename(path), plan.get("type"))
                continue
            if str(plan.get("code")) not in ALLOWED_CODES:
                logging.warning("수동 계획 %s: 허용 종목 아님 %s — 무시", os.path.basename(path), plan.get("code"))
                continue
            d = date.fromisoformat(plan["date"])
            state_path = state_path_for(path, state_dir)
            st = None
            if os.path.exists(state_path):
                with open(state_path, encoding="utf-8") as f:
                    st = json.load(f)
            if d == today:
                picks.append((path, plan))
            elif d < today and st and not st.get("done") and any(
                    t.get("status") in ("open", "ordered", "unknown") for t in st.get("tranches", {}).values()):
                picks.append((path, plan))
        except Exception:
            logging.exception("수동 계획 읽기 실패 %s", path)
    if not picks:
        return []
    if client_factory is None:
        from kiwoom_trading.execution.real import build_real_client
        client_factory = build_real_client
    client = client_factory()
    out = []
    for path, plan in picks:
        try:
            r = ManualPlanRunner(plan, path, client, market, conn, today, notify=notify, now=now, state_dir=state_dir, **kw)
            if r.st.get("done"):
                continue
            out.append(r)
            logging.info("수동 실전 계획 %s: %s", os.path.basename(path), r.card_line())
        except Exception:
            logging.exception("수동 계획 준비 실패 %s", path)
    return out
