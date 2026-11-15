"""🪜 이평선 재정배열 코인 선물 모의 — 매일 매매일지.

하루 = 00:00~24:00 UTC = 한국 09:00 ~ 다음 날 09:00. 파일 이름의 날짜는 한국 시작일.
    python -m kiwoom_trading.strategies.crypto_align.journal 2026-11-16          # 그날 일지 다시 만들기 (전송 안 함)
    python -m kiwoom_trading.strategies.crypto_align.journal 2026-11-16 --send   # 전송까지

- 매수는 그날 [09:00, 다음 날 09:00) 안, 매도는 (09:00, 다음 날 09:00] 안이면 그날 일지에 들어감
  (전날 산 것을 그날 09:00 에 판 건 전날 일지).
- 출력: docs/journal/crypto/<심볼>-YYYY-MM-DD.md, 차트 data/journal/crypto/<심볼>-YYYYMMDD.png,
  텔레그램 요약 + 차트 사진 (리포트 HTML 은 live.py 가 함께 보냄).
- 문서는 '~임/~됨/~함' 문체, 끝에 약어 풀이 (스킬 trade-journal).
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, timedelta, timezone

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.strategies.crypto_align import core

KST = timezone(timedelta(hours=9))
SEED = 1000.0
DOC_DIR = os.path.join(PROJECT_ROOT, "docs", "journal", "crypto")
CHART_DIR = os.path.join(PROJECT_ROOT, "data", "journal", "crypto")
NAME = "🪜 이평선 재정배열"
PLAIN = "이평선 재정배열"   # 차트 제목용 (이모지 글꼴 깨짐)


def _k(ms: int, fmt: str = "%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, KST).strftime(fmt)


def _p(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _day_ms(day: date) -> tuple[int, int]:
    s = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    return s, s + core.DAY_MS


def _equity_stats(ts: list[dict], key: str) -> tuple[float, float]:
    eq, pk, mdd = 1.0, 1.0, 0.0
    for t in ts:
        eq *= 1 + t[key]
        pk = max(pk, eq)
        mdd = min(mdd, eq / pk - 1)
    return eq - 1, mdd


def _chart(symbol: str, day: date, bars: list[core.Bar], trades: list[dict], pos: core.Position | None) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception:
        logging.warning("matplotlib 없음 — 차트 건너뜀")
        return ""
    s, e = _day_ms(day)
    closes = [b.c for b in bars]
    f, sl = core.sma(closes, core.FAST), core.sma(closes, core.SLOW)
    idx = [i for i, b in enumerate(bars) if s - core.DAY_MS // 2 <= b.t <= e]   # 앞 12시간 + 그날 + 다음 날 첫 봉
    if not idx:
        return ""
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(12, 5.5))
    xs = list(range(len(idx)))
    for x, i in zip(xs, idx):
        b = bars[i]
        col = "#d62728" if b.c >= b.o else "#1f5fbf"
        ax.vlines(x, b.l, b.h, color=col, linewidth=0.6)
        ax.add_patch(Rectangle((x - 0.3, min(b.o, b.c)), 0.6, max(abs(b.c - b.o), 1e-9), color=col, linewidth=0))
    ax.plot(xs, [f[i] for i in idx], color="#0f7c8c", linewidth=1.2, label="60선")
    ax.plot(xs, [sl[i] for i in idx], color="#b7791f", linewidth=1.2, label="120선")
    ax.axvline(next((x for x, i in zip(xs, idx) if bars[i].t >= s), 0) - 0.5, color="#888", linewidth=0.8, linestyle=":")
    tpos = {bars[i].t: x for x, i in zip(xs, idx)}
    for n, t in enumerate(trades, 1):
        if t["entry_t"] in tpos:
            ax.scatter([tpos[t["entry_t"]]], [t["entry"]], marker="^", s=130, color="#00a000", zorder=5,
                       label="매수" if n == 1 else None)
            ax.annotate(f"{n}", (tpos[t["entry_t"]], t["entry"]), textcoords="offset points", xytext=(0, -16), ha="center", fontsize=8)
        if t["exit_t"] in tpos:
            ax.scatter([tpos[t["exit_t"]]], [t["exit"]], marker="v", s=130, color="#ff7f0e", zorder=5,
                       label="매도" if n == 1 else None)
    if pos is not None and pos.entry_t in tpos:
        ax.scatter([tpos[pos.entry_t]], [pos.entry], marker="^", s=130, color="#00a000", zorder=5)
        ax.axhline(pos.stop, color="#1f5fbf", linestyle="--", linewidth=0.9, label=f"손절선 {pos.stop:,.2f}")
    step = max(1, len(xs) // 12)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([_k(bars[i].t, "%d일 %H:%M") for i in idx[::step]], fontsize=8)
    ax.set_title(f"{day:%m-%d} {symbol} {PLAIN} 모의 · 15분봉 (한국 시각, 점선 = 09:00)", fontsize=11)
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    os.makedirs(CHART_DIR, exist_ok=True)
    path = os.path.join(CHART_DIR, f"{symbol}-{day:%Y%m%d}.png")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def build(symbol: str, day: date, bars: list[core.Bar], st: core.State, rates: list[tuple[int, float]]) -> tuple[str, str, list[dict]]:
    from kiwoom_trading.strategies.crypto_align.live import load_trades
    s, e = _day_ms(day)
    all_tr = load_trades(symbol)
    exits = [t for t in all_tr if s < t["exit_t"] <= e]
    entries_open = st.pos if (st.pos and s <= st.pos.entry_t < e) else None
    upto = [t for t in all_tr if t["exit_t"] <= e]
    seg = [b for b in bars if s <= b.t < e]
    closes = [b.c for b in bars]
    f, sl = core.sma(closes, core.FAST), core.sma(closes, core.SLOW)
    last_i = max((i for i, b in enumerate(bars) if b.t < e), default=None)
    day_fund = sum(r for t, r in rates if s < t <= e)

    L = [f"# 📓 {NAME} {symbol} 모의 매매일지 {day:%Y-%m-%d}", "",
         f"- 기간: {day:%m-%d} 09:00 ~ {day + timedelta(days=1):%m-%d} 09:00 (한국 시각) · 실제 주문 없는 가상 장부, 같은 매매를 1배·2배 잔고로 적음",
         f"- 규칙: 15분봉 60선이 120선을 위로 넘고 종가 > 60선 → 다음 봉 시가 롱, 매수가 −3% 손절, 익절 없음, 다음 날 09:00 첫 봉 시가 매도 (수수료 0.05%×2·펀딩비 포함)", ""]
    L += ["## 시장", ""]
    if seg:
        o, c = seg[0].o, seg[-1].c
        hi, lo = max(b.h for b in seg), min(b.l for b in seg)
        L.append(f"- {symbol}: 시가 {o:,.2f} → 종가 {c:,.2f} ({_p(c / o - 1)}), 고가 {hi:,.2f} · 저가 {lo:,.2f} (하루 폭 {_p(hi / lo - 1)})")
    if last_i is not None and f[last_i] and sl[last_i]:
        state = "정배열 (60선 > 120선)" if f[last_i] > sl[last_i] else "역배열 (60선 < 120선)"
        L.append(f"- 하루 끝 이평선: 60선 {f[last_i]:,.2f} · 120선 {sl[last_i]:,.2f} → {state}, 간격 {_p(f[last_i] / sl[last_i] - 1)}")
    L.append(f"- 그날 펀딩비 합: {day_fund * 100:+.4f}% (롱은 + 면 냄)")
    L.append("")

    L += ["## 매매 한 건씩", ""]
    day_net, day_net2 = 0.0, 0.0
    review: list[str] = []
    if not exits and not entries_open:
        L += ["- 끝난 매매 없음. 60선이 120선을 위로 넘는 신호가 없었음.", ""]
    for n, t in enumerate(exits, 1):
        hold_h = (t["exit_t"] - t["entry_t"]) / 3_600_000
        room = t["low"] / t["stop"] - 1 if t["low"] else None
        L += [f"### {n}. {_k(t['entry_t'])} 매수 → {_k(t['exit_t'])} 매도 ({t['reason']})", "",
              f"- 신호: {_k(t['signal_t'])} 봉 마감, 60선 {t['fast']:,.2f} 이 120선 {t['slow']:,.2f} 위로 넘음",
              f"- 매수 {t['entry']:,.2f} · 손절선 {t['stop']:,.2f} · 매도 {t['exit']:,.2f} · 보유 {hold_h:.1f}시간",
              f"- 보유 중 최고 {t['high']:,.2f} ({_p(t['high'] / t['entry'] - 1)}) · 최저 {t['low']:,.2f} ({_p(t['low'] / t['entry'] - 1)})",
              f"- 손익: 가격 {_p(t['ret'])} · 펀딩 {t['fund'] * 100:+.3f}% → **1배 {_p(t['net'])} · 2배 {_p(t['net2'])}** (수수료 포함)",
              f"- 규칙대로였나: 규칙대로 (자동 판정)" + (f" · 판정이 {(t['logged_t'] - t['exit_t']) / 60000:.0f}분 늦게 기록됨 (PC 꺼짐·절전)"
                                                     if t.get("logged_t") and t["logged_t"] - t["exit_t"] > 40 * 60000 else ""), ""]
        day_net += t["net"]
        day_net2 += t["net2"]
        if t["reason"].startswith("손절"):
            review.append(f"{n}번 손절: {_k(t['entry_t'])} 매수 뒤 −3% 손절. 그날 하루 폭 {_p(max(b.h for b in seg) / min(b.l for b in seg) - 1) if seg else '?'}")
        elif room is not None and room < 0.01:
            review.append(f"{n}번 손절선 1% 안까지 내려갔다 살아남 (최저 {t['low']:,.2f}, 손절선 {t['stop']:,.2f})")
        if t["net"] >= 0.05:
            review.append(f"{n}번 +5%↑ 큰 수익 ({_p(t['net'])}, 2배 {_p(t['net2'])})")
    if entries_open:
        p = entries_open
        last_c = seg[-1].c if seg else p.entry
        L += [f"### 지금 들고 있음: {_k(p.entry_t)} 매수 {p.entry:,.2f}", "",
              f"- 손절선 {p.stop:,.2f}, 다음 날 09:00 매도 예정. 하루 끝 가격 {last_c:,.2f} ({_p(last_c / p.entry - 1)}, 2배 {_p(2 * (last_c / p.entry - 1))})", ""]

    # 누적 성적
    n_all = len(upto)
    L += ["## 성적 (모의 시작부터 이날까지)", ""]
    if n_all:
        wins = sum(1 for t in upto if t["net"] > 0)
        c1, m1 = _equity_stats(upto, "net")
        c2, m2 = _equity_stats(upto, "net2")
        gw = sum(t["net"] for t in upto if t["net"] > 0)
        gl = -sum(t["net"] for t in upto if t["net"] < 0)
        pf = f"{gw / gl:.2f}" if gl else "—"
        L += ["| | 1배 | 2배 |", "|---|---|---|",
              f"| 가상 잔고 (USDT, 시작 {SEED:,.0f}) | {SEED * (1 + c1):,.1f} ({_p(c1)}) | {SEED * (1 + c2):,.1f} ({_p(c2)}) |",
              f"| 최대 낙폭 | {_p(m1)} | {_p(m2)} |",
              f"| 이날 끝난 매매 합 | {_p(day_net)} | {_p(day_net2)} |", "",
              f"- 끝난 매매 {n_all}건 · 이긴 {wins}건 · 손익비 {pf} · 건당 평균 {_p(sum(t['net'] for t in upto) / n_all)} (1배)"]
        streak = 0
        for t in reversed(upto):
            if t["net"] < 0:
                streak += 1
            else:
                break
        if streak >= 3:
            review.append(f"최근 {streak}건 연속 손실")
        # 최근 7일 표
        L += ["", "| 날짜 (09시 시작) | 건수 | 1배 합 | 2배 합 |", "|---|---|---|---|"]
        for k in range(6, -1, -1):
            dd = day - timedelta(days=k)
            ds, de = _day_ms(dd)
            tt = [t for t in all_tr if ds < t["exit_t"] <= de]
            L.append(f"| {dd:%m-%d} | {len(tt)} | {_p(sum(t['net'] for t in tt))} | {_p(sum(t['net2'] for t in tt))} |")
    else:
        L.append("- 아직 끝난 모의 매매 없음.")
    L.append("")

    L += ["## 📝 복기 칸 (자동)", ""]
    L += [f"- {r}" for r in review] or ["- 따로 볼 것 없음 (손절·손절선 접근·연속 손실·+5% 큰 수익 없음)."]
    L += ["", "---", core.abbr_footer(symbol)]
    md = "\n".join(L) + "\n"

    tg = [f"📓 {NAME} {symbol} 모의 일지 {day:%m-%d} 09시~다음 날 09시"]
    if exits:
        for n, t in enumerate(exits, 1):
            tg.append(f"{n}. {_k(t['entry_t'], '%H:%M')} {t['entry']:,.2f} → {_k(t['exit_t'], '%m-%d %H:%M')} {t['exit']:,.2f} "
                      f"{t['reason']} · 1배 {_p(t['net'])} · 2배 {_p(t['net2'])}")
    else:
        tg.append("끝난 매매 없음")
    if entries_open:
        tg.append(f"보유 중: {_k(entries_open.entry_t)} 매수 {entries_open.entry:,.2f}, 손절 {entries_open.stop:,.2f}")
    if n_all:
        c1, m1 = _equity_stats(upto, "net")
        c2, m2 = _equity_stats(upto, "net2")
        tg.append(f"누적 {n_all}건 · 잔고 1배 {SEED * (1 + c1):,.1f} ({_p(c1)}) · 2배 {SEED * (1 + c2):,.1f} ({_p(c2)}) USDT")
    if review:
        tg.append("📝 " + " / ".join(review))
    return md, "\n".join(tg), exits


def write_day(symbol: str, day: date, bars: list[core.Bar], st: core.State, rates: list[tuple[int, float]],
              send: bool = False) -> str:
    md, tg, exits = build(symbol, day, bars, st, rates)
    os.makedirs(DOC_DIR, exist_ok=True)
    path = os.path.join(DOC_DIR, f"{symbol}-{day:%Y-%m-%d}.md")
    s, e = _day_ms(day)
    pos = st.pos if (st.pos and s <= st.pos.entry_t < e) else None
    chart = _chart(symbol, day, bars, exits, pos)
    if chart:
        md = md.replace("## 시장", f"![차트](../../../data/journal/crypto/{os.path.basename(chart)})\n\n## 시장", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    if send:
        from kiwoom_trading.common.telegram import send_telegram_message, send_telegram_photo
        send_telegram_message(tg)
        if chart:
            send_telegram_photo(chart, caption=f"{day:%m-%d} {symbol} {NAME} 15분봉")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("day", help="YYYY-MM-DD (한국 09시 시작일)")
    ap.add_argument("--symbol", default="SOXLUSDT")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    import json
    bars, _ = core.load_bars(a.symbol)
    rates = core.load_funding(a.symbol)
    with open(os.path.join(core.data_dir(a.symbol), "state.json"), encoding="utf-8") as f:
        st = core.State.from_json(json.load(f))
    print(write_day(a.symbol, date.fromisoformat(a.day), bars, st, rates, send=a.send))


if __name__ == "__main__":
    main()
