"""250일 신고가 스윙 — 10만 원 실전 규칙 계좌 계산 (2026-11-02 사용자 '250일 신고가 스윙 10만 계좌로 계산해줘').

스윙 규칙 (chart_patterns.patterns 와 같음): D 종가가 전날까지 250일 고가 위 & 거래량 ≥ 50일 평균 1.5배 & 상승 마감,
  20일 평균 대금 30억↑·종가 1,000원↑·상한가 마감 제외 → D+1 시가 매수 (상한가 시작이면 못 삼),
  매도 = −8% 손절(먼저) 또는 종가 20일선 아래 마감 다음 날 시가 (최대 60일).
계좌 (strict_select.choose.real_sim 과 같은 규칙): 시드 10만, 신호마다 종목당 3만 원(1주 > 3만이면 1주), 예수금 안에서, 같은 종목 보유 중 안 삼.
  같은 날 신호는 그날 대금 큰 순서로. 가격은 일봉 수정주가(근사).
1) 스윙만 4년 (2022-07~2026-10)  2) 지금 실전 구성(1️⃣2️⃣4️⃣5️⃣6️⃣📕🌙) 1년 + 스윙
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/long_daily/swing250_account.py
"""
import os, pickle, sys
from datetime import date, time
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.research.strict_select import choose as C

S = C.S
OUT = os.path.join(E.DATA, "long_daily")
f = open(os.path.join(OUT, "swing250_account.txt"), "w", encoding="utf-8")
SIG0 = date(2022, 7, 1)


def say(s=""):
    print(s); f.write(str(s) + "\n"); f.flush()


def swing_trades():
    rows = []
    for d in E.CAL:
        for c, r in E.daily_day(d).items():
            if E.is_common(c): rows.append((d, c, *r))
    df = pd.DataFrame(rows, columns=["date", "code", "o", "h", "l", "c", "v", "val"]).sort_values(["code", "date"])
    out = []
    for code, g in df.groupby("code", sort=False):
        if len(g) < 130: continue
        o, h, l, c, v, val = (g[k].astype(float).values for k in ("o", "h", "l", "c", "v", "val"))
        ds = g.date.values
        av50 = pd.Series(v).rolling(50, min_periods=30).mean().shift(1).values
        val20 = pd.Series(val).rolling(20).mean().values
        ma20 = pd.Series(c).rolling(20).mean().values
        i, n = 120, len(c)
        while i < n - 1:
            if ds[i] < SIG0:
                i += 1; continue
            ok = (val20[i] >= 3e9 and c[i] >= 1000 and c[i] > c[i - 1] and c[i] / c[i - 1] - 1 < 0.295
                  and c[i] > h[max(0, i - 250):i].max() and av50[i] and v[i] / av50[i] >= 1.5 and o[i + 1] / c[i] - 1 < 0.295)
            if not ok:
                i += 1; continue
            buy = o[i + 1]; sp = buy * 0.92; out_i = None; ret = None
            for k in range(i + 1, min(n, i + 61)):
                if l[k] <= sp:
                    ret = (min(o[k], sp) if k > i + 1 else sp) / buy - 1 - E.COST; out_i = k; break
                if c[k] < ma20[k] and k + 1 < n:
                    ret = o[k + 1] / buy - 1 - E.COST; out_i = k + 1; break
            if ret is None:
                if i + 61 < n:
                    ret = o[i + 61] / buy - 1 - E.COST; out_i = i + 61
                else:
                    break                                   # 아직 안 끝난 매매는 뺌
            out.append(dict(date=ds[i + 1], t=time(9, 0), kind="7️⃣", code=code, px=buy, ret=ret, sell_d=ds[out_i],
                            rk=-val[i], xt=None, sig=ds[i]))
            i = out_i                                       # 들고 있는 동안 같은 종목 새 신호 없음
    return out


def run(trades, kinds, days, label):
    S.DAYS = days; S.SPLIT = days[len(days) // 2]
    r = C.real_sim(trades, kinds=kinds)
    say(f"  {label:34s} 10만 → {r['final']:>12,.0f}원 낙폭 {r['mdd']:.1%} 앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} {'★' if r['star'] else ' '}"
        f" | " + " ".join(f"{('스윙' if k == '7️⃣' else k)} {v / 1e4:+.1f}만({r['n'].get(k, 0)}건)" for k, v in r["pnl"].items())
        + f" | 못 삼 {r['skip'].get('예수금 부족', 0)}")
    return r


def main():
    sw = swing_trades()
    say(f"250일 신고가 스윙 매매 {len(sw)}건 ({min(t['date'] for t in sw)} ~ {max(t['date'] for t in sw)}), 건당 {np.mean([t['ret'] for t in sw]):+.2%}, "
        f"평균 보유 {np.mean([(pd.Timestamp(t['sell_d']) - pd.Timestamp(t['date'])).days for t in sw]):.0f}일(달력)")
    for y in sorted({t['date'].year for t in sw}):
        x = [t['ret'] for t in sw if t['date'].year == y]; say(f"   {y}: {len(x)}건 {np.mean(x):+.2%}")
    pickle.dump(sw, open(os.path.join(OUT, "swing250_trades.pkl"), "wb"))

    say("\n## 1) 스윙만 · 10만 계좌 (4년, 종목당 3만 원)")
    all_days = [d for d in E.CAL if d >= SIG0]
    run(sw, {"7️⃣"}, all_days, "4년 2022-07~")
    for y0, y1 in ((date(2022, 7, 1), date(2023, 6, 30)), (date(2023, 7, 1), date(2024, 6, 30)), (date(2024, 7, 1), date(2025, 6, 30)), (date(2025, 7, 1), date(2026, 10, 30))):
        run([t for t in sw if y0 <= t['date'] <= y1], {"7️⃣"}, [d for d in all_days if y0 <= d <= y1], f"{y0:%Y-%m}~{y1:%Y-%m} (10만에서 다시 시작)")

    say("\n## 2) 지금 실전 구성과 함께 (1년, 1분봉 매매 기록 기간)")
    base = C.apply(pickle.load(open(os.path.join(C.OUT, "trades_feat.pkl"), "rb")), C.ALT)
    base = [t for t in base if t["kind"] != "7️⃣"]
    days1 = list(S.DAYS)
    REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}
    sw1 = [t for t in sw if days1[0] <= t["date"] <= days1[-1]]
    run(base, REAL, days1, "지금 실전")
    run(base + sw1, REAL | {"7️⃣"}, days1, "지금 실전 + 스윙")
    run(sw1, {"7️⃣"}, days1, "스윙만 (같은 1년)")
    for d0 in (date(2026, 8, 1),):
        dd = [d for d in days1 if d >= d0]
        run([t for t in base if t["date"] >= d0], REAL, dd, "최근 3달: 지금 실전")
        run([t for t in base + sw1 if t["date"] >= d0], REAL | {"7️⃣"}, dd, "최근 3달: 지금 실전 + 스윙")
        run([t for t in sw1 if t["date"] >= d0], {"7️⃣"}, dd, "최근 3달: 스윙만")


if __name__ == "__main__":
    main()
