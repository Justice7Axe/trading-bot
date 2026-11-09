"""조회 상위 진입 = 익절 신호? (2026-10-30, 연구 전용) — 1단계: 보유 구간 목록 + 그 안의 조회 상위 첫 진입 사건.

보유 구간 출처
  paper    : 스캐너 DB 복사본 paper_trades (closed, 10-13~), 일부 익절(part_qty/part_price) 섞어 실제 수익률
  real     : real_trades (closed)
  bt       : data/account_alloc/trades.pkl (1년 매매 목록, 10-13~10-22 만 조회 자료와 겹침), ret = 비용 뺀 값
사건 (조회 1분 순위 search_1m, 상위 20 만 저장)
  A = 그날 08:00 부터 매수 시각까지 상위 N 에 한 번도 없다가 보유 중 처음 들어옴 ('처음 들면')
  B = 보유 중, 직전 30분 동안 상위 N 에 없다가 새로 들어온 첫 분 (매수 전 이미 상위였다 빠진 뒤 다시 듦·다음 날 아침 첫 등장 포함)
  N = 20, 10.  보유 다음 날(밤샘)은 그날 08:00 부터 다시 셈 (A 는 매수일 이력만 봄 → 다음 날 08:00 진입도 A)
출력: data/search_sell/positions.parquet, events.parquet
"""
import os
import pickle
from datetime import datetime, time, timedelta, date

import duckdb
import numpy as np
import pandas as pd

ROOT = r"D:\Ellie\trading"
OUT = os.path.join(ROOT, "data", "search_sell"); os.makedirs(OUT, exist_ok=True)
S = duckdb.connect(os.path.join(ROOT, "data", "screener_snapshot.duckdb"), read_only=True)
TRADING = [date(2026, 10, x) for x in (13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30)]
ETF_WORDS = ("KODEX", "TIGER", "인버스", "레버리지", "RISE", "ACE", "SOL ", "PLUS")


def nxt(d):
    later = [x for x in TRADING if x > d]
    return later[0] if later else None


def cost_of(name):
    return 0.0005 if name and any(w in name for w in ETF_WORDS) else 0.0025


def paper_rows():
    df = S.execute("""SELECT id, date, code, name, kind, mode, buy_ts, buy_price, qty, sell_ts, sell_price, sell_reason,
                             part_qty, part_price, virtual, overflow
                      FROM paper_trades WHERE status='closed' AND date>='2026-10-13'
                        AND buy_ts IS NOT NULL AND sell_ts IS NOT NULL AND buy_price>0 AND sell_price>0""").df()
    out = []
    for r in df.itertuples():
        q = r.qty or 0; pq = int(r.part_qty) if pd.notna(r.part_qty) else 0
        if pq > 0 and q > 0 and pd.notna(r.part_price):
            px = (pq * r.part_price + (q - pq) * r.sell_price) / q     # qty = 처음 수량이라 가정 (part_qty ≤ qty)
        else:
            px = r.sell_price
        c = cost_of(r.name)
        out.append(dict(src="paper", id=r.id, date=r.date, code=r.code, name=r.name, kind=r.kind, mode=r.mode,
                        buy_ts=pd.Timestamp(r.buy_ts), buy=float(r.buy_price), exit_ts=pd.Timestamp(r.sell_ts),
                        act=px / r.buy_price - 1 - c, cost=c, reason=r.sell_reason, part=pq > 0,
                        virtual=bool(r.virtual), overflow=bool(r.overflow)))
    return out


def real_rows():
    df = S.execute("""SELECT id, date, code, name, kind, buy_ts, buy_price, qty, sell_ts, sell_price, reason, part_qty, part_price
                      FROM real_trades WHERE status='closed' AND sell_price>0""").df()
    out = []
    for r in df.itertuples():
        c = cost_of(r.name)
        out.append(dict(src="real", id=r.id, date=r.date, code=r.code, name=r.name, kind=r.kind, mode="실전",
                        buy_ts=pd.Timestamp(r.buy_ts), buy=float(r.buy_price), exit_ts=pd.Timestamp(r.sell_ts),
                        act=r.sell_price / r.buy_price - 1 - c, cost=c, reason=r.reason, part=False, virtual=False, overflow=False))
    return out


