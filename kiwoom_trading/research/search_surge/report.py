"""4단계: trades.parquet → 조건별 성적표 data/search_surge/report.txt

★ = 앞 반(날짜 기준)·뒤 반 모두 + & 가장 좋은 5일을 빼도 합계 +  (backtest-rules)
"""
import itertools, os
from datetime import date, time
import numpy as np
import pandas as pd

OUT = r"D:\Ellie\trading\data\search_surge"
tr = pd.read_parquet(os.path.join(OUT, "trades.parquet"))
f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")
MAIN = os.environ.get("MAIN", "x_s3_t5")


def say(s=""):
    print(s); f.write(s + "\n")


def st(df, col=MAIN):
    d = df.dropna(subset=[col])
    v = d[col].values
    if len(v) == 0: return None
    ds = sorted(d.date.unique()); h = ds[len(ds) // 2] if len(ds) > 1 else ds[0]
    a = d[d.date < h][col]; b = d[d.date >= h][col]
    bd = d.groupby("date")[col].sum().sort_values(ascending=False)
    rest = bd.iloc[5:].sum()
    star = len(v) >= 15 and len(a) and len(b) and a.mean() > 0 and b.mean() > 0 and rest > 0
    return dict(n=len(v), days=len(bd), mean=v.mean(), med=np.median(v), win=(v > 0).mean(), sum=v.sum(),
                a=a.mean() if len(a) else np.nan, b=b.mean() if len(b) else np.nan, rest5=rest, star=star,
                mfe=d.mfe30.mean(), mae=d.mae30.mean())


def line(title, df, col=MAIN, w=44):
    r = st(df, col)
    if not r: say(f"  {title:{w}s}    0건"); return r
    say(f" {'★' if r['star'] else ' '}{title:{w}s} {r['n']:4d}건 {r['days']:2d}일 건당 {r['mean']:+.2%} 중앙 {r['med']:+.2%} 승률 {r['win']:.0%} "
        f"| 앞 {r['a']:+.2%} 뒤 {r['b']:+.2%} 최고5일빼면 {r['rest5']*100:+.0f}% | 30분 최고 {r['mfe']:+.1%} 최저 {r['mae']:+.1%}")
    return r


def bucket(s, edges, labels):
    return pd.cut(s, edges, labels=labels, right=False)


S = tr[tr.kind == "S"].copy()
for df in (tr,):
    df["t"] = df.hm.dt.time
    df["tb"] = np.select([df.t < time(9, 10), df.t < time(10, 0), df.t < time(12, 0)], ["1) 09:00~09:10", "2) 09:10~10:00", "3) 10:00~12:00"], "4) 12:00~14:30")
    df["vk_b"] = np.select([df.vk_rank.isna(), df.vk_rank <= 20, df.vk_rank <= 50, df.vk_rank <= 100], ["5) 200위 밖", "1) ≤20", "2) 21~50", "3) 51~100"], "4) 101~200")
    df["v5_b"] = np.select([df.vk_v5.isna(), df.vk_v5 >= 100e8, df.vk_v5 >= 30e8, df.vk_v5 >= 10e8], ["5) 모름(200위 밖)", "1) ≥100억", "2) 30~100억", "3) 10~30억"], "4) <10억")
    df["cr_b"] = np.select([df.cr < 0, df.cr < 0.03, df.cr < 0.07, df.cr < 0.15, df.cr < 0.25], ["1) <0", "2) 0~3%", "3) 3~7%", "4) 7~15%", "5) 15~25%"], "6) ≥25%")
    df["vw_b"] = np.select([df.vs_vwap < 0, df.vs_vwap < 0.02, df.vs_vwap < 0.05], ["1) VWAP 아래", "2) 0~2%", "3) 2~5%"], "4) ≥5%")
    df["hi_b"] = np.select([df.vs_high >= -0.005, df.vs_high >= -0.03], ["1) 고점 근처(−0.5%)", "2) −0.5~−3%"], "3) −3% 아래")
    df["r5_b"] = np.select([df.v5_ratio.isna(), df.v5_ratio < 1, df.v5_ratio < 2, df.v5_ratio < 4], ["?", "1) <1배", "2) 1~2배", "3) 2~4배"], "4) ≥4배")
    df["pv_b"] = np.select([df.prev_vrank <= 50, df.prev_vrank <= 200], ["1) 전날 ≤50", "2) 51~200"], "3) 200 밖")
    df["vkup"] = df.vk_rank10 - df.vk_rank            # 10분 사이 대금 순위 오름 (+ = 오름)
    df["prog_b"] = np.select([df.prog.isna(), df.prog > 0], ["모름", "프로그램 +"], "프로그램 −/0")
    df["pd_b"] = np.select([df.prog_d20.isna(), df.prog_d20 > 0], ["모름", "20분 프로그램 +"], "20분 프로그램 −/0")
    df["fi_b"] = np.select([df.fore.isna() & df.inst.isna(), (df.fore > 0) & (df.inst > 0), (df.fore > 0) | (df.inst > 0)],
                           ["잠정치 없음", "외인·기관 둘 다 +", "한쪽만 +"], "둘 다 −")
    df["srch"] = df.s1_first.notna() & (df.s1_first <= df.hm)   # 그 분까지 조회 상위 20 에 든 적 있음
    df["srch10"] = df.s1_cnt10 > 0                                # 최근 10분 안에 조회 상위 20
S = tr[tr.kind == "S"].copy()

say(f"# 조회 급증 조기 발굴 연구 — 사건 분 다음 1분봉 시가 매수, 기본 매도 {MAIN} (손절 −3%·익절 +5%·아니면 다음 날 09:00), 비용 0.25%")
say(f"# 기간 {tr.date.min()} ~ {tr.date.max()} ({tr.date.nunique()}거래일), S=조회 1분 상위 20 첫 등장 {len(S)}건")
say()
say("## 0. 매도 방식별 (조회 급증 S 전체 · 대금 가속 V30/V 전체)")
for col in ["x_s2_t3", "x_s2_t5", "x_s2_t0", "x_s3_t3", "x_s3_t5", "x_s3_t0", "r1519", "nd_open"]:
    line(f"S  {col}", S, col)
for k in ("V30", "V"):
    for col in ["x_s3_t5", "x_s2_t5", "r1519"]:
        line(f"{k} {col}", tr[tr.kind == k], col)
say()
for name, colb in [("시장 분위기", "regime"), ("시각", "tb"), ("KRX 대금 순위(그 분)", "vk_b"), ("최근 5분 KRX 대금", "v5_b"),
                   ("이미 오른 폭(추격)", "cr_b"), ("VWAP 대비", "vw_b"), ("그 분까지 고점 대비", "hi_b"), ("1분봉 5분 대금 ÷ 그날 평균 5분", "r5_b"),
                   ("전날 대금 순위", "pv_b"), ("프로그램 순매수(10-26~)", "prog_b"), ("프로그램 20분 변화", "pd_b"), ("잠정 외인·기관", "fi_b")]:
    say(f"## S × {name}")
    for g, d in S.groupby(colb):
        line(f"{g}", d)
    say()
say("## S × 조회 순위 (첫 등장 때)")
line("1~10위로 바로 진입", S[S.s_rank_at <= 10]); line("11~20위", S[S.s_rank_at > 10])
say()
say("## S × 10분 사이 대금 순위 오름 (그 분·10분 전 둘 다 200위 안)")
for lo, hi in [(-999, 0), (0, 10), (10, 30), (30, 999)]:
    line(f"{lo}~{hi}칸", S[(S.vkup >= lo) & (S.vkup < hi)])
say()
say("## 조회가 더해 주는 것: 대금 가속(V30·V) 사건을 조회 여부로 나눔")
for k in ("V30", "V"):
    d = tr[tr.kind == k]
    line(f"{k} 그 분까지 조회 상위20 든 적 있음", d[d.srch]); line(f"{k} 조회 없음", d[~d.srch])
    line(f"{k} 최근 10분 조회 상위20", d[d.srch10]); line(f"{k} 최근 10분 조회 없음", d[~d.srch10])
say()
tr.to_parquet(os.path.join(OUT, "trades_feat.parquet"))

# ---- 조합 찾기 (S 사건만) — 두 조건 조합, n≥20 & 6일 이상
say("## 두 조건 조합 (S, n≥20, 6일↑) — 건당 상위 15. ⚠️ 여러 조합 중 고른 값이라 우연일 수 있음")
conds = {
    "대금≤50위": S.vk_rank <= 50, "대금≤100위": S.vk_rank <= 100, "대금 200위 안": S.vk_rank.notna(), "대금 200위 밖": S.vk_rank.isna(),
    "5분대금≥30억": S.vk_v5 >= 30e8, "5분대금≥10억": S.vk_v5 >= 10e8, "5분대금<10억": S.vk_v5 < 10e8,
    "등락<0": S.cr < 0, "등락 0~7%": (S.cr >= 0) & (S.cr < 0.07), "등락 3~15%": (S.cr >= 0.03) & (S.cr < 0.15), "등락<15%": S.cr < 0.15, "등락≥15%": S.cr >= 0.15,
    "VWAP 위": S.vs_vwap > 0, "VWAP 아래": S.vs_vwap <= 0, "VWAP+0~3%": (S.vs_vwap > 0) & (S.vs_vwap < 0.03),
    "고점근처": S.vs_high >= -0.005, "고점−3%아래": S.vs_high < -0.03,
    "5분봉대금≥2배": S.v5_ratio >= 2, "5분봉대금≥4배": S.v5_ratio >= 4, "5분봉대금<1배": S.v5_ratio < 1,
    "09:10 전": S.t < time(9, 10), "09:10~10:00": (S.t >= time(9, 10)) & (S.t < time(10, 0)), "10시 뒤": S.t >= time(10, 0),
    "조회 10위 안": S.s_rank_at <= 10, "전날 대금≤50": S.prev_vrank <= 50, "전날 대금≤200": S.prev_vrank <= 200, "전날 대금 200밖": S.prev_vrank > 200,
    "대금순위 10분 +10칸↑": S.vkup >= 10, "상승장": S.regime == "U", "하락장 아님": S.regime != "D", "보통": S.regime == "N",
}
res = []
for (n1, c1), (n2, c2) in itertools.combinations(conds.items(), 2):
    d = S[c1 & c2]
    r = st(d)
    if r and r["n"] >= 20 and r["days"] >= 6:
        res.append((n1 + " & " + n2, r))
for n1, c1 in conds.items():
    r = st(S[c1])
    if r and r["n"] >= 20 and r["days"] >= 6: res.append((n1, r))
res.sort(key=lambda x: -x[1]["mean"])
say(f"  시험한 조합 {len(res)}개, ★ {sum(r['star'] for _, r in res)}개")
for nm, r in res[:15]:
    say(f"  {"★" if r["star"] else " "} {nm:36s} {r['n']:4d}건 {r['days']:2d}일 건당 {r['mean']:+.2%} 중앙 {r['med']:+.2%} 승률 {r['win']:.0%} 앞 {r['a']:+.2%} 뒤 {r['b']:+.2%} 최고5일빼면 {r['rest5']*100:+.0f}%")
say("  (아래 = 건당 하위 10)")
for nm, r in res[-10:]:
    say(f"    {nm:36s} {r['n']:4d}건 건당 {r['mean']:+.2%} 앞 {r['a']:+.2%} 뒤 {r['b']:+.2%}")
f.close()
