"""당일 1분봉 차트에 우리 매수·매도 자리를 키움처럼 표시 (2026-10-28 사용자 '종목별 1분봉 차트에 매수·매도 타점').

빨간 ▲ = 매수, 파란 ▼ = 매도 (실전·모의·가상 이름표), 회색 △ = 포착했지만 못 산 신호 (이유 첫 마디).
자료: 1분봉은 키움 ka10080 (KRX 정규장), 매매 기록은 data/screener_snapshot.duckdb (스캐너가 10분마다 만드는 사본).

    .venv\\Scripts\\python.exe -m kiwoom_trading.analysis.trade_chart 2026-10-28 003160 010170 ... [--out data/charts]
"""
import argparse
import os
import re
from datetime import date, datetime, time

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

SNAP = os.path.join(PROJECT_ROOT, "data", "screener_snapshot.duckdb")
for f in ("C:/Windows/Fonts/malgun.ttf",):
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
plt.rcParams["axes.unicode_minus"] = False


def _why(note: str) -> str:
    """못 산 이유를 짧게."""
    if "추격" in note:
        m = re.search(r"([+-]\d+\.\d%)", note)
        return f"추격 금지 ({m.group(1) if m else '+1%↑'})"
    for key, short in (("금액 부족", "잔고 부족"), ("보유 중", "이미 보유"), ("최대", "보유 한도"), ("외인", "전날 수급"), ("하루 1종목", "하루 1종목")):
        if key in note:
            return short
    return note.split(" —")[0].split(" (")[0][:14]


def _marks(conn, day: date, code: str) -> list[tuple]:
    """[(시각, 가격, 'buy'|'sell'|'seen', 이름표)]"""
    out = []
    for kind, virt, ovf, sig_ts, sig_px, st, b_ts, b_px, s_ts, s_px, why, note in conn.execute(
            """SELECT kind, virtual, overflow, signal_ts, signal_price, status, buy_ts, buy_price, sell_ts, sell_price, sell_reason, note
               FROM paper_trades WHERE code = ? AND (date = ? OR CAST(sell_ts AS DATE) = ?)""", [code, day, day]).fetchall():
        who = "가상" if ovf or virt else "모의"
        if b_ts and b_ts.date() == day and b_px:
            out.append((b_ts, b_px, "buy", f"{who} 매수 [{kind}]"))
        if s_ts and s_ts.date() == day and s_px:
            out.append((s_ts, s_px, "sell", f"{who} 매도 {why or ''}"))
        if st in ("skipped", "failed") and sig_ts and sig_ts.date() == day:
            out.append((sig_ts, sig_px, "seen", f"포착 [{kind}]\n못 삼: {_why(note or '')}"))
    for kind, b_ts, b_px, s_ts, s_px, why, st in conn.execute(
            """SELECT kind, buy_ts, buy_price, sell_ts, sell_price, reason, status FROM real_trades
               WHERE code = ? AND (date = ? OR CAST(sell_ts AS DATE) = ?)""", [code, day, day]).fetchall():
        if b_ts and b_ts.date() == day and b_px and st != "failed":
            out.append((b_ts, b_px, "buy", f"실전 매수 [{kind}]"))
        if s_ts and s_ts.date() == day and s_px:
            out.append((s_ts, s_px, "sell", f"실전 매도 {why or ''}"))
    for book, b_ts, b_px, s_ts, s_px, why in conn.execute(
            """SELECT book, buy_ts, buy_price, sell_ts, sell_price, reason FROM ledger_trades
               WHERE code = ? AND (date = ? OR CAST(sell_ts AS DATE) = ?)""", [code, day, day]).fetchall():
        if b_ts and b_ts.date() == day and b_px:
            out.append((b_ts, b_px, "buy", f"가상 매수 [{book}]"))
        if s_ts and s_ts.date() == day and s_px:
            out.append((s_ts, s_px, "sell", f"가상 매도 [{book}] {why or ''}"))
    return [m for m in out if time(9, 0) <= m[0].time() <= time(15, 30)]


