"""디앤서 상따 (4장 p.198~207)·테마 짝꿍 (p.166~183) — 공통 엔진 판 (코드 검토 반영, 2026-10-25).
1분봉 = minute_history + kang_minute(장중 +15%↑ 날·전날 +15%↑ 다음 날, 강창권 세션). kang 이 없으면 멈춘다(NEED_KANG).

[상따] 책: 시세 초입 상한가 선호, 시총 500억 이하·3연상 이후 피함, +20% 근처부터 보고 **+25%부터 모아 가다 상한가에 불타기**,
  선호는 **애프터마켓 상따**(다음 날 프리마켓 거래 종목을 애프터에서 매수), 다음 날 '갭이 없어도 무조건' 프리마켓 갭·시초가에 매도.
  L1 애프터 상따: 정규장 상한가(+29.5%↑) 마감 → 19:55 봉 종가가 상한가 아래면(체결 가능) 그 가격 매수, 아니면 '못 삼'
     → 다음 날 08:00 NXT 시가 / 프리 3분할 / 09:00 시가.
  L2 +25% 모아 가기: 09:00~15:18 처음 +25%(전일 종가×f 기준) 닿은 봉 다음 봉 시가 매수(그 봉 내내 상한가면 못 삼)
     → 15:19 가격이 상한가면 다음 날 매도(동시호가에서 풀리면 그 손실도 다음 날 가격에 반영), 아니면 15:19 정리.
  나눔: 시총(전날, 지금 주식 수 × 일봉 종가) 500억↑, 앞선 연속 상한가 수(0 첫 상한가 / 1 2연상 / 2↑ 3연상 이후). 우선주 제외.
[테마 짝꿍] 대장 = 테마 안에서 가장 빨리 상한가 간 종목. 후속주 매수 자리 = 대장 상한가 진입 ★5, 2차 VI(약 +25%) ★4.
  후속주가 상한가 가면 10분 안 매도, 대장이 멈칫하면 손절.
  근사: 테마 = 업종(stocks.sector, 26개라 거칠다). 신호 시각까지 같은 업종에서 +10% 닿은 종목이 3개↑.
  ★5 대장 = 그 업종에서 가장 먼저 상한가 닿은 종목, ★4 대장 = 가장 먼저 +25% 닿은 종목 (그 시각에 알 수 있는 것만).
  후속주 = 신호 시각에 같은 업종에서 +5%~+20% 인 종목 중 등락률 1·2위 (그날 1분봉 있는 종목 전부에서).
  매도 = 후속주 상한가 닿은 뒤 10분(시각) 지난 첫 봉 종가 / 대장이 상한가 닿은 뒤 상한가×0.97 아래 종가면 다음 봉 시가 / 아니면 15:19.
"""
import os, sys
from collections import defaultdict
from datetime import datetime, time, timedelta
from engine import *
from engine import _min_codes

R = Report("t_limitup.txt")


def tags(c, d):
    n = streak_limitup(c, d)
    return ["전체"] + (["시총 500억↑"] if mcap(c, prev_day(d)) >= 5e10 else []) + [("첫 상한가" if n == 0 else "2연상" if n == 1 else "3연상 이후")]


def plus(t, m):
    return (datetime.combine(date.today(), t) + timedelta(minutes=m)).time()


