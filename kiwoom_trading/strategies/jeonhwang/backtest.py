"""전황 대형주 추세추종 매매 1년 백테스트 (규칙: indicators/jeonhwang.py, 설명: .claude/skills/jeonhwang/SKILL.md).

    python -m kiwoom_trading.strategies.jeonhwang.backtest                # 전체 비교표 → data/jeonhwang/backtest.txt
    python -m kiwoom_trading.strategies.jeonhwang.backtest --trades       # 기본 규칙 매매 목록도 CSV 로

자료 (잠금을 피해 복사본을 읽는다):
  일봉 data/daily_ohlcv.duckdb (2024-10~, 수정주가) · 지수 data/index.duckdb (코스피 001·코스닥 101)
  1분봉 data/minute_history.duckdb (통합 AL, 2025-10-15~, 날짜별 대금 상위 200 + 그 다음 날)
선택 편향 막기: 매매일 T 의 대상은 'T-1 대금 200위 안'인 종목만 (그 종목은 T 1분봉이 반드시 있다).
매도 기본: 손절 기준 닿으면 즉시, 아니면 다음 날 시가 (메모리 backtest-exit-rules). 비용 0.25%.
다음 날 시가 수익 = (다음 날 일봉 시가 ÷ 그날 일봉 종가) × (그날 1분봉 종가 ÷ 매수가) — 1분봉 원가격·일봉 수정주가 섞임 방지.
"""
import argparse
import pickle
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import duckdb
import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.analysis.indicators import jeonhwang as jh
from kiwoom_trading.common.daily_store import PROJECT_ROOT

OUT_DIR = os.path.join(PROJECT_ROOT, "data", "jeonhwang")
COST = 0.0025
WATCH_DAYS = 120          # 관심종목 유지 (거래일, 약 6개월 — 책 '3~6개월')
REG_START, REG_END = time(9, 0), time(15, 30)


def _copy(name: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), f"jh_{os.getpid()}_{name}")
    shutil.copy(os.path.join(PROJECT_ROOT, "data", name), dst)
    return dst


# ---- 일봉 · 지수 ------------------------------------------------------------------


def load_daily(conn) -> pd.DataFrame:
    df = conn.execute("""SELECT o.code, o.date, o.open, o.high, o.low, o.close, o.value, s.listed_shares, s.sector, s.market
                         FROM daily_ohlcv o JOIN stocks s USING (code) WHERE o.close > 0 ORDER BY o.code, o.date""").df()
    g = df.groupby("code", sort=False)["close"]
    df["prev_close"] = g.shift(1)
    df["chg"] = df["close"] / df["prev_close"] - 1
    for n in (20, 60, 120):
        df[f"ma{n}"] = g.transform(lambda s, n=n: s.rolling(n, min_periods=n).mean())
    df["next_open"] = df.groupby("code", sort=False)["open"].shift(-1)
    df["next_date"] = df.groupby("code", sort=False)["date"].shift(-1)
    df["cap"] = df["close"] * df["listed_shares"]          # 지금 상장주식수 × 그날 종가 (근사)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["next_date"] = pd.to_datetime(df["next_date"]).dt.date
    df["vrank"] = df.groupby("date")["value"].rank(ascending=False, method="first")
    df["crank"] = df.groupby("date")["chg"].rank(ascending=False, method="first")
    return df


def load_index_zones(conn) -> dict[str, dict[date, int]]:
    """{지수코드: {판단일: 구간}} — 판단일 전날 종가까지로 계산."""
    out = {}
    for code in ("001", "101"):
        rows = conn.execute("SELECT date, close FROM idx_daily WHERE code=? ORDER BY date", [code]).fetchall()
        days, closes = [r[0] for r in rows], [r[1] for r in rows]
        out[code] = {days[i]: jh.index_zone(closes[:i]) for i in range(1, len(days))}
    return out


# ---- 1분봉 ---------------------------------------------------------------------


