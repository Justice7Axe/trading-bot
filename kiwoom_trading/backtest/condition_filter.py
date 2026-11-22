"""🍔 영웅문4 조건검색식(햄버거1·햄버거2·불개미검증) 재현 + '지금까지 매매를 이 조건에 걸린 종목만 했다면' 비교 (2026-11-22 사용자 요청).

조건식 원문 (영웅문4 캡처, 대상 업종 전체·거래정지/환기/정리매매 제외, 매수 기준):
  [햄버거1] (2026-11-22 변경) 검색시간 09:10~15:20 · 시총(현재가) ≥ 4,000억 · [1분] 0봉전 고가 ≥ 20봉 중 최고 종가 · [1분] 대금 ≥ 10억
            · [1분] 1봉전 종가 대비 0봉전 고가 ≥ +0.4% · [일] 1봉전 종가 대비 0봉전 종가 ≤ +24%
  [햄버거2] (2026-11-22 변경) 검색시간 09:10~15:10 · 시총 ≥ 4,000억 · 20봉 최고 종가 돌파(햄버거1 과 같은 해석) · [1분] 대금 ≥ 25억
            · [1분] 1봉전 종가 대비 0봉전 고가 ≥ +0.6% · [일] 등락률 ≤ +24%
  [불개미검증] 시총 ≥ 4,000억 · [일] 거래대금 ≥ 4,000억 (그 시각까지 누적) · [일] 등락률 ≥ +4% (그 시각 현재가)

재현 방식 (모두 장중 '그 시각까지 아는 값'):
  - 1분봉: data/minute_history.duckdb (통합 AL, 원가격). 날짜 D 종목 = D 의 대금 상위 ∪ D-1 의 대금 상위 (약 550종목).
    이미 일어난 매매의 조건만 확인하므로 종목을 고르는 미래 정보 문제는 없음 (대상 종목은 매매 기록이 정함).
    여기에 없는 종목·날은 daily_ohlcv.duckdb 의 minute_ohlcv(AL, 10-13~, 스캐너 감시 종목)·kang_minute(AL, 장중 +15% 종목)로 채움.
    정규장 봉(09:00~15:30, 15:20~15:29 단일가는 봉 없음, 15:30 = 종가 단일가 봉)만 씀.
  - 1분 대금 = 거래량 × (고가+저가+종가)/3 (햄버거 rules.bar_value 와 같음, 봉 대금 칸이 없어 근사).
    정규장 시간 AL 거래량 ≈ KRX 거래량 (10-13~ 둘 다 있는 77.9만 봉에서 KRX/AL = 0.99) → KRX 기준 조건과 1% 안 차이.
  - '0봉전 고가가 20봉중 최고종가': 키움 정의대로 0봉 포함 → 고가[0] ≥ max(종가[0..19]).
    고가[0] ≥ 종가[0] 이 늘 맞으므로 이는 고가[0] ≥ max(종가[1..19]) 와 같음. 0봉 제외 해석(고가[0] ≥ max(종가[1..20]))은 *_x 칸으로 따로 셈.
    20봉은 키움 1분 차트처럼 날을 넘어 이어 셈 (09:00 봉은 전날 15:30 봉까지), 전날 1분봉이 없으면 그날 봉만으로 셈.
  - 1봉전 종가: 바로 앞 정규장 봉 종가 (09:00 봉은 전날 정규장 종가).
  - 전일 종가(일 등락률 기준): 전 거래일 1분봉 정규장 마지막 종가 → daily_regular 종가 → (09-14 전만) daily_ohlcv 종가.
    09-14 부터 daily_ohlcv 종가 = 20:00 애프터 종가라 쓰지 않음.
  - 시가총액 = 상장주식수(stocks.listed_shares, 지금 값) × 그 봉 종가. 그 사이 증자·분할은 반영 못 함.
  - 불개미검증 누적 대금 = 그날 09:00 부터 그 봉까지 1분 대금 합 (프리장 대금 안 넣음).

매매 판정 (full_report.Data 가 모은 끝난 매매 그대로, 5️⃣ 이상 체결 = full_report.odd_fill 은 뺌):
  (가) 매수 시각(그 분 봉 포함)까지 그날 한 번이라도 걸림 / (나) 매수 분 포함 직전 10분 안에 걸림.
  정규장 09:01~15:30 매수만 장중 판정. 09:00 분 매수(시가 매수형)는 전 거래일, 15:30 뒤(애프터) 매수는 그날 정규장에서 '그날 걸렸나'만 봄 ((가)=(나)).
  인버스·지수 ETF 는 판정에서 빼고 따로 셈. 1분봉이 없으면 일봉으로 확실히 탈락인지만 보고(시총 상한·하루 대금 상한·하루 고가 등락률), 아니면 '판정 불가'.

    python -m kiwoom_trading.backtest.condition_filter --root D:/Ellie/trading            # 계산 + 보고서 (md·html)
    python -m kiwoom_trading.backtest.condition_filter --root D:/Ellie/trading --rebuild  # 1분봉 조건 판정 표 다시 만들기
"""
from __future__ import annotations

import argparse
import html as _html
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT


# ------------------------------------------------------------------ 조건식 정의
@dataclass(frozen=True)
class MinuteCond:
    """햄버거형: 1분봉 하나로 판정."""
    key: str
    label: str
    min_cap: float = 4_000e8          # 시가총액 (원)
    min_bar_value: float = 17e8       # 1분봉 대금 (원)
    min_high_pct: float = 0.004       # 1봉전 종가 대비 0봉전 고가
    max_day_pct: float = 0.24         # 전일 종가 대비 현재가
    t_from: time = time(9, 0)         # 검색시간 (봉 시작 시각 기준)
    t_to: time = time(15, 30)

    def check(self, cap: float, high: float, maxc20: float, bar_value: float, prev_bar_close: float, close: float, prev_close: float,
              t: time) -> bool:
        """봉 하나 판정 (문서·시험용, 실제 계산은 sql())."""
        return (self.t_from <= t <= self.t_to and cap >= self.min_cap and high >= maxc20 and bar_value >= self.min_bar_value
                and prev_bar_close > 0 and high / prev_bar_close - 1 >= self.min_high_pct and close / prev_close - 1 <= self.max_day_pct)

    def sql(self, excl: bool = False) -> str:
        mx = "maxc20x" if excl else "maxc20"
        return (f"(tm BETWEEN TIME '{self.t_from}' AND TIME '{self.t_to}' AND cap >= {self.min_cap} AND h >= {mx} AND val >= {self.min_bar_value}"
                f" AND c1 > 0 AND h / c1 - 1 >= {self.min_high_pct} AND c / pc - 1 <= {self.max_day_pct})")


