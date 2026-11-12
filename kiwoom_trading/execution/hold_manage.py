"""산 뒤 관리 규칙 R1~R7 — 며칠 들고 가는 매매의 대응 계획·손실 한도·나눠 팔기·다시 고르기·시간 손절·물타기·오후 크기 제한
(2026-11-13 사용자 '전부'. 출처: 하와이 대저택 '주식으로 평생 돈 버는 법 -20%에서 결판납니다' (2026-11-10), 리 프리먼 쇼어 『투자의 기술』).

며칠 들고 가는 매매 (HOLD_MODES): 모의 방식 '추세'(7️⃣ 주도주 추세)·'VWMA'(🌀 프랙탈 바닥)·'KELL_D'·'KELL_M'(📈 켈 수축)·'HA_D'·'HA_M'(🕯 하이킨아시)·'보유일'(📅 자사주 신탁),
  실전은 7️⃣ 주도주 추세(REAL_HOLD_KINDS) — 다른 실전 매매는 원래 규칙대로 다음 날 09:00 에 팔기 때문에 해당 없음.
R1 대응 계획: 사기 전에 손절가(또는 '손절 없음')·익절·보유 규칙·추가 매수 계획을 한 줄로 만들어 매매 기록 note 에 남김. 못 만들면 '대응 계획 없음 (R1)' 으로 안 삼.
    손절·익절은 지금처럼 모두 주문으로 실행 (알림만 하는 길 없음).
R2 다시 고르기: 전날 이전에 산 보유 종목을 09:10 시장 판정 뒤 첫 확인에서 오늘 고르는 기준으로 다시 봄 —
    (a) 09:10 주식 대금 100위 안 (b) 전날 외인·기관 둘 다 순매도 아님 (c) 최근 프로그램 순매수 ≥ 0 (자료 있을 때)
    (d) 테마 형성 (같은 네이버 테마 안 지금 +4%↑ 종목 2개↑). 2개 이상 탈락 & 지금가 < 매수가 → 그 자리에서 매도. 하루 한 번만 판정.
R3 손실 한도: 지금가 ≤ 첫 매수가 × 0.80 → 모의는 R6 추가(조건 되면) 아니면 매도, 실전은 매도. ≤ × 0.67 → 모의·실전 모두 전부 매도.
R4 시간 손절 (7️⃣): 산 날부터 20거래일이 지나도록 일봉 종가가 매수가 × 1.05 를 한 번도 못 넘으면 다음 09:00 매도 (스캐너 시작 때 일봉으로 판정).
R5 소믈리에 나눠 익절 (7️⃣): 매수가 +20%·+40%·+60% 에서 처음 수량의 1/4 씩 매도, 나머지는 원래 20일선 이탈 규칙. 남은 수량이 2주 안 되면 전부.
R6 사냥꾼 추가 (모의만): R3 −20% 에 처음 닿으면, 아직 안 했고·하루 손실 한도로 멈추지 않았고·오늘 12:00 전 실현 손실이 없으면 처음 수량만큼 한 번 더 삼.
R7 오후 크기 제한: 12:00 뒤 오늘 실현 손익이 마이너스면 새 매수 금액 배수를 1.0 넘게 키우지 않음 (🏆 테마 대장 2배 등 → 1배).

같은 확인 안의 순서 (하나가 실행되면 그 확인은 끝 — 두 번 팔지 않음):
  ① 매매마다 원래 매도 규칙 (손절·익절·09:00 선 이탈·색 매도·5거래일 매도) → ② R3 손실 한도 (추가 또는 매도)
  → ③ R5 나눠 익절 (7️⃣) → ④ R2 다시 고르기 (전날 이전 매수) → ⑤ R4 시간 손절 (7️⃣, 09:00 판정분)
R2·R3·R5·R6 은 정규장(09:00~15:19)에서만 판정 (NXT 가상 시간에는 안 봄).
숫자(−20%/−33%, 20거래일/+5%, +20/40/60% 1/4, 2개 탈락, 12:00)는 영상·책 규칙을 사용자와 정한 값 — 검증 전 가정.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Iterable, Optional

HOLD_MODES = ("추세", "VWMA", "KELL_D", "KELL_M", "HA_D", "HA_M", "보유일")
ADD_AT = 0.80               # R3·R6: 첫 매수가 × 0.80 (−20%)
CUT_AT = 0.67               # R3: 첫 매수가 × 0.67 (−33%) → 전부 매도
TIME_DAYS, TIME_GAIN = 20, 0.05   # R4: 20거래일 동안 종가가 +5% 를 못 넘음
TP_STEPS = (0.20, 0.40, 0.60)     # R5: 매수가 대비
TP_FRAC = 0.25                    # R5: 처음 수량의 1/4
R2_RANK, R2_FAILS = 100, 2        # R2: 대금 100위 · 4개 중 2개 탈락
THEME_UP, THEME_MIN = 0.04, 2     # R2 (d): 같은 테마 +4%↑ 2종목↑
R7_AT = time(12, 0)               # R6·R7: 오전 손실 기준 시각

STATE_SCHEMA = """CREATE TABLE IF NOT EXISTS hold_state (   -- 산 뒤 관리 R3·R5·R6·R2 진행 상태 (모의 = paper_trades.id, 실전 = 'real:' + real_trades.id)
    id VARCHAR PRIMARY KEY, base DOUBLE, added BOOLEAN, steps INTEGER, r2_date DATE, ts TIMESTAMP)"""


# ---------------------------------------------------------------- 상태 (재시작해도 남게 DB 에)
def get_state(conn, tid: str) -> dict:
    """{base: 첫 매수가|None, added: R6 했나, steps: R5 몇 단계 팔았나, r2_date: R2 판정한 날}."""
    try:
        conn.execute(STATE_SCHEMA)
        r = conn.execute("SELECT base, added, steps, r2_date FROM hold_state WHERE id = ?", [tid]).fetchone()
    except Exception:
        logging.exception("산 뒤 관리 상태 읽기 실패 %s", tid)
        r = None
    return {"base": r[0], "added": bool(r[1]), "steps": int(r[2] or 0), "r2_date": r[3]} if r else {"base": None, "added": False, "steps": 0, "r2_date": None}


def put_state(conn, tid: str, st: dict) -> None:
    try:
        conn.execute(STATE_SCHEMA)
        conn.execute("INSERT OR REPLACE INTO hold_state VALUES (?, ?, ?, ?, ?, ?)",
                     [tid, st.get("base"), bool(st.get("added")), int(st.get("steps") or 0), st.get("r2_date"), datetime.now()])
    except Exception:
        logging.exception("산 뒤 관리 상태 저장 실패 %s", tid)


# ---------------------------------------------------------------- 규칙 (순수 함수)
def plan_text(stop: Optional[float], tp: str, hold: str, add: str) -> Optional[str]:
    """R1 대응 계획 한 줄. 보유 규칙(hold)이 비면 계획을 못 만든 것 → None."""
    if not hold or not hold.strip():
        return None
    stop_txt = f"손절 {stop:,.0f}원" if stop else "손절 없음"
    return f"[계획] {stop_txt} · 익절: {tp or '없음'} · 보유: {hold.strip()} · 추가: {add or '없음'}"


def hold_plan_extra(mode: str, kind_is_trend: bool, paper: bool) -> tuple[str, str]:
    """며칠 들고 가는 매매에 R 규칙을 붙인 (익절 설명 덧붙임, 추가 매수 설명)."""
    if mode not in HOLD_MODES:
        return "", "없음"
    tp = "+20·40·60% 에 1/4 씩(R5)" if kind_is_trend else ""
    cut = f"−20% {'한 번 같은 수량 추가(R6), 안 되면 매도' if paper else '매도'} · −33% 전부 매도(R3)"
    extra = cut + (" · 20거래일 +5% 못 넘으면 09:00 매도(R4)" if kind_is_trend else "") + " · 09:10 다시 고르기 2개 탈락&매수가 아래면 매도(R2)"
    return tp, extra


def loss_action(price: float, base: float, added: bool, paper: bool) -> Optional[tuple[str, str]]:
    """R3 → ('add'|'sell', 이유) 또는 None. base = 첫 매수가 (R6 로 평균가가 내려가도 기준은 그대로)."""
    if not price or not base:
        return None
    if price <= base * CUT_AT:
        return "sell", f"R3 −33% 손실 한도 — 전부 매도 (첫 매수가 {base:,.0f} → {price:,.0f}, {price / base - 1:+.1%})"
    if not added and price <= base * ADD_AT:
        why = f"R3 −20% 손실 한도 (첫 매수가 {base:,.0f} → {price:,.0f}, {price / base - 1:+.1%})"
        return ("add" if paper else "sell"), why
    return None


def tp_step(price: float, buy: float, steps_done: int) -> Optional[float]:
    """R5: 다음 단계(+20→40→60%)에 닿았으면 그 수익률, 아니면 None."""
    if not price or not buy or steps_done >= len(TP_STEPS):
        return None
    lvl = TP_STEPS[steps_done]
    return lvl if price >= buy * (1 + lvl) else None


def tp_qty(total: int, remaining: int) -> tuple[int, bool]:
    """R5 이번에 팔 수량과 '전부 매도' 여부 — 처음 수량(total)의 1/4, 남은 게 2주 안 되거나 1/4 이 남은 전부면 전부."""
    q = max(1, int(total * TP_FRAC))
    if remaining < 2 or q >= remaining:
        return remaining, True
    return q, False


def r7_cap(factor: float, now: datetime, realized_today: float) -> tuple[float, str]:
    """R7: 12:00 뒤 오늘 실현 손익이 마이너스면 배수를 1.0 으로 묶음 → (배수, 이유|'')."""
    if factor > 1.0 and now.time() >= R7_AT and realized_today < 0:
        return 1.0, f"R7 오전 실현 손실 {realized_today:+,.0f}원 → 금액을 키우지 않음 ({factor:g}배 → 1배)"
    return factor, ""


def time_stop(closes: list[float], buy: float, days: int) -> Optional[str]:
    """R4: 산 날부터 days 거래일 종가(closes) — 20거래일 지났고 종가가 매수가 +5% 를 한 번도 못 넘었으면 이유."""
    if days < TIME_DAYS or not closes or not buy:
        return None
    line = buy * (1 + TIME_GAIN)
    mx = max(closes)
    if mx > line:
        return None
    return (f"R4 시간 손절 — 산 뒤 {days}거래일 동안 종가가 매수가 +5%({line:,.0f})를 한 번도 못 넘음 "
            f"(가장 높은 종가 {mx:,.0f}) — 시초 매도")


def recheck_fails(rank: Optional[int], flow: tuple, prog: Optional[float], theme: Optional[tuple]) -> tuple[list[str], list[str]]:
    """R2 네 항목 → (탈락 목록, 통과·자료 없음 목록). rank None = 대금 순위 목록(200위)에 없음, 0 = 순위 자료 없음(통과로 봄), prog None = 자료 없음(통과로 봄),
    theme None = 테마 자료 없음(통과로 봄), (테마 이름, +4%↑ 수) 이면 수가 2 미만일 때 탈락."""
    fails, oks = [], []
    if rank == 0:
        oks.append("대금 순위 자료 없음")
    elif rank is None or rank > R2_RANK:
        fails.append(f"대금 {R2_RANK}위 밖" + (f"({rank}위)" if rank else ""))
    else:
        oks.append(f"대금 {rank}위")
    f, i = flow if flow else (None, None)
    if f is not None and i is not None and f < 0 and i < 0:
        fails.append(f"전날 외인·기관 둘 다 순매도({f / 1e8:+,.0f}억·{i / 1e8:+,.0f}억)")
    else:
        oks.append("전날 수급 둘 다 매도 아님" if f is not None and i is not None else "전날 수급 자료 없음")
    if prog is None:
        oks.append("프로그램 자료 없음")
    elif prog < 0:
        fails.append(f"프로그램 순매도({prog / 1e8:+,.1f}억)")
    else:
        oks.append(f"프로그램 {prog / 1e8:+,.1f}억")
    if theme is None:
        oks.append("테마 자료 없음")
    elif theme[1] < THEME_MIN:
        fails.append("테마 형성 없음" + (f"({theme[0]} {theme[1]}종목)" if theme[0] else ""))
    else:
        oks.append(f"테마 {theme[0]} {theme[1]}종목 +4%↑")
    return fails, oks


# ---------------------------------------------------------------- R2 판정 (스캐너가 09:10 판정 뒤 한 번)
class HoldRecheck:
    """09:10 시장 판정 뒤 첫 확인 때 한 번: 모의·실전의 전날 이전 매수 보유 종목을 R2 네 항목으로 다시 봄.
    결과 {코드: (탈락 목록, 요약)} 를 trader.r2 · real.r2 에 넣어 주면 각자 다음 확인에서 지금가와 비교해 매도."""

    def __init__(self, day: date, conn, selector=None, regime=None) -> None:
        self.day, self.conn, self.regime = day, conn, regime
        self.done = False
        if selector is not None:
            self.flow, self.themes = selector.flow, selector.themes
        else:
            from kiwoom_trading.execution.paper import load_prev_flow
            self.flow = load_prev_flow(day)
            try:
                from kiwoom_trading.common.leader import load_themes
                from kiwoom_trading.strategies.kell_squeeze.live import NAVER_DB
                self.themes = load_themes(NAVER_DB)
            except Exception:
                logging.exception("R2: 네이버 테마 읽기 실패 — 테마 항목은 자료 없음으로 봄")
                self.themes = {}

    def decided(self, now: datetime) -> bool:
        from kiwoom_trading.screener.market_regime import CHECKS, WINDOW_MIN
        first = CHECKS[0]
        if now.time() < first:
            return False
        r = self.regime
        end = time(first.hour, first.minute + WINDOW_MIN)
        return r is None and now.time() >= end or r is not None and (first in r.done or r.strong_up or r.strong_down or now.time() >= end)

    def _prog(self, codes: list[str]) -> dict[str, float]:
        if not codes or self.conn is None:
            return {}
        try:
            rows = self.conn.execute(f"""SELECT code, arg_max(net_amount, ts) FROM program_intraday
                                         WHERE date = ? AND code IN ({','.join('?' * len(codes))}) GROUP BY code""", [self.day, *codes]).fetchall()
            return {c: float(v) for c, v in rows if v is not None}
        except Exception:
            logging.warning("R2: 프로그램 순매수 읽기 실패 — 자료 없음으로 봄")
            return {}

    def evaluate(self, codes: Iterable[str], value_top: list) -> dict[str, tuple[list[str], str]]:
        from kiwoom_trading.strategies.kell_squeeze.live import is_etf
        codes = list(dict.fromkeys(codes))
        stocks = [x for x in sorted(value_top or [], key=lambda x: -(x.trade_value or 0)) if not is_etf(x.name)]
        rank = {x.code: k for k, x in enumerate(stocks, 1)}
        up = {x.code for x in value_top or [] if (x.change_rate or 0) >= THEME_UP}
        count: dict[str, int] = {}
        for c in up:
            for th in self.themes.get(c, ()):
                count[th] = count.get(th, 0) + 1
        prog = self._prog(codes)
        out = {}
        for c in codes:
            if not self.themes:
                theme = None
            else:
                ths = self.themes.get(c, ())
                theme = max(((th, count.get(th, 0)) for th in ths), key=lambda t: t[1], default=("", 0))
            fails, oks = recheck_fails(rank.get(c) if value_top else 0, self.flow.get(c, (None, None)), prog.get(c), theme)
            out[c] = (fails, f"탈락 {len(fails)}/4" + (f": {', '.join(fails)}" if fails else "") + (f" · 통과: {', '.join(oks)}" if oks else ""))
        return out

    def tick(self, now: datetime, value_top: list, trader=None, real=None) -> None:
        if self.done or not self.decided(now):
            return
        self.done = True
        codes = (trader.r2_codes() if trader is not None else []) + (real.r2_codes() if real is not None else [])
        if not codes:
            logging.info("R2 다시 고르기 %s: 전날 이전에 산 보유 종목 없음", f"{now:%H:%M}")
            return
        res = self.evaluate(codes, value_top)
        if trader is not None:
            trader.r2 = res
        if real is not None:
            real.r2 = res
        logging.info("R2 다시 고르기 %s: %s", f"{now:%H:%M}", " / ".join(f"{c} {v[1]}" for c, v in res.items()))


# ---------------------------------------------------------------- R4 판정 (스캐너 시작 때)
def time_stop_exits(holds: dict, today: date, db_path: Optional[str] = None) -> dict:
    """holds = {키: (코드, 매수일, 매수가)} → {키: R4 매도 사유}. 일봉은 9-14 뒤 daily_regular 정규장 값으로 덮어쓴 것 (켈 load_daily)."""
    if not holds:
        return {}
    import pandas as pd
    from kiwoom_trading.strategies.kell_squeeze.live import load_daily
    out = {}
    try:
        hist = load_daily([c for c, _, _ in holds.values()], today, **({"db_path": db_path} if db_path else {}))
    except Exception:
        logging.exception("R4: 일봉 읽기 실패 — 오늘 시간 손절 판정 안 함")
        return {}
    for key, (code, bday, buy) in holds.items():
        g = hist.get(code)
        if g is None or not buy:
            continue
        g = g[pd.to_datetime(g["date"]) >= pd.Timestamp(bday)]
        why = time_stop([float(x) for x in g["close"]], float(buy), len(g))
        if why:
            out[key] = why
    return out