def load_minutes(mh, code: str, start: date, end: date) -> dict[date, list[tuple]]:
    rows = mh.execute("""SELECT ts, open, high, low, close FROM minute_ohlcv WHERE exchange='AL' AND code=? AND ts >= ? AND ts < ?
                         AND CAST(ts AS TIME) >= TIME '09:00' AND CAST(ts AS TIME) <= TIME '15:30' ORDER BY ts""",
                      [code, datetime.combine(start, time(0)), datetime.combine(end + timedelta(days=1), time(0))]).fetchall()
    by = defaultdict(list)
    for r in rows:
        by[r[0].date()].append(r)
    return by


# ---- 후보 · 관심종목 ------------------------------------------------------------------


def find_candidates(df: pd.DataFrame, mh, sp: jh.ScreenParams = jh.ScreenParams()) -> pd.DataFrame:
    """장 마감 후 조건검색 + 일봉 60>120 정배열 + 오버슈팅 제외 + 같은 업종 동반 여부."""
    c = df[(df.vrank <= sp.value_rank) & (df.crank <= sp.chg_rank) & (df.cap >= sp.min_cap) & (df.chg > 0)
           & (df.ma60 > df.ma120)].copy()
    # 같은 업종 다른 종목이 그날 대금 100위 안에서 +3% 이상 (업종 쏠림 · 동일 섹터 비교)
    strong = df[(df.vrank <= 100) & (df.chg >= 0.03)][["date", "code", "sector"]]
    peers = strong.groupby(["date", "sector"]).size().rename("n").reset_index()
    c = c.merge(peers, on=["date", "sector"], how="left")
    c["sector_peers"] = c["n"].fillna(0) - 1     # 자기 자신 빼기 (자신도 대금 100위·+3%일 때)
    c.loc[~((c.vrank <= 100) & (c.chg >= 0.03)), "sector_peers"] += 1
    c["sector_peers"] = c["sector_peers"].clip(lower=0)
    # 오버슈팅: 후보일 09:00~09:59 1분봉 (1분봉이 있는 날만 — 그 전 후보는 판정 못 함)
    keys = c[["code", "date"]].copy()
    mh.register("_keys", keys)
    rows = mh.execute("""SELECT m.code, CAST(m.ts AS DATE) d, m.ts, m.open, m.high, m.low, m.close FROM minute_ohlcv m
                         JOIN _keys k ON m.code = k.code AND CAST(m.ts AS DATE) = k.date
                         WHERE m.exchange='AL' AND CAST(m.ts AS TIME) >= TIME '09:00' AND CAST(m.ts AS TIME) < TIME '10:00'
                         ORDER BY m.code, m.ts""").fetchall()
    first = defaultdict(list)
    for code, d, ts, o, h, l, cl in rows:
        first[(code, d)].append((o, h, l, cl))
    over = []
    for r in c.itertuples():
        b = first.get((r.code, r.date))
        over.append(bool(b) and jh.is_overshoot([x[1:] for x in b], b[0][0], sp))
    c["overshoot"] = over
    return c


# ---- 매매 시뮬레이션 ---------------------------------------------------------------


ZONE_SETS = {
    "2~4%": dict(zone_lo=0.02, zone_hi=0.04),
    "3~6%": dict(zone_lo=0.03, zone_hi=0.06),
    "4~6%": dict(zone_lo=0.04, zone_hi=0.06),
    "3~8%": dict(zone_lo=0.03, zone_hi=0.08),
    "2~8%": dict(zone_lo=0.02, zone_hi=0.08),
}
STOP_SETS = {
    "−2%+120선": dict(stop_pct=0.02, stop_ma120=True),
    "−3%+120선": dict(stop_pct=0.03, stop_ma120=True),
    "−2%만": dict(stop_pct=0.02, stop_ma120=False),
    "120선만": dict(stop_pct=None, stop_ma120=True),
    "−5%+120선": dict(stop_pct=0.05, stop_ma120=True),
}
WINDOWS = {"09:10~10:30": (time(9, 10), time(10, 30)), "09:00~10:30": (time(9, 0), time(10, 30)),
           "09:10~15:00": (time(9, 10), time(15, 0))}


