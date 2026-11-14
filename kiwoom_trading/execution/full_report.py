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
        # 신호 기록 전부 (건너뜀 포함) — '개선점' 절의 모의 계좌 자금·자리 부족 셈에 씀
        self.signal_rows = q(scr, """
                SELECT kind, status, coalesce(note, ''), coalesce(virtual, false), coalesce(overflow, false), code, signal_ts, buy_ts, sell_ts, date
                FROM paper_trades WHERE status <> 'failed'""")
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
<p><b>개선점과 앞으로 할 일은 바로 다음 2절에 정리함 (가장 먼저 볼 곳).</b></p>
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
        return ("<p>기록에서 바로 보이는 사실만 적음. 개선 방향과 앞으로 할 일은 2절에 있음.</p>"
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
                ("2. 개선점과 앞으로 할 일", Plan(self).html()),
                ("3. 매매별 성과", self.sec_kinds()),
                ("4. 날짜별 손익 흐름", self.sec_flow(for_pdf)),
                ("5. 매도 사유 · 보유 시간 · 시장 분위기별", self.sec_analysis()),
                ("6. 실전 매매일지 (전 건)", self.sec_real_journal()),
                ("7. 잘된 점 · 안된 점 (기록에서 보이는 사실)", self.sec_observe()),
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
            cls_ = ' class="newpage"' if (t.startswith("부록") or t.startswith("2. ") or t.startswith("3. ")) else ""
            blocks.append(f"<h2{cls_}>{esc(t)}</h2>{b}")
        flow = "".join(blocks).replace('<div class="scroll">', "").replace("</table></div>", "</table>")
        abbr_js = "[" + ",".join(f"[{_js(k)},{_js(v)}]" for k, v in ABBR.items()) + "]"
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{esc(self.title())}</title><style>{CSS_PRINT}</style></head><body>
<div id="flow">{flow}</div><div id="pages"></div>
<script>
var ABBR={abbr_js};
{PAGINATE_JS}
</script></body></html>"""


# ------------------------------------------------------------------ 2절 개선점과 앞으로 할 일
# 근거는 모두 위 Data 가 읽은 실제 매매 기록에서 셈. 판단(무엇을 켜고 끌지)은 사용자 몫이라 선택지로만 적음.
MIN_N = 20                    # 판정에 필요한 끝난 건수 (모의 + 가상)
ETF_MOVE_LIMIT = 0.10         # 1배 인버스 ETF 가 하루 만에 ±10% 넘게 움직인 기록은 체결 기록 이상으로 보고 평균에서 뺌
UP_REAL_PRICE = 55_000        # 1️⃣ 상승장 장 초를 실전에서 뺄 때 쓴 기준 — 실전 계좌가 살 수 있는 값 (real.REAL_OFF 주석)
try:
    from kiwoom_trading.execution.real import ETF_CODES as _ETF, PLAYS as _PLAYS, REAL_OFF as _REAL_OFF
    REAL_ON_LABELS = [lb for k, (lb, _, _) in _PLAYS.items() if k not in _REAL_OFF]
    REAL_OFF_LABELS = [_PLAYS[k][0] for k in _REAL_OFF if k in _PLAYS]
except Exception:
    _ETF, REAL_ON_LABELS, REAL_OFF_LABELS = {"123310"}, [], []
# 모의 매수까지 이미 꺼진 매매 (코드 기준) — 판정표에서 '이미 멈춤' 으로만 표시하고 다시 제안하지 않음
PAPER_STOPPED = {
    "🎯 돌파 후 눌림": "10-25 장중 종목 찾기 끔 (run_intraday.DISCOVERY = False) — 신호가 안 남",
    "🎯 지지 반등": "10-25 장중 종목 찾기 끔 (run_intraday.DISCOVERY = False) — 신호가 안 남",
    "🎯 눌림 돌파": "10-24 모의 매수 끔, 알림만 (paper.py)",
    "🎯 대형주 수급": "11-09 모의 매수 끔 (PR #191)",
    "3️⃣ 막힌 고점 돌파": "10-29 모의 안 삼 (paper.MOCK_OFF)",
    "🧭 디앤서 14:30 주도주 종가": "10-25 알림만 (paper.py)",
    "💰 10만 원 계좌": "가상 장부 끔 (PR #133)",
}


def base_kind(k: str) -> str:
    """같은 매매의 다른 장부 이름을 하나로 (☕ 가상 장부·📕 수급 확인/없이·📅 일정)."""
    k = re.sub(r" \((가상 장부|수급 확인|수급 없이)\)$", "", k)
    return k.replace("📅 일정 ", "📅 ")


def odd_fill(t: Trade) -> bool:
    return t.code in _ETF and t.ret is not None and abs(t.ret) >= ETF_MOVE_LIMIT


def gross(b: Optional[float], s: Optional[float]) -> Optional[float]:
    return (s / b - 1) if (b and s) else None


def kst(ts: list[Trade]) -> dict:
    s = stats([t.pnl for t in ts])
    rs = [t.ret for t in ts if t.ret is not None]
    s["ret"] = sum(rs) / len(rs) if rs else None
    return s


def card(title: str, problem: str, direction: str, todo: str) -> str:
    return (f'<div class="card"><b>{esc(title)}</b>'
            f'<div><span class="tag t1">기록에서 드러난 문제</span>{esc(problem)}</div>'
            f'<div><span class="tag t2">개선 방향</span>{esc(direction)}</div>'
            f'<div><span class="tag t3">앞으로 할 일</span>{esc(todo)}</div></div>')


def names(xs: list[str]) -> str:
    return " · ".join(xs) if xs else "없음"


class Plan:
    def __init__(self, rep: "Report") -> None:
        self.r = rep
        self.d = rep.d
        self.R = rep.real
        self.P = [t for t in rep.paper if not odd_fill(t)]
        self.V = [t for t in rep.virt if not odd_fill(t)]
        self.odd = [t for t in rep.paper + rep.virt if odd_fill(t)]
        self._a()
        self._b()
        self._c()
        self._d()

    # A. 실전과 모의 ------------------------------------------------------
    def _a(self) -> None:
        by = lambda ts: {k: [t for t in ts if base_kind(t.kind) == k] for k in {base_kind(t.kind) for t in ts}}
        self.kR, self.kP, self.kV = by(self.R), by(self.P), by(self.V)
        self.kP_raw = by(self.r.paper)
        others = [t for t in self.r.paper + self.r.virt if t.sub != "가상 장부"]
        self.pairs = []
        for t in sorted(self.R, key=lambda t: t.buy_ts or datetime.min):
            for p in others:
                if p.code == t.code and p.buy_date == t.buy_date:
                    self.pairs.append((t, p))
        same = [(a, b) for a, b in self.pairs if base_kind(a.kind) == base_kind(b.kind) and not odd_fill(b)]
        self.same_pairs = same
        gaps = [gross(b.buy_price, a.buy_price) for a, b in same if a.buy_price and b.buy_price]
        self.buy_gap = sum(gaps) / len(gaps) if gaps else None
        self.buy_gap_max = max((abs(g) for g in gaps), default=None)
        se = [(a, b) for a, b in same if sell_cat(a.reason) == sell_cat(b.reason)]
        de = [(a, b) for a, b in same if sell_cat(a.reason) != sell_cat(b.reason)]
        diff = lambda xs: (sum(gross(a.buy_price, a.sell_price) - gross(b.buy_price, b.sell_price) for a, b in xs) / len(xs)) if xs else None
        self.same_exit, self.diff_exit = se, de
        self.same_exit_diff, self.diff_exit_diff = diff(se), diff(de)

    def sec_a(self) -> str:
        rows, c1 = [], []
        for k in sorted(self.kR, key=lambda k: -len(self.kR[k])):
            sr = kst(self.kR[k])
            sp = kst(self.kP[k]) if k in self.kP else None
            sv = kst(self.kV[k]) if k in self.kV else None
            gap = (sr["ret"] - sp["ret"]) if (sp and sr["ret"] is not None and sp["ret"] is not None) else None
            note = ""
            raw = self.kP_raw.get(k, [])
            if len(raw) != (len(self.kP.get(k, []))):
                note = f" (이상 체결 빼기 전 {pct(kst(raw)['ret'], 2)})"
            rows.append([k, f"{sr['n']}", pct(sr["ret"], 2), f"{sp['n']}" if sp else "0", (pct(sp["ret"], 2) + note) if sp else "기록 없음",
                         f"{sv['n']}" if sv else "0", pct(sv["ret"], 2) if sv else "기록 없음", pct(gap, 2) if gap is not None else "—"])
            c1.append(gap * 1e4 if gap is not None else None)
        t1 = table(["매매", "실전 건수", "실전 건당", "모의 건수", "모의 건당", "가상 건수", "가상 건당", "실전 − 모의"], rows,
                   num_cols=(1, 2, 3, 5, 6, 7), cls_cols={7: c1})
        prs, cc = [], []
        for a, b in self.pairs:
            ga, gb = gross(a.buy_price, a.sell_price), gross(b.buy_price, b.sell_price)
            tag = "" if base_kind(a.kind) == base_kind(b.kind) else " (다른 매매)"
            if odd_fill(b):
                tag += " (이상 체결)"
            mins = ((a.buy_ts - b.buy_ts).total_seconds() / 60) if (a.buy_ts and b.buy_ts) else None
            dd = (ga - gb) if (ga is not None and gb is not None) else None
            prs.append([f"{a.buy_date:%m-%d}", a.name, ("raw", f"{esc(a.kind)}<br>{esc(b.kind + (' · ' + b.sub if b.sub != '모의' else '') + tag)}"),
                        ("raw", f"{px(a.buy_price)} / {px(b.buy_price)}<br>{esc(pct(gross(b.buy_price, a.buy_price), 2))} · {'—' if mins is None else f'{mins:+.0f}분'}"),
                        f"{px(a.sell_price)} / {px(b.sell_price)}",
                        ("raw", f"{esc(pct(ga, 2))} / {esc(pct(gb, 2) if gb is not None else '아직 보유')}<br><span class='{cls(dd * 1e4 if dd is not None else None)}'>{esc(pct(dd, 2))}</span>"),
                        ("raw", f"{esc(sell_cat(a.reason))}<br>{esc(sell_cat(b.reason) if b.closed else '—')}")])
        t2 = table(["산 날", "종목", "매매 (위 🔴 실전 · 아래 🟢 모의·🟣 가상)", "산 값 실전 / 모의 (차이 · 산 시각 차이)", "판 값 실전 / 모의",
                    "손익률 실전 / 모의 (차이)", "매도 사유 (위 실전 · 아래 모의)"], prs, num_cols=(3, 4, 5), tcls="pairs")
        odd = "".join(f"{t.name} {t.kind} {t.buy_date:%m-%d} 산 값 {px(t.buy_price)} → 판 값 {px(t.sell_price)} ({pct(t.ret)})" for t in self.odd)
        se, de = self.same_exit, self.diff_exit
        k5 = "5️⃣ 약세장 인버스"
        p5 = kst(self.kP.get(k5, [])) if k5 in self.kP else None
        p5raw = kst(self.kP_raw.get(k5, [])) if k5 in self.kP_raw else None
        r5 = kst(self.kR[k5]) if k5 in self.kR else None
        txt5 = ""
        if p5 and p5raw and r5:
            txt5 = (f"{k5}는 모의 건당 {pct(p5raw['ret'], 2)} 로 보였지만 이상 체결 1건을 빼면 {p5['n']}건 {pct(p5['ret'], 2)} 로 실전({r5['n']}건 {pct(r5['ret'], 2)})과 같은 쪽(손실)임. ")
        no_paper = [k for k in self.kR if k not in self.kP]
        prob = (f"{txt5}실전과 모의가 같은 날 같은 종목을 같은 매매로 산 {len(self.same_pairs)}건에서 산 값 차이는 평균 {pct(self.buy_gap, 2)} (가장 클 때 {pct(self.buy_gap_max, 2)}) 로 작음. "
                f"손익률 차이는 매도 사유가 같은 {len(se)}건은 평균 {pct(self.same_exit_diff, 2)}, 매도 사유가 다른 {len(de)}건은 평균 {pct(self.diff_exit_diff, 2)} 임. "
                f"실전에서 산 매매 중 {names(no_paper)}는 모의 계좌 기록이 하나도 없어 실전과 견줄 수 없음.")
        return f"""
<h3>A. 실전과 모의의 차이</h3>
<p class="muted">손익률은 같은 매매 이름으로 묶은 건당 평균임 (실전은 비용 뺀 값, 모의는 0.25% 뺀 값). 아래 짝 표의 손익률은 두 쪽을 똑같이 비용 빼기 전 값(판 값 ÷ 산 값 − 1)으로 견줌.</p>
{t1}
<p class="muted">체결 기록 이상: {esc(odd or '없음')} — 1배 인버스 ETF 가 하룻밤에 ±{ETF_MOVE_LIMIT:.0%} 넘게 움직인 기록이라 이 절의 평균·판정에서 뺌.</p>
<h3>같은 날 같은 종목을 실전·모의 둘 다 산 건</h3>{t2}
{card("A. 실전과 모의가 갈리는 곳", prob,
      "체결 값은 거의 같으니 실전·모의 결과 차이는 '언제 팔았나' 와 '모의에서 아예 못 산 매매' 에서 생김. 매도 규칙을 실전·모의에 똑같이 맞추고, 실전 매매는 모의에도 반드시 기록이 남게 해야 함.",
      "매주 금요일 이 표를 다시 봄. 매도 사유가 다른 짝이 나오면 그 주에 어느 쪽 규칙이 바뀌었는지 확인함. 실전 매매 중 모의 기록이 없는 매매는 아래 '앞으로 할 일 3' 의 매매별 가상 계좌로 먼저 기록을 쌓음.")}"""

    # B. 실전 손익 구조 ---------------------------------------------------
    def _b(self) -> None:
        R = sorted(self.R, key=lambda t: t.sell_ts)
        self.Rs = R
        self.wins = [t for t in R if t.pnl > 0]
        self.losses = [t for t in R if t.pnl <= 0]
        run = mx = 0
        mx_end = None
        for t in R:
            run = run + 1 if t.pnl <= 0 else 0
            if run > mx:
                mx, mx_end = run, t.sell_ts
        self.max_streak, self.max_streak_end, self.cur_streak = mx, mx_end, run
        self.cur_streak_sum = sum(t.pnl for t in R[len(R) - run:]) if run else 0.0
        self.cur_streak_from = R[len(R) - run].sell_ts if run else None
        wk = defaultdict(list)
        for t in R:
            wk[t.sell_ts.date() - timedelta(days=t.sell_ts.weekday())].append(t)
        self.weeks = sorted(wk.items())
        # 기준에 처음 닿은 때와 그 뒤 실전 손익 (기록 그대로)
        self.trig = {}
        for n in (3, 5):
            run = 0
            for i, t in enumerate(R):
                run = run + 1 if t.pnl <= 0 else 0
                if run >= n:
                    after = R[i + 1:]
                    self.trig[f"{n}연패"] = (t.sell_ts, len(after), sum(x.pnl for x in after))
                    break
        for lim in (0.03, 0.05):
            hit = None
            for mon, ts in self.weeks:
                cum = 0.0
                for i, t in enumerate(ts):
                    cum += t.pnl
                    if cum <= -lim * REAL_SEED:
                        hit = (t.sell_ts, ts[i + 1:])
                        break
                if hit:
                    break
            if hit:
                self.trig[f"주간 −{lim:.0%}"] = (hit[0], len(hit[1]), sum(x.pnl for x in hit[1]))

    def sec_b(self) -> str:
        W, L = self.wins, self.losses
        sw, sl = kst(W), kst(L)
        aw = sum(t.pnl for t in W) / len(W) if W else None
        al = sum(t.pnl for t in L) / len(L) if L else None
        rw = sum(t.ret for t in W) / len(W) if W else None
        rl = sum(t.ret for t in L) / len(L) if L else None
        t0 = table(["구분", "건수", "합계", "건당 평균 (원)", "건당 평균 (손익률)"],
                   [["이긴 매매", f"{len(W)}", won(sum(t.pnl for t in W)), won(aw), pct(rw, 2)],
                    ["진 매매", f"{len(L)}", won(sum(t.pnl for t in L)), won(al), pct(rl, 2)]],
                   num_cols=(1, 2, 3, 4), cls_cols={2: [sw["sum"], sl["sum"]]})
        rc = by_key(L, lambda t: sell_cat(t.reason))
        rc.sort(key=lambda kv: kv[1]["sum"])
        t1 = table(["진 매매의 매도 사유", "건수", "손실 합계", "건당 평균"], [[k, f"{v['n']}", won(v["sum"]), won(v["avg"])] for k, v in rc],
                   num_cols=(1, 2, 3), cls_cols={2: [v["sum"] for _, v in rc]})
        hold = []
        for h in HOLD_ORDER:
            w = [t for t in W if hold_cat(t) == h]
            l = [t for t in L if hold_cat(t) == h]
            if w or l:
                hold.append([h, f"{len(w)}", f"{len(l)}", won(sum(t.pnl for t in w + l))])
        t2 = table(["보유 시간", "이긴 건수", "진 건수", "합계"], hold, num_cols=(1, 2, 3))
        direct = [t for t in self.Rs if sell_cat(t.reason) == "직접 매도 (사용자)"]
        auto = [t for t in self.Rs if sell_cat(t.reason) != "직접 매도 (사용자)"]
        sd, sa = kst(direct), kst(auto)
        t3 = table(["누가 팔았나", "건수", "이김 / 짐", "합계", "건당 손익률"],
                   [["사용자가 직접 판 것", f"{sd['n']}", f"{sd['w']} / {sd['l']}", won(sd["sum"]), pct(sd["ret"], 2)],
                    ["규칙대로 자동으로 판 것", f"{sa['n']}", f"{sa['w']} / {sa['l']}", won(sa["sum"]), pct(sa["ret"], 2)]],
                   num_cols=(1, 2, 3, 4), cls_cols={3: [sd["sum"], sa["sum"]]})
        wrows = [[f"{m:%m-%d} 주", f"{len(ts)}", f"{sum(1 for t in ts if t.pnl > 0)}", won(sum(t.pnl for t in ts)), pct(sum(t.pnl for t in ts) / REAL_SEED)]
                 for m, ts in self.weeks]
        t4 = table(["주 (월요일)", "건수", "이긴 건수", "합계", f"시드 {REAL_SEED / 1e4:,.0f}만 원 대비"], wrows, num_cols=(1, 2, 3, 4),
                   cls_cols={3: [sum(t.pnl for t in ts) for _, ts in self.weeks]})
        top_loss = rc[0] if rc else None
        auto_loss = [t for t in L if sell_cat(t.reason) != "직접 매도 (사용자)"]
        prob = (f"실전 {len(self.Rs)}건 중 {len(W)}건만 이김. 이긴 건 평균 {won(aw)} 인데 진 건 평균 {won(al)} 이라 손익비 {num((aw / -al) if (aw and al) else None)} 임. "
                + (f"진 매매 중 가장 큰 손실 사유는 '{top_loss[0]}' {top_loss[1]['n']}건 {won(top_loss[1]['sum'])}. " if top_loss else "")
                + f"가장 길게 이어진 연속 손실은 {self.max_streak}건, 지금도 {self.cur_streak}연패 중 ({self.cur_streak_from:%m-%d} 부터 {won(self.cur_streak_sum)}). "
                + f"사용자가 직접 판 {sd['n']}건은 합계 {won(sd['sum'])}, 자동으로 판 {sa['n']}건은 {won(sa['sum'])}.")
        return f"""
<h3>B. 실전 손익 구조</h3>
<p class="muted">손익은 비용을 뺀 값. 판 시각 순서로 셈.</p>
{t0}
<h3>진 매매는 어떻게 팔렸나</h3>{t1}
<h3>보유 시간별 이김·짐</h3>{t2}
<h3>사용자가 직접 판 것 vs 자동으로 판 것</h3>{t3}
<h3>주별 실전 손익</h3>{t4}
{card("B. 실전은 지는 횟수도 많고, 한 번 질 때 잃는 돈도 큼", prob,
      "실전에서 손실이 이어질 때 자동으로 새 매수를 멈추는 장치가 필요함. 사용자가 직접 판 매매가 자동 매도보다 결과가 나았던 까닭(언제·왜 팔았는지)을 매매일지에 남겨 규칙으로 옮길 수 있는지 봄.",
      "아래 '앞으로 할 일 2' 의 연속 손실 멈춤 숫자를 사용자가 고르면 바로 넣음. 직접 판 매매는 매번 일지 복기 칸에 '규칙대로였으면 얼마' 를 적음 (이미 있는 기능). 손실 사유는 '앞으로 할 일 7' 로 매일 한 줄씩 쌓음.")}"""

    # C. 모의 계좌 자금·자리 부족 -----------------------------------------
    def _c(self) -> None:
        held = defaultdict(list)    # code → [(kind, buy_ts, sell_ts)] 모의 계좌가 실제로 산 것
        for kind, status, note, virt, ovf, code, sts, bts, xts, d in self.d.signal_rows:
            if bts is not None and not virt and not ovf:
                held[code].append((kind, bts, xts))
        agg = defaultdict(lambda: defaultdict(int))
        cash_days = set()
        for kind, status, note, virt, ovf, code, sts, bts, xts, d in self.d.signal_rows:
            k = base_kind(J.label(kind))
            a = agg[k]
            a["signals"] += 1
            if ovf:
                a["overflow"] += 1
                if "주문 가능 금액 부족" in note:
                    a["ovf_cash"] += 1
                    cash_days.add(d)
                continue
            if bts is not None:
                a["bought" if not virt else "nxt"] += 1
                continue
            if status != "skipped":
                continue
            if note.startswith("주문 가능 금액 부족"):
                a["cash"] += 1
                cash_days.add(d)
            elif re.search(r"최대 \d+종목 보유 중|동시 \d+종목 보유 중", note):
                a["slots"] += 1
            elif note.startswith("이미 보유 중"):
                other = any(h[0] != kind and h[1] <= (sts or h[1]) and (h[2] is None or h[2] > (sts or h[1])) for h in held.get(code, []))
                a["other" if other else "same"] += 1
            else:
                a["rule"] += 1
        self.cagg = agg
        self.cash_days = cash_days
        self.c_tot = {x: sum(a[x] for a in agg.values()) for x in ("cash", "slots", "overflow", "other", "bought", "signals", "ovf_cash")}

    def sec_c(self) -> str:
        rows, rv = [], []
        for k, a in self.cagg.items():
            blocked = a["cash"] + a["slots"] + a["overflow"] + a["other"]
            if not blocked:
                continue
            base = a["bought"] + a["nxt"] + blocked
            rows.append((blocked / base if base else 0, [k + (" (이미 멈춤)" if k in PAPER_STOPPED else ""), f"{a['signals']}", f"{a['bought']}", f"{a['nxt']}",
                                                          f"{a['overflow']}", f"{a['cash']}", f"{a['slots']}", f"{a['other']}", f"{blocked / base:.0%}" if base else "—"]))
        rows.sort(key=lambda x: -x[0])
        t = table(["매매", "신호 전체", "모의 계좌로 삼", "NXT 가상 체결", "잔고 밖 가상", "주문 가능 금액 부족", "보유 한도 (최대 N종목)", "다른 매매가 같은 종목 보유",
                   "못 산 비율"], [r for _, r in rows], num_cols=(1, 2, 3, 4, 5, 6, 7, 8), tcls="wide ctab")
        self.c_worst = [r[1][0] for r in rows if r[0] >= 0.5 and not r[1][0].endswith("(이미 멈춤)")]
        ct = self.c_tot
        k6 = "6️⃣ 주도주 신고가"
        a6 = self.cagg.get(k6, {})
        p6 = (f"{k6}는 실전에서 산 매매인데 모의 신호 {a6.get('signals', 0)}건 중 {a6.get('other', 0)}건이 다른 매매가 같은 종목을 먼저 사서 막혔고, 모의 기록이 0건임. "
              if a6 and not a6.get("bought") else "")
        prob = (f"모의 계좌 하나({PAPER_START / 1e4:,.0f}만 원)를 여러 매매가 같이 써서, 돈이나 자리가 없어 못 산 신호가 "
                f"주문 가능 금액 부족 {ct['cash']}건 · 보유 한도 {ct['slots']}건 · 다른 매매가 같은 종목을 먼저 산 것 {ct['other']}건 · 잔고 밖 가상으로 돌린 것 {ct['overflow']}건임 "
                f"(같은 기간 모의 계좌가 실제로 산 것은 {ct['bought']}건). 주문 가능 금액이 모자란 날은 {len(self.cash_days)}일. {p6}"
                f"아직 켜진 매매 중 절반 넘게 못 산 매매: {names(self.c_worst)}.")
        return f"""
<h3>C. 모의 계좌 하나를 나눠 써서 생긴 왜곡</h3>
<p class="muted">paper_trades 의 신호 기록(건너뜀 포함)에서 셈. '다른 매매가 같은 종목 보유' 는 '이미 보유 중' 으로 건너뛴 신호 중 그 시각 모의 계좌가 다른 매매로 같은 종목을 들고 있던 것. 잔고 밖 가상은 못 산 신호를 계좌 밖에서 가상으로 적은 것(10-29 부터). 비율 = (못 산 신호) ÷ (모의 계좌로 산 것 + NXT 가상 체결 + 못 산 신호). 시장 분위기·엄격 선정처럼 규칙으로 안 산 신호는 셈에서 뺌.</p>
{t}
{card("C. 어떤 매매는 모의로 제대로 재지 못함", prob,
      "매매마다 따로 가상 계좌를 두어 돈·자리 다툼 없이 모든 신호를 같은 크기로 기록해야 매매끼리 공정하게 견줄 수 있음.",
      "'앞으로 할 일 3' 대로 매매별 가상 계좌(예: 각 100만 원)를 만들고, 모의 계좌는 지금처럼 실주문 체결 확인용으로 둠. 넣은 뒤 첫 금요일 보고서부터 이 표의 '못 산 비율' 이 0% 가 되는지 확인함.")}"""

    # D. 매매별 판정 ------------------------------------------------------
    def _d(self) -> None:
        kinds = []
        for g in (self.kR, self.kP, self.kV):
            for k in g:
                if k not in kinds:
                    kinds.append(k)
        out = []
        for k in kinds:
            sr = kst(self.kR[k]) if k in self.kR else None
            sp = kst(self.kP[k]) if k in self.kP else None
            sv = kst(self.kV[k]) if k in self.kV else None
            n = (sp["n"] if sp else 0) + (sv["n"] if sv else 0)
            have = [s for s in (sp, sv) if s and s["n"]]
            if k in PAPER_STOPPED:
                v = "이미 멈춤"
            elif n < MIN_N:
                v = "지켜봄"
            elif all((s["ret"] or 0) > 0 and (s["pf"] is None or s["pf"] > 1) for s in have):
                v = "유지"
            elif all((s["ret"] or 0) < 0 for s in have):
                v = "멈춤 검토"
            else:
                v = "지켜봄"
            why = ("" if v != "지켜봄" else (f"모의+가상 {n}건 (<{MIN_N})" if n < MIN_N else "모의·가상 결과가 엇갈림"))
            if v == "이미 멈춤":
                why = PAPER_STOPPED[k]
            state = ("실전 켜짐" if k in REAL_ON_LABELS else "실전 뺌 · 모의만" if k in REAL_OFF_LABELS else "모의·가상만") if k not in PAPER_STOPPED else "모의 매수 꺼짐"
            out.append((k, state, sr, sp, sv, n, v, why))
        order = {"유지": 0, "지켜봄": 1, "멈춤 검토": 2, "이미 멈춤": 3}
        out.sort(key=lambda x: (order[x[6]], -x[5]))
        self.dres = out
        self.groups = {g: [x[0] for x in out if x[6] == g] for g in order}

    def sec_d(self) -> str:
        def cell(s):
            if not s or not s["n"]:
                return ("raw", '<span class="muted">—</span>')
            return ("raw", f"{s['n']}건 · 건당 <span class='{cls(s['ret'] * 1e4 if s['ret'] is not None else None)}'>{esc(pct(s['ret'], 2))}</span><br>"
                           f"<span class='{cls(s['sum'])}'>{esc(won(s['sum']))}</span> · PF {esc(num(s['pf']))}")
        rows = [[k, st, cell(sr), cell(sp), cell(sv), ("raw", f"<b>{esc(v)}</b>" + (f"<br><span class='muted'>{esc(why)}</span>" if why else ""))]
                for k, st, sr, sp, sv, n, v, why in self.dres]
        t = table(["매매", "지금 상태", "🔴 실전", "🟢 모의", "🟣 가상", "판정"], rows, tcls="verdict")
        G = self.groups
        prob = (f"모의·가상 기록 기준으로 유지 {len(G['유지'])}개 · 지켜봄 {len(G['지켜봄'])}개 · 멈춤 검토 {len(G['멈춤 검토'])}개 · 이미 멈춤 {len(G['이미 멈춤'])}개. "
                f"지금 실전에 켜진 매매({names(REAL_ON_LABELS)}) 가운데 '유지' 에 든 것: {names([k for k in REAL_ON_LABELS if k in G['유지']])}.")
        return f"""
<h3>D. 매매별 판정표</h3>
<p class="muted">판정 기준 (모의·가상 기록만 봄, 실전은 건수가 적어 참고): 유지 = 모의·가상 중 기록 있는 쪽이 모두 건당 + 이고 PF 1 넘음, 끝난 건수 {MIN_N}건 이상 ·
지켜봄 = {MIN_N}건 미만이거나 모의·가상 결과가 엇갈림 · 멈춤 검토 = 기록 있는 쪽이 모두 건당 − 이고 {MIN_N}건 이상 · 이미 멈춤 = 코드에서 모의 매수가 이미 꺼진 매매(다시 제안 안 함).
같은 매매의 장부는 하나로 묶음 (☕ 가상 장부, 📕 수급 확인·수급 없이). 이상 체결 기록은 뺌.</p>
{t}
<div class="note"><b>묶음별 목록</b>
<div>유지: {esc(names(G['유지']))}</div>
<div>지켜봄: {esc(names(G['지켜봄']))}</div>
<div>멈춤 검토: {esc(names(G['멈춤 검토']))}</div>
<div>이미 멈춤: {esc(names(G['이미 멈춤']))}</div></div>
{card("D. 실전에 켜진 매매 대부분이 모의·가상에서 아직 + 로 확인되지 않음", prob,
      "실전 돈은 모의·가상에서 + 가 충분히 쌓인 매매에만 쓰고, 나머지는 모의·가상에서 기록을 더 쌓는 쪽이 기록과 맞음.",
      f"이 판정표를 매주 금요일 다시 만들고, 묶음이 바뀐 매매만 사용자에게 알림. 멈춤 검토 매매({names(G['멈춤 검토'])}) 는 사용자가 정하면 모의 매수를 끔.")}"""

    # E. 조건 있음 / 없음 --------------------------------------------------
    def sec_e(self) -> str:
        rows, vals = [], []

        def add(group: str, label: str, ts: list[Trade]):
            s = kst(ts)
            rows.append([group, label, f"{s['n']}", rate(s["win"]), pct(s["ret"], 2), won(s["sum"]), num(s["pf"])])
            vals.append(s["sum"] if s["n"] else None)

        V = self.r.virt
        hk = [t for t in V if t.kind == J.BOOK_LABEL["수급 확인"]]
        hn = [t for t in V if t.kind == J.BOOK_LABEL["수급 없이"]]
        hr = self.kR.get("📕 홍인기 상한가 풀림", [])
        add("📕 홍인기 상한가 풀림", "수급 확인 (기관 가집계·프로그램 둘 다 순매수일 때만) · 가상 장부", hk)
        add("📕 홍인기 상한가 풀림", "수급 없이 (실전이 따라 사는 장부) · 가상 장부", hn)
        add("📕 홍인기 상한가 풀림", "실전 (수급 없이 장부와 같은 신호)", hr)
        up = self.kP.get("1️⃣ 상승장 장 초", [])
        add("1️⃣ 상승장 장 초", f"모의 · 산 값 {UP_REAL_PRICE:,}원 이하 (실전 계좌가 살 수 있는 값)", [t for t in up if t.buy_price <= UP_REAL_PRICE])
        add("1️⃣ 상승장 장 초", f"모의 · 산 값 {UP_REAL_PRICE:,}원 넘음", [t for t in up if t.buy_price > UP_REAL_PRICE])
        add("1️⃣ 상승장 장 초", "실전", self.kR.get("1️⃣ 상승장 장 초", []))
        vw = [(a, b) for a, b in self.same_pairs if sell_cat(a.reason) == "VWAP 이탈"]
        for a, b in vw:
            rows.append(["VWAP 이탈 매도", f"{a.buy_date:%m-%d} {a.name} {a.kind}: 실전 VWAP 이탈 매도 vs 모의 원래 규칙 ({sell_cat(b.reason)})", "1",
                         "—", f"{pct(gross(a.buy_price, a.sell_price), 2)} / {pct(gross(b.buy_price, b.sell_price), 2)}", "—", "—"])
            vals.append(None)
        # 같은 매매가 시장 분위기에 따라 갈리는 것 (분위기마다 3건 이상)
        self.reg_rows = []
        for k, ts in sorted(self.kP.items(), key=lambda kv: -len(kv[1])):
            if k in PAPER_STOPPED:
                continue
            byr = defaultdict(list)
            for t in ts:
                if not t.regime.startswith("기록 없음"):
                    byr[t.regime].append(t)
            ok = {r: x for r, x in byr.items() if len(x) >= 3}
            if len(ok) >= 2:
                for r, x in sorted(ok.items(), key=lambda kv: -len(kv[1])):
                    add(k + " (시장 분위기)", f"모의 · 산 날 {r}", x)
                    self.reg_rows.append(f"{k} {r} {len(x)}건 {pct(kst(x)['ret'], 2)}")
        t = table(["매매", "조건", "건수", "승률", "건당 손익률", "합계", "PF"], rows, num_cols=(2, 3, 4, 5, 6), cls_cols={5: vals})
        shk, shn = kst(hk), kst(hn)
        sup_l = kst([t for t in up if t.buy_price <= UP_REAL_PRICE])
        sup_h = kst([t for t in up if t.buy_price > UP_REAL_PRICE])
        prob = (f"📕 홍인기 상한가 풀림은 실전이 따라 사는 '수급 없이' 장부가 {shn['n']}건 건당 {pct(shn['ret'], 2)} · 합계 {won(shn['sum'])} 이고, '수급 확인' 장부는 {shk['n']}건 {pct(shk['ret'], 2)} 뿐이라 아직 비교가 안 됨. "
                f"1️⃣ 상승장 장 초의 모의 + 는 산 값 {UP_REAL_PRICE / 1e4:,.1f}만 원 넘는 종목({sup_h['n']}건 {pct(sup_h['ret'], 2)}) 에서 나왔고, 실전 계좌가 살 수 있는 값의 종목은 {sup_l['n']}건 {pct(sup_l['ret'], 2)} 임. "
                + (f"같은 매매가 시장 분위기에 따라 갈린 것 (분위기마다 3건 이상, 판정 기록 있는 날만): {' · '.join(self.reg_rows)}. " if self.reg_rows else "")
                + "조건 때문에 건너뛴 신호(예: 🎯 주도주 모양 '전날 외인·기관 둘 다 순매수 아님', 1️⃣ '전날 외인·기관 둘 다 순매도')는 결과 기록이 없어 조건 효과를 셀 수 없음.")
        return f"""
<h3>E. 같은 매매의 조건 있음 / 없음</h3>
<p class="muted">기록에 두 갈래가 함께 남아 있는 것만 견줌. 손익률은 건당 평균, 짝 비교 줄은 '실전 / 모의' 비용 빼기 전 손익률.</p>
{t}
{card("E. 조건 효과는 아직 건수가 모자라거나, 실전 금액 크기와 엮여 있음", prob,
      f"📕 는 실전이 '수급 확인' 장부를 따르게 바꿀지 판단하려면 수급 확인 장부 건수가 더 필요함. 1️⃣ 는 실전 시드로 살 수 있는 값의 종목만 따로 계속 셈. 시장 분위기로 갈리는 매매는 지금 매수하는 분위기가 맞는지 기록으로 계속 확인함.",
      "📕 수급 확인 장부가 20건 쌓이는 금요일에 이 표로 다시 견줌. 1️⃣ 는 시드를 늘릴 때(앞으로 할 일 6) '살 수 있는 값' 이 바뀌므로 그때 이 줄을 기준으로 다시 봄.")}"""

    # 앞으로 할 일 --------------------------------------------------------
    def sec_todo(self) -> str:
        G = self.groups
        keep = G["유지"]
        move = [k for k in REAL_ON_LABELS if k not in keep]
        tr = self.trig

        def trig_txt(key):
            if key not in tr:
                return f"{key}: 기록에서 한 번도 닿지 않음"
            ts, n, s = tr[key]
            if key.startswith("주간"):
                return f"{key}: {ts:%m-%d %H:%M} 에 처음 닿았고 그 주에 그 뒤로 난 실전 {n}건 합계 {won(s)}"
            return f"{key}: {ts:%m-%d %H:%M} 에 처음 닿았고 그 뒤 지금까지 실전 {n}건 합계 {won(s)}"
        losses_by = by_key(self.losses, lambda t: sell_cat(t.reason))
        lose_txt = " · ".join(f"{k} {v['n']}건" for k, v in sorted(losses_by, key=lambda kv: -kv[1]["n"]))
        ct = self.c_tot
        # 시드 증액 조건: 최근 4주(월~금) 매주 PF 1.2 이상 & 4주 합계 30건 이상인 매매 (모의 또는 가상)
        last_mon = self.r.last - timedelta(days=self.r.last.weekday())
        mons = [last_mon - timedelta(weeks=i) for i in range(3, -1, -1)]
        ok_seed = []
        for k in set(self.kP) | set(self.kV):
            for g in (self.kP, self.kV):
                ts = g.get(k, [])
                wk = [[t for t in ts if t.sell_ts.date() - timedelta(days=t.sell_ts.weekday()) == m] for m in mons]
                if sum(len(w) for w in wk) >= 30 and all(w and (stats([t.pnl for t in w])["pf"] or 0) >= 1.2 for w in wk):
                    ok_seed.append(k)
        items = [
            ("실전 범위 정리", f"D 판정표 기준 '유지' 묶음: {names(keep)}. 지금 실전에 켜진 매매 {len(REAL_ON_LABELS)}개 중 '유지' 가 아닌 것: {names(move)}.",
             "지금 있는 기능: 매매별 실전 켜고 끄기(real.REAL_OFF). 새로 필요: 없음 (목록만 고치면 됨).",
             f"선택지 — 가) 실전은 '유지' 매매만 남기고 {names(move)} 는 모의로만 · 나) 지금 그대로 두고 매주 판정만 봄 · 다) 일부만 뺌. "
             + ("참고: '유지' 의 1️⃣ 상승장 장 초는 모의 + 가 실전 시드로는 못 사는 값의 종목에서 나왔음(E). " if "1️⃣ 상승장 장 초" in keep else "")
             + "결정은 사용자 몫임."),
            ("실전 연속 손실 자동 멈춤", f"최대 {self.max_streak}연패, 지금 {self.cur_streak}연패 ({won(self.cur_streak_sum)}). " + " · ".join(trig_txt(k) for k in ("3연패", "5연패", "주간 −3%", "주간 −5%")) + ".",
             "지금 있는 기능: 텔레그램 '실전 쉼'(그날 새 매수만 멈춤)·'멈춰'(스캐너 끔) — 사람이 보내야 함. 새로 필요: 기준에 닿으면 자동으로 실전 새 매수를 멈추고 텔레그램으로 알리는 장치 (손절·다음 날 매도는 그대로).",
             f"선택지 — 가) 5연패 · 나) 주간 −3% (시드 {REAL_SEED:,.0f}원이면 −{REAL_SEED * 0.03:,.0f}원) · 다) 둘 중 먼저 닿는 것 · 라) 3연패. 다시 켜는 방법도 함께 고름 (다음 주 월요일 자동 / 사용자 '실전 재개')."),
            ("모의 측정을 매매별 가상 계좌로", f"주문 가능 금액 부족 {ct['cash']}건 · 보유 한도 {ct['slots']}건 · 다른 매매가 같은 종목 보유 {ct['other']}건 · 잔고 밖 가상 {ct['overflow']}건 (C). 절반 넘게 못 산 매매: {names(self.c_worst)}.",
             "지금 있는 기능: 잔고 밖 가상(overflow)으로 일부 신호를 계좌 밖에 적음, 🔁·📍·🪜 전용 몫. 새로 필요: 매매마다 따로 시작 금액을 둔 가상 계좌(돈·자리 다툼 없음)와 매매별 계좌 곡선.",
             "선택지 — 가) 매매별 각 100만 원 · 나) 각 1천만 원(모의 계좌와 같은 크기) · 다) 실전과 같은 종목당 3만 원 크기도 함께 적음."),
            ("실전·모의 체결 차이 기록", f"같은 날 같은 종목 같은 매매 짝 {len(self.same_pairs)}건, 산 값 차이 평균 {pct(self.buy_gap, 2)}, 매도 사유가 달랐던 짝 {len(self.diff_exit)}건 (A).",
             "지금 있는 기능: real_trades 에 산 값·판 값·사유만 남음. 새로 필요: 실전 주문마다 신호가·주문가·체결가·주문 때 매수/매도 1호가를 남기고, 매주 금요일 신호가 대비 체결 차이를 표로 봄.",
             "선택지 — 가) 실전만 기록 · 나) 실전·모의 둘 다 기록."),
            ("종목 선정 강화 (하승훈 카페 '핫이슈 테마 체크' 종목 안에서만 삼)", f"실전 {len(self.Rs)}건 중 {len(self.wins)}건만 이김 (승률 {rate(len(self.wins) / len(self.Rs) if self.Rs else None)}).",
             "지금 있는 기능: 카페 목록 글 제목은 로그인 없이 읽힘. 새로 필요: 본문 읽기(네이버 로그인 쿠키 필요)·종목 뽑기·모든 실전·모의 매수에 '카페 목록 안' 조건 붙이기 — 사용자가 쿠키를 넣으면 바로 적용하도록 대기 중.",
             "선택지 — 범위 가) 전날 특징테마 글만 · 나) 특징테마 + 일자별 테마주 정리 둘 다 · 다) 최근 N일 글."),
            ("평가 주기와 시드 증액 기준", f"지금 '최근 4주 매주 PF 1.2 이상 · 4주 합계 30건 이상' 을 채운 매매(모의 또는 가상): {names(sorted(set(ok_seed)))}.",
             "지금 있는 기능: 이 보고서를 손으로 만드는 명령(full_report), 금요일 📓 주간 매매일지. 새로 필요: 매주 금요일 20:30 이 보고서 자동 생성·텔레그램 전송, 시드 증액 조건 자동 점검.",
             "선택지 — 시드 100만 원으로 늘리는 조건 가) 모의 또는 가상 4주 연속 매주 PF 1.2 이상 & 30건 이상 · 나) 같은 조건 + 실전도 2주 연속 + · 다) 6주 연속 PF 1.1 이상 & 50건 이상."),
            ("매매일지에 실전 손실 원인 한 줄", f"실전 진 매매 {len(self.losses)}건의 매도 사유: {lose_txt}.",
             "지금 있는 기능: 📓 매일 매매일지와 복기 칸(손절·직접 매도·손절선 1% 안 접근·놓친 +5%·연속 손실 표시). 새로 필요: 그날 실전 손실 건마다 원인 한 줄(신호가 약했나·늦게 샀나·체결 차이·시장 분위기·매도 규칙) 자동 기록과 주간 묶음 집계.",
             "선택지 — 가) 자동 분류만 · 나) 자동 분류 + 사용자가 텔레그램으로 한 줄 덧붙이기."),
        ]
        lis = "".join(f'<div class="todo"><b>{i}. {esc(t)}</b><div><span class="tag t1">기록 근거</span>{esc(a)}</div><div><span class="tag t2">있는 것 · 새로 필요</span>{esc(b)}</div>'
                      f'<div><span class="tag t3">고를 것</span>{esc(c)}</div></div>' for i, (t, a, b, c) in enumerate(items, 1))
        return f"""
<h3>앞으로 할 일 (번호로 골라 주면 그대로 진행함)</h3>
<p class="muted">각 항목은 위 A~E 의 기록 숫자를 근거로 함. 바꿀지·어떤 숫자로 할지는 사용자가 정함.</p>
{lis}"""

    def html(self) -> str:
        G = self.groups
        ct = self.c_tot
        k5 = "5️⃣ 약세장 인버스"
        p5 = kst(self.kP.get(k5, [])) if k5 in self.kP else None
        top = [f"🔴 실전은 {len(self.Rs)}건 중 {len(self.wins)}건 이김, 합계 {won(sum(t.pnl for t in self.Rs))} (시드 대비 {sum(t.pnl for t in self.Rs) / REAL_SEED:+.1%}), 지금 {self.cur_streak}연패 중.",
               f"실전과 모의가 같은 매매로 같은 종목을 산 {len(self.same_pairs)}건에서 산 값 차이는 평균 {pct(self.buy_gap, 2)} 로 작음. 결과 차이는 언제 팔았나에서 생김."
               + (f" {k5}의 모의 + 는 이상 체결 1건 때문이었고 빼면 {pct(p5['ret'], 2)}." if (p5 and self.odd) else ""),
               f"모의 계좌를 여러 매매가 나눠 써서 돈·자리 때문에 못 산 신호가 {ct['cash'] + ct['slots'] + ct['other'] + ct['overflow']}건임 (모의 계좌로 산 것 {ct['bought']}건).",
               f"판정: 유지 {names(G['유지'])} / 멈춤 검토 {names(G['멈춤 검토'])} / 지켜봄 {len(G['지켜봄'])}개 / 이미 멈춤 {len(G['이미 멈춤'])}개."]
        head = ('<p>사용자가 가장 먼저 볼 절임. 모든 숫자는 실제 매매 기록(실전·모의·가상)에서 셈. 각 항목은 <b>기록에서 드러난 문제 → 개선 방향 → 앞으로 할 일</b> 순서로 적음. '
                '무엇을 바꿀지는 사용자가 정하고, 맨 아래 \'앞으로 할 일\' 번호로 고르면 됨.</p>'
                '<div class="note"><b>한눈에 보기</b>' + "".join(f"<div>· {esc(x)}</div>" for x in top) + "</div>")
        return head + self.sec_a() + self.sec_b() + self.sec_c() + self.sec_d() + self.sec_e() + self.sec_todo()


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
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:10px 0 14px;font-size:13.5px}
.card>b{display:block;margin-bottom:4px} .card>div,.todo>div{margin:3px 0}
.tag{display:inline-block;font-size:11px;font-weight:600;border-radius:4px;padding:0 6px;margin-right:6px;white-space:nowrap}
.tag.t1{background:#fee2e2;color:#991b1b} .tag.t2{background:#dbeafe;color:#1e40af} .tag.t3{background:#dcfce7;color:#166534}
table.pairs th,table.verdict th,table.ctab th{white-space:normal} table.ctab td:first-child{white-space:nowrap} table.pairs td.r{white-space:nowrap}
.todo{background:var(--card);border:1px solid var(--line);border-left:4px solid #16a34a;border-radius:8px;padding:8px 12px;margin:8px 0;font-size:13.5px} .todo>b{display:block;margin-bottom:3px}
"""

CSS_SCREEN = CSS_BASE + """
header,section{max-width:1080px;margin:0 auto;padding:14px 16px}
section{background:transparent;border-top:1px solid var(--line);margin-top:8px}
.top{display:flex;align-items:center;justify-content:space-between;gap:8px}
#tg{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;font-size:18px;padding:4px 10px;cursor:pointer}
nav{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px} nav a{font-size:12.5px;color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--card)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:8px}
.scroll table{border:0} td{white-space:nowrap} table.journal td:last-child{white-space:normal;min-width:220px} table.verdict td:last-child{white-space:normal;min-width:200px}
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
.card{font-size:8.4pt;padding:2mm 3mm;margin:2mm 0 3mm} .tag{font-size:7pt} .todo{font-size:8.4pt;padding:2mm 3mm;margin:2mm 0}
table.verdict{font-size:7.4pt}
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
