"""거감음봉(유목민 『투자의 정석』) 일봉 백테스트 — 2026-10-28.

책 규칙 (블로그 여러 곳의 책 정리로 확인):
  1) 바닥권에서 거래량 폭증: 폭증일(D0) 거래량 ≥ 전 거래일의 5배 (500~1,000%↑)
  2) 다음 날(D1) 거래량 급감: D0 의 25% 이하 (12% 미만 최상) + 음봉. 감소 폭이 크고 음봉이 길수록 좋다
  3) D1 주가가 5일선과 이격이 크지 않음: 맞닿으면 좋고, 크게 깨면 안 됨
  매수 = D1 종가(하루 매집), 매도 = 다음 날(최대 5거래일 안), 손절 −5% (블로거들이 따르는 책 권장).
  매수 금지: 역배열, 추격, 이평선 이격 큰 종목.

자료: daily_ohlcv(수정주가) → engine.daily_day (9-14 이후는 1분봉 있으면 정규장 값으로 바로잡음).
매도 규칙(backtest-rules): 손절가 닿으면 즉시(시가가 이미 아래면 시가), 익절가 닿으면 그 값, 아니면 정해진 날 09:00 시가. 종가 매도 없음.
"""
import os, sys
from collections import defaultdict
from datetime import date
import numpy as np

from kiwoom_trading.backtest import engine as E

E.OUT = os.path.join(E.DATA, "geogam"); os.makedirs(E.OUT, exist_ok=True)
START = date(2024, 11, 15)          # 120일 이평·고가 계산 여유는 짧은 종목만 빠짐
COST = E.COST


def is_etf(name):
    name = name or ""
    return any(k in name for k in ("KODEX", "TIGER", "KBSTAR", "RISE", "ACE", "SOL ", "HANARO", "KOSEF", "ARIRANG", "PLUS", "ETN", "스팩", "KIWOOM", "TIMEFOLIO", "1Q", "WON "))


def build_series():
    """code → 날짜 순 [(date,o,h,l,c,v,value)] (정규장 값으로 바로잡은 일봉)."""
    S = defaultdict(list)
    for d in E.CAL:
        for c, r in E.daily_day(d).items():
            S[c].append((d, *r))
    return S


def signals(S):
    """조건 칸을 모두 계산해 둔 후보 목록 (폭증 ≥3배·급감 ≤40%·음봉까지 넓게 → 변형은 나중에 거름)."""
    out = []
    for c, rows in S.items():
        if not E.is_common(c) or is_etf(E.NAME.get(c)):
            continue
        n = len(rows)
        cl = np.array([r[4] for r in rows], float)
        for i in range(121, n - 8):
            dm1, d0, d1 = rows[i - 2], rows[i - 1], rows[i]
            if d1[0] < START: continue
            v_1, v0, v1 = dm1[5] or 0, d0[5] or 0, d1[5] or 0
            if v_1 <= 0 or v0 <= 0 or v1 <= 0: continue
            if v0 < 3 * v_1 or v1 > 0.4 * v0: continue
            o1, h1, l1, c1 = d1[1:5]
            if not (c1 < o1): continue                      # 음봉 (캔들)
            # 모든 줄이 실제 연속 거래일인지 (거래정지 끼면 뺌)
            if E.CIDX[d1[0]] - E.CIDX[dm1[0]] != 2: continue
            ma5 = cl[i - 4:i + 1].mean()
            ma20, ma60, ma120 = cl[i - 19:i + 1].mean(), cl[i - 59:i + 1].mean(), cl[i - 119:i + 1].mean()
            hi120 = max(r[2] for r in rows[i - 121:i - 1])  # 폭증 전 120일 고가
            out.append(dict(
                code=c, d=d1[0], i=i, buy=c1,
                spike=v0 / v_1, dry=v1 / v0,
                up0=d0[4] / dm1[4] - 1, chg1=c1 / d0[4] - 1, body1=c1 / o1 - 1,
                gap5=c1 / ma5 - 1, touch5=l1 <= ma5 <= h1,
                val0=d0[6] or 0, vol0=v0,
                bottom=dm1[4] / hi120 - 1,             # 폭증 전날 종가가 120일 고가 대비 얼마나 빠졌나
                below60=dm1[4] < cl[i - 61:i - 1].mean(),
                reverse=ma5 < ma20 < ma60 < ma120,     # 역배열
                unsure=(c, d1[0]) in E.UNSURE,
            ))
    return out


def exit_ret(rows, i, buy, hold, stop, tp, entry_next_open=False):
    """D1 종가(또는 D2 시가) 매수 → D2..D(1+hold) 일봉으로 손절·익절 확인, 아니면 D(2+hold) 09:00 시가.
    entry_next_open 이면 D2 시가 매수, D2 봉 안에서는 손절만 본다(순서 모름 → 익절은 안 봄)."""
    j0 = i + 1
    if entry_next_open:
        buy = rows[j0][1]
    sp = buy * (1 - stop) if stop else None
    tpp = buy * (1 + tp) if tp else None
    for k in range(j0, j0 + hold):
        o, h, l = rows[k][1], rows[k][2], rows[k][3]
        first = entry_next_open and k == j0
        if sp and not first and o <= sp: return o / buy - 1 - COST, "손절"
        if sp and l <= sp: return sp / buy - 1 - COST, "손절"
        if tpp and not first and o >= tpp: return o / buy - 1 - COST, "익절"
        if tpp and not first and h >= tpp: return tpp / buy - 1 - COST, "익절"
    return rows[j0 + hold][1] / buy - 1 - COST, "시가"


