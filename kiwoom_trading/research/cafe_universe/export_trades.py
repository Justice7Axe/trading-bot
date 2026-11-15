"""기존 매매 1년 매매 목록을 한 표로 → data/cafe_history/trades_all.csv (카페 종목 제한 비교 입력, 2026-11-15).

출처 (새 규칙 안 만듦, 저장된 목록 그대로 또는 기존 함수 그대로):
  1️⃣2️⃣3️⃣4️⃣6️⃣7️⃣🌙📕🔁☕  data/account_alloc/trades.pkl (research/account_alloc/build_trades.py, 2025-10-16~2026-10-22)
     5️⃣ 약세장 인버스는 ETF(카페 제한 밖)라 뺌.
  🏄 쿨라매기 돌파  data/qullamaggie/improve_kr_trades_500__기준_지금_규칙_5거래일째_절반_.csv (전날 대금 상위 500, 수익 = gross − 0.25%)
     + 참고로 전날 대금 상위 50 판 (🏄50).
  🪜 애프터 정배열  data/ma120_cross/align_bt.csv  GC+ALN · 전날 애프터 ≥ 2% · ~10:40 (모의 규칙과 같음), 매수가 = 신호 다음 봉 시가
  📍 중심선        strategies/centerline backtest_strong.strong_entry + backtest_cross.exit_ (기준봉 대금 10위·시총 5천억↑·돌파 봉 5배·익절 +3%·C−1%, 모의 규칙)
  📈 켈 수축 돌파 · 📏 변동성 돌파 · 🐢 터틀 돌파: 백테스트 없음(모의만, '백테스트 안 함') → 목록 없음.
칸: kind, date, t(매수 시각), code, px(매수 1분봉 원가격), ret(비용 뺀 수익률), sell_d(현금 돌아오는 날, 없으면 다음 거래일)
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.cafe_universe.export_trades
"""
from __future__ import annotations

import os
import pickle
import sys
from datetime import date, datetime, time

import pandas as pd

ROOT = r"D:\Ellie\trading"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "cafe_history")
COST = 0.0025


def from_alloc() -> list[dict]:
    T = pickle.load(open(os.path.join(DATA, "account_alloc", "trades.pkl"), "rb"))
    out = []
    for t in T:
        if t["kind"] == "5️⃣":
            continue
        out.append(dict(kind=t["kind"], date=t["date"], t=t["t"], code=str(t["code"]).zfill(6), px=t["px"], ret=t["ret"],
                        sell_d=t.get("sell_d")))
    return out


def from_qulla() -> list[dict]:
    out = []
    for pool, lab in (("500", "🏄"), ("50", "🏄50")):
        p = os.path.join(DATA, "qullamaggie", f"improve_kr_trades_{pool}__기준_지금_규칙_5거래일째_절반_.csv")
        df = pd.read_csv(p, dtype={"sym": str}, encoding="utf-8-sig")
        for r in df.itertuples():
            ts = pd.Timestamp(r.buy_ts)
            out.append(dict(kind=lab, date=ts.date(), t=ts.time(), code=str(r.sym).zfill(6), px=float(r.buy),
                            ret=float(r.gross) - COST, sell_d=pd.Timestamp(r.exit_date).date()))
    return out


def from_align(E) -> list[dict]:
    df = pd.read_csv(os.path.join(DATA, "ma120_cross", "align_bt.csv"), dtype={"code": str}, encoding="utf-8-sig")
    df = df[(df.kind == "GC+ALN") & (df.after >= 0.02) & (df["last"] == "10:40")]
    out = []
    for r in df.itertuples():
        ts = pd.Timestamp(r.T); d = ts.date(); c = str(r.code).zfill(6)
        b = E.bars(c, d) if d <= E.P1 else []
        nb = next((x for x in b if x[0] > ts.time()), None)
        out.append(dict(kind="🪜", date=d, t=(nb[0] if nb else ts.time()), code=c, px=float(nb[1]) if nb else float("nan"),
                        ret=float(r.ret), sell_d=None))
    return out


def from_centerline(E) -> list[dict]:
    from kiwoom_trading.strategies.centerline import backtest_strong as S
    from kiwoom_trading.strategies.centerline import backtest_cross as X
    out = []
    for b in X.B.bases(0.10):
        d0, c = b[0], b[1]
        if E.value_rank(d0).get(c, 9999) > 10 or E.mcap(c, d0) < 5e11:
            continue
        e = S.strong_entry(b, 5, False)
        if not e:
            continue
        d, bars, j, C = e
        r, _ = X.exit_(c, d, bars, j, C, 0.03, "S2")
        if r is None or abs(r) >= 0.35:
            continue
        out.append(dict(kind="📍", date=d, t=bars[j][0], code=c, px=float(bars[j][1]), ret=float(r), sell_d=None))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    rows = from_alloc() + from_qulla()
    from kiwoom_trading.backtest import engine as E
    rows += from_align(E)
    rows += from_centerline(E)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "trades_all.csv"), index=False, encoding="utf-8-sig")
    print(df.groupby("kind").agg(n=("ret", "size"), mean=("ret", "mean"), d0=("date", "min"), d1=("date", "max")))


if __name__ == "__main__":
    main()