def main():
    L1, L2, TH = defaultdict(list), defaultdict(list), defaultdict(list)
    cnt = defaultdict(int)
    R.say("1분봉 출처: " + ", ".join(str(src.execute("SELECT count(*) FROM minute_backfill_done").fetchone()[0]) + "종목·일" for src in MIN_SRC))
    for d in days():
        pd_ = daily_day(prev_day(d))
        codes = [c for c in _min_codes(d) if c in pd_ and is_common(c)]
        B = load_day(codes, d)
        nd = next_day(d)
        info = {}
        for c in codes:
            reg = regular(B[c])
            f = factor(c, d)
            if len(reg) < 30 or not f: continue
            info[c] = (reg, pd_[c][3] * f)
        # ---------------- 상따
        for c, (reg, pc) in info.items():
            lim = pc * 1.295
            if max(x[2] for x in reg) < pc * 1.25: continue
            tg = tags(c, d)
            ch = chg(c, d)
            if ch is not None and ch >= LIMIT:
                cnt["상한가 마감"] += 1
                am = [x for x in B[c] if time(19, 0) <= x[0] <= time(19, 55)]
                if not am: cnt["  애프터 봉 없음"] += 1
                elif am[-1][4] >= lim * 0.999: cnt["  19:55 상한가 잠김(못 삼)"] += 1
                else:
                    if nd: load_day([c], nd)
                    for k, v in next_day_exits(c, d, am[-1][4]).items():
                        for t in tg: L1[(t, k)].append((d, v))
                    cnt["  애프터 매수"] += 1
            j = next((i for i, x in enumerate(reg) if x[2] >= pc * 1.25), None)
            if j is None or reg[j][0] > time(15, 18) or j + 1 >= len(reg): continue
            nb = reg[j + 1]
            if nb[3] >= lim * 0.999: cnt["+25% 다음 봉 내내 상한가(못 삼)"] += 1; continue
            buy = nb[1]; cnt["+25% 매수"] += 1
            p1519 = at(reg, time(15, 19))
            if p1519 >= lim * 0.999:
                if nd: load_day([c], nd)
                ex = next_day_exits(c, d, buy)
            else:
                v = p1519 / buy - 1 - COST
                ex = {"08:00 NXT 시가": v, "프리 3분할": v, "09:00 시가": v}
            for k, v in ex.items():
                for t in tg: L2[(t, k)].append((d, v))
        # ---------------- 테마 짝꿍 (업종 근사)
        bysec = defaultdict(list)
        for c in info: bysec[SECTOR.get(c)].append(c)
        hit = lambda c, m: next((x[0] for x in info[c][0] if x[2] >= info[c][1] * m), None)
        for sec, cs in bysec.items():
            if not sec: continue
            for star, mult in (("★5 대장 상한가", 1.295), ("★4 대장 +25%", 1.25)):
                firsts = sorted((hit(c, mult), c) for c in cs if hit(c, mult))
                if not firsts: continue
                t_sig, lc = firsts[0]
                n10 = sum(1 for c in cs if (hit(c, 1.10) or time(23, 59)) <= t_sig)
                if n10 < 3: continue
                lreg, lpc = info[lc]
                cands = []
                for c in cs:
                    if c == lc: continue
                    p = at(info[c][0], t_sig)
                    if p and 1.05 <= p / info[c][1] <= 1.20: cands.append((p / info[c][1], c))
                for rank, (_, c) in enumerate(sorted(cands, reverse=True)[:2], 1):
                    reg, pc = info[c]
                    j = next((i for i, x in enumerate(reg) if x[0] > t_sig), None)
                    if j is None or reg[j][0] > time(15, 18): continue
                    buy = reg[j][1]; out = None; t_lim = None
                    for k in range(j, len(reg)):
                        x = reg[k]
                        if x[0] > time(15, 19): break
                        if t_lim is None and x[2] >= pc * 1.295: t_lim = x[0]
                        if t_lim and x[0] >= plus(t_lim, 10): out = x[4]; break
                        lx = at(lreg, x[0])
                        led_lim = any(y[2] >= lpc * 1.295 for y in lreg if y[0] <= x[0])
                        if not t_lim and led_lim and lx < lpc * 1.295 * 0.97:
                            out = reg[k + 1][1] if k + 1 < len(reg) else x[4]; break
                    if out is None: out = at(reg, time(15, 19))
                    TH[(star, f"후속 {rank}등")].append((d, out / buy - 1 - COST))
        print(d, file=sys.stderr, flush=True)
    R.say(f"디앤서 상따·테마 짝꿍 1년 ({P0}~{P1}) — " + ", ".join(f"{k} {v}" for k, v in cnt.items()) + f" | 다음 날 가격 기준 맞춤 {dict(BASIS_FIX)}")
    R.say("\nL1 애프터 상따 (정규장 상한가 마감 → 19:55 봉 종가가 상한가 아래일 때만 매수)")
    for t in ("전체", "시총 500억↑", "첫 상한가", "2연상", "3연상 이후"):
        for k in ("08:00 NXT 시가", "프리 3분할", "09:00 시가"):
            R.stats(L1[(t, k)], f"  {t} → {k}", 40)
    R.say("\nL2 +25% 모아 가기 (15:19 상한가면 다음 날 매도, 아니면 15:19 정리)")
    for t in ("전체", "시총 500억↑", "첫 상한가", "2연상", "3연상 이후"):
        for k in ("08:00 NXT 시가", "프리 3분할", "09:00 시가"):
            R.stats(L2[(t, k)], f"  {t} → (상한가 유지 시) {k}", 40)
    R.say("\n테마 짝꿍 (업종 근사, 신호 시각까지 같은 업종 +10% 3종목↑)")
    for star in ("★5 대장 상한가", "★4 대장 +25%"):
        for rk in ("후속 1등", "후속 2등"):
            R.stats(TH[(star, rk)], f"  {star} → {rk}", 40)


if __name__ == "__main__":
    main()
