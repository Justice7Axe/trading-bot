"""📕 홍인기 매매일지의 상따 밖 매매 방식 1년 백테스트 (2026-10-27 사용자: "눌림부터 전부 다 해줘").

일지 566건(data/hong/journal_trades.csv) 중 눌림 249 · 돌파 96 · 대형주 수급 추종 86 · 상따 72(run_hong_backtest) · 시가·갭 25 · 종가 배팅 18.
여기서는 일지에서 반복되는 자리를 규칙으로 옮겨 시험한다. 자료·체결은 디앤서 공통 엔진(engine.py):
  1분봉은 '전날 대금 200위 + 다음 날'이 다 있는 minute_history → 대상은 **전날 기준으로만** 고른다(그날 순위로 고르면 미래 정보).
  비용 0.25%. 매도는 목표가·손절가 닿으면 그 가격(같은 봉이면 손절 먼저), 아니면 다음 날 09:00 시가 (종가 매도 안 함).

[눌림 N1] 전일 주도주 D+1·D+2 전일 종가 눌림 — 일지: "매우 강한 D+1 종목, +3%부터 하락시 분할매수", "전일종가 근처 재매수",
   목표 "시초가"·"당일 고가". 대상 = 전날(D+1) 또는 그 전날(D+2, 전날도 상승) 대금 30위 안 · +5%↑.
   그날 시가가 매수가보다 위(갭상승 뒤 눌림)일 때 09:00~11:00 지정가(전일 종가 +1% / 0%) 체결.
   매도: 목표 = 그날 시가 또는 +3%, 손절 = 전일 종가 −2%, 아니면 다음 날 09:00.
[눌림 N2] 지수 과대 낙폭 — 일지: "코스피(선물) 고점대비 3% 하락부터 분할매수, 5%면 비중 확대", "저점 대비 약 2% 반등시 수익실현",
   "대형주 중 가장 강한 종목". 코스피 1분봉이 그날 고점 대비 −3% 처음 닿은 봉 → 전날 시총 5위 안 중 그 시각 등락률 1위를 다음 봉 시가에.
   매도: 코스피가 매수 뒤 저점 대비 +2% 반등한 봉 종가 / 손절 없음·−3% 비교 / 아니면 다음 날 09:00.
[눌림 N3] 당일 강세 종목 상승폭 1/3~1/2 되돌림 — 일지: "상승 초입 매수 못해 상승폭 1/3 눌림시 매수", 목표 "당일 고점".
   대상 = 전날 대금 200위 안 중 그 시각 누적 대금 10위 안(대상 안 순위) · 고가 +5%↑. 09:30~14:00, 고가에서
   (고가 − 전일 종가) × k 만큼 내려온 가격에 지정가 (k = 1/3, 1/2). 목표 = 그 고가, 손절 −2%, 아니면 다음 날 09:00.

실행: .venv/Scripts/python.exe -m kiwoom_trading.analysis.run_hong_styles_backtest [--report-only]  → data/hong/styles.txt
"""
from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime, time

import numpy as np

from kiwoom_trading.backtest import engine as E  # noqa: E402  (공통 엔진, docs/architecture.md)

OUT = os.path.join(E.DATA, "hong")
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------- 공통
def mkt_tags():
    """{date: '둘 다 20일선 아래' / '둘 중 하나↑ 20일선 위'} — 전날 마감 기준."""
    out = {}
    for code in ("001", "101"):
        rows = E.IX.execute("SELECT date, close FROM idx_daily WHERE code=? ORDER BY date", [code]).fetchall()
        cl = np.array([r[1] for r in rows], float)
        for i in range(20, len(rows)):
            out.setdefault(rows[i][0], [None, None])[0 if code == "001" else 1] = cl[i - 1] < cl[i - 20:i].mean()
    return {d: ("둘 다 20일선 아래" if all(v) else "둘 중 하나↑ 20일선 위") for d, v in out.items()}


MKT = mkt_tags()


