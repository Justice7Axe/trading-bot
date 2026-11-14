"""📚 전체 매매일지·성과 보고서 — 지금까지 모든 실전·모의·가상 매매를 HTML 한 장과 A4 PDF 로 (2026-11-14 사용자 텔레그램 요청).

자료는 실제 기록만 씀 (백테스트 없음):
  🔴 실전  real_trades (키움 실계좌, pnl 은 매도 때 비용까지 뺀 값)
  🟢 모의  paper_trades 중 virtual = false (키움 모의 계좌 정규장 실주문). 손익은 journal._paper_net (비용 0.25% 뺌, 나눠 판 것 반영)
  🟣 가상  paper_trades 중 virtual = true (NXT 프리·애프터 가상 체결, overflow = 잔고 밖 가상) + ledger_trades (주문 없는 가상 장부들)
  모의 계좌 평가 자산은 paper_days (1천만 원 시작). 시장 분위기는 journal._market (market_regime 표 → 장중 로그 순서).
계산 방식은 performance_page·journal 과 같음: 승률 = 이긴 건 ÷ 전체, PF = 이익 합 ÷ 손실 합, MDD = 누적 손익 고점에서 가장 많이 빠진 폭.

    python -m kiwoom_trading.execution.full_report                       # data/reports/trading_journal_YYYYMMDD.html·.pdf
    python -m kiwoom_trading.execution.full_report --root D:/Ellie/trading --out D:/Ellie/trading/data/reports
    python -m kiwoom_trading.execution.full_report --no-pdf              # HTML 만
PDF 는 같은 내용을 인쇄용 HTML 로 만든 뒤 Edge(또는 Chrome) headless --print-to-pdf 로 찍음. 쪽 나누기와 쪽마다 약어 풀이는 인쇄용 HTML 안의 스크립트가 함.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.execution import journal as J

PAPER_START = 10_000_000
REAL_SEED = 100_000          # real.SEED 와 같음 (불러오기 실패 대비)
try:
    from kiwoom_trading.execution.real import SEED as REAL_SEED   # noqa: F811
except Exception:
    pass

# 쪽(절)마다 아래에 붙이는 약어 풀이 — 본문에 처음 나온 순서대로. API·IP·DB·URL·HTTP 는 풀지 않음
ABBR = {
    "PF": "Profit Factor, 이익 합계 ÷ 손실 합계 (1보다 크면 번 돈이 잃은 돈보다 많음)",
    "MDD": "Maximum Drawdown, 최대 낙폭 (누적 손익이 가장 높았던 때에서 가장 많이 빠진 폭)",
    "NXT": "Nextrade, 대체거래소 (프리장 08:00~08:50·애프터장 15:30~20:00)",
    "KRX": "Korea Exchange, 한국거래소 정규장",
    "VWAP": "Volume Weighted Average Price, 거래량 가중 평균 가격",
    "ETF": "Exchange Traded Fund, 상장지수펀드",
}
SECTION_LABEL = {"real": "🔴 실전", "paper": "🟢 모의", "virtual": "🟣 가상"}
EDGE_PATHS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe")


# ------------------------------------------------------------------ 자료
@dataclass
class Trade:
    group: str                 # real / paper / virtual
    sub: str                   # 세부 구분 (모의 / NXT 가상 체결 / 잔고 밖 / 가상 장부)
    kind: str                  # 매매 이름 (번호·이모지 + 이름)
    code: str
    name: str
    qty: int
    buy_ts: Optional[datetime]
    buy_price: Optional[float]
    sell_ts: Optional[datetime]
    sell_price: Optional[float]
    pnl: Optional[float]
    reason: str
    status: str
    buy_date: date
    regime: str = ""
    note: str = ""

    @property
    def ret(self) -> Optional[float]:
        if self.pnl is None or not self.buy_price or not self.qty:
            return None
        return self.pnl / (self.buy_price * self.qty)

    @property
    def closed(self) -> bool:
        return self.status == "closed" and self.pnl is not None and self.sell_ts is not None


def _pick_db(root: str) -> str:
    """screener.duckdb / screener_snapshot.duckdb 중 최근에 바뀐 것부터 읽기 전용으로 열리는 것."""
    cands = [os.path.join(root, "data", f) for f in ("screener.duckdb", "screener_snapshot.duckdb")]
    cands = sorted([p for p in cands if os.path.exists(p)], key=os.path.getmtime, reverse=True)
    for p in cands:
        try:
            duckdb.connect(p, read_only=True).close()
            return p
        except Exception:
            continue
    raise RuntimeError("screener DB 를 열 수 없음")


def sell_cat(reason: str) -> str:
    r = reason or ""
    if "직접" in r or "사용자" in r:
        return "직접 매도 (사용자)"
    if r.startswith("VWAP"):
        return "VWAP 이탈"
    if "손절" in r:
        return "손절"
    if "5거래일" in r:
        return "보유일 채운 뒤 09:00 매도"
    if "다음 날" in r:
        return "다음 날 09:00 매도"
    if "목표" in r or "익절" in r:
        return "익절 (목표가)"
    if "고점 대비" in r:
        return "고점 대비 되밀림 매도"
    if "큰 음봉" in r:
        return "큰 음봉 매도"
    if "하이킨아시" in r:
        return "하이킨아시 색 바뀜"
    if "장 마감" in r:
        return "장 마감 정리 (15:19)"
    if "가상 시간 끝" in r:
        return "애프터 가상 시간 끝 정리"
    return r or "기록 없음"


def hold_cat(t: Trade) -> str:
    if not t.buy_ts or not t.sell_ts:
        return "기록 없음"
    if t.sell_ts.date() > t.buy_ts.date():
        import numpy as np
        n = int(np.busday_count(t.buy_ts.date(), t.sell_ts.date()))
        return "다음 거래일까지 들고 감" if n <= 1 else "2거래일 넘게 들고 감"
    m = (t.sell_ts - t.buy_ts).total_seconds() / 60
    return "그날 30분 안" if m < 30 else "그날 30분~2시간" if m < 120 else "그날 2시간 넘게"


HOLD_ORDER = ["그날 30분 안", "그날 30분~2시간", "그날 2시간 넘게", "다음 거래일까지 들고 감", "2거래일 넘게 들고 감", "기록 없음"]


def regime_cat(rg: str) -> str:
    return rg or "기록 없음"


class Data:
    def __init__(self, root: str) -> None:
        self.root = root
        self.db_path = _pick_db(root)
        J.DATA = os.path.join(root, "data")          # 일지 모듈의 자료 위치를 이 보고서 기준으로 (워크트리에서 돌려도 본 폴더 자료)
        self.ctx = J.Ctx(self.db_path)
        self.trades: list[Trade] = []
        self.skipped: dict[str, int] = defaultdict(int)
        self.failed = 0
        self.paper_days: list[tuple[date, int]] = []
        self.liquidations: list[tuple] = []
        self.journal_files: set[date] = set()
        self._regimes: dict[date, str] = {}
        self._load()

    def regime(self, d: date) -> str:
        if d not in self._regimes:
            try:
                rg, _ = J._market(self.ctx, d, J._log_lines(d))
            except Exception:
                rg = ""
            if not rg and d < date(2026, 10, 20):
                rg = "기록 없음 (판정 기능 시작 전)"
            self._regimes[d] = regime_cat(rg)
        return self._regimes[d]

    def _load(self) -> None:
        q = self.ctx.q
        scr = self.ctx.scr
        for (d, code, name, kind, qty, bts, bp, sts, sp, reason, pnl, status, note) in q(scr, """
                SELECT date, code, coalesce(name, code), kind, qty, buy_ts, buy_price, sell_ts, sell_price, coalesce(reason, ''), pnl, status,
                       coalesce(note, '') FROM real_trades ORDER BY buy_ts"""):
            self.trades.append(Trade("real", "실전", J.label(kind), code, name, qty or 0, bts, bp, sts, sp, pnl, reason, status, d, note=note))
        for (d, code, name, kind, mode, status, qty, bts, bp, sts, sp, why, virt, ovf, pq, pp, note) in q(scr, """
                SELECT date, code, coalesce(name, code), kind, mode, status, qty, buy_ts, buy_price, sell_ts, sell_price, coalesce(sell_reason, ''),
                       coalesce(virtual, false), coalesce(overflow, false), part_qty, part_price, coalesce(note, '') FROM paper_trades ORDER BY signal_ts"""):
            if status == "failed":
                self.failed += 1
                continue
            if status == "skipped" or bp is None:
                if status == "skipped":
                    self.skipped[J.label(kind)] += 1
                continue
            pnl = J._paper_net(qty, bp, sp, pq, pp) if status == "closed" else None
            group = "virtual" if (virt or ovf) else "paper"
            sub = "잔고 밖" if ovf else "NXT 가상 체결" if virt else "모의"
            st = "closed" if (status == "closed" and pnl is not None) else "open"
            self.trades.append(Trade(group, sub, J.label(kind), code, name, qty or 0, bts, bp, sts, sp, pnl, why, st, d, note=note))
        for (book, d, code, name, bts, bp, qty, sts, sp, reason, pnl, status) in q(scr, """
                SELECT book, date, code, coalesce(name, code), buy_ts, buy_price, qty, sell_ts, sell_price, coalesce(reason, ''), pnl, status
                FROM ledger_trades ORDER BY buy_ts"""):
            self.trades.append(Trade("virtual", "가상 장부", J.book_label(book or "?"), code, name, qty or 0, bts, bp, sts, sp, pnl, reason,
                                     "closed" if (status == "closed" and pnl is not None) else "open", d))
        self.paper_days = [(d, a) for d, a in q(scr, "SELECT date, asset_end FROM paper_days WHERE asset_end IS NOT NULL ORDER BY date")]
        self.liquidations = q(scr, "SELECT date, name, code, qty, note FROM real_liquidations ORDER BY ts")
        jdir = os.path.join(self.root, "docs", "journal")
        if os.path.isdir(jdir):
            for f in os.listdir(jdir):
                m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)\.md", f)
                if m:
                    self.journal_files.add(date(int(m[1]), int(m[2]), int(m[3])))
        for t in self.trades:
            t.regime = self.regime(t.buy_date)

    def closed(self, group: Optional[str] = None) -> list[Trade]:
        xs = [t for t in self.trades if t.closed and (group is None or t.group == group)]
        return sorted(xs, key=lambda t: t.sell_ts)

    def open(self) -> list[Trade]:
        return [t for t in self.trades if not t.closed]


# ------------------------------------------------------------------ 계산
def stats(pnls: list[float], start: Optional[float] = None) -> dict:
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gw, gl = sum(wins), -sum(p for p in losses if p < 0)
    cum = peak = 0.0
    mdd_won = 0.0
    mdd_pct = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd_won = max(mdd_won, peak - cum)
        if start:
            mdd_pct = max(mdd_pct, 1 - (start + cum) / (start + peak))
    aw = gw / len(wins) if wins else None
    al = -gl / len([p for p in losses if p < 0]) if any(p < 0 for p in losses) else None
    return {"n": n, "w": len(wins), "l": n - len(wins), "win": len(wins) / n if n else None, "sum": sum(pnls),
            "avg": sum(pnls) / n if n else None, "aw": aw, "al": al, "payoff": (aw / -al) if (aw and al) else None,
            "pf": (gw / gl) if gl else None, "mdd_won": mdd_won, "mdd_pct": mdd_pct if start else None}


def won(x: Optional[float], sign: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x:+,.0f}원" if sign else f"{x:,.0f}원"


def pct(x: Optional[float], d: int = 1) -> str:
    return "—" if x is None else f"{x:+.{d}%}"


def rate(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.0%}"


def num(x: Optional[float], d: int = 2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def px(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:,.0f}"


def cls(x: Optional[float]) -> str:
    return "" if x is None or abs(x) < 0.5 else ("pos" if x > 0 else "neg")


# ------------------------------------------------------------------ HTML 조각
def esc(s) -> str:
    return html.escape(str(s))


def table(head: list[str], rows: list[list], num_cols: tuple = (), cls_cols: dict | None = None, caption: str = "", tcls: str = "") -> str:
    """rows 칸은 str (이스케이프함) 또는 ('raw', html). cls_cols = {열번호: 행별 값 목록} → 양수 파랑·음수 빨강."""
    cls_cols = cls_cols or {}
    th = "".join(f'<th class="{"r" if i in num_cols else ""}">{esc(h)}</th>' for i, h in enumerate(head))
    body = []
    for ri, r in enumerate(rows):
        tds = []
        for i, c in enumerate(r):
            k = ["r"] if i in num_cols else []
            if i in cls_cols:
                k.append(cls(cls_cols[i][ri]))
            v = c[1] if isinstance(c, tuple) and c and c[0] == "raw" else esc(c)
            tds.append(f'<td class="{" ".join(x for x in k if x)}">{v}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f'<div class="scroll"><table class="{tcls}">{cap}<thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def stat_row(label: str, s: dict, extra: list | None = None) -> list:
    return [label, f"{s['n']}", f"{s['w']} / {s['l']}", rate(s["win"]), won(s["sum"]), won(s["avg"]),
            num(s["payoff"]), num(s["pf"]), won(-s["mdd_won"]) if s["n"] else "—"] + (extra or [])


STAT_HEAD = ["구분", "건수", "이김 / 짐", "승률", "합계 손익", "건당 평균", "손익비", "PF", "MDD (원)"]


def by_key(trades: list[Trade], key, order: Optional[list] = None) -> list[tuple[str, dict]]:
    g = defaultdict(list)
    for t in trades:
        g[key(t)].append(t.pnl)
    items = [(k, stats(v)) for k, v in g.items()]
    if order:
        items.sort(key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    else:
        items.sort(key=lambda kv: -kv[1]["sum"])
    return items


def abbr_footer_html(text: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", text)
    found = []
    for ab in ABBR:
        m = re.search(rf"(?<![A-Za-z]){re.escape(ab)}(?![A-Za-z])", plain)
        if m:
            found.append((m.start(), ab))
    if not found:
        return ""
    found.sort()
    return '<div class="abbr"><b>약어 풀이</b>' + "".join(f"<div>{ab}: {esc(ABBR[ab])}</div>" for _, ab in found) + "</div>"


# ------------------------------------------------------------------ 그래프
def svg_cum(points: list[tuple[str, float]], title: str, unit: str = "원", base: float = 0.0) -> str:
    """누적 손익(또는 잔고) 꺾은선. points = [(날짜 라벨, 값)]."""
    if len(points) < 2:
        return '<p class="muted">그릴 자료가 모자람</p>'
    w, h, pl, pr, pt, pb = 720, 230, 78, 16, 26, 30
    vals = [v for _, v in points] + [base]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    lo, hi = lo - span * 0.06, hi + span * 0.06
    span = hi - lo
    X = lambda i: pl + i * (w - pl - pr) / (len(points) - 1)
    Y = lambda v: pt + (hi - v) / span * (h - pt - pb)
    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(points))
    area = f"{X(0):.1f},{Y(base):.1f} " + line + f" {X(len(points) - 1):.1f},{Y(base):.1f}"
    last = points[-1][1]
    tone = "pos" if last >= base else "neg"
    ticks = []
    for v in sorted({hi - span * 0.06, base, lo + span * 0.06}):
        ticks.append(f'<line x1="{pl}" x2="{w - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="{"zero" if v == base else "grid"}"/>'
                     f'<text x="{pl - 6}" y="{Y(v) + 4:.1f}" class="axis" text-anchor="end">{v:+,.0f}</text>' if base == 0 else
                     f'<line x1="{pl}" x2="{w - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="{"zero" if v == base else "grid"}"/>'
                     f'<text x="{pl - 6}" y="{Y(v) + 4:.1f}" class="axis" text-anchor="end">{v:,.0f}</text>')
    n = len(points)
    idx = sorted({0, n // 3, 2 * n // 3, n - 1})
    xl = "".join(f'<text x="{X(i):.1f}" y="{h - 10}" class="axis" text-anchor="{"start" if i == 0 else "end" if i == n - 1 else "middle"}">{esc(points[i][0])}</text>' for i in idx)
    dots = "".join(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.4" class="dot {tone}"><title>{esc(lb)} {v:+,.0f}{unit}</title></circle>'
                   for i, (lb, v) in enumerate(points))
    return (f'<figure><svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">'
            f'<text x="{pl}" y="16" class="ttl">{esc(title)}</text>{"".join(ticks)}'
            f'<polygon points="{area}" class="area {tone}"/><polyline points="{line}" class="curve {tone}"/>{dots}{xl}'
            f'<text x="{w - pr}" y="16" class="axis" text-anchor="end">마지막 {last:+,.0f}{unit}</text></svg></figure>' if base == 0 else
            f'<figure><svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">'
            f'<text x="{pl}" y="16" class="ttl">{esc(title)}</text>{"".join(ticks)}'
            f'<polygon points="{area}" class="area {tone}"/><polyline points="{line}" class="curve {tone}"/>{dots}{xl}'
            f'<text x="{w - pr}" y="16" class="axis" text-anchor="end">마지막 {last:,.0f}{unit} ({last / base - 1:+.1%})</text></svg></figure>')


def mpl_png(series: list[tuple[str, list[tuple[str, float]], float]]) -> tuple[str, int, int]:
    """PDF 용 matplotlib 그림 (base64 PNG). series = [(제목, [(라벨, 값)], 기준선)]."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fp = r"C:\Windows\Fonts\malgun.ttf"
    if os.path.exists(fp):
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    k = len(series)
    fig, axes = plt.subplots(k, 1, figsize=(7.4, 2.25 * k), dpi=170)
    size = fig.get_size_inches() * fig.dpi
    axes = [axes] if k == 1 else list(axes)
    for ax, (title, pts, base) in zip(axes, series):
        if len(pts) < 2:
            ax.set_axis_off()
            ax.set_title(title + " — 자료 모자람", fontsize=9, loc="left")
            continue
        xs = list(range(len(pts)))
        ys = [v for _, v in pts]
        color = "#1d4ed8" if ys[-1] >= base else "#dc2626"
        ax.axhline(base, color="#a8a29e", lw=0.8, ls="--")
        ax.fill_between(xs, ys, base, color=color, alpha=0.10, lw=0)
        ax.plot(xs, ys, color=color, lw=1.6, marker="o", ms=2.6)
        ax.set_title(title, fontsize=9.5, loc="left")
        n = len(pts)
        idx = sorted({0, n // 3, 2 * n // 3, n - 1})
        ax.set_xticks(idx, [pts[i][0] for i in idx], fontsize=7.5)
        ax.tick_params(axis="y", labelsize=7.5)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.grid(axis="y", color="#e7e5e4", lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        tail = f"마지막 {ys[-1]:+,.0f}원" if base == 0 else f"마지막 {ys[-1]:,.0f}원 ({ys[-1] / base - 1:+.1%})"
        ax.text(1.0, 1.02, tail, transform=ax.transAxes, ha="right", fontsize=8, color="#57534e")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode(), int(size[0]), int(size[1])


# ------------------------------------------------------------------ 보고서
class Report:
    def __init__(self, data: Data, today: date) -> None:
        self.d = data
        self.today = today
        self.real = data.closed("real")
        self.paper = data.closed("paper")
        self.virt = data.closed("virtual")
        self.all_closed = data.closed()
        self.s_real = stats([t.pnl for t in self.real], REAL_SEED)
        self.s_paper = stats([t.pnl for t in self.paper], PAPER_START)
        self.s_virt = stats([t.pnl for t in self.virt])
        starts = [t.buy_date for t in data.trades] + [d for d, _ in data.paper_days]
        ends = [t.sell_ts.date() for t in self.all_closed]
        self.first, self.last = min(starts), max(ends + [d for d, _ in data.paper_days])
        # 모의 계좌 평가 자산 (미실현 포함) MDD
        curve = [PAPER_START] + [a for _, a in data.paper_days]
        peak, mdd = PAPER_START, 0.0
        for v in curve:
            peak = max(peak, v)
            mdd = max(mdd, 1 - v / peak)
        self.paper_asset_mdd = mdd
        self.paper_asset_last = curve[-1]

    # 공통 조각 ----------------------------------------------------------
    def cum_points(self, trades: list[Trade]) -> list[tuple[str, float]]:
        by_day = defaultdict(float)
        for t in trades:
            by_day[t.sell_ts.date()] += t.pnl
        pts, cum = [("시작", 0.0)], 0.0
        for d in sorted(by_day):
            cum += by_day[d]
            pts.append((f"{d:%m-%d}", cum))
        return pts

    def asset_points(self) -> list[tuple[str, float]]:
        return [("시작", float(PAPER_START))] + [(f"{d:%m-%d}", float(a)) for d, a in self.d.paper_days]

    def kind_table(self, trades: list[Trade], with_sub: bool = False) -> str:
        key = (lambda t: f"{t.kind} · {t.sub}") if with_sub else (lambda t: t.kind)
        rows, vals = [], []
        for k, s in by_key(trades, key):
            rows.append(stat_row(k, s))
            vals.append(s["sum"])
        return table(["매매"] + STAT_HEAD[1:], rows, num_cols=(1, 2, 3, 4, 5, 6, 7, 8), cls_cols={4: vals, 5: [None] * len(vals)})

    def dim_table(self, key, order: Optional[list] = None, head0: str = "구분") -> str:
        groups = [("real", self.real), ("paper", self.paper), ("virtual", self.virt)]
        keys = []
        per = {}
        for g, ts in groups:
            per[g] = dict(by_key(ts, key))
            for k in per[g]:
                if k not in keys:
                    keys.append(k)
        if order:
            keys.sort(key=lambda k: order.index(k) if k in order else 99)
        else:
            keys.sort(key=lambda k: -sum(per[g][k]["n"] for g, _ in groups if k in per[g]))
        head = [head0] + [f"{SECTION_LABEL[g]} {x}" for g, _ in groups for x in ("건수", "승률", "합계")]
        rows, cc = [], {i: [] for i in range(1, 10)}
        for k in keys:
            r = [k]
            for gi, (g, _) in enumerate(groups):
                s = per[g].get(k)
                r += [f"{s['n']}" if s else "", rate(s["win"]) if s else "", won(s["sum"]) if s else ""]
                for j in range(3):
                    cc[1 + gi * 3 + j].append(s["sum"] if (s and j == 2) else None)
            rows.append(r)
        return table(head, rows, num_cols=tuple(range(1, 10)), cls_cols={3: cc[3], 6: cc[6], 9: cc[9]}, tcls="wide")

    # 절 -------------------------------------------------------------------
    def sec_summary(self) -> str:
        sr, sp, sv = self.s_real, self.s_paper, self.s_virt
        opn = self.d.open()
        kpi = [("기간", f"{self.first:%Y-%m-%d} ~ {self.last:%Y-%m-%d}"),
               ("🔴 실전 합계", f"{won(sr['sum'])} (시드 {REAL_SEED:,.0f}원 대비 {sr['sum'] / REAL_SEED:+.1%})"),
               ("🟢 모의 계좌 평가 자산", f"{self.paper_asset_last:,.0f}원 ({self.paper_asset_last / PAPER_START - 1:+.1%})"),
               ("🟣 가상 합계", won(sv["sum"])),
               ("끝난 매매 수", f"실전 {sr['n']} · 모의 {sp['n']} · 가상 {sv['n']}건")]
        kp = '<div class="kpis">' + "".join(f'<div class="kpi"><span>{esc(a)}</span><b>{esc(b)}</b></div>' for a, b in kpi) + "</div>"
        rows = [stat_row("🔴 실전 (키움 실계좌)", sr, [pct(-sr["mdd_pct"]) + " (시드 기준)"]),
                stat_row("🟢 모의 (키움 모의 계좌)", sp, [pct(-self.paper_asset_mdd) + " (평가 자산 기준)"]),
                stat_row("🟣 가상 (주문 없음)", sv, ["— (시작 금액이 장부마다 달라 원으로만)"])]
        t = table(STAT_HEAD + ["MDD (비율)"], rows, num_cols=(1, 2, 3, 4, 5, 6, 7, 8, 9),
                  cls_cols={4: [sr["sum"], sp["sum"], sv["sum"]], 5: [sr["avg"], sp["avg"], sv["avg"]]})
        n_open = defaultdict(int)
        for x in opn:
            n_open[x.group] += 1
        skipped = sum(self.d.skipped.values())
        return f"""
<p>이 보고서는 {self.first:%Y-%m-%d} 부터 {self.last:%Y-%m-%d} 까지 실제로 기록된 매매만 모아 정리함. 실전 매매는 2026-10-26 에 시작했고, 그 전 기간은 모의·가상 기록만 있음.</p>
<div class="note"><b>세 가지 구분</b>
<div>🔴 실전: 키움 실계좌에서 실제 돈으로 사고판 매매. 시드 {REAL_SEED:,.0f}원, 종목당 3만 원 안. 손익은 수수료·세금 어림값을 뺀 값임.</div>
<div>🟢 모의: 키움 모의 계좌({PAPER_START / 1e4:,.0f}만 원 시작)에서 정규장에 실제 주문을 넣은 매매. 손익은 매수 금액의 0.25% 를 비용으로 뺀 값임.</div>
<div>🟣 가상: 주문 없이 그때 시세로 사고판 것으로 적은 매매. NXT 프리·애프터장 가상 체결, 모의 계좌 잔고·보유 한도로 못 사서 따로 적은 '잔고 밖' 매매, 매매법별 가상 장부(☕ 카페 테마 대장·📕 홍인기 상한가 풀림·📅 일정 등)를 모두 묶음.</div></div>
<div class="note"><b>숫자 읽는 법</b>
<div>승률: 이긴 건수 ÷ 끝난 건수. 이긴 건 = 손익이 0원보다 큰 것.</div>
<div>손익비: 이긴 매매 평균 이익 ÷ 진 매매 평균 손실. 1보다 크면 한 번 이길 때 버는 돈이 한 번 질 때 잃는 돈보다 큼.</div>
<div>PF: 이익 합계 ÷ 손실 합계. 1보다 크면 전체로 번 돈이 잃은 돈보다 많음.</div>
<div>MDD: 누적 손익이 가장 높았던 때에서 가장 많이 빠진 폭. 원 단위는 끝난 매매 순서대로 쌓은 값이고, 모의 비율은 매일 평가 자산(들고 있는 종목 평가 포함) 기준임.</div></div>
{kp}
<h3>구분별 요약 (끝난 매매만)</h3>{t}
<p class="muted">아직 들고 있는 것: 실전 {n_open['real']}건 · 모의 {n_open['paper']}건 · 가상 {n_open['virtual']}건 (부록 C). 신호는 났지만 한도·조건으로 모의에서 사지 않은 신호 {skipped:,}건은 매매가 아니라 숫자에서 뺌.
실전 시드 대비 수익률은 합계 손익 ÷ 시드 {REAL_SEED:,.0f}원으로 계산함.</p>"""

    def sec_kinds(self) -> str:
        top = by_key(self.real, lambda t: t.kind)
        return f"""
<p>매매 이름은 번호·이모지 옆에 이름을 함께 적음. 실전·모의·가상을 따로 봄. 합계 손익이 큰 순서임.</p>
<h3>🔴 실전 매매별</h3>{self.kind_table(self.real)}
<h3>🟢 모의 매매별</h3>{self.kind_table(self.paper)}
<p class="muted">모의에서 신호가 났지만 사지 않은 신호 수 (매매별): {esc(' · '.join(f'{k} {v}건' for k, v in sorted(self.d.skipped.items(), key=lambda kv: -kv[1])))}</p>
<h3>🟣 가상 매매별 (세부 구분 포함)</h3>{self.kind_table(self.virt, with_sub=True)}"""

    def sec_flow(self, for_pdf: bool = False) -> str:
        series = [("🔴 실전 누적 손익 (매도한 날 기준)", self.cum_points(self.real), 0.0),
                  ("🟢 모의 누적 손익 (끝난 매매)", self.cum_points(self.paper), 0.0),
                  ("🟢 모의 계좌 평가 자산 (매일 마감)", self.asset_points(), float(PAPER_START)),
                  ("🟣 가상 누적 손익 (끝난 매매)", self.cum_points(self.virt), 0.0)]
        if for_pdf:
            pdf_series = [(re.sub(r"^[^\w(]+", "", t).strip(), p, b) for t, p, b in series]   # matplotlib 은 컬러 이모지를 못 그려 글자로만
            charts = ""
            for part in (pdf_series[:2], pdf_series[2:]):      # 두 개씩 한 그림 (쪽 나누기 때 그림 크기를 미리 알게 width·height 를 적음)
                b64, wpx, hpx = mpl_png(part)
                charts += f'<img class="chart" width="{wpx}" height="{hpx}" src="data:image/png;base64,{b64}" alt="누적 손익 그래프">'
        else:
            charts = "".join(svg_cum(p, t, base=b) for t, p, b in series)
        # 날짜별
        by_day = defaultdict(lambda: {"real": 0.0, "paper": 0.0, "virtual": 0.0, "n": 0})
        for t in self.all_closed:
            x = by_day[t.sell_ts.date()]
            x[t.group] += t.pnl
            x["n"] += 1
        days = sorted(by_day)
        rows, cum_r, cum_all = [], 0.0, 0.0
        cr, cp, cv, ca = [], [], [], []
        for d in days:
            x = by_day[d]
            cum_r += x["real"]
            rows.append([f"{d:%m-%d} ({'월화수목금토일'[d.weekday()]})", self.d.regime(d), f"{x['n']}", won(x["real"]) if x["real"] else "",
                         won(x["paper"]) if x["paper"] else "", won(x["virtual"]) if x["virtual"] else "", won(cum_r), "있음" if d in self.d.journal_files else ""])
            cr.append(x["real"] or None)
            cp.append(x["paper"] or None)
            cv.append(x["virtual"] or None)
            ca.append(cum_r)
        day_t = table(["매도한 날", "그날 시장 분위기", "끝난 건수", "🔴 실전", "🟢 모의", "🟣 가상", "🔴 실전 누적", "일지 파일"], rows,
                      num_cols=(2, 3, 4, 5, 6), cls_cols={3: cr, 4: cp, 5: cv, 6: ca})

        def period_table(keyf, head0):
            agg = defaultdict(lambda: {"real": 0.0, "paper": 0.0, "virtual": 0.0, "nr": 0, "np": 0, "nv": 0})
            for t in self.all_closed:
                a = agg[keyf(t.sell_ts.date())]
                a[t.group] += t.pnl
                a[{"real": "nr", "paper": "np", "virtual": "nv"}[t.group]] += 1
            rs, c1, c2, c3 = [], [], [], []
            for k in sorted(agg):
                a = agg[k]
                rs.append([k[1], f"{a['nr']}", won(a["real"]), f"{a['np']}", won(a["paper"]), f"{a['nv']}", won(a["virtual"])])
                c1.append(a["real"])
                c2.append(a["paper"])
                c3.append(a["virtual"])
            return table([head0, "🔴 실전 건수", "🔴 실전 합계", "🟢 모의 건수", "🟢 모의 합계", "🟣 가상 건수", "🟣 가상 합계"], rs,
                         num_cols=(1, 2, 3, 4, 5, 6), cls_cols={2: c1, 4: c2, 6: c3})

        def wk(d: date):
            mon = d - timedelta(days=d.weekday())
            return (mon, f"{mon:%m-%d} ~ {mon + timedelta(days=4):%m-%d}")

        month_t = period_table(lambda d: ((d.year, d.month), f"{d.year}년 {d.month}월"), "달")
        week_t = period_table(wk, "주 (월~금)")
        note = ("그래프는 matplotlib 으로 그린 그림임." if for_pdf else "점에 마우스를 올리면 그날 값이 보임.")
        return f"""
<p>매도한 날 기준으로 손익을 쌓음. {note} 모의 계좌 평가 자산은 들고 있는 종목의 평가 손익까지 들어간 값이라 끝난 매매 누적과 다름.</p>
{charts}
<h3>달별 합계</h3>{month_t}
<h3>주별 합계</h3>{week_t}
<h3>날짜별 손익</h3>{day_t}
<p class="muted">'일지 파일' 은 docs/journal 에 그날 매매일지가 있는지 표시함. 시장 분위기는 09:10 판정 기록(없으면 장중 로그)이고, 판정 기록이 없는 날은 '기록 없음' 임.</p>"""

    def sec_analysis(self) -> str:
        reason_t = self.dim_table(lambda t: sell_cat(t.reason), head0="매도 사유")
        hold_t = self.dim_table(hold_cat, order=HOLD_ORDER, head0="보유 시간")
        reg_t = self.dim_table(lambda t: t.regime, head0="산 날 시장 분위기")
        sub_t = self.dim_table(lambda t: t.sub, head0="세부 구분")
        return f"""
<p>같은 기준으로 실전·모의·가상을 나란히 놓음. 표가 넓으면 옆으로 밀어서 봄.</p>
<h3>매도 사유별</h3>
<p class="muted">VWAP 이탈: 1분봉 5개가 연속으로 그날 VWAP 아래에서 끝나면 파는 규칙 (2026-11-12 부터 실전에 들어감). 다음 날 09:00 매도: 그날 손절·익절에 안 닿아 다음 날 장 시작 첫 가격에 판 것.
큰 음봉 매도: 5분선 아래 큰 음봉이나 평소보다 몸통이 큰 음봉이 나와 판 것. 장 마감 정리: 15:19 에 남은 모의 종목을 판 것. 애프터 가상 시간 끝 정리: NXT 애프터장 가상 매수분을 19:50 에 정리한 것.</p>
{reason_t}
<h3>보유 시간별</h3>
<p class="muted">산 시각부터 판 시각까지. 다음 날로 넘긴 매매는 거래일 수로 셈.</p>
{hold_t}
<h3>산 날 시장 분위기별</h3>
<p class="muted">시장 분위기는 09:10 에 대금 상위 주식 등락 중앙값과 코스피 움직임으로 정한 판정임 (강한 상승장 · 강한 하락장 · 보통 날 등). 판정 기록이 없는 날은 '기록 없음'.</p>
{reg_t}
<h3>세부 구분별</h3>{sub_t}"""

    def sec_real_journal(self) -> str:
        rows, cc = [], []
        for t in sorted(self.real, key=lambda t: t.buy_ts or datetime.min):
            rows.append([f"{t.buy_ts:%m-%d %H:%M}" if t.buy_ts else f"{t.buy_date:%m-%d}", t.kind, f"{t.name} ({t.code})", f"{t.qty}",
                         px(t.buy_price), px(t.sell_price), won(t.pnl), pct(t.ret), f"{t.sell_ts:%m-%d %H:%M}" if t.sell_ts else "",
                         t.reason + (f" · {t.note}" if t.note else "")])
            cc.append(t.pnl)
        liq = ""
        if self.d.liquidations:
            liq = ("<p class=\"muted\">매매가 아닌 기록: " + esc(" · ".join(f"{d:%m-%d} {nm}({code}) {q}주 정리 주문" for d, nm, code, q, _ in self.d.liquidations))
                   + " — 실전 시작 날 원래 들고 있던 종목을 판 것이라 손익 계산에서 뺌.</p>")
        return f"""
<p>실전 매매 전 건을 산 시각 순서로 적음 ({len(rows)}건). 손익은 비용을 뺀 값, 수익률은 손익 ÷ 산 금액.</p>
{table(['산 시각', '매매', '종목', '수량', '산 값', '판 값', '손익', '수익률', '판 시각', '매도 사유'], rows, num_cols=(3, 4, 5, 6, 7), cls_cols={6: cc, 7: cc}, tcls="journal")}
{liq}"""

    def sec_observe(self) -> str:
        R, P, V = self.real, self.paper, self.virt
        sr = self.s_real
        good, bad, both_l = [], [], []
        if R:
            best = [t for t in sorted(R, key=lambda t: -t.pnl) if t.pnl > 0][:3]
            worst = sorted(R, key=lambda t: t.pnl)[:3]
            if best:
                good.append("🔴 실전에서 번 매매: " + " · ".join(f"{t.name} [{t.kind}] {won(t.pnl)} ({sell_cat(t.reason)})" for t in best) + ".")
            direct = [t for t in R if sell_cat(t.reason) == "직접 매도 (사용자)"]
            if direct:
                wd = sum(1 for t in direct if t.pnl > 0)
                good.append(f"🔴 사용자가 직접 판 실전 매매는 {len(direct)}건, 합계 {won(sum(t.pnl for t in direct))} 임. 실전에서 이긴 {sr['w']}건 중 {wd}건이 직접 매도였음.")
            bad.append(f"🔴 실전은 끝난 {sr['n']}건 중 {sr['w']}건만 이겼음 (승률 {rate(sr['win'])}). 합계는 {won(sr['sum'])}, 시드 대비 {sr['sum'] / REAL_SEED:+.1%} 임.")
            bad.append("🔴 실전에서 가장 크게 잃은 매매: " + " · ".join(f"{t.name} [{t.kind}] {won(t.pnl)} ({sell_cat(t.reason)})" for t in worst) + ".")
            cats = sorted(by_key(R, lambda t: sell_cat(t.reason)), key=lambda kv: kv[1]["sum"])
            bad.append("🔴 실전 매도 사유별 합계 (나쁜 순서): " + " · ".join(f"{k} {v['n']}건 {won(v['sum'])}" for k, v in cats) + ".")
            most = max(by_key(R, lambda t: t.kind), key=lambda kv: kv[1]["n"])
            bad.append(f"🔴 실전에서 가장 많이 산 매매: {most[0]} — {most[1]['n']}건 중 {most[1]['w']}건 이김, 합계 {won(most[1]['sum'])}.")
            run = mx = 0
            for t in R:
                run = run + 1 if t.pnl <= 0 else 0
                mx = max(mx, run)
            bad.append(f"🔴 실전 연속 손실은 가장 길 때 {mx}건 이어졌음 (판 시각 순서).")
        if P:
            ks = by_key(P, lambda t: t.kind)
            good.append("🟢 모의에서 합계가 가장 좋은 매매: " + " · ".join(f"{k} {v['n']}건 {won(v['sum'])}" for k, v in ks[:3] if v["sum"] > 0) + ".")
            bad.append("🟢 모의에서 합계가 가장 나쁜 매매: " + " · ".join(f"{k} {v['n']}건 {won(v['sum'])}" for k, v in ks[::-1][:3]) + ".")
            bad.append(f"🟢 모의 계좌 평가 자산은 {PAPER_START:,.0f}원에서 {self.paper_asset_last:,.0f}원이 됐음 ({self.paper_asset_last / PAPER_START - 1:+.1%}, 가장 많이 빠졌을 때 {pct(-self.paper_asset_mdd)}).")
        if V:
            ks = by_key(V, lambda t: t.kind)
            good.append("🟣 가상에서 합계가 가장 좋은 매매: " + " · ".join(f"{k} {v['n']}건 {won(v['sum'])}" for k, v in ks[:3] if v["sum"] > 0) + ".")
            bad.append("🟣 가상에서 합계가 가장 나쁜 매매: " + " · ".join(f"{k} {v['n']}건 {won(v['sum'])}" for k, v in ks[::-1][:3]) + ".")
        for nm, ts in (("🔴 실전", R), ("🟢 모의", P)):
            rg = [(k, v) for k, v in by_key(ts, lambda t: t.regime) if v["n"] >= 3]
            if len(rg) >= 2:
                both_l.append(f"{nm} 매매를 산 날 시장 분위기별로 보면 {rg[0][0]} {rg[0][1]['n']}건 {won(rg[0][1]['sum'])} 이 가장 좋고, "
                              f"{rg[-1][0]} {rg[-1][1]['n']}건 {won(rg[-1][1]['sum'])} 이 가장 나빴음 (3건 이상인 분위기만).")
        same = []
        for k in sorted(set(t.kind for t in R) & set(t.kind for t in P)):
            a = sum(t.pnl for t in R if t.kind == k)
            b = sum(t.pnl for t in P if t.kind == k)
            same.append(f"{k} 실전 {won(a)} / 모의 {won(b)}")
        if same:
            both_l.append("실전과 모의에서 함께 돈 매매의 합계: " + " · ".join(same) + ". 실전은 종목당 3만 원, 모의는 종목당 100만 원 안이라 금액 크기가 다름.")
        ul = lambda xs: "<ul class=\"obs\">" + "".join(f"<li>{esc(x)}</li>" for x in xs) + "</ul>"
        return ("<p>기록에서 바로 보이는 사실만 적음. 규칙을 바꾸자는 내용은 넣지 않음.</p>"
                f"<h3>잘된 점</h3>{ul(good)}<h3>안된 점</h3>{ul(bad)}<h3>함께 볼 것</h3>{ul(both_l)}")

    def _journal_rows(self, trades: list[Trade]) -> tuple[list, list]:
        rows, cc = [], []
        for t in sorted(trades, key=lambda t: (t.buy_ts or datetime.combine(t.buy_date, datetime.min.time()))):
            reason = t.reason if len(t.reason) <= 46 else t.reason[:45] + "…"
            rows.append([f"{t.buy_ts:%m-%d %H:%M}" if t.buy_ts else f"{t.buy_date:%m-%d}", t.kind, t.sub, t.name, f"{t.qty}", px(t.buy_price), px(t.sell_price),
                         won(t.pnl), pct(t.ret), f"{t.sell_ts:%m-%d %H:%M}" if t.sell_ts else "", reason])
            cc.append(t.pnl)
        return rows, cc

    def sec_paper_journal(self) -> str:
        rows, cc = self._journal_rows(self.paper)
        return (f"<p>🟢 모의 계좌에서 끝난 매매 전 건 ({len(rows)}건). 손익은 비용 0.25% 를 뺀 값임. 사유가 길면 줄여 적음.</p>"
                + table(["산 시각", "매매", "구분", "종목", "수량", "산 값", "판 값", "손익", "수익률", "판 시각", "매도 사유"], rows,
                        num_cols=(4, 5, 6, 7, 8), cls_cols={7: cc, 8: cc}, tcls="journal"))

    def sec_virtual_journal(self) -> str:
        rows, cc = self._journal_rows(self.virt)
        return (f"<p>🟣 가상으로 끝난 매매 전 건 ({len(rows)}건). 구분 칸: NXT 가상 체결 · 잔고 밖 · 가상 장부. 가상 장부 손익은 장부가 적은 값(비용 포함) 그대로임.</p>"
                + table(["산 시각", "매매", "구분", "종목", "수량", "산 값", "판 값", "손익", "수익률", "판 시각", "매도 사유"], rows,
                        num_cols=(4, 5, 6, 7, 8), cls_cols={7: cc, 8: cc}, tcls="journal"))

    def sec_open_and_notes(self) -> str:
        opn = sorted(self.d.open(), key=lambda t: (t.group, t.buy_ts or datetime.min))
        rows = [[SECTION_LABEL[t.group], f"{t.buy_ts:%m-%d %H:%M}" if t.buy_ts else f"{t.buy_date:%m-%d}", t.kind, t.sub, t.name, f"{t.qty}", px(t.buy_price)] for t in opn]
        t = table(["구분", "산 시각", "매매", "세부", "종목", "수량", "산 값"], rows, num_cols=(5, 6)) if rows else "<p>없음.</p>"
        return f"""
<p>{self.today:%Y-%m-%d} 기준으로 아직 팔지 않은 것. 평가 손익은 계산하지 않음 (끝난 매매만 숫자에 넣음).</p>{t}
<h3>자료와 계산 방식</h3>
<ul class="obs">
<li>읽은 자료: {esc(os.path.basename(self.d.db_path))} (읽기 전용) — real_trades · paper_trades · ledger_trades · paper_days · market_regime · real_liquidations, 그리고 docs/journal 일지 파일 목록과 장중 로그(시장 분위기).</li>
<li>모의 손익 계산은 매매일지(journal.py)와 같음: (판 값 − 산 값) × 수량 − 산 금액 × 0.25%, 절반 먼저 판 것은 그 값으로 따로 셈. 실전·가상 장부 손익은 표에 적힌 값 그대로 씀.</li>
<li>예전 10만 원 계좌 기록(small_trades 1건)은 💰 10만 원 계좌 가상 장부로 옮겨져 있어 두 번 세지 않음. 모의 주문 실패 {self.d.failed}건은 체결이 없어 뺌.</li>
<li>보고서 만든 시각: {datetime.now():%Y-%m-%d %H:%M}. 다시 만들기: <code>python -m kiwoom_trading.execution.full_report</code></li>
</ul>"""

    def sections(self, for_pdf: bool = False) -> list[tuple[str, str]]:
        return [("1. 요약", self.sec_summary()),
                ("2. 매매별 성과", self.sec_kinds()),
                ("3. 날짜별 손익 흐름", self.sec_flow(for_pdf)),
                ("4. 매도 사유 · 보유 시간 · 시장 분위기별", self.sec_analysis()),
                ("5. 실전 매매일지 (전 건)", self.sec_real_journal()),
                ("6. 잘된 점 · 안된 점 (기록에서 보이는 사실)", self.sec_observe()),
                ("부록 A. 🟢 모의 매매일지 (전 건)", self.sec_paper_journal()),
                ("부록 B. 🟣 가상 매매일지 (전 건)", self.sec_virtual_journal()),
                ("부록 C. 아직 들고 있는 것 · 자료 설명", self.sec_open_and_notes())]

    # 출력 -------------------------------------------------------------------
    def title(self) -> str:
        return f"매매일지 · 매매 성과 보고서 ({self.first:%Y-%m-%d} ~ {self.last:%Y-%m-%d})"

    def build_html(self) -> str:
        secs = self.sections(False)
        nav = "".join(f'<a href="#s{i}">{esc(t)}</a>' for i, (t, _) in enumerate(secs))
        body = "".join(f'<section id="s{i}"><h2>{esc(t)}</h2>{b}{abbr_footer_html(t + b)}</section>' for i, (t, b) in enumerate(secs))
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(self.title())}</title><style>{CSS_SCREEN}</style></head><body>
<header><div class="top"><h1>📚 {esc(self.title())}</h1><button id="tg" type="button" aria-label="밝게·어둡게 바꾸기">🌓</button></div>
<p class="muted">{self.today:%Y-%m-%d} 기준 · 실제 기록만 씀 (백테스트 없음) · 🔴 실전 · 🟢 모의 · 🟣 가상</p><nav>{nav}</nav></header>
{body}
<script>
(function(){{var r=document.documentElement,k='tj-theme',s=localStorage.getItem(k);if(s)r.dataset.theme=s;
document.getElementById('tg').onclick=function(){{var d=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
r.dataset.theme=d==='dark'?'light':'dark';localStorage.setItem(k,r.dataset.theme);}};}})();
</script></body></html>"""

    def build_print_html(self) -> str:
        secs = self.sections(True)
        blocks = [f'<h1 class="doc">📚 {esc(self.title())}</h1><p class="muted">{self.today:%Y-%m-%d} 기준 · 실제 기록만 씀 (백테스트 없음) · 🔴 실전 · 🟢 모의 · 🟣 가상</p>']
        for i, (t, b) in enumerate(secs):
            cls_ = ' class="newpage"' if i in (6, 7, 8) else ""
            blocks.append(f"<h2{cls_}>{esc(t)}</h2>{b}")
        flow = "".join(blocks).replace('<div class="scroll">', "").replace("</table></div>", "</table>")
        abbr_js = "[" + ",".join(f"[{_js(k)},{_js(v)}]" for k, v in ABBR.items()) + "]"
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{esc(self.title())}</title><style>{CSS_PRINT}</style></head><body>
<div id="flow">{flow}</div><div id="pages"></div>
<script>
var ABBR={abbr_js};
{PAGINATE_JS}
</script></body></html>"""


def _js(s: str) -> str:
    import json
    return json.dumps(s, ensure_ascii=False)


CSS_BASE = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#6b6560;--card:#ffffff;--line:#e7e5e4;--pos:#1d4ed8;--neg:#dc2626;--head:#f5f5f4;--accent:#2563eb}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0c0a09;--fg:#e7e5e4;--muted:#a8a29e;--card:#1c1917;--line:#2e2a27;--pos:#60a5fa;--neg:#f87171;--head:#1f1b18;--accent:#60a5fa}}
:root[data-theme="dark"]{--bg:#0c0a09;--fg:#e7e5e4;--muted:#a8a29e;--card:#1c1917;--line:#2e2a27;--pos:#60a5fa;--neg:#f87171;--head:#1f1b18;--accent:#60a5fa}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 "Malgun Gothic","맑은 고딕",system-ui,-apple-system,"Segoe UI Emoji",sans-serif}
h1{font-size:22px;margin:6px 0} h2{font-size:18px;margin:4px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)} h3{font-size:15px;margin:18px 0 6px}
.muted{color:var(--muted)} .pos{color:var(--pos)} .neg{color:var(--neg)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px}
.kpi span{display:block;color:var(--muted);font-size:12px} .kpi b{font-size:15px;font-variant-numeric:tabular-nums}
.note{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:8px 12px;margin:10px 0;font-size:13.5px}
.note b{display:block;margin-bottom:2px}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums;background:var(--card)}
th,td{text-align:left;padding:5px 7px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--head);color:var(--muted);font-weight:600;white-space:nowrap} td.r,th.r{text-align:right;white-space:nowrap}
ul.obs{padding-left:20px} ul.obs li{margin:4px 0}
.abbr{margin-top:18px;padding-top:8px;border-top:1px dashed var(--line);color:var(--muted);font-size:12px}
.abbr b{display:block;margin-bottom:2px}
code{font-size:12px;background:var(--head);padding:1px 4px;border-radius:4px}
"""

CSS_SCREEN = CSS_BASE + """
header,section{max-width:1080px;margin:0 auto;padding:14px 16px}
section{background:transparent;border-top:1px solid var(--line);margin-top:8px}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px}
#tg{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;font-size:18px;padding:4px 10px;cursor:pointer}
nav{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px} nav a{font-size:12.5px;color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--card)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:8px}
.scroll table{border:0} td{white-space:nowrap} table.journal td:last-child{white-space:normal;min-width:220px}
figure{margin:12px 0} svg{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
.curve{fill:none;stroke-width:2} .curve.pos{stroke:var(--pos)} .curve.neg{stroke:var(--neg)}
.area{stroke:none;opacity:.12} .area.pos{fill:var(--pos)} .area.neg{fill:var(--neg)}
.dot.pos{fill:var(--pos)} .dot.neg{fill:var(--neg)}
.grid{stroke:var(--line)} .zero{stroke:var(--muted);stroke-dasharray:4 4} .axis{fill:var(--muted);font-size:11px} .ttl{fill:var(--fg);font-size:13px;font-weight:600}
@media (max-width:640px){body{font-size:14px} h1{font-size:18px} h2{font-size:16px} header,section{padding:10px} table{font-size:11.5px}}
"""

CSS_PRINT = CSS_BASE + """
@page{size:A4;margin:0}
:root{--bg:#fff}
body{background:#fff;font-size:9.5pt;line-height:1.45;-webkit-print-color-adjust:exact;print-color-adjust:exact}
#flow{position:absolute;left:-9999px;top:0;width:186mm}
.page{width:210mm;height:297mm;box-sizing:border-box;padding:12mm 12mm 8mm;position:relative;overflow:hidden;page-break-after:always;break-after:page;display:flex;flex-direction:column}
.page:last-child{page-break-after:auto;break-after:auto}
.content{flex:1 1 auto;overflow:hidden}
.foot{flex:0 0 27mm;height:27mm;box-sizing:border-box;overflow:hidden;border-top:1px dashed #d6d3d1;padding-top:3mm;margin-top:2mm;color:#57534e;font-size:7.5pt;line-height:1.4}
.foot .pn{float:right}
h1.doc{font-size:16pt;margin:0 0 2mm} h2{font-size:12.5pt;margin:3mm 0 2.5mm} h3{font-size:10.5pt;margin:4mm 0 1.5mm}
.kpis{grid-template-columns:repeat(3,1fr);gap:2mm} .kpi{padding:2mm 3mm} .kpi b{font-size:9.5pt}
.note{font-size:8.6pt;padding:2mm 3mm;margin:2mm 0}
table{font-size:7.6pt;border:1px solid #e7e5e4;margin-bottom:1mm} th,td{padding:1.1mm 1.5mm}
table.wide{font-size:7pt} table.journal{font-size:7pt} table.journal td:last-child{white-space:normal} table.journal td:nth-child(2){white-space:nowrap}
caption{caption-side:top;text-align:left;font-size:7.5pt;color:#57534e}
img.chart{width:100%;height:auto;margin:2mm 0}
p{margin:1.5mm 0} ul.obs li{margin:1.2mm 0}
"""

PAGINATE_JS = r"""
(function(){
  var flow=document.getElementById('flow'), pages=document.getElementById('pages');
  var cur=null, n=0;
  function newPage(){
    var p=document.createElement('div');p.className='page';
    var c=document.createElement('div');c.className='content';
    var f=document.createElement('div');f.className='foot';
    p.appendChild(c);p.appendChild(f);pages.appendChild(p);cur=c;n++;
    return c;
  }
  // 약어 풀이 자리(.foot)는 높이를 고정해 두고 남은 높이에 본문을 채움
  function fits(){ return cur.scrollHeight <= cur.clientHeight + 1; }
  function lastIsHeading(){ var l=cur.lastElementChild; return l && /^H[123]$/.test(l.tagName); }
  newPage();
  var nodes=Array.prototype.slice.call(flow.childNodes).filter(function(x){return x.nodeType===1;});
  nodes.forEach(function(el){
    if(el.classList.contains('newpage') && cur.childElementCount>0){ newPage(); }
    cur.appendChild(el);
    if(fits()) return;
    if(el.tagName==='TABLE'){
      // 줄 단위로 나눔 (머리줄은 쪽마다 다시)
      cur.removeChild(el);
      var head=el.tHead, rows=Array.prototype.slice.call(el.tBodies[0].rows);
      var mk=function(){ var t=el.cloneNode(false); if(head) t.appendChild(head.cloneNode(true)); var b=document.createElement('tbody'); t.appendChild(b); return t; };
      var t=mk(); cur.appendChild(t);
      if(!fits() || rows.length===0){ cur.removeChild(t); var hd=lastIsHeading()?cur.lastElementChild:null; newPage(); if(hd) cur.appendChild(hd); t=mk(); cur.appendChild(t); }
      var placed=0;
      rows.forEach(function(r){
        t.tBodies[0].appendChild(r);
        if(!fits()){
          t.tBodies[0].removeChild(r);
          if(placed===0){ cur.removeChild(t); var hd2=lastIsHeading()?cur.lastElementChild:null; newPage(); if(hd2) cur.appendChild(hd2); }
          else { newPage(); }
          t=mk(); cur.appendChild(t); t.tBodies[0].appendChild(r); placed=0;
        }
        placed++;
      });
      return;
    }
    cur.removeChild(el);
    var moved=[];
    while(lastIsHeading()){ moved.unshift(cur.lastElementChild); cur.removeChild(cur.lastElementChild); }
    if(cur.childElementCount===0 && moved.length===0){ cur.appendChild(el); return; }
    newPage(); moved.forEach(function(m){cur.appendChild(m);}); cur.appendChild(el);
  });
  // 쪽마다 약어 풀이 (그 쪽 본문에 처음 나온 순서)
  var all=pages.querySelectorAll('.page');
  for(var i=0;i<all.length;i++){
    var c=all[i].querySelector('.content'), f=all[i].querySelector('.foot');
    var txt=c.innerText, found=[];
    ABBR.forEach(function(a){ var m=new RegExp('(^|[^A-Za-z])'+a[0]+'(?![A-Za-z])').exec(txt); if(m) found.push([m.index,a]); });
    found.sort(function(x,y){return x[0]-y[0];});
    var h='<span class="pn">'+(i+1)+' / '+all.length+'</span>';
    h+= found.length ? '<b>약어 풀이</b> ' + found.map(function(x){return '<div>'+x[1][0]+': '+x[1][1]+'</div>';}).join('') : '<div>이 쪽에 풀이할 약어 없음</div>';
    f.innerHTML=h;
  }
  flow.parentNode.removeChild(flow);
  document.body.setAttribute('data-done','1');
})();
"""


def find_browser() -> Optional[str]:
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p
    return shutil.which("msedge") or shutil.which("chrome")


def print_pdf(html_text: str, out_pdf: str) -> None:
    exe = find_browser()
    if not exe:
        raise RuntimeError("Edge·Chrome 을 찾지 못해 PDF 를 못 만듦")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "print.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(html_text)
        if os.path.exists(out_pdf):
            os.remove(out_pdf)
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
               "--virtual-time-budget=20000", f"--user-data-dir={os.path.join(tmp, 'prof')}", f"--print-to-pdf={out_pdf}",
               "file:///" + src.replace("\\", "/")]
        subprocess.run(cmd, check=False, capture_output=True, timeout=180)
    if not os.path.exists(out_pdf):
        raise RuntimeError("PDF 만들기 실패")


def main() -> None:
    ap = argparse.ArgumentParser(description="전체 매매일지·성과 보고서 (HTML + PDF)")
    ap.add_argument("--root", default=PROJECT_ROOT, help="자료가 있는 저장소 폴더 (data/·docs/journal)")
    ap.add_argument("--out", default=None, help="저장 폴더 (기본 <root>/data/reports)")
    ap.add_argument("--date", default=None, help="파일 이름 날짜 YYYYMMDD (기본 오늘)")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    root = a.root
    if not os.path.exists(os.path.join(root, "data", "screener.duckdb")) and not os.path.exists(os.path.join(root, "data", "screener_snapshot.duckdb")):
        main_root = os.path.abspath(os.path.join(root, "..", "..", ".."))     # .claude/worktrees/<이름> 에서 돌리면 본 폴더 자료
        if os.path.exists(os.path.join(main_root, "data", "screener.duckdb")):
            root = main_root
    today = datetime.strptime(a.date, "%Y%m%d").date() if a.date else date.today()
    out_dir = a.out or os.path.join(root, "data", "reports")
    os.makedirs(out_dir, exist_ok=True)
    data = Data(root)
    try:
        rep = Report(data, today)
        base = os.path.join(out_dir, f"trading_journal_{today:%Y%m%d}")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(rep.build_html())
        print(base + ".html")
        if not a.no_pdf:
            ph = rep.build_print_html()
            with open(base + ".print.html", "w", encoding="utf-8") as f:
                f.write(ph)
            print_pdf(ph, base + ".pdf")
            os.remove(base + ".print.html")
            print(base + ".pdf")
    finally:
        data.ctx.close()


if __name__ == "__main__":
    main()