@dataclass(frozen=True)
class DayCond:
    """불개미검증형: 그 시각까지 누적 대금·현재 등락률."""
    key: str
    label: str
    min_cap: float = 4_000e8
    min_day_value: float = 4_000e8
    min_day_pct: float = 0.04

    def check(self, cap: float, cum_value: float, close: float, prev_close: float) -> bool:
        return cap >= self.min_cap and cum_value >= self.min_day_value and close / prev_close - 1 >= self.min_day_pct

    def sql(self, excl: bool = False) -> str:
        return f"(cap >= {self.min_cap} AND cumval >= {self.min_day_value} AND c / pc - 1 >= {self.min_day_pct})"


H1 = MinuteCond("h1", "햄버거1 (11-22 변경)", min_bar_value=10e8, min_high_pct=0.004, t_from=time(9, 10), t_to=time(15, 20))
H2 = MinuteCond("h2", "햄버거2 (11-22 변경)", min_bar_value=25e8, min_high_pct=0.006, t_from=time(9, 10), t_to=time(15, 10))
BG = DayCond("bg", "불개미검증")
CONDS = (H1, H2, BG)

REG_FROM, REG_TO = time(9, 0), time(15, 30)
NXT_SWITCH = date(2026, 9, 14)          # 이날부터 daily_ohlcv 종가 = 20:00 애프터 종가
MIN_N = 10                              # 이보다 적으면 '건수 부족'
# stocks 표에 없는 종목 (상장주식수, 상장 뒤 최고가) — 키움 ka10001 로 2026-11-22 확인. 시총 위쪽 한계로 '확실히 탈락' 판정에만 씀
SHARES_EXTRA = {"0205H0": (6_670_000, 4_160)}     # 에스케이증권제14호기업인수목적 (SPAC): 최대 시총 약 277억
INVERSE_KINDS = ("5️⃣ 약세장 인버스", "인버스 갭")
ETF_NAME = re.compile(r"인버스|레버리지|KODEX|TIGER|KOSEF|ARIRANG|HANARO|KBSTAR|RISE |ACE |SOL |PLUS |ETN|선물")
GROUPS = [("real", "🔴 실전"), ("paper", "🟢 모의"), ("virtual", "🟣 가상"), ("account", "🧾 매매별 가상 계좌")]


def paths(root: str) -> dict:
    d = os.path.join(root, "data")
    return {"mh": os.path.join(d, "minute_history.duckdb"), "daily": os.path.join(d, "daily_ohlcv.duckdb"),
            "reg": os.path.join(d, "daily_regular.duckdb"), "kang": os.path.join(d, "kang_minute.duckdb"),
            "cache": os.path.join(d, "condition_filter", "hits.duckdb"), "reports": os.path.join(d, "reports")}


# ------------------------------------------------------------------ 1분봉 조건 판정 표
def build_hits(root: str, extra_codedays: set[tuple[str, date]]) -> None:
    """모든 1분봉에 세 조건을 판정해 걸린 봉(hits)과 종목·날 자료 유무(cover)를 캐시 DB 에 저장."""
    P = paths(root)
    os.makedirs(os.path.dirname(P["cache"]), exist_ok=True)
    if os.path.exists(P["cache"]):
        os.remove(P["cache"])
    con = duckdb.connect(P["cache"])
    con.execute("SET preserve_insertion_order = false")
    con.execute(f"SET temp_directory = '{os.path.join(os.path.dirname(P['cache']), 'tmp').replace(os.sep, '/')}'")
    for a, k in (("mh", "mh"), ("dl", "daily"), ("rg", "reg"), ("kg", "kang")):
        con.execute(f"ATTACH '{P[k].replace(os.sep, '/')}' AS {a} (READ_ONLY)")
    reg = f"strftime(ts, '%H:%M') BETWEEN '{REG_FROM:%H:%M}' AND '{REG_TO:%H:%M}'"
    # 1) 정규장 봉: minute_history 우선, 없는 종목·날만 다른 곳에서 (매매가 있던 종목·날과 그 전날만)
    con.execute(f"""CREATE TABLE bars AS SELECT code, ts, ts::date d, open o, high h, low l, close c, volume v, 'mh' src
                    FROM mh.minute_ohlcv WHERE {reg} AND volume > 0""")
    con.execute("CREATE TABLE have AS SELECT DISTINCT code, d FROM bars")
    con.execute("CREATE TABLE want(code VARCHAR, d DATE)")
    if extra_codedays:
        con.executemany("INSERT INTO want VALUES (?, ?)", sorted(extra_codedays))
    for alias, tag in (("dl", "dl"), ("kg", "kg")):
        con.execute(f"""INSERT INTO bars SELECT m.code, m.ts, m.ts::date, m.open, m.high, m.low, m.close, m.volume, '{tag}'
                        FROM {alias}.minute_ohlcv m JOIN want w ON m.code = w.code AND m.ts::date = w.d
                        WHERE m.exchange = 'AL' AND {reg.replace('ts', 'm.ts')} AND m.volume > 0
                          AND NOT EXISTS (SELECT 1 FROM have x WHERE x.code = m.code AND x.d = m.ts::date)""")
        con.execute("DELETE FROM have; INSERT INTO have SELECT DISTINCT code, d FROM bars")
    con.execute("""CREATE TABLE cover AS SELECT code, d, any_value(src) src, count(*) nbars, min(ts) first_ts, max(ts) last_ts FROM bars GROUP BY 1, 2""")
    # 2) 달력·전일 종가·주식수
    con.execute("""CREATE TABLE cal AS SELECT d, lag(d) OVER (ORDER BY d) pd FROM (
                     SELECT DISTINCT date d FROM dl.daily_ohlcv WHERE code IN ('005930', '000660') UNION SELECT DISTINCT d FROM cover)""")
    con.execute("""CREATE TABLE lastbar AS SELECT code, d, arg_max(c, ts) c, max(ts) lt FROM bars GROUP BY 1, 2""")
    con.execute(f"""CREATE TABLE pclose AS
        SELECT v.code, v.d, coalesce(CASE WHEN strftime(lb.lt, '%H:%M') >= '15:19' THEN lb.c END, r.close,
                                     CASE WHEN cal.pd < DATE '{NXT_SWITCH}' THEN dd.close END) pc, cal.pd
        FROM cover v JOIN cal USING (d)
        LEFT JOIN lastbar lb ON lb.code = v.code AND lb.d = cal.pd
        LEFT JOIN rg.daily_regular r ON r.code = v.code AND r.date = cal.pd
        LEFT JOIN dl.daily_ohlcv dd ON dd.code = v.code AND dd.date = cal.pd""")
    con.execute("CREATE TABLE shares AS SELECT code, listed_shares sh FROM dl.stocks WHERE listed_shares > 0")
    # 3) 봉별 값 (창 함수)
    con.execute("""CREATE TABLE feat AS
        WITH w AS (
          SELECT code, ts, d, h, c, v * (h + l + c) / 3.0 val,
                 lag(c) OVER (PARTITION BY code ORDER BY ts) lc, lag(d) OVER (PARTITION BY code ORDER BY ts) ld,
                 max(c) OVER (PARTITION BY code ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) mx_all,
                 min(d) OVER (PARTITION BY code ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) md_all,
                 max(c) OVER (PARTITION BY code, d ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) mx_day,
                 max(c) OVER (PARTITION BY code ORDER BY ts ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) mxx_all,
                 min(d) OVER (PARTITION BY code ORDER BY ts ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) mdx_all,
                 max(c) OVER (PARTITION BY code, d ORDER BY ts ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) mxx_day,
                 sum(v * (h + l + c) / 3.0) OVER (PARTITION BY code, d ORDER BY ts ROWS UNBOUNDED PRECEDING) cumval
          FROM bars)
        SELECT w.code, w.ts, w.d, w.ts::time tm, w.h, w.c, w.val, w.cumval, p.pc, s.sh * w.c cap,
               CASE WHEN w.ld = w.d OR w.ld = p.pd THEN w.lc ELSE p.pc END c1,
               CASE WHEN w.md_all >= coalesce(p.pd, w.d) THEN w.mx_all ELSE w.mx_day END maxc20,
               CASE WHEN w.mdx_all >= coalesce(p.pd, w.d) THEN w.mxx_all ELSE coalesce(w.mxx_day, w.c) END maxc20x
        FROM w JOIN pclose p ON p.code = w.code AND p.d = w.d LEFT JOIN shares s ON s.code = w.code
        WHERE p.pc > 0""")
    flags = ", ".join(f"{c.sql()} {c.key}, {c.sql(True)} {c.key}_x" for c in CONDS)
    anyf = " OR ".join(f"{c.sql()} OR {c.sql(True)}" for c in CONDS)
    con.execute(f"CREATE TABLE hits AS SELECT code, ts, d, tm, val, cumval, cap, c / pc - 1 day_pct, h / c1 - 1 high_pct, {flags} FROM feat WHERE {anyf}")
    con.execute("CREATE TABLE meta AS SELECT now() made_at, (SELECT count(*) FROM bars) nbars, (SELECT count(*) FROM feat) nfeat, "
                "(SELECT count(*) FROM bars b WHERE NOT EXISTS (SELECT 1 FROM shares s WHERE s.code = b.code)) no_shares")
    for t in ("bars", "feat", "lastbar", "have", "want"):
        con.execute(f"DROP TABLE {t}")
    con.close()


