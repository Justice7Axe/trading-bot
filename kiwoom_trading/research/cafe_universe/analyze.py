"""☕ 카페 종목 제한 백테스트 — 날짜별 그때의 카페 목록 U(D) 로 기존 매매 1년 목록을 거름 (2026-11-15).

U(D) (point-in-time, D일 07:50 전에 올라온 글만 — D일 장중 글은 안 씀):
  U60  (지금 규칙, 11-15 사용자 '2개월 전 것까지'): D 전 60일(달력) 안 ① 하승훈 '특징테마'(오전장 제외)·'일자별 테마주 정리' 모든 글 종목
       ∪ ② 나는주식트레이더다 '당일특징주' 모든 글 종목
  OLD  (비교, 바로 전 규칙): 하승훈 가장 최근 특징테마 1개 + 일자별 1개 ∪ 트레이더 D 전 7일 안 당일특징주
입력: data/cafe_history.duckdb (collect.py) · data/cafe_history/trades_all.csv (export_trades.py)
비교 기간: 60일 창이 다 차는 날부터 (글 모은 첫날 + 60일) — 그 전 매매는 뺌.
지표: 건수·건당·합계(건당 100만 원)·손익비(이익 합 ÷ 손실 합)·최대 낙폭(날짜별 누적, 100만/건)·최고 5건 뺀 합계·★(앞·뒤 반 모두 + & 최고 5일 빼도 +)
  + 10만 원 실전 규칙 계좌 (종목당 3만 원, 1주가 3만 넘으면 1주, 예수금 안에서, 같은 종목 보유 중 안 삼, 다음 날 09:00/매도일 아침 현금 돌아옴)
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.cafe_universe.analyze
출력: data/cafe_history/report.txt · universe_daily.csv
"""
from __future__ import annotations

import bisect
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import duckdb
import numpy as np
import pandas as pd

ROOT = r"D:\Ellie\trading"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "cafe_history")
HASUNG, TRADER = "하승훈", "나는주식트레이더다"
NAMES = {"1️⃣": "1️⃣ 상승장 장 초", "2️⃣": "2️⃣ 저항 돌파", "3️⃣": "3️⃣ 막힌 고점 돌파", "4️⃣": "4️⃣ 역행 강세 종가",
         "6️⃣": "6️⃣ 주도주 신고가", "7️⃣": "7️⃣ 주도주 추세", "📕": "📕 상한가 풀림", "🌙": "🌙 종가 재돌파", "🔁": "🔁 시가 탈환",
         "☕": "☕ 카페 테마 대장", "📍": "📍 중심선", "🪜": "🪜 애프터 정배열", "🏄": "🏄 쿨라매기 돌파(전날 대금 500)",
         "🏄50": "🏄 쿨라매기 돌파(전날 대금 50)"}
ORDER = list(NAMES)
LIVE = {"6️⃣", "📕", "4️⃣", "1️⃣", "2️⃣", "🌙"}       # 실전 매매(5️⃣ 인버스 뺌)
WINDOW = 60
CUT = time(7, 50)


class Rep:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def say(self, s=""):
        print(s)
        self.f.write(s + "\n")
        self.f.flush()


def load_posts():
    c = duckdb.connect(os.path.join(DATA, "cafe_history.duckdb"), read_only=True)
    posts = c.execute("SELECT post_id, cafe, kind, posted_ts, status, n_codes, ocr, miss FROM posts WHERE kind IS NOT NULL").df()
    hist = c.execute("SELECT post_id, cafe, code FROM cafe_history").df()
    c.close()
    codes = hist.groupby(["cafe", "post_id"]).code.apply(set).to_dict()
    posts["codes"] = [codes.get((r.cafe, r.post_id), set()) for r in posts.itertuples()]
    posts = posts[posts.status == "done"].sort_values("posted_ts").reset_index(drop=True)
    return posts


def universes(posts, days):
    """{D: (U60, OLD)}"""
    ts = posts.posted_ts.values.astype("datetime64[ns]")
    out = {}
    for d in days:
        cut = np.datetime64(datetime.combine(d, CUT))
        lo60 = np.datetime64(datetime.combine(d, CUT) - timedelta(days=WINDOW))
        lo7 = np.datetime64(datetime.combine(d, CUT) - timedelta(days=7))
        m = (ts < cut) & (ts >= lo60)
        u60 = set().union(*posts.codes[m]) if m.any() else set()
        old = set()
        before = posts[ts < cut]
        for k in ("특징테마", "일자별"):
            x = before[(before.cafe == HASUNG) & (before.kind == k)]
            if len(x):
                old |= x.codes.iloc[-1]
        t7 = (ts < cut) & (ts >= lo7) & (posts.cafe.values == TRADER)
        if t7.any():
            old |= set().union(*posts.codes[t7])
        out[d] = (u60, old)
    return out


