"""📊 운용 성과 페이지 — 실전·모의 계좌 잔고 그래프, 손익비·승률·최대 낙폭, 매매별 표를 HTML 한 장으로 (2026-11-10 사용자 '1번').

서태준 사이트 /performance 틀을 따름: 잔고 곡선 + 손익비(PF) + 최대 낙폭 + 총 매매 수. 매일 20:00 업데이트가 만들어 텔레그램 파일로 보냄.
    python -m kiwoom_trading.execution.performance_page            # 만들기만 (data/reports/performance.html)
    python -m kiwoom_trading.execution.performance_page --send     # 텔레그램으로 보내기
"""
from __future__ import annotations

import argparse
import html
import os
from collections import defaultdict
from datetime import date

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT

DB = os.path.join(PROJECT_ROOT, "data", "screener.duckdb")
SNAPSHOT = os.path.join(PROJECT_ROOT, "data", "screener_snapshot.duckdb")
OUT = os.path.join(PROJECT_ROOT, "data", "reports", "performance.html")
PAPER_START = 10_000_000
ACCOUNT_TABLE, ACCOUNT_START = "paper_account_trades", 1_000_000   # paper.ACCOUNT_TABLE · ACCOUNT_START (매매별 가상 계좌)


def _connect():
    for path in (DB, SNAPSHOT):     # 장중엔 스캐너가 본 DB 를 잠그므로 사본으로
        try:
            return duckdb.connect(path, read_only=True)
        except Exception:
            continue
    raise RuntimeError("screener DB 를 열 수 없음")


def _stats(pnls: list[float], start: float) -> dict:
    win = sum(x for x in pnls if x > 0)
    loss = -sum(x for x in pnls if x < 0)
    eq = peak = start
    mdd = 0.0
    curve = [start]
    for x in pnls:
        eq += x
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak if peak else 0)
        curve.append(eq)
    return {"n": len(pnls), "sum": sum(pnls), "pf": (win / loss) if loss else None,
            "win": (sum(1 for x in pnls if x > 0) / len(pnls)) if pnls else 0.0, "mdd": mdd, "curve": curve}


def _svg(curve: list[float], labels: list[str]) -> str:
    if len(curve) < 2:
        return '<p class="muted">아직 자료 없음</p>'
    w, h, pad = 720, 220, 36
    lo, hi = min(curve), max(curve)
    span = (hi - lo) or 1
    pts = [(pad + i * (w - 2 * pad) / (len(curve) - 1), h - pad - (v - lo) / span * (h - 2 * pad)) for i, v in enumerate(curve)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    base_y = h - pad - (curve[0] - lo) / span * (h - 2 * pad)
    first, last = (labels[0], labels[-1]) if labels else ("", "")
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="잔고 곡선">'
            f'<line x1="{pad}" x2="{w - pad}" y1="{base_y:.1f}" y2="{base_y:.1f}" class="base"/>'
            f'<polyline points="{line}" class="curve"/>'
            f'<text x="{pad}" y="{h - 8}" class="axis">{html.escape(first)}</text>'
            f'<text x="{w - pad}" y="{h - 8}" class="axis" text-anchor="end">{html.escape(last)}</text>'
            f'<text x="{pad}" y="16" class="axis">{hi:,.0f}원</text>'
            f'<text x="{pad}" y="{h - pad - 4}" class="axis">{lo:,.0f}원</text></svg>')


def _won(x: float) -> str:
    return f"{x:+,.0f}원"


def _kpis(s: dict, start: float) -> str:
    pf = f"{s['pf']:.2f}" if s["pf"] is not None else "손실 없음"
    items = [("누적 손익", _won(s["sum"]) + f" ({s['sum'] / start:+.1%})"), ("손익비 (PF)", pf),
             ("승률", f"{s['win']:.0%}"), ("최대 낙폭 (MDD)", f"−{s['mdd']:.1%}"), ("매매 수", f"{s['n']}건")]
    return '<div class="kpis">' + "".join(f'<div class="kpi"><span>{k}</span><b>{v}</b></div>' for k, v in items) + "</div>"


