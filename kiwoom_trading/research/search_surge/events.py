"""조회 급증 + 거래대금 + 수급 조기 발굴 연구 — 1단계: 사건 목록 만들기 (2026-10-30, 연구 전용).

자료: data/screener_snapshot.duckdb (스캐너 DB 복사본)
  rank_snapshots: search_1m(1분 조회 순위 상위 20), search_day(누적 조회 상위 20), value_krx(KRX 누적 대금 상위 200, 매분)
사건 두 종류 (09:00~14:30, 종목·일 첫 번째만, 보통주만):
  S  = 조회(1분) 상위 20 에 그날(08:00 부터) 처음 들어온 분
  V  = 대금 가속 (V30 = 30억 문턱): value_krx 5분 대금 증가 ≥ 100억 & 5분 전 대비 가격 +1%↑ & 당일 +0%↑ 인 첫 분 (조회와 무관한 비교 기준)
출력: data/search_surge/events.parquet  (사건 분 기준 '그 분까지 아는 값'만)
"""
import os
from datetime import datetime, time, timedelta
import duckdb
import pandas as pd

ROOT = r"D:\Ellie\trading"
OUT = os.path.join(ROOT, "data", "search_surge"); os.makedirs(OUT, exist_ok=True)
SNAP = os.path.join(ROOT, "data", "screener_snapshot.duckdb")
DAILY = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "eng_daily_ohlcv.duckdb")   # 일봉 DB 복사본 (엔진이 만든 것)

S = duckdb.connect(SNAP, read_only=True)
D = duckdb.connect(DAILY, read_only=True)
COMMON = {c for (c,) in D.execute("SELECT code FROM stocks").fetchall() if c[-1] not in "579K"}
NAME = dict(D.execute("SELECT code, name FROM stocks").fetchall())
CAL = [d for (d,) in D.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]


def prev_day(d):
    return max(x for x in CAL if x < d)


def load(source, d):
    df = S.execute("SELECT ts, rank, code, change_rate, price, trade_value FROM rank_snapshots WHERE source=? AND date=? ORDER BY ts, rank",
                   [source, d]).df()
    df["hm"] = df.ts.dt.floor("min")
    # 같은 분에 두 번 찍힌 경우 마지막 것
    df = df.sort_values("ts").drop_duplicates(["hm", "code"], keep="last")
    return df