def stats(df, mid):
    if not len(df):
        return None
    r = df.ret.values
    win, loss = r[r > 0].sum(), -r[r < 0].sum()
    byd = df.groupby("date").ret.sum().sort_index() * 100     # 만 원 (건당 100만)
    cum = byd.cumsum().values
    mdd = float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max())
    a, b = df[df.date < mid].ret, df[df.date >= mid].ret
    top5d = byd.sort_values(ascending=False).head(5).sum()
    top5 = np.sort(r)[::-1][:5].sum() * 100
    star = (a.sum() > 0 if len(a) else False) and (b.sum() > 0 if len(b) else False) and byd.sum() - top5d > 0
    return dict(n=len(r), mean=r.mean(), total=r.sum() * 100, pf=win / loss if loss > 0 else float("inf"), mdd=mdd,
                ex5=r.sum() * 100 - top5, wr=(r > 0).mean(), a=a.mean() if len(a) else float("nan"),
                b=b.mean() if len(b) else float("nan"), star=star)


def fmt(s):
    if s is None:
        return "    0건"
    pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "∞"
    return (f"{s['n']:5d}건 건당 {s['mean'] * 100:+6.2f}% 합계 {s['total']:+7.0f}만 손익비 {pf:>5s} 낙폭 {s['mdd']:5.0f}만 "
            f"최고5건 빼면 {s['ex5']:+6.0f}만 | 앞 {s['a'] * 100:+.2f} 뒤 {s['b'] * 100:+.2f}{' ★' if s['star'] else ''}")


def tick_up(p):
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < lim:
            return int(np.ceil(p / t) * t)
    return int(np.ceil(p / 1000) * 1000)