def run_exit(c, d, reg, k, buy, tp=None, sp=None, limit_fill=False, until=time(15, 30)):
    """reg[k] 봉에서 buy 에 삼 → 목표 tp·손절 sp (같은 봉이면 손절 먼저), 아니면 다음 날 09:00. 지정가 체결 봉은 목표를 다음 봉부터 본다."""
    for i, x in enumerate(reg[k:]):
        if x[0] > until:
            break
        if sp and x[3] <= sp:
            return min(x[1], sp) / buy - 1 - E.COST, "손절"
        if limit_fill and i == 0:
            continue
        if tp and x[2] >= tp:
            return max(x[1], tp) / buy - 1 - E.COST, "목표"
    nx = E.next_day_exits(c, d, buy)
    if "09:00 시가" not in nx:
        return None, None
    return nx["09:00 시가"], "다음 날"


def ctx(c, d):
    """그날 정규장 1분봉, 전일 종가(1분봉 기준 환산)."""
    reg = E.regular(E.bars(c, d))
    f = E.factor(c, d)
    p = E.prev_day(d)
    pdd = E.daily_day(p).get(c)
    if len(reg) < 60 or not f or not pdd:
        return None, None
    return reg, pdd[3] * f


# ---------------------------------------------------------------- N1 전일 주도주 D+1·D+2 전일 종가 눌림
def n1_day(d):
    p, p2 = E.prev_day(d), E.prev_day(d, 2)
    vr1, vr2 = E.value_rank(p), E.value_rank(p2)
    cands = {}
    for c, r in vr1.items():
        if r <= 30 and E.is_common(c) and (E.chg(c, p) or 0) >= 0.05:
            cands[c] = "D+1"
    for c, r in vr2.items():
        if r <= 30 and E.is_common(c) and c not in cands and (E.chg(c, p2) or 0) >= 0.05 and (E.chg(c, p) or -1) >= 0:
            cands[c] = "D+2"
    E.load_day(list(cands), d)
    out = []
    for c, dn in cands.items():
        reg, pc = ctx(c, d)
        if not reg:
            continue
        o = reg[0][1]
        for lv in (0.01, 0.0):
            L = pc * (1 + lv)
            if o <= L * 1.005:
                continue
            k = next((i for i, x in enumerate(reg) if x[0] <= time(11, 0) and x[3] <= L), None)
            if k is None:
                continue
            buy = min(reg[k][1], L)
            high_before = max(x[2] for x in reg[:k + 1])
            base = dict(code=c, date=d, t=reg[k][0], dn=dn, lv=lv, gap=o / pc - 1, rank=vr1.get(c) if dn == "D+1" else vr2.get(c),
                        big=E.mcap_rank(p).get(c, 9999) <= 30, mkt=MKT.get(d))
            for tpn, tp in (("시가", o), ("+3%", buy * 1.03)):
                r, why = run_exit(c, d, reg, k, buy, tp=tp, sp=pc * 0.98, limit_fill=True)
                if r is not None:
                    out.append(dict(base, style="N1", tpn=tpn, ret=r, why=why))
    return out


# ---------------------------------------------------------------- N2 지수 과대 낙폭 → 가장 강한 대형주
_IDX = {}


def kospi_min(d):
    if d not in _IDX:
        rows = E.IX.execute("SELECT ts, open, high, low, close FROM idx_min WHERE code='001' AND ts >= ? AND ts < ? ORDER BY ts",
                            [datetime.combine(d, time(9, 0)), datetime.combine(d, time(15, 31))]).fetchall()
        _IDX[d] = [(r[0].time(), *r[1:]) for r in rows]
    return _IDX[d]


