"""디앤서 수급주 매매 (『실전 시황 트레이딩』 3장 p.85~92 선정, 4장 p.184~197 매매) — 공통 엔진 판.

책 정의 (원문 확인 2026-10-25):
- "외국인과 기관 같은 메이저 세력이 집중하며 변동성을 일으키는 종목", "보통 시가총액이 큰 종목에서 관찰된다" (p.184~185).
- 4조건 (p.86): ① 큰 거래대금 ② 시장을 이끄는 주도 섹터 ③ 프로그램과 외국인·기관 같은 큰 자금 유입 ④ 신고가·추세 돌파처럼 강한 흐름.
- 하락 추세인데 수급만 보고 사지 않는다 · 수급·변동성·거래대금이 동시에 생긴 뒤 연속성 있는 매수세인지 (p.86~87).
  하루 샀다고 수급이 좋다 하지 않는다 — 연속성 (p.92). 관심 밖 종목의 수급은 의미 없음 (p.89).
- 매매 (p.185~188): 09:10쯤부터 방향 확인, 09~10시 관찰로 진입, 애매하면 11시 이후 피함, 14시부터 다시.
  볼 것 = 전일 종가 위인지, 전일 고가로 가는지, 중요한 가격을 메이저가 지키는지, 250일 신고가 자리.
  의미 있는 자리 돌파 → 절반, 확인 후 나머지 (여기선 한 번에 산 것으로 계산). 손절 2% 이내.
  메이저 수급 + 250일 신고가 20% 안 추세 + 전일 고점 위 신고가 영역이면 다음 날까지, 박스·하락 모양이면 2~3% 익절.
- 책은 **그날 장중 실시간 수급**(외인 = 프로그램, 기관 = 시간대별 투자자)으로 판단한다. 우리는 장중 수급 과거 자료가 없다
  (잠정치 저장은 2026-10-14부터 8일뿐) → (가) 전날까지의 연속 수급으로 대신, (나) 그날 확정 양매수인 날만 = 장중 수급을 완벽히 읽었을 때의 **상한선**(미래 정보).
숫자 정의 (미리 정함):
  대형 = 전날 시총 순위(지금 주식 수 × 수정 종가) 30위 / 100위 안 · 관심 = 전날 대금 30위 / 50위 안
  상승 추세 = 전날 종가 ≥ 20일 이동평균 & ≥ 250일 고가 × 0.8 (일봉끼리)
  연속 수급 = 전날 양매수 / 최근 3일 중 2일↑ 양매수 / 전날·전전날 연속 양매수
  진입 (09:10~10:30, 다음 봉 시가): a 오전 고가(09:00~09:09 고가) 돌파 · b 전일 고가 돌파(시가가 아래였을 때) · c 전일 종가 재돌파(시가가 아래였을 때)
         + 오후 창 14:00~15:00 (책: 14시부터 다시) 은 a 대신 '그날 고가 돌파'
  매도: 손절 −2% · (i) 익절 +2.5% 아니면 15:19 · (ii) 익절 없음, 15:19 가격이 250일 고가 80%↑ & 전일 고가 위면 다음 날 09:00 시가
"""
import sys
from collections import defaultdict
from datetime import time
from engine import *

R = Report("t_supply.txt")