def sim10(df, cal, seed=100_000, per=30_000):
    """10만 원 실전 규칙 계좌 (정수 주). 현금은 매도일(없으면 다음 거래일) 아침에 돌아옴."""
    cash = float(seed)
    hold = []   # (돌아오는 날, 돌려받는 돈, 종목, 손익)
    curve, n, skip = [], 0, 0
    byd = defaultdict(list)
    for t in df.itertuples():
        byd[t.date].append(t)
    days = [d for d in cal if df.date.min() <= d <= df.date.max()] if len(df) else []
    for d in days:
        keep = []
        for h in hold:
            if h[0] <= d:
                cash += h[1]
            else:
                keep.append(h)
        hold = keep
        got = {h[2] for h in hold}
        for t in sorted(byd.get(d, []), key=lambda t: str(t.t)):
            if t.code in got or not (t.px == t.px) or t.px <= 0:
                skip += 1
                continue
            lim = tick_up(t.px * 1.01)
            q = min(max(1, int(per // lim)), int(cash // lim))
            if q < 1:
                skip += 1
                continue
            cash -= q * lim
            p = q * t.px * t.ret
            sd = t.sell_d if isinstance(t.sell_d, date) else None
            if sd is None or sd <= d:
                i = bisect.bisect_right(cal, d)
                sd = cal[i] if i < len(cal) else d + timedelta(days=1)
            hold.append((sd, q * lim + p, t.code, p))
            got.add(t.code)
            n += 1
        curve.append(cash + sum(h[1] - h[3] for h in hold))
    eq = cash + sum(h[1] for h in hold)
    if not curve:
        return None
    curve[-1] = eq
    v = np.array(curve)
    pk = np.maximum.accumulate(np.r_[seed, v])[1:]
    return dict(final=eq, ret=eq / seed - 1, mdd=float(((pk - v) / pk).max()), n=n, skip=skip)


def fsim(s):
    if s is None:
        return "-"
    return f"{s['final'] / 1e4:6.1f}만({s['ret'] * 100:+5.0f}%) 낙폭 {s['mdd'] * 100:4.1f}% 산 {s['n']}건 못 산 {s['skip']}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    R = Rep(os.path.join(OUT, "report.txt"))
    posts = load_posts()
    T = pd.read_csv(os.path.join(OUT, "trades_all.csv"), dtype={"code": str}, encoding="utf-8-sig")
    T["code"] = T.code.str.zfill(6)
    T["date"] = pd.to_datetime(T.date).dt.date
    T["sell_d"] = pd.to_datetime(T.sell_d).dt.date
    T["sell_d"] = T.sell_d.where(T.sell_d.notna(), None)
    dm = duckdb.connect(os.path.join(DATA, "daily_ohlcv.duckdb"), read_only=True)
    cal = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    dm.close()
    cal = [d if isinstance(d, date) else d.date() for d in cal]

    first = posts.posted_ts.min().date()
    start = first + timedelta(days=WINDOW)
    end = T.date.max()
    R.say(f"☕ 카페 종목 제한 백테스트 ({datetime.now():%Y-%m-%d %H:%M})")
    for cafe in (HASUNG, TRADER):
        p = posts[posts.cafe == cafe]
        R.say(f"  {cafe}: 글 {len(p)}개 ({p.posted_ts.min():%Y-%m-%d} ~ {p.posted_ts.max():%Y-%m-%d}) · 종목 0개 글 {int((p.n_codes == 0).sum())}"
              f" · OCR 글 {int(p.ocr.fillna(False).sum())} · 글당 종목 평균 {p.n_codes.mean():.0f}")
        for k, g in p.groupby("kind"):
            nm = g.miss.fillna("").map(lambda s: len([x for x in s.split(", ") if x]))
            R.say(f"     {k}: {len(g)}개, 글당 종목 {g.n_codes.mean():.0f}, 못 맞춘 이름 글당 {nm.mean():.1f}")
    days = sorted(d for d in set(T.date) if start <= d <= end)
    U = universes(posts, days)
    pd.DataFrame([(d, len(a), len(b)) for d, (a, b) in U.items()], columns=["date", "u60", "old"]).to_csv(
        os.path.join(OUT, "universe_daily.csv"), index=False)
    s60 = [len(a) for a, _ in U.values()]
    so = [len(b) for _, b in U.values()]
    R.say(f"\n비교 기간 {start} ~ {end} (60일 창이 다 차는 날부터, 매매 있는 {len(days)}거래일)")
    R.say(f"  카페 목록 크기: U60(지금 규칙) 평균 {np.mean(s60):.0f}종목 (최소 {min(s60)}·최대 {max(s60)}) · OLD(전 규칙) 평균 {np.mean(so):.0f}종목")
    R.say("  ⚠️ 나는주식트레이더다 '당일특징주' 글은 2026-03-09 부터만 있음 → 그 전은 하승훈 카페만으로 된 목록")

    T = T[(T.date >= start) & (T.date <= end)].copy()
    T["in60"] = [r.code in U[r.date][0] for r in T.itertuples()]
    T["inold"] = [r.code in U[r.date][1] for r in T.itertuples()]
    T.to_csv(os.path.join(OUT, "trades_flagged.csv"), index=False, encoding="utf-8-sig")
    mid = start + (end - start) / 2
    R.say(f"  앞·뒤 반 나눔 {mid}")

    R.say("\n[1] 매매별 — 전체 / 카페 안(U60) / 카페 밖(U60) / 참고: 카페 안(전 규칙 OLD)  (합계·낙폭은 건당 100만 원 가정)")
    summary = []
    for k in ORDER:
        x = T[T.kind == k]
        if not len(x):
            continue
        R.say(f"\n{NAMES[k]}  (카페 안 비율 {x.in60.mean() * 100:.0f}% · 전 규칙 {x.inold.mean() * 100:.0f}%)")
        sa, si, so_, sold = stats(x, mid), stats(x[x.in60], mid), stats(x[~x.in60], mid), stats(x[x.inold], mid)
        R.say(f"  전체      {fmt(sa)}")
        R.say(f"  카페 안   {fmt(si)}")
        R.say(f"  카페 밖   {fmt(so_)}")
        R.say(f"  안(전규칙) {fmt(sold)}")
        ma, mi, mo = sim10(x, cal), sim10(x[x.in60], cal), sim10(x[~x.in60], cal)
        R.say(f"  10만 계좌  전체 {fsim(ma)} | 카페 안 {fsim(mi)} | 카페 밖 {fsim(mo)}")
        summary.append((k, sa, si, so_, sold, ma, mi))

    R.say("\n[2] 실전 매매 묶음 (6️⃣ 주도주 신고가·📕 상한가 풀림·4️⃣ 역행 강세 종가·1️⃣ 상승장 장 초·2️⃣ 저항 돌파·🌙 종가 재돌파, 5️⃣ 인버스 뺌) 10만 계좌")
    L = T[T.kind.isin(LIVE)].drop_duplicates(["date", "code"])
    for lab, x in (("전체", L), ("카페 안 U60", L[L.in60]), ("카페 밖", L[~L.in60]), ("카페 안 전 규칙", L[L.inold])):
        R.say(f"  {lab:12s} {fsim(sim10(x, cal))}  | {fmt(stats(x, mid))}")

    R.say("\n[3] 한 줄 요약 (건당: 전체 → 카페 안 / 카페 밖)")
    for k, sa, si, so_, sold, ma, mi in summary:
        g = lambda s: f"{s['mean'] * 100:+.2f}%({s['n']})" if s else "-(0)"
        R.say(f"  {NAMES[k]}: {g(sa)} → 안 {g(si)} / 밖 {g(so_)} · 전 규칙 안 {g(sold)}")


if __name__ == "__main__":
    main()
