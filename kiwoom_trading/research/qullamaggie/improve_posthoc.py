"""🏄 쿨라매기 돌파 — 사후 확인 (improve.py 참고 표를 본 뒤 덧붙임, 고르는 절차 밖).

improve.py 참고 표에서 '고르는 기간·확인 기간·A 1시간봉' 세 곳 모두 기준보다 좋았던 매도 변경(E4 절반 안 팖·20일선, E6 본전 없앰·20일선)을
자세히 봄: 최고 5·10건 뺀 합계, 해마다, 계좌 10만 달러, 비용 0.25%. 확인 기간을 이미 본 뒤 고른 것이라 '확인'이 아니라 '사후 관찰'임.

실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv/Scripts/python.exe kiwoom_trading/research/qullamaggie/improve_posthoc.py
출력: data/qullamaggie_us/improve_posthoc.txt
"""
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, r"D:\Ellie\trading")
from kiwoom_trading.research.qullamaggie import improve as IM   # noqa: E402
from kiwoom_trading.research.qullamaggie import us_bt as U       # noqa: E402


def main():
    R = IM.Rep("improve_posthoc.txt")
    sec = IM.sectors()
    uni, src, d0, h0, fails = U.load()
    d0 = d0[~(d0[["open", "high", "low", "close", "adjclose"]] <= 0).any(axis=1)]
    d = IM.prepare(d0)
    spyd = d[d.sym == "SPY"].set_index("date")
    cal = list(spyd.index)
    d = d[d.date.isin(set(cal))]
    spyf = {}
    for k in range(2, len(cal)):
        p, pp = spyd.iloc[k - 1], spyd.iloc[k - 2]
        spyf[cal[k]] = dict(m10=bool(p.close > p.ma10), m20=bool(p.close > p.ma20), m50=bool(p.close > p.ma50) if np.isfinite(p.ma50) else None,
                            u10=bool(p.ma10 > pp.ma10), u20=bool(p.ma20 > pp.ma20))
    spy_close = spyd.close.to_dict()
    stocks_d = d[d.sym != "SPY"]
    px = IM.Px(stocks_d)
    h0 = h0.copy(); h0["date"] = h0.ts.dt.date
    mins = h0.ts.dt.hour * 60 + h0.ts.dt.minute
    h0 = h0[(mins >= 570) & (mins <= 930)]
    H, HV = {}, {}
    for s_, g in h0.groupby(["sym", "date"]).volume.sum().groupby(level=0):
        HV[s_] = g.droplevel(0).rolling(20, min_periods=10).mean().shift(1).dropna().to_dict()
    for (s_, dt), g in h0.groupby(["sym", "date"], sort=False):
        H.setdefault(s_, {})[dt] = list(zip(list(g.ts.dt.to_pydatetime()), g.open.values, g.high.values, g.low.values, g.close.values, g.volume.values))
    hd = sorted(set(h0.date)); a_start, a_end = hd[0], min(hd[-1], cal[-1])
    b_start, b_end = cal[130], cal[-1]

    def bars_B(s):
        return lambda dt: None

    def bars_A(s):
        A = px.a[s]

        def f(dt):
            x = H.get(s, {}).get(dt)
            if x is None or len(x) < 5:
                return None
            ff = A["F"][A["pos"][dt]]
            return [(ts, o * ff, h * ff, l * ff, c * ff) for ts, o, h, l, c, v in x]
        return f
    cw = IM.candidates(stocks_d, px, cal, b_start, b_end)
    EB = IM.entries_B(px, cw, spyf, sec)
    EA = IM.entries_A(px, [c for c in cw if a_start <= c["D"] <= a_end], spyf, sec, H, HV)
    IS = [e for e in EB if e["D"] <= IM.IS_END]; OOS = [e for e in EB if e["D"] > IM.IS_END]
    cache = {}
    R.say("사후 관찰 — improve.py 참고 표(확인 기간 결과)를 본 뒤 고른 매도 변경. 고르는 절차 밖이라 '확인'이 아님. 비용 0.1%")
    for nm, fl, ex in (("(기준) 지금 규칙", [], "E0 지금(5일째 절반·본전·10일선)"),
                       ("E4 절반 안 팖·20일선", [], "E4 절반 안 팖·20일선"),
                       ("E6 본전 없앰·20일선", [], "E6 본전 없앰·20일선"),
                       ("E3 20일선 트레일", [], "E3 20일선 트레일"),
                       ("ADR ≥ 4% + E4", ["ADR ≥ 4%"], "E4 절반 안 팖·20일선")):
        R.say(f"\n[{nm}]")
        for pn, E, end, bm in (("B 고르는 기간", IS, IM.IS_END, bars_B), ("B 확인 기간", OOS, b_end, bars_B), ("A 1시간봉", EA, a_end, bars_A)):
            T = IM.run(E, IM.compose(fl), IM.EXITS[ex], end, px, bm, cache)
            st = IM.stats(T)
            R.say(IM.line(pn, st, 16))
            R.say(IM.line(pn + " 비용 0.25%", IM.stats(T, 0.0025), 16))
            v = np.sort((T.gross - IM.COST).values)[::-1]
            r = np.sort(((T.gross - IM.COST) / np.maximum(T.s, 0.005)).values)[::-1]
            R.say(f"     최고 5건 빼면 {v[5:].sum():+.0%} ({r[5:].sum():+.1f}R) · 최고 10건 빼면 {v[10:].sum():+.0%} ({r[10:].sum():+.1f}R) · "
                  f"보유 평균 {np.mean([(x - y).days for x, y in zip(T.exit_date, T.D)]):.0f}일(달력) · 마지막 매도 {dict(Counter(T['last']))}")
            if pn != "A 1시간봉":
                R.say("     해마다: " + " · ".join(f"{y} {len(g)}건 {(g.gross - IM.COST).sum():+.0%}" for y, g in T.groupby(T.D.map(lambda x: x.year))))
            TT = T.rename(columns={"D": "date"}).reset_index(drop=True)
            a = U.account(TT, cal, end, px, IM.COST, spy_close)
            a2 = U.account(TT, cal, end, px, 0.0025, spy_close)
            R.say(f"     10만 달러: {a['first']}~{a['last']} ${a['final']:,.0f} ({a['ret']:+.0%}, 연 {a['cagr']:+.1%}) 낙폭 {a['mdd']:.0%} · 비용 0.25% ${a2['final']:,.0f} "
                  f"| SPY {a['sp_ret']:+.0%} (연 {a['sp_cagr']:+.1%}, 낙폭 {a['sp_mdd']:.0%}) | 못 산 {a['skipped']}")


if __name__ == "__main__":
    main()