def n2_day(d):
    ix = kospi_min(d)
    if len(ix) < 60:
        return []
    out = []
    for drop in (0.03, 0.05):
        hi, trig = None, None
        for i, x in enumerate(ix):
            hi = x[2] if hi is None else max(hi, x[2])
            if x[3] <= hi * (1 - drop) and x[0] <= time(14, 30):
                trig = i
                break
        if trig is None:
            continue
        t = ix[trig][0]
        p = E.prev_day(d)
        big = [c for c, r in E.mcap_rank(p).items() if r <= 5 and E.is_common(c)]
        E.load_day(big, d)
        best = None
        for c in big:
            reg, pc = ctx(c, d)
            if not reg:
                continue
            j = next((k for k, x in enumerate(reg) if x[0] >= t), None)
            if j is None or j + 1 >= len(reg):
                continue
            ch = reg[j][4] / pc - 1
            if best is None or ch > best[0]:
                best = (ch, c, reg, j)
        if not best:
            continue
        ch, c, reg, j = best
        buy = reg[j + 1][1]
        # 코스피가 매수 뒤 저점 대비 +2% 반등한 시각
        low, back = None, None
        for x in ix[trig + 1:]:
            low = x[3] if low is None else min(low, x[3])
            if x[4] >= low * 1.02:
                back = x[0]
                break
        base = dict(code=c, date=d, t=reg[j + 1][0], drop=drop, chg=ch, mkt=MKT.get(d))
        for stopn, sp in (("손절 없음", None), ("−3%", buy * 0.97)):
            if back:
                rb = _sell_at(c, d, reg, j + 1, buy, sp, back)
                if rb is None:
                    continue
                r, why = rb
            else:
                r, why = run_exit(c, d, reg, j + 1, buy, sp=sp)
            if r is not None:
                out.append(dict(base, style="N2", stopn=stopn, ret=r, why=why, back=back))
    return out


def _sell_at(c, d, reg, k, buy, sp, t):
    """t 시각(코스피 반등 봉)까지 손절 먼저 보고, 안 걸리면 t 봉 종가에 매도."""
    for x in reg[k:]:
        if sp and x[3] <= sp:
            return min(x[1], sp) / buy - 1 - E.COST, "손절"
        if x[0] >= t:
            return x[4] / buy - 1 - E.COST, "지수 +2% 반등"
    return None


# ---------------------------------------------------------------- N3 당일 강세 상승폭 되돌림
def n3_day(d):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    U = [c for c, r in vr.items() if r <= 200 and E.is_common(c)]
    B = E.load_day(U, d)
    info = {}
    for c in U:
        reg, pc = ctx(c, d)
        if reg:
            info[c] = (reg, pc, np.cumsum([x[4] * x[5] for x in reg]), {x[0]: i for i, x in enumerate(reg)})
    out = []
    for c, (reg, pc, cv, ti) in info.items():
        hi = None
        done = set()
        for i, x in enumerate(reg):
            t = x[0]
            if t > time(14, 0):
                break
            if hi is not None and t >= time(9, 30) and hi >= pc * 1.05:
                for k in (1 / 3, 1 / 2):
                    if k in done:
                        continue
                    L = hi - (hi - pc) * k
                    if x[3] <= L < reg[i - 1][4]:      # 위에서 내려와 처음 닿은 봉 (09:30 전에 이미 빠진 것은 안 삼)
                        done.add(k)
                        # 그 시각 누적 대금 순위 (대상 안)
                        mine = cv[i]
                        rank = 1 + sum(1 for o, (r2, _, cv2, ti2) in info.items() if o != c and t in ti2 and cv2[ti2[t]] > mine)
                        if rank > 10:
                            continue
                        buy = min(x[1], L)
                        r, why = run_exit(c, d, reg, i, buy, tp=hi, sp=buy * 0.98, limit_fill=True)
                        if r is not None:
                            out.append(dict(style="N3", code=c, date=d, t=t, k=k, rise=hi / pc - 1, rank=rank, ret=r, why=why, mkt=MKT.get(d),
                                            big=E.mcap_rank(p).get(c, 9999) <= 30))
                if len(done) == 2:
                    break
            hi = x[2] if hi is None else max(hi, x[2])
    return out


