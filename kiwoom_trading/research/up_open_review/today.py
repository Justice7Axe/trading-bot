"""2026-11-04 1️⃣ 상승장 장 초 신호 25종목 — 09:10 에 알 수 있던 정보와 그 뒤 결과 (2026-11-04 사용자 '광전자는 왜 손실, 다른 종목은 왜 이익').

입력 (모두 읽기만): data/screener_snapshot.duckdb (rank_snapshots 1분 간격 가격·대금, buy_signals, paper_trades, real_trades),
                  data/daily_ohlcv.duckdb (일봉·수급·상장 정보 — 11-03 까지).
오늘 1분봉은 아직 없어 rank_snapshots(대금 상위 200 안에 있을 때만, 약 1분 간격) 가격으로 경로를 만든다 → 장중 최고·최저는 근사.
9-14 이후 일봉 종가 = 20:00 애프터 종가라, 전일 종가는 rank_snapshots 의 등락률(정규장 KRX 기준)로 거꾸로 구한다.
출력: data/up_open_review/today.txt · today.pkl
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.up_open_review.today
"""
import os
import pickle
import re
import sys
from datetime import date, datetime, time

import duckdb

DATA = r"D:\Ellie\trading\data"
OUT = os.path.join(DATA, "up_open_review")
os.makedirs(OUT, exist_ok=True)
D = date(2026, 11, 4)
PREV = date(2026, 11, 3)
KIND = "상승장 장 초"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = duckdb.connect(os.path.join(DATA, "screener_snapshot.duckdb"), read_only=True)
    dm = duckdb.connect(os.path.join(DATA, "daily_ohlcv.duckdb"), read_only=True)
    sig = s.execute("SELECT code, name, price, level, reason FROM buy_signals WHERE date=? AND kind=? ORDER BY ts", [D, KIND]).fetchall()
    paper = {(c, k): (st, bp, sp, sr) for c, k, st, bp, sp, sr in s.execute(
        "SELECT code, kind, status, buy_price, sell_price, sell_reason FROM paper_trades WHERE date=?", [D]).fetchall()}
    real = {c: (bp, sp, r, st) for c, bp, sp, r, st in s.execute(
        "SELECT code, buy_price, sell_price, reason, status FROM real_trades WHERE date=?", [D]).fetchall()}
    days = [d for (d,) in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ? ORDER BY date DESC LIMIT 260", [D]).fetchall()]
    rows = []
    for code, name, px10, opn, reason in sig:
        rk = int(re.search(r"대금 (\d+)위", reason).group(1))
        snap = s.execute("""SELECT ts, rank, change_rate, price, trade_value FROM rank_snapshots WHERE date=? AND source='value_krx' AND code=?
                            ORDER BY ts""", [D, code]).fetchall()
        pre = [x for x in snap if x[0].time() < time(9, 10, 30)]
        post = [x for x in snap if x[0].time() >= time(9, 10, 30)]
        x10 = pre[-1] if pre else None
        pc = x10[3] / (1 + x10[2]) if x10 else None          # 정규장 전일 종가 (등락률로 거꾸로)
        hi10 = max([x[3] for x in pre] + [px10])
        lo10 = min([x[3] for x in pre] + [opn])
        val10 = x10[4] if x10 else None
        buy = paper.get((code, KIND), (None, None))[1] or real.get(code, (None,))[0] or px10
        stop = buy * 0.94
        mx = max((x[3] for x in post), default=None)
        mn = min((x[3] for x in post), default=None)
        hit = next((x[0] for x in post if x[3] <= stop), None)
        last = post[-1] if post else None
        # 일봉 (11-03 까지): 최근 10일 대금·등락, 52주 고가
        h = dm.execute("""SELECT date, open, high, low, close, value FROM daily_ohlcv WHERE code=? AND date < ? ORDER BY date DESC LIMIT 260""",
                       [code, D]).fetchall()
        st = dm.execute("SELECT list_date, listed_shares, sector, market FROM stocks WHERE code=?", [code]).fetchone() or (None, None, None, None)
        inv = dm.execute("SELECT date, foreign_, institution FROM investor_daily WHERE code=? AND date < ? ORDER BY date DESC LIMIT 5",
                         [code, D]).fetchall()
        v20 = [r[5] for r in h[:20] if r[5]]
        avg20 = sum(v20) / len(v20) if v20 else None
        hi250 = max(r[2] for r in h[:250]) if h else None
        mx10 = max(h[:10], key=lambda r: r[5] or 0) if h else None
        rows.append(dict(
            code=code, name=name, rk=rk, krx_rank=x10[1] if x10 else None, open=opn, px10=px10, pc=pc,
            gap=opn / pc - 1 if pc else None, chg10=px10 / pc - 1 if pc else None, from_open=px10 / opn - 1,
            off_hi=px10 / hi10 - 1, pos=(px10 - lo10) / (hi10 - lo10) if hi10 > lo10 else 1.0, hi10=hi10,
            val10=val10, val10_ratio=val10 / avg20 if val10 and avg20 else None, avg20=avg20,
            buy=buy, mx=mx, mn=mn, max_up=mx / buy - 1 if mx else None, max_dn=mn / buy - 1 if mn else None,
            stop_ts=hit, last_ts=last[0] if last else None, last=last[3] if last else None, last_ret=last[3] / buy - 1 if last else None,
            d1=(h[0][4] / h[1][4] - 1) if len(h) > 1 else None, d5=(h[0][4] / h[5][4] - 1) if len(h) > 5 else None,
            prev_val=h[0][5] if h else None, prev_val_ratio=(h[0][5] / avg20) if h and avg20 else None,
            spike_day=mx10[0] if mx10 else None, spike_val=mx10[5] if mx10 else None,
            hi250_dist=(h[0][4] / hi250 - 1) if hi250 else None, ndays=len(h),
            list_date=st[0], mcap=(st[1] or 0) * (pc or 0), sector=st[2], market=st[3],
            fr=inv[0][1] if inv else None, ins=inv[0][2] if inv else None, inv5=inv,
            hist10=[(r[0], r[4], r[5]) for r in h[:10]],
            paper=paper.get((code, KIND)), real=real.get(code)))
    pickle.dump(rows, open(os.path.join(OUT, "today.pkl"), "wb"))
    f = open(os.path.join(OUT, "today.txt"), "w", encoding="utf-8")

    def say(t=""):
        print(t); f.write(t + "\n")
    say("2026-11-04 1️⃣ 상승장 장 초 신호 25종목 (09:10 정보 → 그 뒤 결과, 가격 경로는 rank_snapshots 약 1분 간격)")
    for r in sorted(rows, key=lambda r: r["rk"]):
        def p(v, n=1):
            return "  -  " if v is None else f"{v * 100:+.{n}f}%"
        say(f"{r['rk']:2d} {r['name']:10s} {r['code']} 시총 {r['mcap'] / 1e8:9,.0f}억 | 갭 {p(r['gap'])} 09:10 전일比 {p(r['chg10'])} 시가比 {p(r['from_open'])}"
            f" 고점比 {p(r['off_hi'])} 위치 {r['pos']:.2f} | 09:10 대금 {(r['val10'] or 0) / 1e8:6,.0f}억 (20일 평균의 {r['val10_ratio'] or 0:.2f}배)"
            f" | 전날 {p(r['d1'])} 5일 {p(r['d5'])} 전날 대금 {(r['prev_val'] or 0) / 1e8:6,.0f}억({r['prev_val_ratio'] or 0:.1f}배)"
            f" 10일 최대 대금 {r['spike_day']} {(r['spike_val'] or 0) / 1e8:,.0f}억 | 52주 고가比 {p(r['hi250_dist'])} 일수 {r['ndays']}"
            f" | 외인 {(r['fr'] or 0) / 1e8:+,.0f}억 기관 {(r['ins'] or 0) / 1e8:+,.0f}억"
            f" || 매수 {r['buy']:,.0f} 최고 {p(r['max_up'])} 최저 {p(r['max_dn'])} 손절 {r['stop_ts'].strftime('%H:%M') if r['stop_ts'] else '없음'}"
            f" 마지막({r['last_ts'].strftime('%H:%M') if r['last_ts'] else '-'}) {p(r['last_ret'])} | {r['sector']} | 모의 {r['paper']} 실전 {r['real']}")


if __name__ == "__main__":
    main()
