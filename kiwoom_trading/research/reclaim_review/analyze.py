"""🔁 시가 탈환 재점검 — 집계·시장 분위기별·강화 후보·계좌 시뮬 (2026-11-06 복기 노트 후보 B).

입력 data/reclaim_review/trades.pkl (build.py). 출력 data/reclaim_review/report.txt
  bt = 옛 백테스트 방식(timing.py E1: 신호 봉 다음 봉 시가 — 09:02 같은 이른 매수도 09:10 까지 저가를 다 본 뒤 고른 것)
  lv = 지금 live·paper 그대로(09:11 에 셋업을 보고 매수, 신호가 +1% 넘으면 추격 안 함)
  '지금 규칙' = lv + 전날 기관 순매수(엄격 선정 A) + 신규 상장 20거래일 안 뺌 + 그날 셋업 30번째까지(MAX_WATCH)
계좌: (1) 🔁 전용 몫 100만 따로 (정수 주, 1주 > 100만이면 못 삼, 동시 1종목, 장중에 다 팔리면 몫 돌아옴, 다음 날 09:00 매도분은 그날 아침 돌아옴)
      (2) 1천만 모의 계좌 전체 (research/account_alloc/sim.run, 다른 매매 = strict_select/trades_feat.pkl 에 A안 적용, 🔁 = 이 목록, rpool 10%)
실행: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m kiwoom_trading.research.reclaim_review.analyze
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import date, time

import numpy as np

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "reclaim_review")
SPLIT = date(2026, 4, 20)
M3, M1 = date(2026, 8, 6), date(2026, 10, 6)
ALL = pickle.load(open(os.path.join(OUT, "trades.pkl"), "rb"))
LAST = max(t["date"] for t in ALL)
REG_NAME = {"U": "강한 상승장", "N+": "상승 흐름 보통", "N-": "하락 흐름 보통(약세장)", "D": "강한 하락장", None: "판정 없음"}

f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s, flush=True); f.write(s + "\n")


def pos(v):
    return v is not None and v > 0


def now_rule(t):
    return (t["mode"] == "lv" and t["skip"] is None and pos(t["ib"]) and not (t["nlist"] is not None and t["nlist"] <= 20)
            and t["setup_k"] <= 30)


def st(rows):
    """rows → 통계 dict (100만/건)."""
    v = np.array([t["ret"] for t in rows]) if rows else np.array([])
    if len(v) == 0:
        return dict(n=0)
    bd = defaultdict(float)
    for t in rows:
        bd[t["date"]] += t["ret"]
    days = sorted(bd); eq = np.cumsum([bd[d] for d in days]); mdd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    a = [t["ret"] for t in rows if t["date"] < SPLIT]; b = [t["ret"] for t in rows if t["date"] >= SPLIT]
    m3 = [t["ret"] for t in rows if t["date"] >= M3]; m1 = [t["ret"] for t in rows if t["date"] >= M1]
    s10 = np.sort(v)[::-1][10:]
    top5d = sum(sorted(bd.values(), reverse=True)[5:])
    win, loss = v[v > 0], v[v <= 0]
    return dict(n=len(v), mean=v.mean(), sum=v.sum() * 100, a=np.mean(a) if a else np.nan, b=np.mean(b) if b else np.nan,
                na=len(a), nb=len(b), m3=np.mean(m3) if m3 else np.nan, n3=len(m3), s3=sum(m3) * 100,
                m1=np.mean(m1) if m1 else np.nan, n1=len(m1), s1=sum(m1) * 100,
                x10=s10.mean() if len(s10) else np.nan, x10s=s10.sum() * 100, x5d=top5d * 100, win=np.mean(v > 0),
                pf=(win.mean() / -loss.mean()) if len(win) and len(loss) else np.nan, mdd=mdd * 100,
                star=bool(a and b and np.mean(a) > 0 and np.mean(b) > 0 and top5d > 0))


def line(lab, rows, w=34):
    s = st(rows)
    if not s["n"]:
        say(f"   {lab:{w}s}    0건"); return s
    say(f" {'★' if s['star'] else ' '} {lab:{w}s} {s['n']:5d}건 건당 {s['mean']:+.2%} 합계 {s['sum']:+6.0f}만 | 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%} "
        f"| 3달 {s['n3']:3d}건 {s['m3']:+.2%} ({s['s3']:+.0f}만) | 1달 {s['n1']:3d}건 {s['m1']:+.2%} ({s['s1']:+.0f}만) "
        f"| 최고10건 빼면 {s['x10']:+.2%} ({s['x10s']:+.0f}만) 최고5일 빼면 {s['x5d']:+.0f}만 | 승률 {s['win']:.0%} 손익비 {s['pf']:.2f} 낙폭 {s['mdd']:.0f}만")
    return s


def pool_sim(rows, d0=None, d1=None, pool=1_000_000):
    """🔁 전용 몫 100만 따로 — 고정 금액(복리 아님). → (손익 원, 산 건수, 못 산 건수(1주>몫), 몫 겹쳐 못 삼, 낙폭 원)."""
    byd = defaultdict(list)
    for t in rows:
        if (d0 is None or t["date"] >= d0) and (d1 is None or t["date"] <= d1):
            byd[t["date"]].append(t)
    pnl = 0.0; n = 0; big = 0; busy = 0; curve = []
    for d in sorted(byd):
        free_at = time(0, 0)            # 몫이 비는 시각 (전날 것은 09:00 에 팔림)
        held = False
        for t in sorted(byd[d], key=lambda x: (x["t"], x["pvr"])):
            if held and (free_at is None or free_at >= t["t"]):
                busy += 1; continue
            q = int(pool // t["px"])
            if q < 1:
                big += 1; continue
            pnl += q * t["px"] * t["ret"]; n += 1
            held, free_at = True, t["xt"]   # xt None = 다음 날까지 들고 감
        curve.append(pnl)
    c = np.r_[0, curve]; mdd = float((np.maximum.accumulate(c) - c).max())
    return pnl, n, big, busy, mdd


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    bt = [t for t in ALL if t["mode"] == "bt"]
    lv = [t for t in ALL if t["mode"] == "lv"]
    lv_ok = [t for t in lv if t["skip"] is None]
    NOW = [t for t in ALL if now_rule(t)]
    say(f"🔁 시가 탈환 재점검 — {min(t['date'] for t in ALL)} ~ {LAST}, 비용 0.25%, 100만/건 합계, 반기 {SPLIT}, 최근 3달 {M3}~, 최근 1달 {M1}~")
    say("\n## 1. 지금 규칙 1년 (옛 백테스트 방식과 비교)")
    line("옛 방식 bt (이른 매수 포함)", bt)
    line("옛 방식 bt + 전날 기관 +", [t for t in bt if pos(t["ib"])])
    line("live 방식 lv (09:11~, 추격 금지 전)", [t for t in lv if t["ret"] is not None] + [])
    say(f"   lv 신호 {len(lv)}건 중 추격(+1%↑)으로 안 삼 {sum(t['skip'] == '추격' for t in lv)} · 손절선 아래 {sum(t['skip'] == '손절선 아래' for t in lv)}")
    line("lv 추격 금지 뒤", lv_ok)
    line("lv + 전날 기관 +", [t for t in lv_ok if pos(t["ib"])])
    s_now = line("★지금 규칙 (lv+기관+·신규상장 뺌·30개)", NOW)
    early = [t for t in bt if t["t"] < time(9, 11)]
    say(f"   옛 bt 중 09:11 전 매수 {len(early)}건 ({len(early) / len(bt):.0%}) — 이 매수는 09:10 까지 저가가 안 깨진다는 걸 미리 안 것(미래 정보)")
    line("  옛 bt 09:11 전 매수만", early)
    line("  옛 bt 09:11 뒤 매수만", [t for t in bt if t["t"] >= time(9, 11)])
    say("\n  지금 규칙 매도 이유별:")
    for w in ("손절", "트레일링", "절반 익절 뒤 다음 날", "다음 날 09:00"):
        line(f"  {w}", [t for t in NOW if t["why"] == w], 30)
    say("\n  지금 규칙 달마다:")
    bym = defaultdict(list)
    for t in NOW:
        bym[t["date"].strftime("%Y-%m")].append(t["ret"])
    for m in sorted(bym):
        v = bym[m]; say(f"   {m}: {len(v):4d}건 건당 {np.mean(v):+.2%} 합계 {sum(v) * 100:+5.0f}만 승률 {np.mean(np.array(v) > 0):.0%}")

    say("\n## 2. 시장 분위기별 (09:10 판정, 지금 규칙)")
    for r in ("U", "N+", "N-", "D", None):
        line(REG_NAME[r], [t for t in NOW if t["reg"] == r])
    say("  코스피 52주 고점 대비 (전날 종가, 장 전에 앎):")
    line("약세장 밖 (고점 −10% 안)", [t for t in NOW if t["dd52"] is not None and t["dd52"] > -0.10])
    line("약세장 (고점 −10% 밖)", [t for t in NOW if t["dd52"] is not None and t["dd52"] <= -0.10])
    say("  최근 3달 분위기별:")
    for r in ("U", "N+", "N-", "D"):
        line(" 3달 " + REG_NAME[r], [t for t in NOW if t["reg"] == r and t["date"] >= M3])
    say("  최근 1달 분위기별:")
    for r in ("U", "N+", "N-", "D"):
        line(" 1달 " + REG_NAME[r], [t for t in NOW if t["reg"] == r and t["date"] >= M1])

    say("\n## 3. 강화 후보 (매수 전에 아는 정보만, 미리 정한 7개) — 남는 쪽 / 빠지는 쪽")
    C = [("강한 하락장 날 안 삼", lambda t: t["reg"] != "D"),
         ("약세장 보통 날(N-) 안 삼", lambda t: t["reg"] != "N-"),
         ("강한 상승장·상승 흐름 보통 날만", lambda t: t["reg"] in ("U", "N+")),
         ("약세장이면 강한 상승장 날만 (paper 399줄 예외에서 🔁 뺌)", lambda t: t["dd52"] > -0.10 or t["reg"] == "U"),
         ("프리장 갭 5% 이하만", lambda t: t["gap"] <= 0.05),
         ("전날 대금 50위 안", lambda t: t["pvr"] <= 50),
         ("전날 외인도 + (외인·기관 둘 다)", lambda t: pos(t["fb"])),
         ("시총 1조↑", lambda t: t["mc"] >= 1e12),
         ("09:11 뒤 새로 난 신호만 (09:11 전 신호는 안 삼)", lambda t: t["sig_t"] >= time(9, 11)),
         ("09:11 뒤 신호만 + 약세장이면 강한 상승장 날만", lambda t: t["sig_t"] >= time(9, 11) and (t["dd52"] > -0.10 or t["reg"] == "U"))]
    res = {}
    for nm, fn in C:
        keep = [t for t in NOW if fn(t)]; drop = [t for t in NOW if not fn(t)]
        say(f"\n  [{nm}]")
        res[nm] = (line("남는 쪽", keep), line("빠지는 쪽", drop), keep)

    say("\n## 4. 실제 모의 기록과 같은 날 대조용 (10-16 ~)")
    for t in sorted([t for t in lv if t["date"] >= date(2026, 10, 16)], key=lambda x: (x["date"], x["t"])):
        res_txt = ("건너뜀 " + t["skip"]) if t["skip"] else f"{t['ret']:+.2%} ({t['why']})"
        say(f"   {t['date']} {t['code']} {t['name']:14s} 신호 {t['sig_t']:%H:%M} {t['sig_px']:,.0f} → 매수 {t['t']:%H:%M} {t['px']:,.0f} 손절 {t['stop']:,.0f} "
            f"| 기관 {'+' if pos(t['ib']) else '−'} 외인 {'+' if pos(t['fb']) else '−'} 분위기 {t['reg']} 셋업 {t['setup_k']}번째 상장 {t['nlist']}일 "
            f"| {res_txt}{'  ◀지금 규칙' if now_rule(t) else ''}")

    say("\n## 5. 계좌 (1) 🔁 전용 몫 100만 따로 — 고정 금액, 정수 주")
    variants = [("지금 규칙", NOW)] + [(nm, res[nm][2]) for nm, _ in C]
    for lab, rows in variants:
        y = pool_sim(rows); m3 = pool_sim(rows, M3); m1 = pool_sim(rows, M1)
        say(f"   {lab:30s} 1년 {y[0] / 1e4:+6.1f}만 ({y[1]}건, 1주>100만 {y[2]} · 몫 겹침 {y[3]}, 낙폭 {y[4] / 1e4:.1f}만) | 3달 {m3[0] / 1e4:+5.1f}만 ({m3[1]}건) | 1달 {m1[0] / 1e4:+5.1f}만 ({m1[1]}건)")
    say("   멈춤                           0만")
    pickle.dump(dict(NOW=NOW, res={k: v[2] for k, v in res.items()}), open(os.path.join(OUT, "sets.pkl"), "wb"))
    f.close()


if __name__ == "__main__":
    main()