# ---------------------------------------------------------------- B1 돌파: 끼 있는 대장 60일 신고가 돌파
def kki(c, d, n=60, up=0.15):
    """최근 n 거래일 안에 +up 이상 오른 날이 있나 (일지: '끼가 좋은 종목')."""
    h = E.hist(c, d, n)
    return any(h[i + 1][4] and h[i][4] / h[i + 1][4] - 1 >= up for i in range(len(h) - 1))


def b1_day(d):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    U = [c for c, r in vr.items() if r <= 200 and E.is_common(c)]
    E.load_day(U, d)
    info = {}
    for c in U:
        reg, pc = ctx(c, d)
        if reg:
            info[c] = (reg, pc, np.cumsum([x[4] * x[5] for x in reg]), {x[0]: i for i, x in enumerate(reg)})
    out = []
    for c, (reg, pc, cv, ti) in info.items():
        h = E.hist(c, d, 60)
        if len(h) < 60:
            continue
        f = E.factor(c, d)
        lvl = max(x[2] for x in h) * f
        for i in range(1, len(reg) - 1):
            x, t = reg[i], reg[i][0]
            if t < time(9, 5) or t > time(14, 30):
                continue
            if x[4] > lvl >= reg[i - 1][4] and x[4] > x[1]:
                rank = 1 + sum(1 for o, (r2, _, cv2, ti2) in info.items() if o != c and t in ti2 and cv2[ti2[t]] > cv[i])
                base = dict(style="B1", code=c, date=d, t=t, rank=rank, kki=kki(c, d), chg=x[4] / pc - 1, mkt=MKT.get(d),
                            big=E.mcap_rank(p).get(c, 9999) <= 30)
                buy = reg[i + 1][1]
                for tpn, tp in (("+4%", buy * 1.04), ("목표 없음", None)):
                    r, why = run_exit(c, d, reg, i + 1, buy, tp=tp, sp=buy * 0.98)
                    if r is not None:
                        out.append(dict(base, how="돌파 다음 봉", tpn=tpn, ret=r, why=why))
                k = next((j for j in range(i + 1, min(i + 31, len(reg))) if reg[j][3] <= lvl), None)
                if k is not None:
                    pb = min(reg[k][1], lvl)
                    for tpn, tp in (("+4%", pb * 1.04), ("목표 없음", None)):
                        r, why = run_exit(c, d, reg, k, pb, tp=tp, sp=pb * 0.98, limit_fill=True)
                        if r is not None:
                            out.append(dict(base, how="첫 눌림 지정가", tpn=tpn, ret=r, why=why))
                break
    return out


# ---------------------------------------------------------------- S1 전일 기관 대량 순매수 → 다음 날
def s1_day(d):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    dp = E.daily_day(p)
    cands = []
    for c, r in vr.items():
        if r > 200 or not E.is_common(c):
            continue
        iv = E.inv(c, p)
        val = dp.get(c, (0,) * 6)[5]
        if iv and val and iv[1] > 0 and iv[1] / val >= 0.15:
            cands.append((c, iv[1] / val, iv[0] > 0))
    E.load_day([c for c, _, _ in cands], d)
    out = []
    for c, ratio, fbuy in cands:
        reg, pc = ctx(c, d)
        if not reg:
            continue
        base = dict(style="S1", code=c, date=d, ratio=ratio, both=fbuy, mkt=MKT.get(d), big=E.mcap_rank(p).get(c, 9999) <= 30)
        o = reg[0][1]
        for tpn, tp in (("+3%", o * 1.03), ("목표 없음", None)):
            r, why = run_exit(c, d, reg, 0, o, tp=tp, sp=o * 0.98)
            if r is not None:
                out.append(dict(base, how="09:00 시가", tpn=tpn, t=reg[0][0], ret=r, why=why))
        if o > pc * 1.005:
            k = next((i for i, x in enumerate(reg) if x[0] <= time(11, 0) and x[3] <= pc), None)
            if k is not None:
                for tpn, tp in (("+3%", pc * 1.03), ("목표 없음", None)):
                    r, why = run_exit(c, d, reg, k, pc, tp=tp, sp=pc * 0.98, limit_fill=True)
                    if r is not None:
                        out.append(dict(base, how="전일 종가 지정가", tpn=tpn, t=reg[k][0], ret=r, why=why))
    return out


