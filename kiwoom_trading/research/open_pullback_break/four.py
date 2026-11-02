"""장 초 고점 눌림 재돌파 매수 · 1분 이평 역배열 매도 — 검증된 4종목만 (2026-11-03 사용자: SK하이닉스·삼성전자·한미반도체·제주반도체 에만).

규칙은 bt.py 기본값(09:00~09:10 고가 → −1.5% 눌림 → 09:15~11:00 재돌파 마감 다음 봉 시가, 손절 = 눌림 저가).
매도 A = 1분 이평 5<20<60<120 역배열 (못 오면 다음 날 09:00), 비교 C = 손절만·다음 날 09:00.
손실 매매 중 대표 5건을 1분봉 그림으로 → data/open_pullback_break/charts/
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.open_pullback_break.four
"""
import os
import sys
from datetime import datetime, time

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.research.open_pullback_break.bt import ma, prepend_prev

OUT = os.path.join(E.DATA, "open_pullback_break")
CH = os.path.join(OUT, "charts")
os.makedirs(CH, exist_ok=True)
CODES = {"000660": "SK하이닉스", "005930": "삼성전자", "042700": "한미반도체", "080220": "제주반도체"}


def trade(c, d, full, off, prev_close, w=10, dp=0.015):
    reg = full[off:]
    first = [x for x in reg if x[0] < time(9, w)]
    if len(first) < 3:
        return None
    h0 = max(x[2] for x in first)
    low_after = None; dipped = False; kb = None
    for k in range(len(first), len(reg)):
        x = reg[k]
        if x[0] > time(11, 0):
            break
        low_after = x[3] if low_after is None else min(low_after, x[3])
        if low_after <= h0 * (1 - dp):
            dipped = True
        if dipped and x[0] >= time(9, 15) and x[4] > h0:
            kb = k; break
    if kb is None or kb + 1 >= len(reg):
        return dict(date=d, code=c, entry=False, h0=h0, dipped=dipped)
    buy = reg[kb + 1][1]; sp = low_after
    closes = np.array([x[4] for x in full], float)
    m5, m20, m60, m120 = (ma(closes, n) for n in (5, 20, 60, 120))
    nx = E.next_day_exits(c, d, buy).get("09:00 시가")
    out = dict(date=d, code=c, entry=True, h0=h0, stop=sp, t_buy=reg[kb + 1][0], buy=buy, close=E.at(reg, time(15, 30)),
               day_high_after=max(x[2] for x in reg[kb + 1:]))
    for nm in ("A", "C"):
        r = xt = why = None
        for k in range(kb + 1, len(reg)):
            x = reg[k]; j = k + off
            if x[0] > time(15, 19):
                break
            if x[3] <= sp:
                r, xt, why = min(x[1], sp) / buy - 1 - E.COST, x[0], "손절(눌림 저가)"; break
            if nm == "A" and k > kb + 1 and not np.isnan(m120[j]) and m5[j] < m20[j] < m60[j] < m120[j]:
                r, xt, why = x[4] / buy - 1 - E.COST, x[0], "역배열"; break
        if r is None:
            r, xt, why = nx, None, "다음 날 09:00"
        out[nm] = r; out[nm + "_t"] = xt; out[nm + "_why"] = why
    return out