# ------------------------------------------------------------------ 매매 판정
@dataclass
class Judged:
    t: object                       # full_report.Trade
    mode: str                       # intraday / session (장 밖·시가 매수 → 그날 전체) / etf
    sday: Optional[date]            # 판정한 정규장 날
    src: str = ""                   # 1분봉 출처 (mh / dl / kg / 일봉 / 없음)
    res: dict = field(default_factory=dict)   # {(cond, 'ga'|'na'): True/False/None}
    first_hit: dict = field(default_factory=dict)


def is_etf(t, etf_codes: set) -> bool:
    return t.code in etf_codes or t.kind in INVERSE_KINDS or bool(ETF_NAME.search(t.name or ""))


def load_trades(root: str):
    from kiwoom_trading.execution import full_report as F
    data = F.Data(root)
    out = []
    for t in data.trades + data.accounts:
        if not t.closed or F.odd_fill(t):
            continue
        out.append(t)
    odd = [t for t in data.trades if t.closed and F.odd_fill(t)]
    return out, odd, F


def session_of(t, cal: list[date]) -> tuple[str, Optional[date]]:
    bt = t.buy_ts
    d, tm = bt.date(), bt.time()
    prev = [x for x in cal if x < d]
    upto = [x for x in cal if x <= d]
    if time(9, 1) <= tm <= REG_TO and d in cal:
        return "intraday", d
    if tm > REG_TO:
        return "session", (upto[-1] if upto else None)
    return "session", (prev[-1] if prev else None)


def judge(root: str, trades: list, etf_codes: set) -> tuple[list[Judged], dict]:
    P = paths(root)
    con = duckdb.connect(P["cache"], read_only=True)
    cal = [r[0] for r in con.execute("SELECT d FROM cal ORDER BY d").fetchall()]
    cover = {(c, d): s for c, d, s in con.execute("SELECT code, d, src FROM cover").fetchall()}
    hits = defaultdict(list)
    for row in con.execute(f"SELECT code, d, ts, {', '.join(c.key for c in CONDS)} FROM hits ORDER BY ts").fetchall():
        hits[(row[0], row[1])].append(row[2:])
    meta = dict(zip(("made_at", "nbars", "nfeat", "no_shares"), con.execute("SELECT * FROM meta").fetchone()))
    con.close()
    dl = duckdb.connect(P["daily"], read_only=True)
    rg = duckdb.connect(P["reg"], read_only=True)
    shares = dict(dl.execute("SELECT code, listed_shares FROM stocks WHERE listed_shares > 0").fetchall())
    out = []
    for t in trades:
        if is_etf(t, etf_codes):
            out.append(Judged(t, "etf", None, "ETF"))
            continue
        mode, sday = session_of(t, cal)
        j = Judged(t, mode, sday)
        if sday is None:
            j.src = "없음"
            j.res = {(c.key, m): None for c in CONDS for m in ("ga", "na")}
            out.append(j)
            continue
        key = (t.code, sday)
        if key in cover:
            j.src = cover[key]
            hs = hits.get(key, [])
            if mode == "intraday":
                bm = t.buy_ts.replace(second=0, microsecond=0)
                lo = bm - timedelta(minutes=9)
            else:
                bm, lo = datetime.combine(sday, time(23, 59)), datetime.combine(sday, time(0, 0))
            for i, c in enumerate(CONDS):
                ga = [h[0] for h in hs if h[1 + i] and h[0] <= bm]
                na = [h for h in ga if h >= lo]
                j.res[(c.key, "ga")] = bool(ga)
                j.res[(c.key, "na")] = bool(na)
                if ga:
                    j.first_hit[c.key] = ga[0]
        else:
            # 1분봉 없음 → 일봉으로 확실히 탈락인지만 봄 (위쪽 한계값 = 하루 고가·하루 대금, 이 값으로도 못 넘으면 장중 어느 때도 못 넘음)
            j.src = "일봉"
            sh = shares.get(t.code) or SHARES_EXTRA.get(t.code, (None, None))[0]
            r = dl.execute("SELECT high, value FROM daily_ohlcv WHERE code = ? AND date = ?", [t.code, sday]).fetchone()
            rr = rg.execute("SELECT high, value FROM daily_regular WHERE code = ? AND date = ?", [t.code, sday]).fetchone()
            pd = [x for x in cal if x < sday]
            pc = None
            if pd:
                q = rg.execute("SELECT close FROM daily_regular WHERE code = ? AND date = ?", [t.code, pd[-1]]).fetchone()
                if q:
                    pc = q[0]
                elif pd[-1] < NXT_SWITCH:
                    q = dl.execute("SELECT close FROM daily_ohlcv WHERE code = ? AND date = ?", [t.code, pd[-1]]).fetchone()
                    pc = q[0] if q else None
            hi = (rr or r or (None, None))[0] or SHARES_EXTRA.get(t.code, (None, None))[1]
            val = max(x for x in ((r or (0, 0))[1], (rr or (0, 0))[1], 0) if x is not None) if (r or rr) else None
            for c in CONDS:
                fail = False
                if sh and hi and sh * hi < c.min_cap:
                    fail = True
                if isinstance(c, MinuteCond) and val is not None and val < c.min_bar_value:
                    fail = True
                if isinstance(c, DayCond):
                    if val is not None and val < c.min_day_value:
                        fail = True
                    if pc and hi and hi / pc - 1 < c.min_day_pct:
                        fail = True
                for m in ("ga", "na"):
                    j.res[(c.key, m)] = False if fail else None
            if all(v is None for v in j.res.values()):
                j.src = "없음"
        out.append(j)
    return out, meta