def run(args) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    if args.report_only:                             # 저장한 시뮬레이션 결과로 표만 다시
        with open(os.path.join(OUT_DIR, "trades.pkl"), "rb") as fh:
            trades, trade_days = pickle.load(fh)
        report(defaultdict(list, trades), trade_days, args)
        return
    dm = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
    ix = duckdb.connect(_copy("index.duckdb"), read_only=True)
    mh_path_used = os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")
    try:
        mh = duckdb.connect(mh_path_used, read_only=True)
    except duckdb.IOException:                       # 백필이 쓰는 중이면 복사본
        mh_path_used = _copy("minute_history.duckdb")
        mh = duckdb.connect(mh_path_used, read_only=True)
    df = load_daily(dm)
    zones = load_index_zones(ix)
    m_first, m_last = mh.execute("SELECT min(ts)::DATE, max(ts)::DATE FROM minute_ohlcv").fetchone()
    print(f"1분봉 {m_first} ~ {m_last}", file=sys.stderr)

    cand = find_candidates(df, mh)
    cand.to_csv(os.path.join(OUT_DIR, "candidates.csv"), index=False, encoding="utf-8-sig")
    days = sorted(df.date.unique())
    di = {d: i for i, d in enumerate(days)}
    d_idx = df.set_index(["code", "date"])

    # 매매일별 관심종목: 후보일 D 가 [T-WATCH, T-1] 안
    watch = defaultdict(dict)          # T -> {code: 가장 최근 후보 행}
    for r in cand.itertuples():
        i = di[r.date]
        for j in range(i + 1, min(i + 1 + WATCH_DAYS, len(days))):
            watch[days[j]][r.code] = r
    trade_days = [d for d in days if m_first + timedelta(days=10) <= d <= m_last and d in watch]

    # 매매일 대상 (일봉 조건): 전날 종가 > 20일선 · 60>120 · 전날 대금 200위
    pairs = defaultdict(list)          # code -> [(T, 후보행, 전날행, 그날행)]
    for T in trade_days:
        prev = days[di[T] - 1]
        for code, cr in watch[T].items():
            try:
                pr, tr = d_idx.loc[(code, prev)], d_idx.loc[(code, T)]
            except KeyError:
                continue
            if pr.vrank > 200 or not (pr.close > pr.ma20) or not (pr.ma60 > pr.ma120) or pd.isna(tr.next_open):
                continue
            pairs[code].append((T, dict(sector=cr.sector, market=cr.market, date=cr.date, sector_peers=cr.sector_peers,
                                        overshoot=cr.overshoot),
                                dict(close=pr.close, ma20=pr.ma20, cap=pr.cap, vrank=pr.vrank),
                                dict(close=tr.close, next_open=tr.next_open)))
    print(f"후보 {len(cand)}건 ({cand.code.nunique()}종목), 매매일 {len(trade_days)}일, 대상 {sum(map(len, pairs.values()))}건",
          file=sys.stderr)

    mh.close()
    mh_path = mh_path_used
    jobs = [(mh_path, code, lst, days, zones) for code, lst in pairs.items()]
    trades = defaultdict(list)         # config 이름 -> [dict]
    with mp.Pool(max(1, (os.cpu_count() or 2) - 2)) as pool:
        for n, res in enumerate(pool.imap_unordered(process_code, jobs)):
            for k, v in res.items():
                trades[k].extend(v)
            if n % 10 == 0:
                print(f"  {n}/{len(jobs)}", file=sys.stderr, flush=True)
    for v in trades.values():
        v.sort(key=lambda t: t["entry_ts"])
    with open(os.path.join(OUT_DIR, "trades.pkl"), "wb") as fh:
        pickle.dump((dict(trades), trade_days), fh)

    report(trades, trade_days, args)



