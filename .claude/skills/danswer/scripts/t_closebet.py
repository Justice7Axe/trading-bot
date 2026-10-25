"""디앤서 종가 베팅 (『실전 시황 트레이딩』 4장 p.103~143, 5장 p.216~222) — 공통 엔진(engine.py) 위 다시 만든 판.

책 규칙 (쪽수):
- 대상: 13~14시·20시 실시간 조회 순위 당일 누적 10위 (p.104~107, 체크리스트 p.142) → 과거 조회 순위가 없어 **그날 대금 10위**로 대신.
- 체크리스트 (p.142~143): 전일 종가 위 · 신고가 또는 라운드 피겨 같은 의미 있는 자리 · **프리·애프터마켓에서 거래되는 종목** ·
  애프터 종가가 고가 근처 마감(마지막까지 매수세) · 손절가.
- 세 유형 (p.117~121): ① 주도주 = 전일 종가 위 또는 당일 고가 근처 마감, 신고가면 더 좋음 ② 시세 초입 = 그날 처음 터진 재료로 새 테마
  ③ 개별주 = 지수가 나빠 주도주가 없는 날 혼자 오르는 종목, 외인·기관 양매수·프로그램 매수가 근거, 목표 1~2%.
- 진입 시각: 주도주·시세 초입 14시부터 / 개별주 19시 이후 / 지수 관련주는 미국장 보고 19~20시 (p.118, 142).
  애프터 종가가 정규장 종가 위에서 끝나야 (LIG넥스원 p.122).
- 매도: 다음 날 프리마켓·대체거래소 갭 (사례 대부분), 손절 = 평단 이탈(% 없음). 직장인: 2일 이상 보유 안 함 (p.222).
- 거르는 종목 (p.217): 대금만 터지고 윗꼬리 마감, 갭 크게 떴다 제자리, 뉴스 급등 뒤 급락.
숫자 정의 (미리 정함, 결과 보고 바꾸지 않음):
  대상 = 그날 대금 10위 · 일봉 등락률 0 < r < +29.5% (상한가는 상따 쪽)
  애프터 거래 = 그날 19:30~20:00 1분봉 있음 / 고가 근처 = 일봉 (종가−저가)/(고가−저가) ≥ 0.8 / 윗꼬리 = < 0.5
  신고가 = 일봉 종가 ≥ 전날까지 250일 고가 (95% 도 봄) / 라운드 피겨 = 종가가 1·2.5·5×10ⁿ 가격의 −3%~+3% 안
  시세 초입 = 전날까지 20일 동안 대금 30위 안에 든 적 없음 & 등락률 ≥ +10%
  개별주 날 = 코스피 하락일, 근거 = 그날 외인·기관 양매수(확정치는 18시 이후 → 19시 매수엔 써도 됨) & 프로그램 순매수 +
매수: 15:30 정규장 종가 / 🌙 17:00~17:59 첫 '종가 위' 봉 종가 / 19:00 / 19:55 애프터 가격 (1분봉 원가격)
매도: 다음 날 08:00 NXT 시가 / 프리 3분할 / 09:00 시가.  비용 0.25%.
"""
import os, pickle, sys
from collections import defaultdict
from datetime import time
import numpy as np
from engine import *

R = Report("t_closebet.txt")
PG = pickle.load(open(os.path.join(DATA, "closing_bet", "program_daily.pkl"), "rb"))
ROUND = sorted({m * 10 ** k for k in range(2, 8) for m in (1, 2.5, 5)})


def near_round(p):
    return any(0.97 <= p / x <= 1.03 for x in ROUND)