def draw(day: date, code: str, name: str, bars: list[dict], marks: list[tuple], path: str, title: str = "") -> None:
    bars = [b for b in bars if time(9, 0) <= b["ts"].time() <= time(15, 30)]
    if not bars:
        return
    idx = {b["ts"].replace(second=0): i for i, b in enumerate(bars)}
    fig, (ax, av) = plt.subplots(2, 1, figsize=(13, 7), sharex=True, gridspec_kw={"height_ratios": [4, 1]})
    for i, b in enumerate(bars):
        up = b["close"] >= b["open"]
        col = "#e8333a" if up else "#2d6fd8"
        ax.vlines(i, b["low"], b["high"], color=col, linewidth=0.7)
        ax.bar(i, abs(b["close"] - b["open"]) or (b["high"] * 0.0005), bottom=min(b["open"], b["close"]), color=col, width=0.7)
        av.bar(i, b["volume"], color=col, width=0.7)
    prev_close = None
    span = max(b["high"] for b in bars) - min(b["low"] for b in bars)
    for k, (ts, px, what, label) in enumerate(sorted(marks)):
        i = idx.get(ts.replace(second=0, microsecond=0, tzinfo=None))
        if i is None:
            i = min(range(len(bars)), key=lambda j: abs((bars[j]["ts"] - ts.replace(tzinfo=None)).total_seconds()))
        b = bars[i]
        off = span * 0.04
        if what == "buy":
            y, mk, col, va, ty = b["low"] - off, "^", "#e8333a", "top", b["low"] - off * 2
        elif what == "sell":
            y, mk, col, va, ty = b["high"] + off, "v", "#2d6fd8", "bottom", b["high"] + off * 2
        else:
            y, mk, col, va, ty = b["low"] - off, "^", "#9a9a9a", "top", b["low"] - off * (2 + (k % 3))
        ax.scatter(i, y, marker=mk, s=140, color=col if what != "seen" else "none", edgecolors=col, linewidths=1.5, zorder=5)
        ax.annotate(f"{label}\n{px:,.0f} {ts:%H:%M}", (i, ty), ha="center", va=va, fontsize=8, color=col,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=col, lw=0.6, alpha=0.85))
    ticks = [i for i, b in enumerate(bars) if b["ts"].minute == 0 or i == 0]
    av.set_xticks(ticks)
    av.set_xticklabels([f"{bars[i]['ts']:%H:%M}" for i in ticks])
    last = bars[-1]["close"]
    ax.set_title(title or f"{name}({code}) {day:%m-%d} 1분봉", fontsize=13)
    ax.grid(alpha=0.2)
    av.grid(alpha=0.2)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo - span * 0.12, hi + span * 0.08)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--out", default=os.path.join(PROJECT_ROOT, "data", "charts"))
    a = ap.parse_args()
    day = datetime.strptime(a.day, "%Y-%m-%d").date()
    os.makedirs(a.out, exist_ok=True)
    conn = duckdb.connect(SNAP, read_only=True)
    names = dict(duckdb.connect(os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb"), read_only=True)
                 .execute("SELECT code, name FROM stocks").fetchall())
    client = build_client()
    for code in a.codes:
        bars = fetch_minute_bars(client, code, day, "KRX")
        marks = _marks(conn, day, code)
        name = names.get(code, code)
        pc = conn.execute("""SELECT change_rate FROM rank_snapshots WHERE date = ? AND code = ? AND source = 'value_krx'
                             ORDER BY ts DESC LIMIT 1""", [day, code]).fetchone()
        title = f"{name}({code}) {day:%m-%d} 1분봉" + (f"  마감 {pc[0]:+.1%}" if pc and pc[0] is not None else "") \
            + ("" if marks else "  — 우리 신호 없음")
        path = os.path.join(a.out, f"{day:%Y%m%d}_{code}.png")
        draw(day, code, name, bars, marks, path, title)
        print(path, len(bars), len(marks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