def bt_rows():
    T = pickle.load(open(os.path.join(ROOT, "data", "account_alloc", "trades.pkl"), "rb"))
    names = dict(S.execute("SELECT DISTINCT code, name FROM rank_snapshots WHERE date>='2026-10-13'").fetchall())
    out = []
    for i, t in enumerate(T):
        d = t["date"]
        if d < date(2026, 10, 13): continue
        if t.get("sell_d") is not None and not (isinstance(t["sell_d"], float) and np.isnan(t["sell_d"])):
            ex = pd.Timestamp(datetime.combine(t["sell_d"], time(9, 0)))       # 7️⃣ 추세 (기간 안에 없음)
        elif t.get("xt") is not None:
            ex = pd.Timestamp(datetime.combine(d, t["xt"]))
        else:
            n = nxt(d)
            if n is None: continue
            ex = pd.Timestamp(datetime.combine(n, time(9, 0)))
        nm = names.get(t["code"], "")
        out.append(dict(src="bt", id=f"bt{i}", date=d, code=t["code"], name=nm, kind=t["kind"], mode="",
                        buy_ts=pd.Timestamp(datetime.combine(d, t["t"])), buy=float(t["px"]), exit_ts=ex,
                        act=float(t["ret"]), cost=cost_of(nm), reason=("장중 매도" if t.get("xt") else "다음 날 09:00"),
                        part=(t["kind"] == "🔁"), virtual=False, overflow=False))
    return out


def search_table():
    df = S.execute("""SELECT ts, date, rank, code, price FROM rank_snapshots WHERE source='search_1m' AND date>='2026-10-13'""").df()
    df["hm"] = df.ts.dt.floor("min")
    df = df.sort_values("ts").drop_duplicates(["date", "hm", "code"], keep="last")
    return df


if __name__ == "__main__":
    P = pd.DataFrame(paper_rows() + real_rows() + bt_rows())
    P["date"] = pd.to_datetime(P.date).dt.date
    print(P.groupby("src").size().to_dict(), flush=True)
    sr = search_table()
    by = {k: g.sort_values("ts") for k, g in sr.groupby("code")}
    snap_min = {d: sorted(g.hm.unique()) for d, g in sr.groupby("date")}      # 날짜별 스냅샷 찍힌 분
    ev = []
    for p in P.itertuples():
        g = by.get(p.code)
        if g is None: continue
        day0 = pd.Timestamp(datetime.combine(p.date, time(8, 0)))
        for N in (20, 10):
            gn = g[g["rank"] <= N]
            pres = set(gn.hm)
            before = gn[(gn.ts >= day0) & (gn.ts <= p.buy_ts)]
            hold = gn[(gn.ts > p.buy_ts) & (gn.ts < p.exit_ts)]
            if not len(hold): continue
            # A: 매수일 08:00~매수 사이 한 번도 없음 → 보유 중 첫 등장
            if not len(before):
                f = hold.iloc[0]
                ev.append(dict(id=p.id, src=p.src, N=N, var="A", ev_ts=f.ts, ev_hm=f.hm, ev_rank=int(f["rank"]),
                               ev_price=float(f.price), pnl_at=float(f.price) / p.buy - 1))
            # B: 직전 30분(같은 날, 스냅샷 기준) 상위 N 에 없다가 새로 들어온 첫 분 (밤샘 다음 날 아침 첫 등장 포함)
            for f in hold.itertuples():
                mins = snap_min.get(f.date, [])
                prev = [m for m in mins if f.hm - timedelta(minutes=30) <= m < f.hm]
                if any(m in pres for m in prev): continue
                ev.append(dict(id=p.id, src=p.src, N=N, var="B", ev_ts=f.ts, ev_hm=f.hm, ev_rank=int(f.rank),
                               ev_price=float(f.price), pnl_at=float(f.price) / p.buy - 1))
                break
    E = pd.DataFrame(ev)
    P.to_parquet(os.path.join(OUT, "positions.parquet")); E.to_parquet(os.path.join(OUT, "events.parquet"))
    print(E.groupby(["src", "N", "var"]).size(), flush=True)