def _table(rows: list[tuple], head: list[str]) -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    tb = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def _by_kind(items: list[tuple[str, float, float]], name) -> list[tuple]:
    """items = (종류, 손익원, 수익률) → 매매별 행."""
    g = defaultdict(list)
    for k, pnl, r in items:
        g[k].append((pnl, r))
    rows = []
    for k, v in sorted(g.items(), key=lambda kv: -sum(p for p, _ in kv[1])):
        pn = [p for p, _ in v]
        win, loss = sum(p for p in pn if p > 0), -sum(p for p in pn if p < 0)
        rows.append((name(k), len(v), f"{sum(1 for p in pn if p > 0) / len(v):.0%}", f"{sum(r for _, r in v) / len(v):+.2%}",
                     _won(sum(pn)), f"{win / loss:.2f}" if loss else "—"))
    return rows


# 전략 단계표 (2026-11-10 사용자 '1번' — 서태준: 소액 실전으로 확인한 뒤 자본을 늘림, 한 구간에서만 통하면 버림)
# 단계: 가상(주문 없음) → 모의(1천만 모의 계좌) → 실전 소액(종목당 3만 원) → 증액. 올리고 내리는 건 표시만 하고 사용자가 정함.
PROMOTE_N, PROMOTE_PF = 30, 1.2          # 다음 단계로: 그 단계 실제 매매 30건 이상 · 손익비 1.2 이상 · 앞 절반·뒤 절반 합계 둘 다 +
DEMOTE_N, DEMOTE_PF, DEMOTE_MDD = 10, 0.8, 0.15   # 실전에서 내릴 만함: 10건 이상인데 손익비 0.8 미만, 또는 매매별 최대 낙폭 15% 넘음


def _judge(pnls: list[float], start: float) -> tuple[str, str]:
    n = len(pnls)
    if not n:
        return "자료 없음", "0건"
    s = _stats(pnls, start)
    half = n // 2
    a, b = sum(pnls[:half]), sum(pnls[half:])
    pf = f"{s['pf']:.2f}" if s["pf"] is not None else "손실 없음"
    desc = f"{n}건 · 손익비 {pf} · 앞 절반 {_won(a)} / 뒤 절반 {_won(b)}"
    ok = n >= PROMOTE_N and (s["pf"] is None or s["pf"] >= PROMOTE_PF) and a > 0 and b > 0
    return ("⬆ 올릴 기준 충족" if ok else f"유지 ({max(0, PROMOTE_N - n)}건 더 필요)" if n < PROMOTE_N else "유지 (기준 못 미침)"), desc


def _stage_rows(real: list, p_items: list, rname, pname) -> list[tuple]:
    from kiwoom_trading.execution.real import PLAYS, REAL_OFF
    r_by, p_by = defaultdict(list), defaultdict(list)
    for r in real:
        r_by[r[2]].append(r[6])
    for k, pnl, _ in p_items:
        p_by[k].append(pnl)
    rows = []
    for k in list(dict.fromkeys(list(PLAYS) + list(p_by))):
        live = k in PLAYS and k not in REAL_OFF
        if live:
            v = r_by.get(k, [])
            s = _stats(v, 30_000 * max(1, len(v))) if v else None
            demote = bool(v) and len(v) >= DEMOTE_N and ((s["pf"] is not None and s["pf"] < DEMOTE_PF) or s["mdd"] > DEMOTE_MDD)
            verdict, desc = _judge(v, 30_000 * max(1, len(v)))
            rows.append((rname(k), "실전 소액", "⬇ 내릴 만함 (모의로)" if demote else verdict, "실전 " + desc))
        else:
            verdict, desc = _judge(p_by.get(k, []), PAPER_START)
            rows.append((pname(k), "모의", verdict.replace("올릴", "실전 소액으로 올릴"), "모의 " + desc))
    return rows


def _account_rows(acct: list, name) -> list[tuple]:
    """매매별 가상 계좌 → 매매별 행 (건수·승률·건당 수익률·합계·손익비·잔고·보유 중)."""
    closed, held = [], defaultdict(int)
    for k, q, bp, sp, pq, pp, st in acct:
        if st != "closed" or not sp or not q:
            held[k] += 1
            continue
        part = min(pq or 0, q)
        pnl = (sp - bp) * (q - part) + ((pp or sp) - bp) * part - bp * q * 0.0025
        closed.append((k, pnl, pnl / (bp * q)))
    rows = [r + (f"{ACCOUNT_START + sum(p for k, p, _ in closed if name(k) == r[0]):,.0f}원", held.pop(next((k for k in list(held) if name(k) == r[0]), None), 0))
            for r in _by_kind(closed, name)]
    rows += [(name(k), 0, "—", "—", _won(0), "—", f"{ACCOUNT_START:,.0f}원", n) for k, n in held.items()]
    return rows