# ------------------------------------------------------------------ 집계
def stats(ts: list) -> dict:
    ts = sorted(ts, key=lambda t: t.sell_ts)
    pn = [t.pnl for t in ts]
    n = len(pn)
    wins = [p for p in pn if p > 0]
    loss = [p for p in pn if p < 0]
    gw, gl = sum(wins), -sum(loss)
    cum = peak = mdd = 0.0
    for p in pn:
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    rets = [t.ret for t in ts if t.ret is not None]
    aw = gw / len(wins) if wins else None
    al = gl / len(loss) if loss else None
    return {"n": n, "win": len(wins) / n if n else None, "sum": sum(pn), "ret": sum(rets) / len(rets) if rets else None,
            "payoff": aw / al if (aw and al) else None, "pf": gw / gl if gl else None, "mdd": mdd}


def f_won(x) -> str:
    return "—" if x is None else f"{x:+,.0f}"


def f_pct(x, d=2) -> str:
    return "—" if x is None else f"{x:+.{d}%}"


def f_num(x) -> str:
    return "—" if x is None else f"{x:.2f}"


def stat_cells(s: dict) -> list[str]:
    if s["n"] == 0:
        return ["0", "—", "0", "—", "—", "—", "—"]
    if s["n"] < MIN_N:
        return [f"{s['n']}", "건수 부족", f_won(s["sum"]), "건수 부족", "건수 부족", "건수 부족", f_won(-s["mdd"])]
    return [f"{s['n']}", f"{s['win']:.0%}", f_won(s["sum"]), f_pct(s["ret"]), f_num(s["payoff"]), f_num(s["pf"]), f_won(-s["mdd"])]


STAT_HEAD = ["건수", "승률", "합계 손익(원)", "건당 평균 손익률", "손익비", "PF", "MDD(원)"]


def md_table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def frequency(root: str) -> dict:
    """minute_history(그날 ∪ 전날 대금 상위 약 550종목) 안에서 조건이 하루에 몇 종목·몇 번 걸렸나, 그날 첫 포착 시각."""
    P = paths(root)
    con = duckdb.connect(P["cache"], read_only=True)
    ndays = con.execute("SELECT count(DISTINCT d) FROM cover WHERE src = 'mh'").fetchone()[0]
    span = con.execute("SELECT min(d), max(d) FROM cover WHERE src = 'mh'").fetchone()
    per_day_codes = con.execute("SELECT avg(n) FROM (SELECT d, count(DISTINCT code) n FROM cover WHERE src = 'mh' GROUP BY d)").fetchone()[0]
    res = {"ndays": ndays, "span": span, "codes_per_day": per_day_codes, "cond": {}}
    buckets = [("09:00~09:04", "09:00", "09:04"), ("09:05~09:09", "09:05", "09:09"), ("09:10~09:29", "09:10", "09:29"),
               ("09:30~09:59", "09:30", "09:59"), ("10:00~10:59", "10:00", "10:59"), ("11:00~12:59", "11:00", "12:59"),
               ("13:00~15:10", "13:00", "15:10"), ("15:11~15:30", "15:11", "15:30")]
    for c in CONDS:
        k = c.key
        base = f"FROM hits h JOIN cover v USING (code, d) WHERE v.src = 'mh' AND h.{k}"
        days_any = con.execute(f"SELECT count(DISTINCT d) {base}").fetchone()[0]
        nstock = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT code, d {base})").fetchone()[0]
        # 걸림 횟수 = 조건이 꺼져 있다가 켜진 횟수 (같은 종목 바로 앞 1분봉이 안 걸렸으면 새로 걸림)
        nev = con.execute(f"""SELECT count(*) FROM (SELECT code, d, ts, lag(ts) OVER (PARTITION BY code, d ORDER BY ts) pts {base})
                               WHERE pts IS NULL OR ts - pts > INTERVAL 1 MINUTE""").fetchone()[0]
        nbar = con.execute(f"SELECT count(*) {base}").fetchone()[0]
        firsts = con.execute(f"SELECT strftime(min(ts), '%H:%M') FROM hits h JOIN cover v USING (code, d) WHERE v.src = 'mh' AND h.{k} GROUP BY code, d").fetchall()
        dist = Counter()
        for (f,) in firsts:
            for lb, a, b in buckets:
                if a <= f <= b:
                    dist[lb] += 1
        nx = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT code, d FROM hits h JOIN cover v USING (code, d) WHERE v.src = 'mh' AND h.{k}_x)").fetchone()[0]
        res["cond"][k] = {"days_any": days_any, "stock_days": nstock, "events": nev, "bars": nbar, "dist": [(lb, dist[lb]) for lb, _, _ in buckets],
                          "stock_days_x": nx}
    con.close()
    # 자료 범위 점검: 하루 대금이 큰 종목·날 중 minute_history 에 있는 비율 (불개미검증 4,000억은 거의 다 있어야 함)
    dl = duckdb.connect(P["daily"], read_only=True)
    dl.execute(f"ATTACH '{P['cache'].replace(os.sep, '/')}' AS cf (READ_ONLY)")
    dl.execute(f"ATTACH '{P['reg'].replace(os.sep, '/')}' AS rg (READ_ONLY)")
    cov = {}
    for lim in (4_000e8, 1_000e8, 300e8, 100e8):
        q = dl.execute(f"""
            WITH dv AS (
              SELECT o.code, o.date d, o.value v
              FROM daily_ohlcv o
              WHERE o.date BETWEEN DATE '{span[0]}' AND DATE '{span[1]}' AND o.code IN (SELECT code FROM stocks WHERE listed_shares > 0))
            SELECT count(*), count(c.code) FROM dv LEFT JOIN cf.cover c ON c.code = dv.code AND c.d = dv.d AND c.src = 'mh' WHERE dv.v >= {lim}""").fetchone()
        cov[lim] = q
    res["coverage"] = cov
    return res