def process_code(job) -> dict:
    """종목 하나의 모든 매매일을 모든 설정으로 시뮬레이션 (프로세스 풀에서 돈다)."""
    mh_path, code, lst, days, zones = job
    di = {d: i for i, d in enumerate(days)}
    mh = duckdb.connect(mh_path, read_only=True)
    lo, hi = days[max(0, di[lst[0][0]] - 12)], lst[-1][0]
    mins = load_minutes(mh, code, lo, hi)
    mh.close()
    m15 = {d: jh.bars_15m([b[0] for b in v], [b[1] for b in v], [b[2] for b in v], [b[3] for b in v], [b[4] for b in v])
           for d, v in mins.items()}
    out = defaultdict(list)
    for T, cr, pr, tr in lst:
        day1m = mins.get(T)
        prev = days[di[T] - 1]
        if not day1m or prev not in mins:
            continue
        hist = []
        for k in range(8, 0, -1):
            hist += m15.get(days[di[T] - k], [])
        if len(hist) < 130:
            continue
        prev_close_px = mins[prev][-1][4]
        ma20_px = pr["ma20"] * prev_close_px / pr["close"]     # 일봉(수정) → 1분봉(원가격) 단위
        m_close = day1m[-1][4]
        base = dict(code=code, date=T, sector=cr["sector"], market=cr["market"], cand_date=cr["date"],
                    sector_peers=cr["sector_peers"], overshoot=cr["overshoot"], kospi_zone=zones["001"].get(T),
                    kosdaq_zone=zones["101"].get(T), cap=pr["cap"], vrank_prev=pr["vrank"])
        for name, kind, p in CONFIGS:
            if kind == "zone":
                fl = jh.simulate_zone_day(hist, day1m, ma20_px, p)
            else:
                fl = jh.simulate_momentum_day(day1m, prev_close_px, p["at"], ma20_px, near_high=p["near"],
                                              min_chg=p["chg"], stop_pct=p["stop"])
            if fl is None:
                continue
            if fl.exit is None:
                ret = (tr["next_open"] / tr["close"]) * (m_close / fl.entry) - 1 - COST
                reason = "다음 날 시가"
            else:
                ret = fl.exit / fl.entry - 1 - COST
                reason = fl.reason
            out[name].append(dict(base, entry_ts=fl.entry_ts, entry=fl.entry, exit_ts=fl.exit_ts, reason=reason, ret=ret))
    return dict(out)

def build_configs():
    cfg = []
    for zn, z in ZONE_SETS.items():
        for sn, s in STOP_SETS.items():
            for wn, (a, b) in WINDOWS.items():
                cfg.append((f"구역 {zn} | 손절 {sn} | {wn}", "zone", jh.with_trade(**z, **s, entry_start=a, entry_end=b)))
    cfg.append(("구역 2~4% | −2%+120선 | 09:10~10:30 | 15분 정배열 조건 없음", "zone",
                jh.with_trade(need_15m_aligned=False)))
    for at in (time(11, 0), time(14, 30), time(15, 0)):
        for near in (0.02, 0.01):
            cfg.append((f"모멘텀 {at:%H:%M} 고가−{near:.0%} 안·상승 | −2%", "mom", dict(at=at, near=near, chg=0.0, stop=0.02)))
    return cfg


CONFIGS = build_configs()
DEFAULT_NAME = "구역 2~4% | 손절 −2%+120선 | 09:10~10:30"


# ---- 결과 ----------------------------------------------------------------------