# ---------------------------------------------------------------- S2 SK하이닉스 vs 삼성전자 강한 쪽
def s2_day(d):
    pair = ("000660", "005930")
    E.load_day(list(pair), d)
    got = {}
    for c in pair:
        reg, pc = ctx(c, d)
        if not reg:
            return []
        j = next((i for i, x in enumerate(reg) if x[0] >= time(10, 0)), None)
        if j is None or j + 1 >= len(reg):
            return []
        got[c] = (reg[j][4] / pc - 1, reg, j)
    c = max(got, key=lambda k: got[k][0])
    ch, reg, j = got[c]
    weak = min(v[0] for v in got.values())
    buy = reg[j + 1][1]
    out = []
    for tpn, tp, sp in (("다음 날 09:00", None, None), ("+2% · −2%", buy * 1.02, buy * 0.98)):
        r, why = run_exit(c, d, reg, j + 1, buy, tp=tp, sp=sp)
        if r is not None:
            out.append(dict(style="S2", code=c, date=d, t=reg[j + 1][0], chg=ch, gap=ch - weak, tpn=tpn, ret=r, why=why, mkt=MKT.get(d)))
    return out


# ---------------------------------------------------------------- G1 NXT 프리장 매수 → KRX 시초가 매도
def g1_day(d):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    cands = [c for c, r in vr.items() if r <= 30 and E.is_common(c) and (E.chg(c, p) or 0) >= 0.05]
    E.load_day(cands, d)
    out = []
    for c in cands:
        b = E.bars(c, d)
        pre = [x for x in b if time(8, 40) <= x[0] < time(8, 50)]     # NXT 프리장은 08:50 에 끝남
        o9 = E.open_at(b, time(9, 0), time(9, 1))
        reg, pc = ctx(c, d)
        if not pre or not o9 or not reg:
            continue
        buy = pre[-1][4]
        out.append(dict(style="G1", code=c, date=d, t=pre[-1][0], pre_chg=buy / pc - 1, ret=o9 / buy - 1 - E.COST, why="09:00 시가", mkt=MKT.get(d)))
    return out


# ---------------------------------------------------------------- C1 애프터 대형주 급락 매수
def c1_day(d):
    p = E.prev_day(d)
    big = [c for c, r in E.mcap_rank(p).items() if r <= 5 and E.is_common(c)]
    E.load_day(big, d)
    out = []
    for c in big:
        b = E.bars(c, d)
        reg = E.regular(b)
        if len(reg) < 60:
            continue
        rc = reg[-1][4]
        after = [x for x in b if time(15, 40) <= x[0] <= time(19, 55)]
        for drop in (0.02, 0.03):
            L = rc * (1 - drop)
            k = next((i for i, x in enumerate(after) if x[3] <= L), None)
            if k is None:
                continue
            buy = min(after[k][1], L)
            tp = buy + (rc - buy) / 2           # 하락폭 절반 회복
            r = None
            for x in after[k + 1:]:
                if x[2] >= tp:
                    r, why = tp / buy - 1 - E.COST, "절반 회복"
                    break
            if r is None:
                nx = E.next_day_exits(c, d, buy)
                if "09:00 시가" not in nx:
                    continue
                r, why = nx["09:00 시가"], "다음 날"
            out.append(dict(style="C1", code=c, date=d, t=after[k][0], drop=drop, ret=r, why=why, mkt=MKT.get(d)))
    return out


# ---------------------------------------------------------------- 실행·보고
STYLES = {"N1": n1_day, "N2": n2_day, "N3": n3_day,
          "B1": b1_day, "S1": s1_day, "S2": s2_day, "G1": g1_day, "C1": c1_day}