# ------------------------------------------------------------------ 보고서
GLOSS = {"KRX": "Korea Exchange, 한국거래소 정규장", "NXT": "Nextrade, 대체거래소 (프리장·애프터장)", "AL": "통합 시세 (KRX + NXT)",
         "ETF": "Exchange Traded Fund, 상장지수펀드", "PF": "Profit Factor, 이익 합계 ÷ 손실 합계",
         "MDD": "Maximum Drawdown, 누적 손익 고점에서 가장 많이 빠진 폭", "SPAC": "Special Purpose Acquisition Company, 기업인수목적회사"}


def gloss(text: str) -> str:
    found = []
    for ab, ex in GLOSS.items():
        m = re.search(rf"(?<![A-Za-z]){ab}(?![A-Za-z])", text)
        if m:
            found.append((m.start(), ab, ex))
    if not found:
        return ""
    found.sort()
    return "\n\n약어 풀이\n" + "\n".join(f"- {ab}: {ex}" for _, ab, ex in found)


def build_report(root: str, js: list[Judged], odd: list, meta: dict, freq: dict, today: date) -> tuple[str, dict]:
    secs: list[tuple[str, str]] = []
    first = min(j.t.buy_date for j in js)
    last = max(j.t.sell_ts.date() for j in js)
    by_g = {g: [j for j in js if j.t.group == g] for g, _ in GROUPS}
    keyres = {}

    # 1. 조건식
    cond_rows = [
        ["검색시간", "**09:10~15:20**", "**09:10~15:10**", "제한 없음"],
        ["시가총액 (현재가 기준)", "4,000억 이상", "4,000억 이상", "4,000억 이상"],
        ["[1분] 0봉전 고가 ≥ 20봉 중 최고 종가", "예", "예 (같은 해석)", "—"],
        ["[1분] 1분봉 대금", "**10억 이상**", "**25억 이상**", "—"],
        ["[1분] 1봉전 종가 대비 0봉전 고가", "**+0.4% 이상**", "**+0.6% 이상**", "—"],
        ["[일] 전일 종가 대비 현재가", "+24% 이하", "+24% 이하", "**+4% 이상**"],
        ["[일] 그날 누적 거래대금", "—", "—", "**4,000억 이상**"],
    ]
    s1 = (f"영웅문4 조건검색식 세 개를 우리 1분봉으로 다시 만들고, {first:%Y-%m-%d} ~ {last:%Y-%m-%d} 에 실제로 적힌 실전·모의·가상 매매를 "
          "'그 종목이 매수 때 이 조건에 걸려 있었나' 로 나눠 봄. 매매 규칙은 하나도 바꾸지 않았고, 기록된 손익을 그대로 나눠 더한 것임.\n\n"
          + md_table(["조건", "햄버거1 (11-22 변경)", "햄버거2 (11-22 변경)", "불개미검증"], cond_rows)
          + "\n\n- 대상은 업종 전체, 거래정지·환기종목·정리매매 제외, 장중 조건검색이라 모든 값은 **그 시각까지의 장중 값**으로 판정함 (불개미검증의 누적 대금·등락률도 그 시각 기준).\n"
          "- 햄버거1·햄버거2 는 2026-11-22 사용자가 바꾼 새 정의만 씀 (예전 정의는 뺌). 둘이 다른 곳은 굵게 표시한 세 칸뿐임: "
          "햄버거1 = 검색시간 09:10~15:20 · 1분 대금 10억 · 고가 +0.4%, 햄버거2 = 09:10~15:10 · 25억 · +0.6%. 시총 4,000억 · 1분봉 20봉 최고 종가 돌파 · 당일 +24% 이하는 같음.\n"
          "- 검색시간은 1분봉 시작 시각으로 셈. 15:20~15:29 는 종가 단일가 시간이라 1분봉이 없어서 햄버거1 의 실제 마지막 판정 봉은 15:19 봉임.\n"
          "- **'0봉전 고가가 20봉중 최고종가'** 는 키움 정의대로 지금 봉을 넣어 `고가[0] ≥ 최근 20개 1분봉 종가(지금 봉 포함) 중 최고값` 으로 셈. "
          "지금 봉의 고가는 늘 지금 봉 종가 이상이라, 이는 '앞 19개 봉 종가 최고값 이상' 과 같음. 지금 봉을 빼고 앞 20개 봉으로 보는 해석도 따로 셌는데 걸린 종목·날 수 차이는 6절 표 끝 칸에 적음.\n"
          "- 20봉은 키움 1분 차트처럼 날을 넘어 이어 셈 (09:00 봉은 전날 정규장 마지막 봉들까지 봄). 전날 1분봉이 없으면 그날 봉만으로 셈.")
    secs.append(("1. 조건식과 재현 방식", s1))

    # 2. 자료
    cov = freq["coverage"]
    src_cnt = Counter(j.src for j in js if j.mode != "etf")
    s2 = ("| 무엇 | 어디서 | 주의 |\n|---|---|---|\n"
          f"| 1분봉 | `data/minute_history.duckdb` (통합 AL, 원가격) — 날짜 D 종목 = **D 의 대금 상위 ∪ D-1 의 대금 상위** (약 550종목) | 그날 상위가 섞여 있어 종목을 고르는 데 쓰면 미래 정보지만, 여기서는 이미 산 종목의 조건만 확인하므로 문제없음. 하루 대금이 큰 종목은 거의 다 들어 있음 |\n"
          "| 1분봉 보충 | `daily_ohlcv.duckdb` 의 `minute_ohlcv` (AL, 10-13~, 스캐너 감시 종목) → `kang_minute.duckdb` (AL, 장중 +15% 종목) | 매매가 있었던 종목·날에서 위 자료가 없을 때만 씀 |\n"
          "| 1분 대금 | 거래량 × (고가+저가+종가)/3 | 봉 대금 칸이 없어 근사 (햄버거 코드 `rules.bar_value` 와 같음) |\n"
          "| 전일 종가 | 전날 1분봉 정규장 마지막 종가 → `daily_regular` 종가 → (09-14 전만) `daily_ohlcv` 종가 | 09-14 부터 `daily_ohlcv` 종가는 20:00 애프터 종가라 쓰지 않음 |\n"
          "| 시가총액 | 상장주식수(`stocks.listed_shares`, 지금 값) × 그 봉 종가 | 기간 중 증자·분할·소각은 반영 못 함 |\n"
          "| 매매 기록 | `screener.duckdb` 를 읽기 전용으로, `execution/full_report.py` 의 `Data` 가 모으는 방식 그대로 | 비용(모의·가상 0.25%, 실전은 기록된 손익) 같음 |\n\n"
          "- **1분 대금은 KRX 만인지 통합(AL)인지**: 1분봉은 전부 통합(AL)임. 정규장 시간에는 NXT 거래가 아주 작아서, 10-13 부터 KRX·AL 둘 다 있는 77.9만 개 봉에서 "
          "KRX 거래량 ÷ AL 거래량 = 0.99 였음. 영웅문 조건검색이 KRX 대금으로 판정해도 차이는 1% 안팎이라 10억·25억 경계 근처 몇 봉만 갈릴 수 있음.\n"
          "- 불개미검증의 누적 대금도 09:00 부터 그 봉까지 정규장 1분 대금 합이라 프리장(NXT 08:00~08:50) 대금은 넣지 않음.\n"
          f"- 1분봉 자료 기간: {freq['span'][0]} ~ {freq['span'][1]} ({freq['ndays']}거래일, 하루 평균 {freq['codes_per_day']:.0f}종목).\n"
          f"- 자료 범위 점검 (그 기간, `daily_ohlcv` 하루 대금 기준 — 09-14 부터는 애프터 포함 통합 대금): 하루 대금 4,000억 이상 종목·날 {cov[4_000e8][0]:,}건 중 {cov[4_000e8][1]:,}건"
          f"({cov[4_000e8][1] / max(cov[4_000e8][0], 1):.0%}) 이 1분봉에 있음, 1,000억 이상 {cov[1_000e8][1] / max(cov[1_000e8][0], 1):.0%}, "
          f"300억 이상 {cov[300e8][1] / max(cov[300e8][0], 1):.0%}, 100억 이상 {cov[100e8][1] / max(cov[100e8][0], 1):.0%}. "
          "그래서 6절의 '하루에 몇 종목 걸렸나' 는 영웅문과 거의 같은 값으로 봐도 됨 (빠질 수 있는 것은 그날·전날 모두 상위 밖인데 1분 10억 봉이 나온 종목뿐).\n"
          f"- 매매 판정에 쓴 1분봉 출처 (ETF 뺀 {sum(src_cnt.values())}건): minute_history {src_cnt['mh']}건, 스캐너 1분봉 {src_cnt['dl']}건, kang_minute {src_cnt['kg']}건, "
          f"1분봉 없이 일봉으로만 본 것 {src_cnt['일봉']}건 (조건별로 확실히 탈락이면 걸러짐, 모르면 판정 불가 — 4절 표), 세 조건 모두 판정 불가 {src_cnt['없음']}건.")
    secs.append(("2. 쓴 자료와 함정 점검", s2))

    # 3. 판정 방식
    mode_cnt = Counter(j.mode for j in js)
    s3 = (f"- 대상: 끝난 매매 {len(js)}건 (🔴 실전 {len(by_g['real'])} · 🟢 모의 {len(by_g['paper'])} · 🟣 가상 {len(by_g['virtual'])} · 🧾 매매별 가상 계좌 {len(by_g['account'])}). "
          "🧾 매매별 가상 계좌는 모의 신호를 매매마다 따로 둔 100만 원 계좌라 다른 구분과 겹치므로 따로 셈.\n"
          + (f"- 뺀 것: {', '.join(f'{t.name} {t.kind} {t.buy_date:%m-%d} ({t.ret:+.1%})' for t in odd)} — full_report 와 같이 1배 인버스 ETF 가 하룻밤 ±10% 넘게 움직인 이상 체결 기록이라 뺌.\n" if odd else "")
          + "- **(가)** 매수 시각까지(매수한 분의 1분봉 포함) 그날 한 번이라도 조건에 걸렸으면 통과.\n"
          "- **(나)** 매수한 분을 포함해 직전 10분(1분봉 10개) 안에 걸렸으면 통과.\n"
          "- 매수한 분의 1분봉은 매수 뒤 몇십 초 값까지 들어 있어 아주 조금 미래 값이 섞임 (요청대로 매수 분 포함).\n"
          f"- 정규장 09:01~15:30 매수({mode_cnt['intraday']}건)만 장중으로 판정함. 09:00 분 매수(📅 자사주 신탁처럼 시가에 사는 매매)는 **전 거래일** 정규장, "
          f"15:30 뒤 애프터 매수(🌙 종가 재돌파 등)는 **그날** 정규장에서 '그날 한 번이라도 걸렸나' 만 봄 — 이 {mode_cnt['session']}건은 (가)=(나).\n"
          f"- 인버스·지수 ETF 매매 {mode_cnt['etf']}건은 시총 조건이 맞지 않아 판정에서 빼고 따로 적음.\n"
          "- 1분봉이 없는 종목·날은 일봉으로 '어느 시각에도 못 넘는다' 가 확실할 때만 탈락으로 봄 (주식수 × 하루 고가 < 4,000억, 하루 대금 < 1분봉 기준 대금, "
          "불개미검증은 하루 대금 < 4,000억 또는 하루 고가 등락률 < 4%). 그것도 모르면 **판정 불가** 로 따로 셈.\n"
          f"- 숫자 읽는 법: 승률 = 이긴 건 ÷ 전체, 손익비 = 이긴 매매 평균 이익 ÷ 진 매매 평균 손실, PF = 이익 합 ÷ 손실 합, MDD = 판 순서대로 쌓은 손익이 고점에서 가장 많이 빠진 폭. "
          f"건수가 {MIN_N}건보다 적은 칸은 비율을 '건수 부족' 으로 적고 건수·합계만 보임.")
    secs.append(("3. 매매 판정 방식", s3))

    # 4. 핵심 결과
    parts = []
    summary_rows = []
    for g, glabel in GROUPS:
        J = by_g[g]
        if not J:
            continue
        stock = [j for j in J if j.mode != "etf"]
        etf = [j for j in J if j.mode == "etf"]
        rows = [["전체 (ETF 포함)"] + stat_cells(stats([j.t for j in J])), ["주식만 (판정 대상)"] + stat_cells(stats([j.t for j in stock]))]
        if etf:
            rows.append(["ETF (판정 뺌)"] + stat_cells(stats([j.t for j in etf])))
        for c in CONDS:
            for m, mlb in (("ga", "(가)"), ("na", "(나)")):
                ps = [j for j in stock if j.res.get((c.key, m)) is True]
                fs = [j for j in stock if j.res.get((c.key, m)) is False]
                us = [j for j in stock if j.res.get((c.key, m)) is None]
                sp, sf, su = stats([j.t for j in ps]), stats([j.t for j in fs]), stats([j.t for j in us])
                rows.append([f"{c.label} {mlb} 통과만"] + stat_cells(sp))
                keyres[(g, c.key, m)] = (sp, sf, su)
        parts.append(f"### {glabel}\n\n" + md_table(["구분"] + STAT_HEAD, rows))
        # 걸러진 것·판정 불가
        frows = []
        for c in CONDS:
            for m, mlb in (("ga", "(가)"), ("na", "(나)")):
                sp, sf, su = keyres[(g, c.key, m)]
                frows.append([f"{c.label} {mlb}", f"{sp['n']}", f_won(sp["sum"]), f"{sf['n']}", f_won(sf["sum"]),
                              ("피했을 손실" if sf["sum"] < 0 else "놓쳤을 이익" if sf["sum"] > 0 else "—"), f"{su['n']}", f_won(su["sum"])])
                summary_rows.append([glabel, f"{c.label} {mlb}", f"{len(stock)}", f_won(stats([j.t for j in stock])['sum']), f"{sp['n']}", f_won(sp["sum"]),
                                     f_pct(sp["ret"]) if sp["n"] >= MIN_N else "건수 부족", f"{sf['n']}", f_won(sf["sum"]), f"{su['n']}"])
        parts.append(md_table(["조건", "통과 건수", "통과 합계(원)", "걸러진 건수", "걸러진 합계(원)", "조건을 썼다면", "판정 불가 건수", "판정 불가 합계(원)"], frows))
    s4_head = ("조건을 썼다면 '통과만' 줄의 매매만 했을 것이고, '걸러진' 매매는 안 했을 것임. 걸러진 합계가 마이너스면 조건이 **피하게 해 줬을 손실**, 플러스면 **놓쳤을 이익**임. "
               "판정 불가 매매는 통과·걸러짐 어느 쪽에도 넣지 않았으므로, 통과 + 걸러짐 + 판정 불가 = 주식만 합계임.\n\n")
    s4_sum = md_table(["구분", "조건", "주식 매매 수", "주식 합계(원)", "통과", "통과 합계(원)", "통과 건당", "걸러짐", "걸러진 합계(원)", "판정 불가"], summary_rows)
    secs.append(("4. 핵심 결과 — 조건에 걸린 종목만 샀다면", s4_head + "#### 한눈에 보기\n\n" + s4_sum + "\n\n" + "\n\n".join(parts)))

    # 5. 매매별
    kind_rows = []
    allstock = [j for j in js if j.mode != "etf"]
    kinds = defaultdict(list)
    for j in allstock:
        kinds[(j.t.group, j.t.kind)].append(j)
    for (g, k), J in kinds.items():
        tot = stats([j.t for j in J])
        row = [dict(GROUPS)[g], k, f"{tot['n']}", f_won(tot["sum"])]
        delta = 0.0
        for c in CONDS:
            ps = [j for j in J if j.res.get((c.key, "ga")) is True]
            fs = [j for j in J if j.res.get((c.key, "ga")) is False]
            sp, sf = stats([j.t for j in ps]), stats([j.t for j in fs])
            row += [f"{sp['n']}", f_won(sp["sum"]), f_won(sf["sum"])]
            delta = max(delta, abs(sf["sum"]))
        un = sum(1 for j in J if all(j.res.get((c.key, "ga")) is None for c in CONDS))
        row.append(f"{un}")
        kind_rows.append((delta, row))
    kind_rows.sort(key=lambda x: -x[0])
    head5 = ["구분", "매매", "건수", "합계(원)"] + [x for c in CONDS for x in (f"{c.label} 통과", "통과 합계", "걸러진 합계")] + ["셋 다 판정 불가"]
    s5 = ("(가) 기준. 걸러진 합계(조건을 썼다면 안 했을 매매의 손익) 절댓값이 큰 순서임. 매매 이름은 기록된 이름표 그대로(번호·이모지 + 이름).\n\n"
          + md_table(head5, [r for _, r in kind_rows]))
    secs.append(("5. 매매별로 크게 달라진 것", s5))

    # 6. 조건 자체의 빈도
    frs, drs = [], []
    for c in CONDS:
        f = freq["cond"][c.key]
        nd = freq["ndays"]
        frs.append([c.label, f"{f['stock_days'] / nd:.1f}", f"{f['events'] / nd:.1f}", f"{f['days_any']} / {nd}", f"{f['stock_days']:,}", f"{f['stock_days_x']:,}"])
        tot = sum(v for _, v in f["dist"]) or 1
        drs.append([c.label] + [f"{v / tot:.0%}" for _, v in f["dist"]])
    s6 = ("minute_history 안(날짜마다 그날 ∪ 전날 대금 상위 약 550종목)에서 센 값임. 하루 대금이 큰 종목은 거의 다 들어 있어 영웅문과 큰 차이는 없을 것임 (2절 자료 범위 점검). "
          "'걸린 횟수' 는 조건이 꺼져 있다가 켜진 횟수(같은 종목 바로 앞 1분봉이 안 걸렸으면 새로 걸림)로, 영웅문 실시간 조건검색의 '편입' 횟수에 가까움.\n\n"
          + md_table(["조건", "하루 평균 걸린 종목 수", "하루 평균 걸린 횟수", "한 종목이라도 걸린 날", "걸린 종목·날 합계", "참고: 0봉 빼는 해석 종목·날"], frs)
          + "\n\n#### 그날 첫 포착 시각 (종목·날마다 처음 걸린 1분봉)\n\n"
          + md_table(["조건"] + [lb for lb, _ in freq["cond"]["h1"]["dist"]], drs))
    secs.append(("6. 조건 자체의 빈도", s6))

    # 7. 한계
    s7 = ("- **0봉 포함·제외 해석**: 키움 정의(0봉 포함)로 계산함. 빼는 해석으로 센 걸린 종목·날 수는 6절 표 끝 칸에 적음.\n"
          "- **1분 대금**: 봉 대금 칸이 없어 거래량 × 평균 가격으로 근사함. 1분봉은 통합(AL)이지만 정규장 시간 KRX 비중이 99% 라 차이는 작음.\n"
          "- **시가총액**: 지금 상장주식수 × 그 시각 가격. 기간 중 유상증자·무상증자·분할·소각이 있었던 종목은 시총이 조금 틀릴 수 있음. 주식수가 없는 종목(ETF, 새 SPAC 등)은 판정 못 함.\n"
          "- **종목 범위**: 1분봉은 날짜마다 그날 ∪ 전날 대금 상위 약 550종목이라 둘 다 상위 밖인 작은 종목은 없음 → 그런 종목을 산 매매는 보충 1분봉이 없으면 일봉으로 확실히 탈락인지만 보고, 그것도 모르면 판정 불가.\n"
          "- **매수 분 봉**: 매수한 분의 1분봉 전체(매수 뒤 몇십 초 포함)를 넣어 판정함 (요청대로). 아주 엄밀하게 하면 매수 분 봉을 빼야 해서 (가)(나) 통과가 조금 줄 수 있음.\n"
          "- **장 밖 매수**: 애프터·시가 매수형은 '그날(또는 전날) 한 번이라도 걸렸나' 만 봐서, 매수 직전 상태를 본 장중 매매와 뜻이 다름.\n"
          "- **표본**: 실전·모의 매매 수가 적어 매매별·조건별 칸 상당수가 '건수 부족' 임. 이 표는 '이 조건을 거름망으로 썼다면 지난 기록이 어떻게 나뉘었나' 이지, 앞으로 이 조건이 낫다는 뜻은 아님.\n"
          "- **매매 규칙은 그대로**: 매수·매도 시각과 값은 실제 기록 그대로 두고 나누기만 함. 조건을 썼다면 자리·돈이 비어서 다른 매매를 샀을 효과는 넣지 않음.")
    secs.append(("7. 재현의 한계", s7))

    title = "🍔 영웅문 조건검색식 (햄버거1·햄버거2·불개미검증) 으로 지난 매매를 걸렀다면"
    head = (f"# {title}\n\n작성 {today:%Y-%m-%d} · 재현 코드 `kiwoom_trading/backtest/condition_filter.py` · 다시 돌리기 "
            "`python -m kiwoom_trading.backtest.condition_filter --root D:/Ellie/trading --rebuild`\n\n"
            "> 사용자 요청 분석 (2026-11-22). 백테스트가 아니라 **실제로 적힌 매매 기록**을 조건에 걸렸는지로 나눈 것임. 매매 규칙은 바꾸지 않음.")
    lines = []
    for g, glabel in GROUPS:
        stock = [j for j in by_g[g] if j.mode != "etf"]
        if not stock:
            continue
        st = stats([j.t for j in stock])
        bits = []
        for c in CONDS:
            for m, mlb in (("ga", "(가)"), ("na", "(나)")):
                sp, sf, su = keyres[(g, c.key, m)]
                avg = f"건당 {f_pct(sp['ret'])}" if sp["n"] >= MIN_N else "건수 부족"
                bits.append(f"{c.label} {mlb} {sp['n']}건 {f_won(sp['sum'])}원 ({avg}, 걸러진 {sf['n']}건 {f_won(sf['sum'])}원)")
        lines.append(f"- **{glabel}** 주식 {st['n']}건 {f_won(st['sum'])}원 (건당 {f_pct(st['ret'])}) → " + " · ".join(bits))
    all_loss = all(v[0]["sum"] < 0 for v in keyres.values() if v[0]["n"])
    n_real = len([j for j in by_g["real"] if j.mode != "etf"])
    head += "\n\n## 요약\n\n" + "\n".join(lines)
    if all_loss:
        head += "\n- 통과만 했어도 모든 구분·조건에서 합계는 여전히 손실임. 조건은 '어떤 매매를 덜 했나' 를 바꿨을 뿐, 손실 매매를 이익으로 바꾸지는 못함."
    head += f"\n- 표본이 작고(실전 주식 {n_real}건) 기간이 한 달 남짓이라 이 숫자만으로 조건을 켜고 끌 근거로 쓰기엔 이름."
    body = head + "".join(f"\n\n## {h}\n\n{t}{gloss(t)}" for h, t in secs) + "\n"
    return body, keyres