def build(today: date | None = None) -> str:
    from kiwoom_trading.execution.real import PLAYS, SEED, is_paused
    from kiwoom_trading.execution.journal import KIND_LABEL as LABELS
    today = today or date.today()
    conn = _connect()
    try:
        real = conn.execute("""SELECT sell_ts, coalesce(name, code), kind, qty, buy_price, sell_price, pnl, reason FROM real_trades
                               WHERE status = 'closed' AND pnl IS NOT NULL ORDER BY sell_ts""").fetchall()
        paper = conn.execute("""SELECT kind, qty, buy_price, sell_price FROM paper_trades
                                WHERE sell_price IS NOT NULL AND buy_price IS NOT NULL AND NOT coalesce(virtual, false)""").fetchall()
        pdays = conn.execute("SELECT date, asset_end FROM paper_days WHERE asset_end IS NOT NULL ORDER BY date").fetchall()
        try:   # 🧾 매매별 가상 계좌 (매매마다 100만 원, paper.AccountTrader) — 표가 없으면 빈 목록
            acct = conn.execute(f"""SELECT kind, qty, buy_price, sell_price, part_qty, part_price, status FROM {ACCOUNT_TABLE}
                                    WHERE buy_price IS NOT NULL AND status IN ('open', 'closed')""").fetchall()
        except Exception:
            acct = []
        paused = is_paused(conn, today)
    finally:
        conn.close()

    rname = lambda k: PLAYS.get(k, (LABELS.get(k, k),))[0]
    pname = lambda k: LABELS.get(k, k)
    rs = _stats([r[6] for r in real], SEED)
    r_labels = [f"{r[0]:%m-%d}" for r in real]
    r_labels = ["시작"] + r_labels
    p_curve = [PAPER_START] + [a for _, a in pdays]
    p_eq_peak, p_mdd = PAPER_START, 0.0
    for v in p_curve:
        p_eq_peak = max(p_eq_peak, v)
        p_mdd = max(p_mdd, 1 - v / p_eq_peak)
    p_items = [(k, (sp - bp) * q - bp * q * 0.0025, sp / bp - 1 - 0.0025) for k, q, bp, sp in paper if bp]
    ps = _stats([p for _, p, _ in p_items], PAPER_START)

    recent = [(f"{r[0]:%m-%d %H:%M}", r[1], rname(r[2]), f"{r[3]}주", f"{r[4]:,.0f} → {r[5]:,.0f}", f"{r[5] / r[4] - 1:+.2%}", _won(r[6]), r[7] or "")
              for r in reversed(real[-15:])]
    real_kind = _by_kind([(r[2], r[6], r[5] / r[4] - 1) for r in real if r[4]], rname)
    paper_kind = _by_kind(p_items, pname)
    p_last = p_curve[-1]
    head = ["매매", "건수", "승률", "건당 수익률", "합계 손익", "손익비"]
    stage_rows = _stage_rows(real, p_items, rname, pname)
    a_rows = _account_rows(acct, pname)

    body = f"""
<header><h1>운용 성과</h1><p class="muted">기준 {today:%Y-%m-%d} · 매일 20:00 새로 만듦 ·
{'⏸ 오늘 실전 쉼' if paused else '▶️ 오늘 실전 켜짐'}</p></header>
<section><h2>🔴 실전 계좌 (시드 {SEED:,.0f}원)</h2>{_kpis(rs, SEED)}{_svg(rs['curve'], r_labels)}
<h3>매매별</h3>{_table(real_kind, head)}
<h3>최근 실전 매매</h3>{_table(recent, ['매도 시각', '종목', '매매', '수량', '매수 → 매도', '수익률', '손익', '매도 이유'])}</section>
<section><h2>🧪 모의 계좌 (시작 {PAPER_START:,.0f}원)</h2>
<div class="kpis"><div class="kpi"><span>평가 자산</span><b>{p_last:,.0f}원 ({p_last / PAPER_START - 1:+.1%})</b></div>
<div class="kpi"><span>손익비 (PF)</span><b>{f"{ps['pf']:.2f}" if ps['pf'] else '—'}</b></div>
<div class="kpi"><span>승률</span><b>{ps['win']:.0%}</b></div><div class="kpi"><span>최대 낙폭 (MDD)</span><b>−{p_mdd:.1%}</b></div>
<div class="kpi"><span>매매 수</span><b>{ps['n']}건</b></div></div>
{_svg(p_curve, ['시작'] + [f"{d:%m-%d}" for d, _ in pdays])}
<h3>매매별 (잔고 밖 가상 제외, 비용 0.25% 뺌)</h3>{_table(paper_kind, head)}</section>
<section><h2>🧾 매매별 가상 계좌 (매매마다 {ACCOUNT_START:,.0f}원)</h2>
<p class="muted">모의 매수 신호 전부를 매매마다 따로 둔 가상 계좌에 같은 규칙으로 적음 (주문 없음, 비용 0.25% 뺌). 계좌 안에서만 돈·자리를 봐서 다른 매매와 다투지 않음. 잔고 = 시작 금액 + 끝난 매매 손익.</p>
{_table(a_rows, head + ['계좌 잔고', '보유 중']) if a_rows else '<p class="muted">아직 기록 없음 (2026-11-16 월요일부터 쌓임)</p>'}</section>
<section><h2>🪜 전략 단계표</h2><p class="muted">가상 → 모의 → 실전 소액(종목당 3만 원) → 증액. 올릴 기준: 그 단계 실제 매매 {PROMOTE_N}건 이상 · 손익비 {PROMOTE_PF} 이상 · 앞 절반과 뒤 절반 합계 둘 다 +.
내릴 기준(실전): {DEMOTE_N}건 이상인데 손익비 {DEMOTE_PF} 미만, 또는 최대 낙폭 {DEMOTE_MDD:.0%} 넘음. 표시만 하고 단계는 사용자가 정함.</p>
{_table(stage_rows, ['매매', '지금 단계', '판정', '근거'])}</section>
<footer><p>약어 풀이</p><ul><li>PF: Profit Factor, 이익 합 ÷ 손실 합 (1보다 크면 번 돈이 잃은 돈보다 큼)</li>
<li>MDD: Maximum Drawdown, 가장 높았던 잔고에서 가장 많이 빠진 비율</li></ul></footer>"""
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>운용 성과</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#ffffff;--line:#e7e5e4;--accent:#2563eb;--base:#d6d3d1}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#0c0a09;--fg:#e7e5e4;--muted:#a8a29e;--card:#1c1917;--line:#292524;--accent:#60a5fa;--base:#44403c}}}}
:root[data-theme="dark"]{{--bg:#0c0a09;--fg:#e7e5e4;--muted:#a8a29e;--card:#1c1917;--line:#292524;--accent:#60a5fa;--base:#44403c}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Malgun Gothic",sans-serif}}
header,section,footer{{max-width:880px;margin:0 auto;padding:16px}}
h1{{font-size:24px;margin:8px 0 0}} h2{{font-size:18px;margin:24px 0 8px}} h3{{font-size:15px;margin:20px 0 6px}}
.muted{{color:var(--muted)}} .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.kpi span{{display:block;color:var(--muted);font-size:12px}} .kpi b{{font-size:16px;font-variant-numeric:tabular-nums}}
svg{{width:100%;height:auto;margin-top:12px;background:var(--card);border:1px solid var(--line);border-radius:10px}}
.curve{{fill:none;stroke:var(--accent);stroke-width:2}} .base{{stroke:var(--base);stroke-dasharray:4 4}} .axis{{fill:var(--muted);font-size:11px}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}} th{{color:var(--muted);font-weight:600}}
footer{{color:var(--muted);font-size:12px}}
</style></head><body>{body}</body></html>"""


def write(today: date | None = None) -> str:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build(today))
    return OUT


def main() -> None:
    ap = argparse.ArgumentParser(description="운용 성과 페이지")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    path = write()
    print(path)
    if a.send:
        from kiwoom_trading.common.telegram import send_telegram_document
        send_telegram_document(path, "📊 운용 성과 페이지 — 받아서 브라우저로 여세요 (실전·모의 잔고 곡선·손익비·최대 낙폭·매매별)")


if __name__ == "__main__":
    main()