def run(styles):
    allt = []
    for i, d in enumerate(E.days()):
        for s in styles:
            allt += STYLES[s](d)
        if i % 20 == 0:
            print(f"  {d} 누적 {len(allt)}", file=sys.stderr)
    if os.path.exists(os.path.join(OUT, "styles.pkl")):     # 다른 방식 결과는 남겨 둔다
        with open(os.path.join(OUT, "styles.pkl"), "rb") as f:
            allt = [t for t in pickle.load(f) if t["style"] not in styles] + allt
    with open(os.path.join(OUT, "styles.pkl"), "wb") as f:
        pickle.dump(allt, f)
    return allt


class Rep(E.Report):
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")


def report(allt):
    R = Rep(os.path.join(OUT, "styles.txt"))
    ds = E.days()
    R.say(f"📕 홍인기 상따 밖 매매 1년 ({ds[0]} ~ {ds[-1]}) — 비용 0.25%, 1건 100만 기준 '만'. ★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +\n")
    S = lambda f: [(t["date"], t["ret"]) for t in allt if f(t)]
    R.say("## 눌림 N1 전일 주도주 D+1·D+2 전일 종가 눌림 (손절 전일 종가 −2%)")
    for lv in (0.01, 0.0):
        for tpn in ("시가", "+3%"):
            n = f"매수 전일 종가{lv:+.0%} · 목표 {tpn}"
            R.stats(S(lambda t: t["style"] == "N1" and t["lv"] == lv and t["tpn"] == tpn), n, 46)
            for g, f in (("D+1", lambda t: t["dn"] == "D+1"), ("D+2", lambda t: t["dn"] == "D+2"), ("대형주(시총 30위)", lambda t: t["big"]),
                         ("둘 다 20일선 아래", lambda t: t["mkt"] == "둘 다 20일선 아래"), ("둘 중 하나↑ 20일선 위", lambda t: t["mkt"] != "둘 다 20일선 아래"),
                         ("전날 대금 10위 안", lambda t: (t["rank"] or 99) <= 10), ("갭 +3%↑", lambda t: t["gap"] >= 0.03)):
                R.stats(S(lambda t, f=f: t["style"] == "N1" and t["lv"] == lv and t["tpn"] == tpn and f(t)), f"   └ {g}", 46)
    R.say("\n## 눌림 N2 지수 과대 낙폭 → 시총 5위 중 그 시각 가장 강한 종목 (매도 코스피 저점 대비 +2% 반등)")
    for drop in (0.03, 0.05):
        for stopn in ("손절 없음", "−3%"):
            R.stats(S(lambda t: t["style"] == "N2" and t["drop"] == drop and t["stopn"] == stopn), f"코스피 고점 대비 −{drop:.0%} · {stopn}", 46)
    n2 = [t for t in allt if t["style"] == "N2" and t["stopn"] == "손절 없음"]
    for t in sorted(n2, key=lambda t: (t["date"], t["drop"])):
        R.say(f"    {t['date']} −{t['drop']:.0%} {t['t']} {E.NAME.get(t['code'], t['code'])[:8]:8s} ({t['chg']:+.1%}) → {t['ret']:+.2%} {t['why']} {t['back'] or ''}")
    R.say("\n## 눌림 N3 당일 강세(대금 10위·고가 +5%↑) 상승폭 되돌림 지정가 (목표 그 고가, 손절 −2%)")
    for k in (1 / 3, 1 / 2):
        R.stats(S(lambda t: t["style"] == "N3" and t["k"] == k), f"되돌림 {'1/3' if k < 0.4 else '1/2'}", 46)
        for g, f in (("대형주(시총 30위)", lambda t: t["big"]), ("고가 +10%↑", lambda t: t["rise"] >= 0.10), ("둘 다 20일선 아래", lambda t: t["mkt"] == "둘 다 20일선 아래")):
            R.stats(S(lambda t, f=f: t["style"] == "N3" and t["k"] == k and f(t)), f"   └ {g}", 46)
    report_more(R, allt)