def md_to_html(md: str, title: str) -> str:
    """보고서 md 를 간단한 HTML 로 (표·제목·목록·인용·굵게·코드)."""
    out, rows, in_list = [], [], False

    def inline(s: str) -> str:
        s = _html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)

    def flush_table():
        nonlocal rows
        if rows:
            h, *b = rows
            out.append('<div class="scroll"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in h) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in b) + "</tbody></table></div>")
            rows = []

    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r"-+", c) for c in cells):
                continue
            rows.append(cells)
            continue
        flush_table()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"(#+) (.*)", line)
        if m:
            n = len(m[1])
            out.append(f"<h{n}>{inline(m[2])}</h{n}>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.strip() == "약어 풀이":
            out.append('<p class="abbr"><b>약어 풀이</b></p>')
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if in_list:
        out.append("</ul>")
    css = ("body{font-family:'Malgun Gothic',sans-serif;max-width:1180px;margin:24px auto;padding:0 16px;color:#1c1917;line-height:1.55}"
           "table{border-collapse:collapse;font-size:13px;margin:8px 0}th,td{border:1px solid #d6d3d1;padding:4px 7px;text-align:right;white-space:nowrap}"
           "th{background:#f5f5f4}td:first-child,td:nth-child(2),th:first-child{text-align:left}.scroll{overflow-x:auto}"
           "blockquote{border-left:4px solid #a8a29e;margin:8px 0;padding:4px 12px;background:#fafaf9}code{background:#f5f5f4;padding:0 3px}"
           "h2{border-bottom:2px solid #e7e5e4;padding-bottom:4px;margin-top:32px}.abbr{margin-top:14px;color:#57534e}")
    return f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{_html.escape(title)}</title><style>{css}</style></head><body>{''.join(out)}</body></html>"


def trade_list_csv(js: list[Judged], path: str) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["group", "kind", "code", "name", "buy_ts", "sell_ts", "pnl", "ret", "mode", "session_day", "src"]
                   + [f"{c.key}_{m}" for c in CONDS for m in ("ga", "na")] + [f"{c.key}_first" for c in CONDS])
        for j in sorted(js, key=lambda j: j.t.buy_ts):
            t = j.t
            w.writerow([t.group, t.kind, t.code, t.name, t.buy_ts, t.sell_ts, round(t.pnl), f"{t.ret:.4f}" if t.ret is not None else "", j.mode, j.sday, j.src]
                       + [j.res.get((c.key, m)) for c in CONDS for m in ("ga", "na")] + [j.first_hit.get(c.key) for c in CONDS])