def build():
    rows = []
    for d in days():
        vr = value_rank(d)
        top = [c for c, r in vr.items() if r <= 10 and is_common(c)]
        top30_20d = set()
        for k in range(1, 21):
            top30_20d |= {c for c, r in value_rank(prev_day(d, k)).items() if r <= 30}
        load_day(top, d)
        nd = next_day(d)
        if nd: load_day(top, nd)
        for c in top:
            r = chg(c, d)
            if r is None or not (0 < r < LIMIT): continue
            f = factor(c, d)
            if f is None: continue
            b = bars(c, d); reg = regular(b)
            o, h, l, cl = daily_day(d)[c][:4]
            hi = hi_n(c, d, 250)
            am = [x for x in b if x[0] >= time(15, 40)]
            ji = next((i for i, x in enumerate(am) if time(17, 0) <= x[0] <= time(17, 59) and x[4] > reg[-1][4]), None)
            rb = am[ji + 1] if ji is not None and ji + 1 < len(am) else None      # 신호 봉 다음 봉 시가에 산다
            iv = inv(c, d); pg = PG.get((c, d))
            rows.append(dict(
                date=d, code=c, rk=vr[c], chg=r, close=reg[-1][4],
                nxt=nxt_known(c, d),                                                 # 전날 애프터 봉 유무 (판단 시점에 앎)
                pos=(cl - l) / (h - l) if h > l else 1.0,
                hi250=cl / hi if hi else None, rnd=near_round(reg[-1][4]),            # 라운드 피겨는 실제 거래 가격(1분봉)
                first=c not in top30_20d and r >= 0.10,
                kchg=kospi_chg(d), both=iv is not None and iv[0] > 0 and iv[1] > 0, inst=iv[1] if iv else None,
                prog=pg[0] if pg else None,
                p_rb=rb[1] if rb else None, p1900=at(am, time(19, 0)), p1955=at(am, time(19, 55)),
                last_am=at(am, time(19, 59)),
            ))
        print(d, len(rows), file=sys.stderr, flush=True)
    return rows


def run(rows, title, cond, buy_key):
    res = defaultdict(list)
    for x in rows:
        if not cond(x): continue
        buy = x["close"] if buy_key == "close" else x[buy_key]
        if not buy: continue
        for k, v in next_day_exits(x["code"], x["date"], buy).items():
            res[k].append((x["date"], v))
    R.say(f" -- {title}")
    for k in ("08:00 NXT 시가", "프리 3분할", "09:00 시가"):
        R.stats(res[k], "   " + k)