def main():
    res = defaultdict(list); n_univ = defaultdict(int)
    cases = []
    for d in days():
        p, pp, p3 = prev_day(d), prev_day(d, 2), prev_day(d, 3)
        mr, vr = mcap_rank(p), value_rank(p)
        cand = [c for c in daily_day(p) if is_common(c) and mr.get(c, 9e9) <= 100 and vr.get(c, 9e9) <= 50]
        load_day(cand, d)
        for c in cand:
            f = factor(c, d)
            if f is None: continue
            reg = regular(bars(c, d))
            if not reg or reg[0][0] > time(9, 1) or sum(1 for x in reg if x[0] <= time(10, 30)) < 60: continue
            pr = daily_day(p)[c]
            ma20, h250 = ma_n(c, d, 20), hi_n(c, d, 250)
            if not ma20 or not h250: continue
            up = pr[3] >= ma20 and pr[3] >= h250 * 0.8
            b1, b2, b3 = both_buy(c, p), both_buy(c, pp), both_buy(c, p3)
            if inv(c, p) is None: continue
            today = both_buy(c, d)
            ti = inv(c, d)
            oracle = {"그날 확정 양매수": today, "그날 기관 순매수": bool(ti) and ti[1] > 0, "그날 외인 순매수": bool(ti) and ti[0] > 0}
            flows = {"수급 조건 없음": True, "전날 양매수": b1, "3일 중 2일 양매수": (b1 + b2 + b3) >= 2, "2일 연속 양매수": b1 and b2}
            sizes = {"시총30·대금30": mr[c] <= 30 and vr[c] <= 30, "시총100·대금50": True}
            o9 = reg[0][1]; pc, ph = pr[3] * f, pr[1] * f
            hi_open = max(x[2] for x in reg if x[0] < time(9, 10))
            sig = {}
            for j, x in enumerate(reg[:-1]):
                t = x[0]
                if time(9, 10) <= t <= time(10, 30):
                    if "a 오전 고가" not in sig and x[4] > hi_open: sig["a 오전 고가"] = j + 1
                    if "b 전일 고가" not in sig and o9 <= ph < x[4] and not any(y[4] > ph for y in reg[:j]): sig["b 전일 고가"] = j + 1
                    if "c 전일 종가 재돌파" not in sig and o9 < pc < x[4] and not any(y[4] > pc for y in reg[:j]): sig["c 전일 종가 재돌파"] = j + 1
                if time(14, 0) <= t <= time(15, 0) and "d 오후 그날 고가" not in sig:
                    hd = max(y[2] for y in reg[:j])
                    if x[4] > hd: sig["d 오후 그날 고가"] = j + 1
            hold = lambda last: last >= h250 * f * 0.8 and last > ph
            outs = {}
            for e, j in sig.items():
                buy = reg[j][1]
                outs[(e, "익절 +2.5%")] = intraday_exit(reg, j, buy, 0.02, 0.025, time(15, 19))[0]
                outs[(e, "익절 없음·조건 맞으면 다음 날")] = intraday_exit(reg, j, buy, 0.02, None, time(15, 19), hold, c, d)[0]
            if NAME.get(c) in ("삼성전자", "SK하이닉스"): cases.append((d, c, up, b1, today, sorted(sig)))
            for sz, oks in sizes.items():
                if not oks: continue
                for fl, okf in flows.items():
                    if not okf: continue
                    for tr, oku in (("상승 추세", up), ("추세 무관", True)):
                        if not oku: continue
                        n_univ[(sz, fl, tr)] += 1
                        for (e, ex), r in outs.items():
                            res[(sz, fl, tr, e, ex, False)].append((d, r))
                            for on, ok in oracle.items():
                                if ok: res[(sz, fl, tr, e, ex, on)].append((d, r))
        print(d, file=sys.stderr, flush=True)
    R.say(f"디앤서 수급주 1년 ({P0}~{P1}, 외인·기관 확정치는 2026-10-13 까지) — 다음 봉 시가 매수, 손절 −2%")
    for sz in ("시총30·대금30", "시총100·대금50"):
        for fl in ("수급 조건 없음", "전날 양매수", "3일 중 2일 양매수", "2일 연속 양매수"):
            for tr in ("상승 추세", "추세 무관"):
                R.say(f"\n-- {sz} · {fl} · {tr} (대상 {n_univ[(sz, fl, tr)]}종목·일)")
                for e in ("a 오전 고가", "b 전일 고가", "c 전일 종가 재돌파", "d 오후 그날 고가"):
                    for ex in ("익절 +2.5%", "익절 없음·조건 맞으면 다음 날"):
                        R.stats(res[(sz, fl, tr, e, ex, False)], f"{e} | {ex}", 52)
                        for on in ("그날 확정 양매수", "그날 기관 순매수", "그날 외인 순매수"):
                            R.stats(res[(sz, fl, tr, e, ex, on)], f"{e} | {ex} | [상한선: {on}]", 52)
    R.say("\n-- 책 사례 (삼성전자 2026-07-03 오전 고가 돌파 10시 무렵 / 07-14 양매수)")
    from datetime import date as _d
    for d, c, up, b1, today, s in cases:
        if d in (_d(2026, 7, 3), _d(2026, 7, 14)):
            R.say(f"  {NAME[c]} {d}: 상승 추세 {up}, 전날 양매수 {b1}, 그날 확정 양매수 {today}, 신호 {s}")


if __name__ == "__main__":
    main()