def stats(tr: list[dict], half: date) -> str:
    if len(tr) < 10:
        return f"{len(tr):4d}건 (적음)"
    v = np.array([t["ret"] for t in tr])
    win, loss = v[v > 0], v[v <= 0]
    pf = (win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else float("nan")
    a = [t["ret"] for t in tr if t["date"] < half]
    b = [t["ret"] for t in tr if t["date"] >= half]
    bd = defaultdict(float)
    for t in tr:
        bd[t["date"]] += t["ret"]
    eq = np.cumsum([bd[d] for d in sorted(bd)])
    mdd = (np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max()
    top = sorted(bd.values(), reverse=True)
    ok = "★" if a and b and np.mean(a) > 0 and np.mean(b) > 0 and sum(top[5:]) > 0 else " "
    return (f"{ok}{len(v):4d}건 합계 {v.sum() * 100:+6.0f}만 건당 {v.mean():+.2%} 손익비 {pf:4.2f} 낙폭 {mdd * 100:4.0f}만 "
            f"| 앞 {np.mean(a) if a else 0:+.2%} 뒤 {np.mean(b) if b else 0:+.2%} | 최고5일 빼면 {sum(top[5:]) * 100:+5.0f}만 "
            f"| 승률 {len(win) / len(v):.0%}")


def account(tr: list[dict], zone_key: str = "kospi_zone", slots: int = 3, start: float = 1e7) -> str:
    """1천만 복리, 하루 최대 slots 종목 (먼저 산 순서), 1구간 = 1/slots, 2구간 = 절반, 3구간 = 안 삼."""
    by = defaultdict(list)
    for t in tr:
        by[t["date"]].append(t)
    eq, peak, mdd, path = start, start, 0.0, []
    for d in sorted(by):
        pnl = 0.0
        for t in sorted(by[d], key=lambda x: x["entry_ts"])[:slots]:
            w = {1: 1.0, 2: 0.5}.get(t[zone_key] or 0, 0.0)
            pnl += eq / slots * w * t["ret"]
        eq += pnl
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        path.append((d, eq))
    return f"1천만 → {eq / 1e4:,.0f}만 ({eq / start - 1:+.0%}), 최대 낙폭 {mdd:.1%}, 매매일 {len(path)}일"


def report(trades: dict, trade_days: list, args) -> None:
    half = trade_days[len(trade_days) // 2]
    lines = [f"전황 대형주 추세추종 1년 백테스트 — 매매일 {trade_days[0]} ~ {trade_days[-1]} ({len(trade_days)}일), 앞/뒤 = {half}",
             "건당 100만 원 기준 합계. 손익비 = 평균 이익 ÷ 평균 손실. ★ = 앞·뒤 모두 + 이고 최고 5일 빼도 +.", ""]

    def section(title, rows):
        lines.append(f"=== {title}")
        for name, tr in rows:
            lines.append(f"  {name:58s} {stats(tr, half)}")
        lines.append("")

    base = trades[DEFAULT_NAME]
    filt = lambda tr, f: [t for t in tr if f(t)]
    section("기본 규칙 (책: 대형주 2~4% 구역, −2% 손절 + 15분봉 120선, 10:30까지) — 지수 구간별", [
        ("지수 조건 없음", base),
        ("코스피 1·2구간 (20일선 위)", filt(base, lambda t: t["kospi_zone"] in (1, 2))),
        ("코스피 1구간 (정배열)", filt(base, lambda t: t["kospi_zone"] == 1)),
        ("코스피 2구간", filt(base, lambda t: t["kospi_zone"] == 2)),
        ("코스피 3구간 (20일선 아래 — 책: 쉰다)", filt(base, lambda t: t["kospi_zone"] == 3)),
        ("코스닥 1·2구간", filt(base, lambda t: t["kosdaq_zone"] in (1, 2))),
        ("코스닥 3구간", filt(base, lambda t: t["kosdaq_zone"] == 3)),
        ("코스피·코스닥 둘 다 1·2구간", filt(base, lambda t: t["kospi_zone"] in (1, 2) and t["kosdaq_zone"] in (1, 2))),
        ("종목 시장 지수 1·2구간", filt(base, lambda t: (t["kospi_zone"] if t["market"] == "KOSPI" else t["kosdaq_zone"]) in (1, 2))),
    ])
    ok_idx = lambda t: t["kospi_zone"] in (1, 2)
    section("기본 규칙 + 코스피 1·2구간 — 후보 조건 보태기", [
        ("전부", filt(base, ok_idx)),
        ("오버슈팅 후보 빼기", filt(base, lambda t: ok_idx(t) and not t["overshoot"])),
        ("같은 업종 동반 1종목↑", filt(base, lambda t: ok_idx(t) and t["sector_peers"] >= 1)),
        ("같은 업종 동반 2종목↑", filt(base, lambda t: ok_idx(t) and t["sector_peers"] >= 2)),
        ("후보된 지 20거래일 안", filt(base, lambda t: ok_idx(t) and (t["date"] - t["cand_date"]).days <= 30)),
        ("시총 10조↑", filt(base, lambda t: ok_idx(t) and t["cap"] >= 1e13)),
        ("전날 대금 50위 안", filt(base, lambda t: ok_idx(t) and t["vrank_prev"] <= 50)),
    ])
    for title, key in (("매수 구역 비교 (손절 −2%+120선, 09:10~10:30, 코스피 1·2구간)", "zone"),
                       ("손절 비교 (구역 2~4%, 09:10~10:30, 코스피 1·2구간)", "stop"),
                       ("매수 시간 비교 (구역 2~4%, −2%+120선, 코스피 1·2구간)", "win")):
        rows = []
        for name, tr in trades.items():
            if not name.startswith("구역"):
                continue
            parts = name.split(" | ")
            if len(parts) != 3:
                continue
            z, s, w = parts[0][3:], parts[1][3:], parts[2]
            if (key == "zone" and s == "−2%+120선" and w == "09:10~10:30") or \
               (key == "stop" and z == "2~4%" and w == "09:10~10:30") or \
               (key == "win" and z == "2~4%" and s == "−2%+120선"):
                rows.append((name, filt(tr, ok_idx)))
        section(title, rows)
    section("15분봉 60>120 정배열 조건 빼면 (코스피 1·2구간)",
            [(n, filt(t, ok_idx)) for n, t in trades.items() if "조건 없음" in n])
    section("모멘텀 매수 (당일 주도주 11:00 · 오후 종가배팅 14:30·15:00, 다음 날 시가, 코스피 1·2구간)",
            [(n, filt(t, ok_idx)) for n, t in trades.items() if n.startswith("모멘텀")])

    # 전체 격자에서 좋은 순
    grid = [(n, filt(t, ok_idx)) for n, t in trades.items() if n.startswith("구역") and "조건 없음" not in n]
    grid = [(n, t) for n, t in grid if len(t) >= 30]
    grid.sort(key=lambda x: -sum(t["ret"] for t in x[1]))
    section("전체 격자 합계 상위 10 (코스피 1·2구간, 30건↑) — 여러 개를 본 만큼 우연히 좋아 보일 수 있음", grid[:10])
    section("전체 격자 합계 하위 5", grid[-5:])

    lines.append("=== 계좌 (1천만 복리, 하루 3종목, 코스피 1구간 1/3 · 2구간 1/6 · 3구간 안 삼)")
    for name in (DEFAULT_NAME, grid[0][0] if grid else DEFAULT_NAME):
        lines.append(f"  {name:58s} {account(trades[name])}")
    lines.append("")
    reasons = defaultdict(list)
    for t in filt(base, ok_idx):
        reasons[t["reason"]].append(t["ret"])
    lines.append("=== 기본 규칙 매도 이유 (코스피 1·2구간)")
    for k, v in sorted(reasons.items(), key=lambda x: -len(x[1])):
        lines.append(f"  {k:16s} {len(v):4d}건 건당 {np.mean(v):+.2%}")
    lines.append("")
    months = defaultdict(list)
    for t in filt(base, ok_idx):
        months[t["date"].strftime("%Y-%m")].append(t["ret"])
    lines.append("=== 기본 규칙 월별 (코스피 1·2구간, 건당 100만)")
    for k in sorted(months):
        v = months[k]
        lines.append(f"  {k} {len(v):3d}건 합계 {sum(v) * 100:+5.0f}만 건당 {np.mean(v):+.2%}")
    out = "\n".join(lines)
    print(out)
    with open(os.path.join(OUT_DIR, "backtest.txt"), "w", encoding="utf-8") as fh:
        fh.write(out + "\n")
    if args.trades:
        pd.DataFrame(base).to_csv(os.path.join(OUT_DIR, "trades_default.csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true", help="trades.pkl 로 표만 다시 만들기")
    ap.add_argument("--trades", action="store_true", help="기본 규칙 매매 목록 CSV 저장")
    run(ap.parse_args())