def main():
    rows = build()
    pickle.dump(rows, open(os.path.join(OUT, "t_closebet_rows.pkl"), "wb"))
    R.say(f"디앤서 종가 베팅 1년 ({P0}~{P1}) — 대금 10위·상승 마감(상한가 제외) {len(rows)}건, 애프터 거래 {sum(x['nxt'] for x in rows)}건")
    R.say("\n[A] 기준과 책 체크리스트 한 항목씩 (정규장 종가 매수)")
    run(rows, "기준: 대금 10위·상승 마감 전부", lambda x: True, "close")
    run(rows, "체크: 애프터 거래 종목만 (p.142)", lambda x: x["nxt"], "close")
    run(rows, "체크: 정규장만 거래 종목 (책: 안 함)", lambda x: not x["nxt"], "close")
    run(rows, "체크: 고가 근처 마감 (위치 ≥ 0.8)", lambda x: x["nxt"] and x["pos"] >= 0.8, "close")
    run(rows, "체크: 윗꼬리 마감 (위치 < 0.5, p.217 거름)", lambda x: x["nxt"] and x["pos"] < 0.5, "close")
    run(rows, "체크: 250일 신고가 (종가 ≥ 250일 고가)", lambda x: x["nxt"] and x["hi250"] and x["hi250"] >= 1.0, "close")
    run(rows, "체크: 250일 고가 95%↑", lambda x: x["nxt"] and x["hi250"] and x["hi250"] >= 0.95, "close")
    run(rows, "체크: 라운드 피겨 ±3%", lambda x: x["nxt"] and x["rnd"], "close")
    run(rows, "체크: 신고가 또는 라운드 피겨 (의미 있는 자리)", lambda x: x["nxt"] and ((x["hi250"] or 0) >= 1.0 or x["rnd"]), "close")
    R.say("\n[B] 매수 시각 (애프터 거래 종목)")
    run(rows, "15:30 정규장 종가", lambda x: x["nxt"], "close")
    run(rows, "🌙 17:00~17:59 첫 '정규장 종가 위' 봉 (지금 운영)", lambda x: x["nxt"], "p_rb")
    run(rows, "19:00 애프터 가격", lambda x: x["nxt"], "p1900")
    run(rows, "19:55 애프터 가격", lambda x: x["nxt"], "p1955")
    run(rows, "19:55 · 애프터가 정규장 종가 위로 끝날 때만 (LIG넥스원형)", lambda x: x["nxt"] and x["p1955"] and x["p1955"] >= x["close"], "p1955")
    R.say("\n[C] 세 유형")
    run(rows, "① 주도주: 고가 근처 마감 · 15:30", lambda x: x["nxt"] and x["pos"] >= 0.8, "close")
    run(rows, "① 주도주: 고가 근처 마감 · 🌙", lambda x: x["nxt"] and x["pos"] >= 0.8, "p_rb")
    run(rows, "① 주도주 + 신고가 · 15:30", lambda x: x["nxt"] and x["pos"] >= 0.8 and (x["hi250"] or 0) >= 1.0, "close")
    run(rows, "① 주도주 + 기관 순매수 (p.105·126) · 19:55", lambda x: x["nxt"] and x["pos"] >= 0.8 and (x["inst"] or 0) > 0, "p1955")
    run(rows, "② 시세 초입 (20일간 대금 30위 밖 → +10%↑) · 15:30", lambda x: x["nxt"] and x["first"], "close")
    run(rows, "② 시세 초입 · 🌙", lambda x: x["nxt"] and x["first"], "p_rb")
    run(rows, "③ 개별주: 코스피 하락일 · 양매수 · 프로그램 + · 19:00", lambda x: x["nxt"] and (x["kchg"] or 0) < 0 and x["both"] and (x["prog"] or 0) > 0, "p1900")
    run(rows, "③ 개별주 + 신고가 95% · 19:00", lambda x: x["nxt"] and (x["kchg"] or 0) < 0 and x["both"] and (x["prog"] or 0) > 0 and (x["hi250"] or 0) >= 0.95, "p1900")
    run(rows, "참고: 코스피 하락일 전부 · 19:00", lambda x: x["nxt"] and (x["kchg"] or 0) < 0, "p1900")
    # 책 사례 확인
    R.say("\n[D] 책 매매일지 사례가 우리 대상에 잡히는지 (대금 10위·상승 마감 · 애프터 거래)")
    cases = [("LIG넥스원", "2026-03-05"), ("한화시스템", "2026-03-05"), ("삼성전자", "2026-05-20"), ("SK하이닉스", "2026-05-20"),
             ("삼성전자", "2026-05-25"), ("SK하이닉스", "2026-05-25"), ("TCC스틸", "2026-04-29"), ("광주신세계", "2026-07-06"),
             ("펄어비스", "2026-03-25"), ("한온시스템", "2026-02-11"), ("삼성전자", "2026-07-14"), ("SK하이닉스", "2026-07-14")]
    from datetime import date as _d
    for nm, ds in cases:
        c = code_by_name(nm); d = _d.fromisoformat(ds)
        x = next((y for y in rows if y["code"] == c and y["date"] == d), None)
        info = f"대금 {value_rank(d).get(c)}위, 등락 {chg(c, d):+.1%}" if c and d in CIDX and chg(c, d) is not None else "자료 없음"
        if x:
            ex = next_day_exits(c, d, x["close"])
            R.say(f"  {nm} {ds}: 대상 O ({info}), 애프터 {x['nxt']}, 위치 {x['pos']:.2f}, 250일 {x['hi250'] or 0:.2f}, 🌙 {'O' if x['p_rb'] else 'X'}, "
                  f"종가 매수 → 09:00 {ex.get('09:00 시가', float('nan')):+.2%}")
        else:
            R.say(f"  {nm} {ds}: 대상 X ({info})")


if __name__ == "__main__":
    main()