def build_day(d):
    s1 = load("search_1m", d); sd = load("search_day", d); vk = load("value_krx", d)
    if vk.empty or s1.empty:
        return []
    pdv = prev_day(d)
    # 전날 대금 순위 (일봉, 9-14 이후 통합 대금 — 순위용 근사) · 20일 평균 대금
    hist = D.execute("""SELECT code, date, value FROM daily_ohlcv WHERE date <= ? AND date > ? - INTERVAL 40 DAY""", [pdv, pdv]).df()
    hist = hist[hist.code.isin(COMMON)]; hist["date"] = pd.to_datetime(hist.date).dt.date
    last = hist[hist.date == pdv].sort_values("value", ascending=False)
    prev_rank = {c: i + 1 for i, c in enumerate(last.code)}
    days20 = sorted(hist.date.unique())[-20:]
    avg20 = hist[hist.date.isin(days20)].groupby("code").value.mean().to_dict()

    vk_c = vk[vk.code.isin(COMMON)]
    piv_v = vk_c.pivot(index="hm", columns="code", values="trade_value")
    piv_p = vk_c.pivot(index="hm", columns="code", values="price")
    piv_cr = vk_c.pivot(index="hm", columns="code", values="change_rate")
    rank_c = vk_c.copy(); rank_c["crank"] = rank_c.groupby("hm").trade_value.rank(ascending=False, method="first")   # 보통주끼리 순위
    piv_r = rank_c.pivot(index="hm", columns="code", values="crank")
    piv_r_all = vk.pivot(index="hm", columns="code", values="rank")
    grid = pd.date_range(datetime.combine(d, time(8, 0)), datetime.combine(d, time(20, 0)), freq="min")
    piv_v, piv_p, piv_r, piv_cr = [x.reindex(grid).ffill(limit=2) for x in (piv_v, piv_p, piv_r, piv_cr)]
    _hs = set(vk.hm); mins = [m for m in grid if m in _hs]

    def vk_at(code, hm, back=0):
        t = hm - timedelta(minutes=back)
        if code not in piv_v.columns or t not in piv_v.index: return None, None, None, None
        v = piv_v.at[t, code]
        if pd.isna(v): return None, None, None, None
        return v, piv_p.at[t, code], piv_r.at[t, code], piv_cr.at[t, code]

    sd_rank = sd.pivot(index="hm", columns="code", values="rank")
    s1_rank = s1.pivot(index="hm", columns="code", values="rank")

    def search_feats(code, hm):
        r1 = s1_rank[code].loc[:hm].dropna() if code in s1_rank.columns else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        rdd = sd_rank[code].loc[:hm].dropna() if code in sd_rank.columns else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        rec = r1[r1.index > hm - timedelta(minutes=10)]
        return dict(s1_rank=(r1.iloc[-1] if len(r1) and r1.index[-1] == hm else None),
                    s1_best10=(rec.min() if len(rec) else None), s1_cnt10=len(rec),
                    s1_first=(r1.index[0] if len(r1) else None),
                    sday_rank=(rdd.iloc[-1] if len(rdd) and rdd.index[-1] >= hm - timedelta(minutes=2) else None))

    t0 = datetime.combine(d, time(9, 0)); t1 = datetime.combine(d, time(14, 30))
    out = []
    # ---- S 사건: 조회 1분 상위 20 첫 등장
    s1c = s1[s1.code.isin(COMMON)]
    first = s1c.groupby("code").hm.min()
    s10 = s1c[s1c["rank"] <= 10].groupby("code").hm.min()
    for code, hm in first.items():
        if not (t0 <= hm <= t1): continue
        row = s1c[(s1c.code == code) & (s1c.hm == hm)].iloc[0]
        out.append(dict(kind="S", code=code, hm=hm, s_rank_at=row["rank"], cr_search=row.change_rate, price_search=row.price,
                        first_top10=s10.get(code)))
    # ---- V 사건: 대금 가속 (조회와 무관)
    vv = piv_v.loc[t0 + timedelta(minutes=5):t1]
    dv = vv - piv_v.shift(5).loc[vv.index]
    up = piv_p.loc[vv.index] >= piv_p.shift(5).loc[vv.index] * 1.01
    for kind, th in (("V", 100e8), ("V30", 30e8)):
        ok = (dv >= th) & up & (piv_cr.loc[vv.index] >= 0)
        for code in ok.columns:
            hit = ok[code][ok[code]]
            if len(hit):
                out.append(dict(kind=kind, code=code, hm=hit.index[0], s_rank_at=None, cr_search=None, price_search=None, first_top10=None))
    rows = []
    for e in out:
        code, hm = e["code"], e["hm"]
        v0, p0, r0, cr0 = vk_at(code, hm)
        v5, _, r5, _ = vk_at(code, hm, 5)
        v10, _, r10, _ = vk_at(code, hm, 10)
        sf = search_feats(code, hm)
        e.update(date=d, name=NAME.get(code), vk_value=v0, vk_rank=r0, vk_rank5=r5, vk_rank10=r10,
                 vk_v5=(v0 - v5) if (v0 is not None and v5 is not None) else None,
                 vk_v10=(v0 - v10) if (v0 is not None and v10 is not None) else None,
                 cr=(cr0 if cr0 is not None else e["cr_search"]), price_snap=(p0 if p0 is not None else e["price_search"]),
                 prev_vrank=prev_rank.get(code), avg20=avg20.get(code), **sf)
        rows.append(e)
    return rows


def regime_0910(d):
    """09:10 대금 상위 보통주 중앙 등락 (스캐너 판정 근사: ≥+2% 상승장 U, ≤−1.5% 하락장 D, 나머지 N)."""
    df = S.execute("""SELECT code, change_rate FROM rank_snapshots WHERE source='value_krx' AND date=?
                      AND ts >= ? AND ts < ? """, [d, datetime.combine(d, time(9, 10)), datetime.combine(d, time(9, 11))]).df()
    df = df[df.code.isin(COMMON)].drop_duplicates("code")
    m = df.change_rate.median()
    return m, ("U" if m >= 0.02 else "D" if m <= -0.015 else "N")


if __name__ == "__main__":
    dates = [d for (d,) in S.execute("SELECT DISTINCT date FROM rank_snapshots WHERE source='value_krx' ORDER BY 1").fetchall()]
    allr = []
    for d in dates:
        r = build_day(d); m, g = regime_0910(d)
        for x in r: x["mkt_med"] = m; x["regime"] = g
        allr += r
        print(d, g, f"{m:+.2%}", "S", sum(x["kind"] == "S" for x in r), "V", sum(x["kind"] == "V" for x in r), "V30", sum(x["kind"] == "V30" for x in r))
    df = pd.DataFrame(allr)
    df.to_parquet(os.path.join(OUT, "events.parquet"))
    print(len(df), df.groupby("kind").size().to_dict())