def main():
    rep = E.Report("backtest.txt")
    S = build_series()
    sig = signals(S)
    rep.say(f"거감음봉 일봉 백테스트  {START} ~ {E.CAL[-9]}  (넓은 후보 {len(sig)}건)")
    rep.say("매수 D1 정규장 종가, 비용 0.25%.  ★ = 앞 반·뒤 반 모두 + & 가장 좋은 5일 빼도 +.  합계는 건당 100만 원 기준(만 원)")

    def run(title, flt, hold=0, stop=None, tp=None, nxt=False, width=58):
        tr = []
        for s in sig:
            if not flt(s): continue
            r, _ = exit_ret(S[s["code"]], s["i"], s["buy"], hold, stop, tp, nxt)
            tr.append((s["d"], r))
        return rep.stats(tr, title, width), tr

    book = lambda s: s["spike"] >= 5 and s["dry"] <= 0.25 and s["up0"] > 0 and -0.03 <= s["gap5"] <= 0.05

    rep.say("\n[1] 책 그대로 (폭증 ≥5배·D0 상승·급감 ≤25%·음봉·종가가 5일선 −3%~+5%) — 매도 방법별")
    run("다음 날 09:00 시가", book)
    for h in (1, 2, 4):
        run(f"손절 −5%, {h + 1}일째 09:00 시가", book, hold=h, stop=0.05)
    for tp in (0.03, 0.05, 0.10):
        run(f"손절 −5%·익절 +{tp:.0%}, 최대 5일째 09:00", book, hold=4, stop=0.05, tp=tp)
    run("다음 날 시가 매수(신호 확정 후) → 손절 −5%, 5일째 09:00", book, hold=4, stop=0.05, nxt=True)

    rep.say("\n[2] 조건 변형 (매도: 다음 날 09:00 시가 / 손절 −5%·5일째 09:00)")
    V = {
        "책 그대로": book,
        "+ 급감 ≤12% (최상)": lambda s: book(s) and s["dry"] <= 0.12,
        "+ 폭증 ≥10배": lambda s: book(s) and s["spike"] >= 10,
        "+ D0 장대양봉 +10%↑": lambda s: book(s) and s["up0"] >= 0.10,
        "+ 바닥권: 폭증 전 120일 고가 −30%↓": lambda s: book(s) and s["bottom"] <= -0.30,
        "+ 바닥권: 폭증 전날 60일선 아래": lambda s: book(s) and s["below60"],
        "+ 역배열 제외": lambda s: book(s) and not s["reverse"],
        "+ 5일선 터치 (저가≤5일선≤고가)": lambda s: book(s) and s["touch5"],
        "+ 장대음봉 (시가 대비 −5%↓)": lambda s: book(s) and s["body1"] <= -0.05,
        "+ D0 거래대금 150억↑": lambda s: book(s) and s["val0"] >= 150e8,
        "+ D0 거래량 1,000만주↑": lambda s: book(s) and s["vol0"] >= 1e7,
        "느슨: 폭증 ≥3배·급감 ≤40%·5일선 −5%~+8%": lambda s: s["up0"] > 0 and -0.05 <= s["gap5"] <= 0.08,
    }
    for k, f in V.items():
        run(k + " | 다음 날", f)
        run(k + " | −5%·5일", f, hold=4, stop=0.05)

    # 책 사례 재현: 블로거가 2026-10-02 장 마감 무렵 거감음봉으로 산 종목 (조이시티·위메이드맥스·에스와이스틸)
    rep.say("\n[3] 사례 확인 — 2026-10-02 블로거 매수 종목이 신호에 잡히나")
    for nm in ("조이시티", "위메이드맥스", "에스와이스틸", "이뮨온시아", "보원케미칼"):
        c = E.code_by_name(nm) if hasattr(E, "code_by_name") else None
        hit = [s for s in sig if s["code"] == c and date(2026, 9, 28) <= s["d"] <= date(2026, 10, 2)]
        if not hit:
            rep.say(f"  {nm}({c}): 넓은 후보에도 없음"); continue
        for s in hit:
            rep.say(f"  {nm}({c}) {s['d']} 폭증 {s['spike']:.1f}배 급감 {s['dry']:.0%} D0 {s['up0']:+.1%} 5일선 {s['gap5']:+.1%} → 책 조건 {'O' if book(s) else 'X'}")

    # 연도·시장 분위기별
    rep.say("\n[4] 책 그대로 · 손절 −5%·5일째 09:00 — 기간별")
    _, tr = run("전체", book, hold=4, stop=0.05)
    by = defaultdict(list)
    for d, r in tr: by[(d.year, (d.month - 1) // 3 + 1)].append(r)
    for k in sorted(by):
        v = by[k]; rep.say(f"  {k[0]} {k[1]}분기  {len(v):4d}건  건당 {np.mean(v):+.2%}  합계 {sum(v) * 100:+.0f}만")
    n_uns = sum(1 for s in sig if book(s) and s["unsure"])
    rep.say(f"\n9-14 이후 1분봉 없어 통합 값 그대로 쓴 신호: {n_uns}건 (정규장 종가 아님 → 매수가 오차)")
    rep.say(f"하루 신호 수(책 그대로): 평균 {len(tr) / max(1, len({d for d, _ in tr})):.1f}종목 / 신호 있는 날 {len({d for d, _ in tr})}일")


if __name__ == "__main__":
    main()