def chart(r, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as mt
    from matplotlib import font_manager
    font_manager.fontManager.addfont("C:/Windows/Fonts/malgun.ttf")
    plt.rcParams["font.family"] = "Malgun Gothic"; plt.rcParams["axes.unicode_minus"] = False
    c, d = r["code"], r["date"]
    reg = E.regular(E.bars(c, d)); full, off = prepend_prev(c, d, reg)
    closes = np.array([x[4] for x in full], float)
    ts = [datetime.combine(d, x[0]) for x in reg]
    fig, ax = plt.subplots(figsize=(13, 6))
    for x, t in zip(reg, ts):
        col = "#d22" if x[4] >= x[1] else "#22d"
        ax.vlines(t, x[3], x[2], color=col, lw=0.6); ax.vlines(t, min(x[1], x[4]), max(x[1], x[4]), color=col, lw=2.2)
    for n, col in ((20, "#f0a000"), (60, "#1a9a1a"), (120, "#000")):
        ax.plot(ts, ma(closes, n)[off:], color=col, lw=1.2, label=f"{n}선")
    ax.axhline(r["h0"], color="#38f", lw=1.2, ls="-"); ax.text(ts[0], r["h0"], " 장 초 고점(09:00~09:10)", color="#38f", fontsize=8, va="bottom")
    ax.axhline(r["stop"], color="#e0f", lw=1, ls="--"); ax.text(ts[0], r["stop"], " 손절선(눌림 저가)", color="#a0a", fontsize=8, va="top")
    tb = datetime.combine(d, r["t_buy"])
    ax.scatter([tb], [r["buy"]], marker="^", s=160, color="red", edgecolor="k", zorder=6)
    ax.annotate(f"매수 {r['t_buy']:%H:%M} {r['buy']:,.0f}", (tb, r["buy"]), xytext=(10, 25), textcoords="offset points", color="red", fontsize=9,
                bbox=dict(boxstyle="round", fc="white", ec="red"))
    if r["A_t"]:
        xa = datetime.combine(d, r["A_t"]); pa = r["buy"] * (1 + r["A"] + E.COST)
        ax.scatter([xa], [pa], marker="v", s=160, color="#15f", edgecolor="k", zorder=6)
        ax.annotate(f"매도 {r['A_t']:%H:%M} {r['A_why']} {r['A']:+.1%}", (xa, pa), xytext=(10, -35), textcoords="offset points", color="#15f",
                    fontsize=9, bbox=dict(boxstyle="round", fc="white", ec="#15f"))
    else:
        ax.text(ts[-1], reg[-1][4], f"  매도 신호 없음 → 다음 날 09:00 {r['A']:+.1%}", color="#15f", fontsize=9)
    ax.set_title(f"{CODES[c]} {d} — 장 초 고점 눌림 재돌파 매수 · 역배열 매도 → {r['A']:+.2%}", fontsize=12)
    ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v:,.0f}")); ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=.3); ax.legend(loc="upper left", fontsize=8)
    plt.tight_layout(); plt.savefig(path, dpi=105); plt.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(os.path.join(OUT, "four.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); f.write(s + "\n"); f.flush()

    rows = []
    for d in E.days():
        if not E.next_day(d):
            continue
        p = E.prev_day(d); pdd = E.daily_day(p)
        for c in CODES:
            reg = E.regular(E.bars(c, d)); fct = E.factor(c, d)
            if len(reg) < 100 or not fct or c not in pdd:
                continue
            full, off = prepend_prev(c, d, reg)
            r = trade(c, d, full, off, pdd[c][3] * fct)
            if r:
                rows.append(r)
    df = pd.DataFrame(rows)
    df.to_parquet(os.path.join(OUT, "four.parquet"))
    ds = sorted(df.date.unique()); h = ds[len(ds) // 2]
    say(f"검증된 4종목 · 장 초 고점 눌림 재돌파 매수 · 역배열 매도 ({ds[0]} ~ {ds[-1]}, 1분봉 있는 날 {len(df)}종목·일)")
    tr = df[df.entry]
    say(f"매수 자리가 나온 날 {len(tr)}번 / 전체 {len(df)} (눌림은 있었는데 재돌파 못 함 {int((~df.entry & df.dipped.astype(bool)).sum())})")
    for nm, g in [("4종목 합계", tr)] + [(CODES[c], tr[tr.code == c]) for c in CODES]:
        if not len(g):
            say(f"  {nm}: 0건"); continue
        a, b = g[g.date < h], g[g.date >= h]
        say(f"  {nm:8s} {len(g):3d}건 | 역배열 매도 건당 {g.A.mean():+.2%} 승률 {(g.A > 0).mean():.0%} (앞 {a.A.mean():+.2%} 뒤 {b.A.mean():+.2%}) "
            f"| 손절만·다음 날 09:00 {g.C.mean():+.2%} 승률 {(g.C > 0).mean():.0%}")
    say("  역배열 매도의 매도 이유: " + str(tr.A_why.value_counts().to_dict()))
    loss = tr[tr.A <= 0].copy()
    say(f"\n손실(역배열 매도 기준) {len(loss)}건 — 유형: " + str(loss.A_why.value_counts().to_dict()))
    # 대표 5건: 손절 2(가장 흔한 유형) · 역배열 늦은 손실 1 · 다음 날 갭 손실 1 · 가장 큰 손실 1 — 종목 고르게
    picks = []
    def take(sub, n):
        for r in sub.itertuples():
            if len(picks) >= 5 or n <= 0:
                break
            if (r.date, r.code) in [(p.date, p.code) for p in picks]:
                continue
            if sum(p.code == r.code for p in picks) >= 2:
                continue
            picks.append(r); n -= 1
    take(loss.sort_values("A"), 1)
    take(loss[loss.A_why == "손절(눌림 저가)"].sort_values("date", ascending=False), 2)
    take(loss[loss.A_why == "역배열"].sort_values("A"), 1)
    take(loss[loss.A_why == "다음 날 09:00"].sort_values("A"), 1)
    take(loss.sort_values("date", ascending=False), 5)
    say("\n대표 손실 5건:")
    paths = []
    for r in picks:
        rr = tr[(tr.date == r.date) & (tr.code == r.code)].iloc[0].to_dict()
        pth = os.path.join(CH, f"{r.code}_{r.date}.png"); chart(rr, pth); paths.append(pth)
        say(f"  {r.date} {CODES[r.code]} 매수 {r.t_buy:%H:%M} {r.buy:,.0f} → {r.A_why} {r.A:+.2%} (그 뒤 당일 고가 {r.day_high_after / r.buy - 1:+.1%}, 종가 {r.close / r.buy - 1:+.1%}) | 손절만·다음 날 {r.C:+.2%}")
    with open(os.path.join(CH, "list.txt"), "w", encoding="utf-8") as g:
        g.write("\n".join(paths))


if __name__ == "__main__":
    main()
