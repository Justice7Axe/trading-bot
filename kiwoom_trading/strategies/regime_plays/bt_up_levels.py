"""1️⃣ 상승장 장 초 — 차트 지지·저항 자리 매수 (2026-10-28 사용자: 대한광통신 09:57 14,250 / 10:57 14,850).

후보·유니버스·자료는 bt_up_pullback.py 와 똑같이 (u_cands.pkl, 강한 상승장 U 날 09:10 대금 40위·시가 위·전날 외인·기관 둘 다 − 제외,
우선주·상한가 근처·09:10~11 봉 없음·다음 날 09:00 없음 제외 → 607건). 1분봉 = engine (원가격, AL 통합). 일봉 수정주가 안 씀.
매 분 그때까지 봉만 봄 (미래 정보 없음). 종목당 하루 P1·P2 각 첫 신호 1번.

P1 시초 저점 지지: L = 09:00~09:10 최저가. 09:11 뒤 '기준 봉' = 저가 ≤ L×1.01 인 봉
   (거래량 변형: 그 봉 거래량 ≥ 직전 20봉 평균 × k 이고 음봉). 기준 봉 뒤 N봉 동안 종가가 L 아래로 안 감 →
   그 뒤 첫 '직전 봉 고가 돌파' 봉(종가 ≥ L)이 신호 → 다음 봉 시가 매수. 도중 종가 < L 이면 처음부터 다시. 신호 ~11:30.
   손절 = max(L × 0.997, 매수가 × 0.94). 터치(닿으면 그 가격) 또는 마감(종가가 아래면 다음 봉 시가).
P2 오전 고점 박스 돌파: H = 09:00~09:30 고가(고정, 09:31 뒤 신호) 또는 직전 봉까지 그날 최고가(계속 갱신).
   신호 봉 직전 M봉 = 박스: 모두 종가 ≤ H, 저가 ≥ H × 0.985 (변형: 박스 뒤 절반 최저 > 앞 절반 최저 = 저점 높임).
   신호 봉 종가 > H 이고 거래량 ≥ 박스 평균 × k → 다음 봉 시가 매수 (신호 ~13:00). 손절 = max(박스 최저 × 0.997, 매수가 × 0.94), 터치.
매도 (a) 손절 아니면 다음 날 09:00 시가 (b) 2R 닿으면 절반 → 나머지 max(매수 뒤 고가 × 0.97, 본전) 트레일링, 15:19 까지 안 끝나면 다음 날 09:00.
   같은 봉에서 손절·익절 둘 다면 손절 먼저. 비용 0.25%. 체결가 상한가 근처(+29%↑) 못 삼.
하루 1천만 원 = 그날 산 종목(자리) 수로 나눔. ★ = 앞·뒤 반기 둘 다 + 이고 가장 좋은 5일 빼도 +.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.regime_plays.bt_up_levels → data/backtest/up_levels.txt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

OUT = os.path.join(E.DATA, "backtest"); os.makedirs(OUT, exist_ok=True)
UNTIL = time(15, 19)
F = None


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


# ───────── 신호 ─────────
def sig_p1(b, kv, N, t_end=time(11, 30)):
    """→ (매수 봉 인덱스, L, 기준 봉 시각, 신호 봉 시각) 또는 None."""
    pre = [x for x in b if x[0] <= time(9, 10)]
    if not pre: return None
    L = min(x[3] for x in pre)
    a = None
    for k in range(len(pre), len(b)):
        t, o, h, l, c, v = b[k][:6]
        if t > t_end: return None
        if a is not None:
            if c < L:
                a = None
            elif k >= a + N and h > b[k - 1][2]:
                if k + 1 < len(b) and b[k + 1][0] <= UNTIL:
                    return k + 1, L, b[a][0], t
                return None
        if a is None and l <= L * 1.01 and c >= L * 0.99:
            if kv:
                if k < 20: continue
                avg = np.mean([x[5] for x in b[k - 20:k]])
                if not (avg > 0 and v >= kv * avg and c < o): continue
            if c >= L or kv:   # 거래량 봉은 L 살짝 아래 마감도 기준으로 (뒤 N봉이 L 위 마감해야 함)
                a = k
    return None


def sig_p2(b, M, kv, hmode, rising=False, t_end=time(13, 0)):
    """→ (매수 봉 인덱스, 박스 최저, H, 신호 봉 시각) 또는 None."""
    H30 = max((x[2] for x in b if x[0] <= time(9, 30)), default=None)
    runH = None
    for k in range(len(b)):
        t, o, h, l, c, v = b[k][:6]
        if t > t_end: return None
        if hmode == "fix":
            H = H30
            ok_t = t >= time(9, 31) and k - M >= 0 and b[k - M][0] > time(9, 30)
        else:
            H = runH
            ok_t = t >= time(9, 11) and k - M >= 0
        if ok_t and H and c > H:
            box = b[k - M:k]
            if all(x[4] <= H and x[3] >= H * 0.985 for x in box):
                bavg = np.mean([x[5] for x in box])
                rise_ok = True
                if rising:
                    hm = M // 2
                    rise_ok = min(x[3] for x in box[hm:]) > min(x[3] for x in box[:hm])
                if bavg > 0 and v >= kv * bavg and rise_ok:
                    if k + 1 < len(b) and b[k + 1][0] <= UNTIL:
                        return k + 1, min(x[3] for x in box), H, t
                    return None
            if hmode == "fix":
                pass    # 고정 H 는 첫 돌파가 조건 못 맞춰도 계속 봄 (박스 다시 생기면)
        runH = h if runH is None else max(runH, h)
    return None


# ───────── 매도 ─────────
def run_exit(b, k, buy, stop, mode, how, nx):
    """b[k] 시가 buy 매수. stop = 손절가. mode 't' 터치 / 'c' 마감(다음 봉 시가). how 'a' 다음 날 09:00 / 'b' 2R 절반+트레일.
    nx = 다음 날 09:00 시가 (가격). → 비용 뺀 수익률."""
    R = buy - stop
    tp = buy + 2 * R if how == "b" else None
    pos, got, half, hi, pending = 1.0, 0.0, False, buy, False
    for x in b[k:]:
        t, o, h, l, c = x[:5]
        if t > UNTIL: break
        if pending:
            return got + pos * (o / buy - 1) - E.COST
        if half:
            tr = max(hi * 0.97, buy)
            if l <= tr:
                return got + pos * (min(o, tr) / buy - 1) - E.COST
        if not half:
            lv = stop if mode == "t" else buy * 0.94      # 터치로 나가는 값 (마감 방식이어도 −6% 는 터치)
            if l <= lv:
                return got + pos * (min(o, lv) / buy - 1) - E.COST
            if mode == "c" and c < stop:
                pending = True; hi = max(hi, h); continue
        if tp is not None and not half and h >= tp:
            px = max(o, tp)
            got += 0.5 * (px / buy - 1); pos = 0.5; half = True
            hi = max(hi, h); continue    # 트레일링은 다음 봉부터
        hi = max(hi, h)
    return got + pos * (nx / buy - 1) - E.COST


# ───────── 집계 ─────────
def stats(tr):
    """tr = [(date, ret, R%)]  (R% 없으면 None)."""
    if len(tr) < 5: return None
    ds = sorted({x[0] for x in tr}); hd = ds[len(ds) // 2]
    v = np.array([x[1] for x in tr]); a = [x[1] for x in tr if x[0] < hd]; bb = [x[1] for x in tr if x[0] >= hd]
    bd = defaultdict(list)
    for x in tr: bd[x[0]].append(x[1])
    dr = {d: np.mean(x) for d, x in bd.items()}
    s = sorted(dr.values(), reverse=True)
    eq = np.cumsum([dr[d] for d in sorted(dr)]) * 1000
    mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    star = "★" if np.mean(a) > 0 and np.mean(bb) > 0 and sum(s[5:]) > 0 else " "
    rr = [x[2] for x in tr if x[2]]
    rm = [x[1] / x[2] for x in tr if x[2]]
    loss = [x[1] for x in tr if x[1] < 0]
    return dict(n=len(v), days=len(dr), mean=v.mean(), a=np.mean(a), b=np.mean(bb), tot=sum(s) * 1000, ex5=sum(s[5:]) * 1000,
                mdd=mdd, star=star, R=np.mean(rr) if rr else None, Rm=np.mean(rm) if rm else None,
                loss=np.mean(loss) if loss else 0, win=np.mean(v > 0))


def line(name, s, extra=""):
    if s is None:
        say(f"   {name:34s} 적음"); return
    R = f"{s['R']:5.2%} {s['Rm']:+5.2f}R" if s["R"] else f"{'-':>5s} {'-':>6s}"
    say(f" {s['star']} {name:34s} {s['n']:4d} {s['mean']:+6.2%} {s['a']:+6.2%} {s['b']:+6.2%} {s['tot']:+6.0f}만 {s['ex5']:+6.0f}만 "
        f"{s['mdd']:4.0f}만 {s['win']:4.0%} {s['loss']:+6.2%} {R} {extra}")


P1S = [  # (이름, k, N, 손절 방식, 매도)
    ("P1 거래량× 없음 N2", None, 2, "t", "a"),
    ("P1 거래량× 없음 N3", None, 3, "t", "a"),
    ("P1 거래량× 없음 N5", None, 5, "t", "a"),
    ("P1 거래량×2 N2", 2, 2, "t", "a"),
    ("P1 거래량×2 N3", 2, 3, "t", "a"),
    ("P1 거래량×2 N5", 2, 5, "t", "a"),
    ("P1 거래량×3 N2", 3, 2, "t", "a"),
    ("P1 거래량×3 N3", 3, 3, "t", "a"),
    ("P1 거래량×3 N5", 3, 5, "t", "a"),
    ("P1 거래량× 없음 N3 마감손절", None, 3, "c", "a"),
    ("P1 거래량×2 N3 마감손절", 2, 3, "c", "a"),
    ("P1 거래량× 없음 N3 ·2R트레일", None, 3, "t", "b"),
    ("P1 거래량×2 N3 ·2R트레일", 2, 3, "t", "b"),
    ("P1 거래량×3 N3 ·2R트레일", 3, 3, "t", "b"),
]
P2S = [  # (이름, M, k, H, 저점높임, 매도)
    ("P2 H09:30 M10 ×2", 10, 2, "fix", False, "a"),
    ("P2 H09:30 M10 ×3", 10, 3, "fix", False, "a"),
    ("P2 H09:30 M20 ×2", 20, 2, "fix", False, "a"),
    ("P2 H09:30 M20 ×3", 20, 3, "fix", False, "a"),
    ("P2 H갱신 M10 ×2", 10, 2, "run", False, "a"),
    ("P2 H갱신 M10 ×3", 10, 3, "run", False, "a"),
    ("P2 H갱신 M20 ×2", 20, 2, "run", False, "a"),
    ("P2 H갱신 M20 ×3", 20, 3, "run", False, "a"),
    ("P2 H09:30 M10 ×2 저점높임", 10, 2, "fix", True, "a"),
    ("P2 H갱신 M10 ×2 저점높임", 10, 2, "run", True, "a"),
    ("P2 H09:30 M10 ×2 ·2R트레일", 10, 2, "fix", False, "b"),
    ("P2 H갱신 M10 ×2 ·2R트레일", 10, 2, "run", False, "b"),
]
ADD = [("09:11 + P1 거래량×2 N3", "P1 거래량×2 N3"), ("09:11 + P2 H09:30 M10 ×2", "P2 H09:30 M10 ×2"),
       ("09:11 + P2 H갱신 M10 ×2", "P2 H갱신 M10 ×2")]


def make_trade(b, f, pc0, stop_lvl, mode, how, nx_px):
    k = f[0]; buy = b[k][1]
    if buy / pc0 - 1 >= 0.29: return None
    stop = max(stop_lvl, buy * 0.94)
    if stop >= buy * 0.995: stop = buy * 0.995     # 매수가가 레벨 아래로 갭 → R 최소 0.5%
    ret = run_exit(b, k, buy, stop, mode, how, nx_px)
    return buy, stop, ret


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(OUT, "up_levels.txt"), "w", encoding="utf-8")
    rows, _ = _load("u_cands.pkl")
    feat = _load("regime_feat.pkl")
    sel = [r for r in rows if r["T"] == time(9, 10) and r["date"] in feat and cls_of(feat[r["date"]]) == "U"
           and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
           and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    say(f"1️⃣ 후보 {len(sel)}건 {len({r['date'] for r in sel})}일, 1분봉 출처 {E.P0}~{E.P1}")
    miss = defaultdict(int)
    res = defaultdict(list)     # 이름 → [(date, ret, R%)]
    fired = defaultdict(set)
    b0 = {}                     # 키 → B0 −6% 수익률
    meta = defaultdict(list)    # 이름 → (매수가/09:11시가 −1, 분)
    tradeinfo = {}              # (이름, 키) → ret
    keys = []
    for r in sel:
        d, c = r["date"], r["code"]
        if not E.is_common(c): miss["우선주"] += 1; continue
        b = E.regular(E.bars(c, d))
        idx = {x[0]: i for i, x in enumerate(b)}
        if not all(t in idx for t in (time(9, 10), time(9, 11))):
            miss["09:10~11 봉 없음"] += 1; continue
        j = idx[time(9, 11)]; buy0 = b[j][1]
        pc0 = b[0][1] / (1 + r["gap"])
        if buy0 / pc0 - 1 >= 0.29: miss["상한가 근처"] += 1; continue
        nx = E.next_day_exits(c, d, buy0).get("09:00 시가")
        if nx is None: miss["다음 날 09:00 없음"] += 1; continue
        nx_px = (nx + E.COST + 1) * buy0
        key = (d, c); keys.append(key)
        # 기준선
        for nm, st in (("B0 09:11 시가 −6% (지금)", 0.06), ("B0 09:11 시가 −6% ·2R트레일", 0.06)):
            how = "b" if "2R" in nm else "a"
            ret = run_exit(b, j, buy0, buy0 * (1 - st), "t", how, nx_px)
            res[nm].append((d, ret, st)); fired[nm].add(key)
            if how == "a": b0[key] = ret
        for nm, kv, N, mode, how in P1S:
            f = sig_p1(b, kv, N)
            if not f: continue
            t = make_trade(b, f, pc0, f[1] * 0.997, mode, how, nx_px)
            if not t: continue
            buy, stop, ret = t
            res[nm].append((d, ret, 1 - stop / buy)); fired[nm].add(key); tradeinfo[(nm, key)] = ret
            meta[nm].append((buy / buy0 - 1, b[f[0]][0].hour * 60 + b[f[0]][0].minute - 540))
        for nm, M, kv, hm, rise, how in P2S:
            f = sig_p2(b, M, kv, hm, rise)
            if not f: continue
            t = make_trade(b, f, pc0, f[1] * 0.997, "t", how, nx_px)
            if not t: continue
            buy, stop, ret = t
            res[nm].append((d, ret, 1 - stop / buy)); fired[nm].add(key); tradeinfo[(nm, key)] = ret
            meta[nm].append((buy / buy0 - 1, b[f[0]][0].hour * 60 + b[f[0]][0].minute - 540))
    say("빠진 것: " + ", ".join(f"{k} {v}" for k, v in miss.items()) + f" → 남은 후보 {len(keys)}건")
    for nm, src in ADD:     # 09:11 매수 1자리 + 신호 나면 1자리 더 (같은 크기)
        for key in keys:
            res[nm].append((key[0], b0[key], 0.06))
            if (src, key) in tradeinfo:
                res[nm].append((key[0], tradeinfo[(src, key)], None))
    nall = len(P1S) + len(P2S) + len(ADD)
    say(f"\n시험한 조합 {nall}개 (P1 {len(P1S)} + P2 {len(P2S)} + 불타기 {len(ADD)}) + 기준 2. 같은 자료에서 고른 것이라 가장 좋은 하나는 우연일 수 있음.")
    say("1천만/일 = 그날 산 자리 수로 나눔. R% = 매수가 대비 손절까지 거리(평균), R배 = 수익률÷R 평균. 손실평균 = 진 거래 평균.")
    say("역선택: '신호 난 B0' = 신호가 난 종목을 09:11 에 샀다면(−6%), '안 난 B0' = 신호 안 난 종목의 09:11 결과.")
    say("=" * 175)
    say(f"   {'조합':34s} {'건수':>4s} {'건당':>6s} {'앞':>6s} {'뒤':>6s} {'1천만/일':>7s} {'최고5일빼':>7s} {'낙폭':>5s} {'승률':>4s} {'손실평균':>6s} "
        f"{'R%':>5s} {'R배':>6s} | 신호 난 B0 · 안 난 B0 | 매수가 vs 09:11 · 매수 시각 중앙")
    for nm in ["B0 09:11 시가 −6% (지금)", "B0 09:11 시가 −6% ·2R트레일"] + [x[0] for x in P1S] + [x[0] for x in P2S] + [x[0] for x in ADD]:
        s = stats(res[nm])
        extra = ""
        if nm in meta and meta[nm]:
            fb = [b0[k] for k in keys if k in fired[nm]]; mb = [b0[k] for k in keys if k not in fired[nm]]
            disc = np.median([x[0] for x in meta[nm]]); tm = int(np.median([x[1] for x in meta[nm]]))
            extra = (f"| {np.mean(fb):+.2%}({len(fb)}) · {(np.mean(mb) if mb else 0):+.2%}({len(mb)}) | {disc:+.1%} · "
                     f"{9 + tm // 60:02d}:{tm % 60:02d} ({s['days'] if s else 0}일)")
        if nm.startswith("P1 거래량× 없음 N2") or nm.startswith("P2 H09:30 M10 ×2") and "저점" not in nm and "2R" not in nm or nm.startswith("09:11 +"):
            say("-" * 175)
        line(nm, s, extra)
    say("\n★ = 앞·뒤 반기 둘 다 + 이고 가장 좋은 5일 빼도 합계 +")


def today_examples():
    say("\n" + "=" * 175)
    say("오늘(2026-10-28) 예시 — KRX 1분봉 (data/leader_capture/bars_krx.pkl). 다음 날 09:00 없음 → 오늘 정규장 종가로 수익 표시 (비용 뺌)")
    B = pickle.load(open(os.path.join(E.DATA, "leader_capture", "bars_krx.pkl"), "rb"))
    d = date(2026, 10, 28)
    for c, nm in (("010170", "대한광통신"), ("003160", "디아이"), ("069540", "빛과전자"), ("253590", "네오셈")):
        raw = B.get((c, d))
        if not raw: say(f"  {nm}({c}) 1분봉 없음"); continue
        b = [(x[0].time(), *x[1:]) for x in raw if time(9, 0) <= x[0].time() <= time(15, 30)]
        idx = {x[0]: i for i, x in enumerate(b)}
        if time(9, 11) not in idx: say(f"  {nm}({c}) 09:11 봉 없음"); continue
        j = idx[time(9, 11)]; buy0 = b[j][1]; close = b[-1][4]
        L = min(x[3] for x in b if x[0] <= time(9, 10)); H30 = max(x[2] for x in b if x[0] <= time(9, 30))
        say(f"  {nm}({c}) 시가 {b[0][1]:,.0f} · L(09:00~10 최저) {L:,.0f} · H(09:00~30 고가) {H30:,.0f} · 09:11 시가 {buy0:,.0f} → 종가 {close:,.0f} "
            f"({close / buy0 - 1 - E.COST:+.1%})")
        for nm2, kv, N, *_ in P1S[:9]:
            f = sig_p1(b, kv, N)
            if not f: say(f"     {nm2:22s} 신호 없음"); continue
            k = f[0]; buy = b[k][1]; stop = max(L * 0.997, buy * 0.94)
            hit = next((x[0] for x in b[k:] if x[0] <= UNTIL and x[3] <= stop), None)
            say(f"     {nm2:22s} 기준 봉 {f[2].strftime('%H:%M')} 신호 {f[3].strftime('%H:%M')} → {b[k][0].strftime('%H:%M')} 매수 {buy:,.0f} "
                f"손절 {stop:,.0f} (R {1 - stop / buy:.1%}) → " + (f"{hit.strftime('%H:%M')} 손절" if hit else f"종가 {close / buy - 1 - E.COST:+.1%} ({(close - buy) / (buy - stop):+.1f}R)"))
        for nm2, M, kv, hm, rise, how in P2S[:10]:
            f = sig_p2(b, M, kv, hm, rise)
            if not f: say(f"     {nm2:22s} 신호 없음"); continue
            k = f[0]; buy = b[k][1]; stop = max(f[1] * 0.997, buy * 0.94)
            hit = next((x[0] for x in b[k:] if x[0] <= UNTIL and x[3] <= stop), None)
            say(f"     {nm2:22s} H {f[2]:,.0f} 신호 {f[3].strftime('%H:%M')} → {b[k][0].strftime('%H:%M')} 매수 {buy:,.0f} 손절 {stop:,.0f} "
                f"(R {1 - stop / buy:.1%}) → " + (f"{hit.strftime('%H:%M')} 손절" if hit else f"종가 {close / buy - 1 - E.COST:+.1%} ({(close - buy) / (buy - stop):+.1f}R)"))


if __name__ == "__main__":
    main()
    today_examples()
    F.close()