def main() -> None:
    ap = argparse.ArgumentParser(description="영웅문 조건검색식으로 지난 매매 거르기")
    ap.add_argument("--root", default=PROJECT_ROOT, help="자료가 있는 저장소 폴더 (data/)")
    ap.add_argument("--rebuild", action="store_true", help="1분봉 조건 판정 표 다시 만들기")
    ap.add_argument("--md", default=os.path.join(PROJECT_ROOT, "docs", "wiki", "bulgaemi", "condition_search_filter.md"))
    args = ap.parse_args()
    root = args.root
    P = paths(root)
    trades, odd, F = load_trades(root)
    etf_codes = set(F._ETF)
    if args.rebuild or not os.path.exists(P["cache"]):
        cal_all = sorted({t.buy_date for t in trades} | {t.buy_date - timedelta(days=k) for t in trades for k in range(1, 6)})
        want = {(t.code, d) for t in trades for d in cal_all if abs((t.buy_date - d).days) <= 5}
        print(f"1분봉 조건 판정 표 만드는 중 (보충 후보 종목·날 {len(want):,})", flush=True)
        build_hits(root, want)
    js, meta = judge(root, trades, etf_codes)
    freq = frequency(root)
    today = date.today()
    md, _ = build_report(root, js, odd, meta, freq, today)
    os.makedirs(os.path.dirname(args.md), exist_ok=True)
    with open(args.md, "w", encoding="utf-8") as f:
        f.write(md)
    os.makedirs(P["reports"], exist_ok=True)
    hp = os.path.join(P["reports"], f"condition_filter_{today:%Y%m%d}.html")
    with open(hp, "w", encoding="utf-8") as f:
        f.write(md_to_html(md, "영웅문 조건검색식으로 지난 매매 거르기"))
    cp = os.path.join(os.path.dirname(P["cache"]), f"trades_{today:%Y%m%d}.csv")
    trade_list_csv(js, cp)
    print(f"보고서 {args.md}\nHTML {hp}\n매매별 판정 {cp}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
