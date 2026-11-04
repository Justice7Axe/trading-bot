"""1️⃣ 상승장 장 초 — 09:10 이전 정보로 만든 거르기 조건 후보 1년 검증 + 계좌 시뮬 (2026-11-04).

입력: data/up_open_review/cands.pkl (build.py), data/strict_select/trades_feat.pkl (다른 매매 기록, 계좌 시뮬용)
기준 (모든 줄 공통): 전일 대비 +15% 넘으면 안 삼(live.UP_MAX_PREV_GAIN), 매도 = 익절 없음·−6%·다음 날 09:00, 비용 0.25%.
  N  = 상장 20거래일 이내 제외 (2026-11-04 사용자 결정, 일봉 첫날 = 상장일)
  실전 = N + 신호 순간 대금 20위 안(엄격 선정 B) — 지금 real.py 에는 전날 외인·기관 둘 다 순매도 제외가 없음
  모의 = 실전 + 전날 외인·기관 둘 다 순매도 제외 (paper.py)
평가: 건수·건당·합계(1건 100만 원)·앞/뒤 반(강한 상승장 날 수로 반)·최고 3건 뺀 건당·★(앞·뒤 + 이고 최고 5일 빼도 합계 +)
계좌: 10만 실전 (strict_select.choose.real_sim, 종목당 3만·정수 주, 지금 실전 매매 6️⃣📕5️⃣4️⃣1️⃣2️⃣🌙) 1년·최근 3달,
      1천만 모의 (account_alloc.sim.run, 3️⃣ 뺀 지금 모의 배분, 엄격 선정 A). 1️⃣ 만 바꾸고 다른 매매는 그대로.
      계좌 시뮬 기간은 다른 매매 기록이 있는 2025-10-16 ~ 2026-10-22 (10-27·10-28 1️⃣ 은 계좌 시뮬에 안 들어감).
출력: data/up_open_review/report.txt
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.up_open_review.analyze
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select import choose as C

DATA = S.DATA
OUT = os.path.join(DATA, "up_open_review")
F = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")
REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}


def say(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


R = [r for r in pickle.load(open(os.path.join(OUT, "cands.pkl"), "rb")) if not r["over15"]]
UDAYS = sorted({r["date"] for r in R})
HALF = UDAYS[len(UDAYS) // 2]
both_sell = lambda r: r["fr"] is not None and r["fr"] < 0 and (r["ins"] or 0) < 0
newl = lambda r: r["age"] <= 20


def st(rows):
    if not rows:
        return None
    v = np.array([r["ret"] for r in rows])
    a = [r["ret"] for r in rows if r["date"] < HALF]; b = [r["ret"] for r in rows if r["date"] >= HALF]
    bd = defaultdict(float)
    for r in rows: bd[r["date"]] += r["ret"]
    s5 = sum(sorted(bd.values(), reverse=True)[5:])
    srt = np.sort(v)[::-1]
    return dict(n=len(v), days=len(bd), mean=v.mean(), sum=v.sum() * 100, a=np.mean(a) if a else np.nan, b=np.mean(b) if b else np.nan,
                ex3=srt[3:].mean() if len(v) > 3 else np.nan, s5=s5 * 100, win=(v > 0).mean(), stop=np.mean([r["stopped"] for r in rows]),
                star=bool(a and b and np.mean(a) > 0 and np.mean(b) > 0 and s5 > 0))


def line(lab, rows, w=44, ref=None):
    s = st(rows)
    if not s:
        say(f"   {lab:{w}s}    0건"); return s
    out = ""
    if ref is not None:
        ids = {id(r) for r in rows}
        o = [r for r in ref if id(r) not in ids]
        if o: out = f" | 빠지는 {len(o):3d}건 {np.mean([r['ret'] for r in o]):+.2%}"
    say(f" {'★' if s['star'] else ' '} {lab:{w}s} {s['n']:4d}건 {s['days']:2d}일 건당 {s['mean']:+.2%} 합계 {s['sum']:+5.0f}만 | 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%}"
        f" | 최고3건 빼면 {s['ex3']:+.2%} 최고5일 빼면 {s['s5']:+5.0f}만 | 승률 {s['win']:.0%} 손절 {s['stop']:.0%}{out}")
    return s


def quint(rows, key, lab, qs=5):
    xs = [r for r in rows if r[key] is not None and r[key] == r[key]]
    if len(xs) < 50:
        return
    cut = np.quantile([r[key] for r in xs], np.linspace(0, 1, qs + 1))
    say(f"  [{lab}] 5등분 (경계 {', '.join(f'{c:.3g}' for c in cut)})")
    for i in range(qs):
        sub = [r for r in xs if cut[i] <= r[key] <= cut[i + 1]] if i == qs - 1 else [r for r in xs if cut[i] <= r[key] < cut[i + 1]]
        s = st(sub)
        if s:
            say(f"     {i + 1} {cut[i]:>9.3g} ~ {cut[i + 1]:<9.3g} {s['n']:4d}건 건당 {s['mean']:+.2%} (앞 {s['a']:+.2%} 뒤 {s['b']:+.2%}) 손절 {s['stop']:.0%}")


# 후보 조건 (True = 산다). 모두 09:10 이전 정보.
CONDS = [
    ("C1 09:10 전일 대비 ≤ +10%", lambda r: r["chg"] <= 0.10),
    ("C2 시가 대비 ≤ +5%", lambda r: r["from_open"] <= 0.05),
    ("C3 직전 5일 등락 ≤ +15%", lambda r: r["d5"] is None or r["d5"] <= 0.15),
    ("C4 10일 안 대금 폭발(3배↑) 뒤 쉬는 종목 제외", lambda r: not (r["d10max"] is not None and r["d10max"] >= 3 and r["spike_ago"] >= 2)),
    ("C5 전날 시총 ≥ 1조", lambda r: r["mcap"] >= 1e12),
    ("C6 09:10 대금 ≤ 20일 평균의 30%", lambda r: r["cval_r"] is None or r["cval_r"] <= 0.30),
    ("C7 C1 + C3 (많이 오른 것 둘 다 거름)", lambda r: r["chg"] <= 0.10 and (r["d5"] is None or r["d5"] <= 0.15)),
    ("D1 코스피 09:10 ≥ +1σ 날만 (중앙값만으로 판정한 날 안 삼)", lambda r: r["K1z"] >= 1),
    ("D2 전날 강한 하락장이면 안 삼", lambda r: r["prev_cls"] != "D"),
    ("D3 D1 + C5 (코스피 1σ 날 · 시총 1조↑)", lambda r: r["K1z"] >= 1 and r["mcap"] >= 1e12),
]


def _byday(rows):
    by = defaultdict(list)
    for r in rows: by[r["date"]].append(r)
    return by


def as_trade(r):
    return dict(date=r["date"], t=time(9, 11), kind="1️⃣", code=r["code"], px=r["buy"], ret=r["ret"], rk=r["vrank"], xt=r["xt"],
                fb=bool(r["fr"] is not None and r["fr"] > 0), ib=bool(r["ins"] is not None and r["ins"] > 0))


BASE_T = pickle.load(open(os.path.join(DATA, "strict_select", "trades_feat.pkl"), "rb"))
OTHER = [t for t in BASE_T if t["kind"] not in ("1️⃣", "7️⃣")]
DAYS1 = list(S.DAYS); SPLIT0 = S.SPLIT


def real_acct(up_rows, d_from=None, other=None, seed=100_000):
    """1️⃣ 를 up_rows 로 바꾼 10만 실전 계좌. up_rows 는 이미 거른 1️⃣ (대금 20위 조건은 여기서 안 검)."""
    other = OTHER if other is None else other
    if d_from:
        dd = [d for d in DAYS1 if d >= d_from]; S.DAYS = dd; S.SPLIT = dd[len(dd) // 2]
    T = [t for t in other if t["kind"] != "1️⃣"] + [as_trade(r) for r in up_rows]
    if d_from:
        T = [t for t in T if t["date"] >= d_from]
    r = C.real_sim(T, kinds=REAL, seed=seed)
    S.DAYS = DAYS1; S.SPLIT = SPLIT0
    return r


def mock_acct(up_rows, other=None):
    other = OTHER if other is None else other
    T = C.apply([t for t in other if t["kind"] != "1️⃣"], C.PICK) + [as_trade(r) for r in up_rows]
    return S.run({"kinds": set(S.KINDS) - {"3️⃣"}}, trades=T)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    say(f"1️⃣ 상승장 장 초 1년 검증 — 강한 상승장 {len(UDAYS)}일 ({UDAYS[0]} ~ {UDAYS[-1]}), 앞/뒤 반 경계 {HALF}")
    say("매수 09:11 시가, 익절 없음 · −6% 손절 · 못 닿으면 다음 날 09:00 시가, 비용 0.25%, 전일 대비 +15% 넘으면 안 삼 (지금 규칙). 합계 = 1건 100만 원.")
    ALL = R
    N = [r for r in ALL if not newl(r)]
    REALB = [r for r in N if r["vrank"] <= 20]
    MOCKB = [r for r in REALB if not both_sell(r)]
    ALL40 = N

    say("\n## 1. 기준선과 상장 20거래일 이내 제외 효과")
    line("1️⃣ 신호 전체 (40위 안, 둘 다 순매도 포함)", ALL)
    line("  └ 상장 20거래일 이내 제외 (N)", N, ref=ALL)
    line("실전 기준 = 대금 20위 안 (제외 전)", [r for r in ALL if r["vrank"] <= 20])
    line("실전 기준 + N", REALB, ref=[r for r in ALL if r["vrank"] <= 20])
    line("모의 기준 = 20위 안·둘 다 순매도 제외 (제외 전)", [r for r in ALL if r["vrank"] <= 20 and not both_sell(r)])
    line("모의 기준 + N", MOCKB)
    nl = [r for r in ALL if newl(r)]
    say(f"   상장 20거래일 이내 1️⃣ 후보: {len(nl)}건 — " + ", ".join(f"{r['date']:%m-%d} {r['name']} {r['ret']:+.1%}" for r in nl))
    say("   (옛 연구 재현 확인: 둘 다 순매도 제외·40위 안·~10-23 → 574건 +1.06% 이어야 함)")
    line("   재현", [r for r in ALL if not both_sell(r) and r["date"] <= UDAYS[-3]])

    say("\n## 2. 특징값 5등분 (N 기준 40위 안 전체) — 한 방향으로 좋아지거나 나빠지는지")
    for key, lab in (("chg", "09:10 전일 대비"), ("from_open", "09:10 시가 대비"), ("gap", "시가 갭"), ("off_hi", "09:00~09:09 고가 대비"),
                     ("pos", "09:00~09:09 범위 안 위치"), ("d1", "전날 등락"), ("d5", "직전 5일 등락"), ("d10max", "10일 최대 대금 ÷ 그 전 20일 평균"),
                     ("hi250", "52주 고가 대비"), ("cval_r", "09:10 대금 ÷ 20일 평균"), ("mcap", "전날 시총"), ("vrank", "09:10 대금 순위")):
        quint(N, key, lab)
    say("\n  [날 특징] (09:10 전에 앎)")
    for lab, f in (("전날 강한 하락장(D) 다음 날", lambda r: r["prev_cls"] == "D"), ("그 밖", lambda r: r["prev_cls"] != "D"),
                   ("코스피 52주 고점 −10% 밖(약세장)", lambda r: r["dd52"] <= -0.10), ("−10% 안", lambda r: r["dd52"] > -0.10),
                   ("코스피 ≥ +1σ 로 판정", lambda r: r["K1z"] >= 1), ("중앙값 +2% 만으로 판정(코스피 < 1σ)", lambda r: r["K1z"] < 1)):
        line(lab, [r for r in N if f(r)], w=40)
    say("  [중앙값만으로 강한 상승장이 된 날 (코스피 < 1σ)] " + " · ".join(
        f"{d:%y-%m-%d} K1z {v[0]['K1z']:.2f} M0 {v[0]['M0']:+.1%} 1️⃣ {np.mean([x['ret'] for x in v]):+.1%}"
        for d, v in sorted(_byday(N).items()) if v[0]["K1z"] < 1))
    say("  [날별 1️⃣ 건당 (N, 40위 안)]")
    by = defaultdict(list)
    for r in N: by[r["date"]].append(r)
    say("   " + " · ".join(f"{d:%y%m%d} {np.mean([x['ret'] for x in v]) * 100:+.1f}" for d, v in sorted(by.items())))

    say("\n## 3. 후보 조건 — 40위 안 전체(N) 기준")
    line("기준 N", N)
    for lab, f in CONDS:
        line(lab, [r for r in N if f(r)], ref=N)
    say("\n## 4. 후보 조건 — 실전 기준(N + 20위 안) 위에 더함")
    line("실전 기준", REALB)
    for lab, f in CONDS:
        line(lab, [r for r in REALB if f(r)], ref=REALB)
    say("\n## 5. 후보 조건 — 모의 기준(N + 20위 안 + 둘 다 순매도 제외) 위에 더함")
    line("모의 기준", MOCKB)
    for lab, f in CONDS:
        line(lab, [r for r in MOCKB if f(r)], ref=MOCKB)

    say("\n## 6. 전날 외인·기관 둘 다 순매도 — 실전 조건(N + 20위 안)에서")
    line("실전 지금 (둘 다 순매도 포함)", REALB)
    line("둘 다 순매도 제외", [r for r in REALB if not both_sell(r)], ref=REALB)
    line("둘 다 순매도인 것만", [r for r in REALB if both_sell(r)])
    line("둘 다 순매도 · 실전이 살 수 있는 값(1주 ≤ 5만)", [r for r in REALB if both_sell(r) and r["buy"] <= 50_000])
    line("둘 다 순매도 아님 · 1주 ≤ 5만", [r for r in REALB if not both_sell(r) and r["buy"] <= 50_000])

    say("\n## 7. 계좌 시뮬 (1️⃣ 만 바꿈)")
    say(f"   다른 매매 기록 trades_feat.pkl: {len(OTHER)}건, 기간 {DAYS1[0]} ~ {DAYS1[-1]}")
    rr = C.real_sim([t for t in C.apply(BASE_T, C.ALT) if t["kind"] != "7️⃣"], kinds=REAL)
    say(f"   (재현) 옛 1️⃣ 기록 그대로 10만 실전 → {rr['final']:,.0f}원 (stop_rules 보고서 3,120,396원)")
    old_real = [t for t in C.apply(BASE_T, C.ALT) if t["kind"] not in ("7️⃣",)]
    d3 = DAYS1[-63]
    cases = [("실전 지금 (20위, N 없음, 둘 다 순매도 포함)", [r for r in ALL if r["vrank"] <= 20]),
             ("+ 상장 20거래일 이내 제외 (N)", REALB),
             ("N + 둘 다 순매도 제외", [r for r in REALB if not both_sell(r)])]
    cases += [(f"N + {lab}", [r for r in REALB if f(r)]) for lab, f in CONDS]
    cases += [(f"N + 둘 다 순매도 제외 + {lab}", [r for r in REALB if f(r) and not both_sell(r)]) for lab, f in CONDS if lab[:2] in ("C1", "C5", "D1", "D3")]
    say("   [10만 실전 계좌, 종목당 3만·정수 주]  1년 최종 · 낙폭 · 앞/뒤 · 1️⃣ 산 건수·손익 | 최근 3달 최종")
    for lab, rows in cases:
        a = real_acct([r for r in rows if r["date"] <= DAYS1[-1]])
        b = real_acct([r for r in rows if r["date"] <= DAYS1[-1]], d_from=d3)
        c3 = real_acct([r for r in rows if r["date"] <= DAYS1[-1]], seed=300_000)
        say(f"   {'★' if a['star'] else ' '} {lab:44s} {a['final']:>11,.0f}원 낙폭 {a['mdd']:.0%} 앞 {a['front']:+.0%} 뒤 {a['back']:+.0%}"
            f" | 1️⃣ {a['n'].get('1️⃣', 0):3d}건 {a['pnl'].get('1️⃣', 0):+9,.0f}원 | 3달 {b['final']:>9,.0f}원 | 시드 30만 {c3['final']:>11,.0f}원 (1️⃣ {c3['pnl'].get('1️⃣', 0):+,.0f})")
    mcases = [("모의 지금 (20위·둘 다 순매도 제외, N 없음)", [r for r in ALL if r["vrank"] <= 20 and not both_sell(r)]),
              ("+ N", MOCKB)] + [(f"N + {lab}", [r for r in MOCKB if f(r)]) for lab, f in CONDS]
    say("   [1천만 모의 계좌, 1️⃣ 자산의 2.5%]  1년 최종 · 낙폭 · 앞/뒤")
    for lab, rows in mcases:
        m = mock_acct([r for r in rows if r["date"] <= DAYS1[-1]])
        say(f"   {'★' if m['star'] else ' '} {lab:44s} {m['final'] / 1e4:>9,.0f}만 낙폭 {m['mdd']:.1%} 앞 {m['front']:+.0%} 뒤 {m['back']:+.0%}"
            f" | 1️⃣ {m['n_k'].get('1️⃣', 0)}건 {m['pnl_k'].get('1️⃣', 0) / 1e4:+,.0f}만")
    # 상장 20거래일 이내 제외를 모든 매매에 넣으면 (참고)
    from kiwoom_trading.research.up_open_review.build import age_of
    other_n = [t for t in OTHER if t.get("code") is None or age_of(t["code"], t["date"]) > 20]
    say(f"\n   [참고] 상장 20거래일 이내 제외를 다른 매매에도: 다른 매매 {len(OTHER)}건 중 {len(OTHER) - len(other_n)}건 빠짐")
    a = real_acct(REALB, other=other_n); m = mock_acct(MOCKB, other=other_n)
    say(f"   10만 실전 {a['final']:,.0f}원 낙폭 {a['mdd']:.0%} · 1천만 모의 {m['final'] / 1e4:,.0f}만 낙폭 {m['mdd']:.1%}")
    gone = defaultdict(lambda: [0, 0.0])
    keep_ids = {id(t) for t in other_n}
    for t in OTHER:
        if id(t) not in keep_ids:
            gone[t["kind"]][0] += 1; gone[t["kind"]][1] += t["ret"]
    say("   빠지는 다른 매매: " + " · ".join(f"{k} {n}건 건당 {s / n:+.2%}" for k, (n, s) in gone.items()))


if __name__ == "__main__":
    main()