def report_more(R, allt):
    S = lambda f: [(t["date"], t["ret"]) for t in allt if f(t)]
    if any(t["style"] == "B1" for t in allt):
        R.say("\n## 돌파 B1 60일 신고가 돌파 (그 시각 대금 순위·끼) — 손절 −2%")
        for how in ("돌파 다음 봉", "첫 눌림 지정가"):
            for tpn in ("+4%", "목표 없음"):
                f0 = lambda t, how=how, tpn=tpn: t["style"] == "B1" and t["how"] == how and t["tpn"] == tpn
                R.stats(S(f0), f"{how} · 목표 {tpn}", 46)
                for g, f in (("대금 10위 안", lambda t: t["rank"] <= 10), ("대금 10위 + 끼", lambda t: t["rank"] <= 10 and t["kki"]),
                             ("대형주(시총 30위)", lambda t: t["big"]), ("둘 다 20일선 아래", lambda t: t["mkt"] == "둘 다 20일선 아래")):
                    R.stats(S(lambda t, f=f, f0=f0: f0(t) and f(t)), f"   └ {g}", 46)
    if any(t["style"] == "S1" for t in allt):
        R.say("\n## 수급 S1 전날 기관 순매수 ≥ 그날 대금 15% → 다음 날 (손절 −2%)")
        for how in ("09:00 시가", "전일 종가 지정가"):
            for tpn in ("+3%", "목표 없음"):
                f0 = lambda t, how=how, tpn=tpn: t["style"] == "S1" and t["how"] == how and t["tpn"] == tpn
                R.stats(S(f0), f"{how} · 목표 {tpn}", 46)
                for g, f in (("외국인도 순매수", lambda t: t["both"]), ("기관 30%↑", lambda t: t["ratio"] >= 0.3), ("대형주(시총 30위)", lambda t: t["big"])):
                    R.stats(S(lambda t, f=f, f0=f0: f0(t) and f(t)), f"   └ {g}", 46)
    if any(t["style"] == "S2" for t in allt):
        R.say("\n## 수급 S2 10:00 SK하이닉스·삼성전자 중 강한 쪽")
        for tpn in ("다음 날 09:00", "+2% · −2%"):
            f0 = lambda t, tpn=tpn: t["style"] == "S2" and t["tpn"] == tpn
            R.stats(S(f0), tpn, 46)
            R.stats(S(lambda t, f0=f0: f0(t) and t["gap"] >= 0.01), "   └ 둘 차이 1%p↑", 46)
            R.stats(S(lambda t, f0=f0: f0(t) and t["chg"] > 0), "   └ 강한 쪽이 상승 중", 46)
    if any(t["style"] == "G1" for t in allt):
        R.say("\n## 시가 G1 전날 주도주(대금 30위·+5%) NXT 08:59 매수 → KRX 09:00 시가 매도")
        R.stats(S(lambda t: t["style"] == "G1"), "전체", 46)
        for g, f in (("프리장 전일 대비 하락", lambda t: t["pre_chg"] < 0), ("프리장 0~+5%", lambda t: 0 <= t["pre_chg"] < 0.05),
                     ("프리장 +5%↑", lambda t: t["pre_chg"] >= 0.05)):
            R.stats(S(lambda t, f=f: t["style"] == "G1" and f(t)), f"   └ {g}", 46)
    if any(t["style"] == "C1" for t in allt):
        R.say("\n## 종가 C1 시총 5위 애프터 급락 매수 → 하락폭 절반 회복 또는 다음 날 09:00")
        for drop in (0.02, 0.03):
            R.stats(S(lambda t, drop=drop: t["style"] == "C1" and t["drop"] == drop), f"정규장 종가 대비 −{drop:.0%}", 46)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--report-only" in sys.argv:
        with open(os.path.join(OUT, "styles.pkl"), "rb") as f:
            report(pickle.load(f))
        return
    styles = [a for a in sys.argv[1:] if a in STYLES] or list(STYLES)
    report(run(styles))


if __name__ == "__main__":
    main()
