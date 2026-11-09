"""👑 테마 대장 규칙 비교: 누적 대금 1위(지금) vs 등락률 1위 — ☕ 카페 대장·6️⃣ 주도주 신고가 크기 (2026-10-30 사용자).

입력 (먼저 만들기):
  ☕  CAFE_LEADER_BY=value CAFE_SUFFIX=_value_now  python -m kiwoom_trading.strategies.cafe_leader.backtest → data/cafe/trades_value_now.pkl
      CAFE_LEADER_BY=chg                          python -m kiwoom_trading.strategies.cafe_leader.backtest → data/cafe/trades_chg.pkl
      (두 번 다 오늘 네이버 테마 목록. 매수 자리·수익률은 대장 규칙과 상관없이 같고 lead 표시만 다름)
  6️⃣  python -m kiwoom_trading.research.leader_rule.playbook_leader → data/leader_rule/playbook_leader_{value,chg}.pkl
결과: data/leader_rule/report.txt
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_rule.compare
"""
import io
import os
import pickle
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.cafe_leader import backtest as C
from kiwoom_trading.research.account_alloc import sim as S

OUT = os.path.join(E.DATA, "leader_rule")


def nm(c):
    r = E.DM.execute("SELECT name FROM stocks WHERE code=?", [c]).fetchone()
    return f"{r[0]}({c})" if r else c


class Rep(E.Report):
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")


def cafe(R):
    tv = pickle.load(open(os.path.join(E.DATA, "cafe", "trades_value_now.pkl"), "rb"))
    tc = pickle.load(open(os.path.join(E.DATA, "cafe", "trades_chg.pkl"), "rb"))
    old = pickle.load(open(os.path.join(E.DATA, "cafe", "trades.pkl"), "rb"))
    key = lambda t: (t["date"], t["code"], t["t"])
    tv.sort(key=key); tc.sort(key=key)     # 같은 날 안 순서가 실행마다 다를 수 있어 정렬해 맞춤
    assert [key(t) for t in tv] == [key(t) for t in tc] and all(a["ret_pull"] == b["ret_pull"] for a, b in zip(tv, tc))
    for t in tv:      # 박스 표시 (같은 매수 자리라 한 번만): 15일(옛 가상 장부) · 10일(지금 실시간 BOX_DAYS)
        t["box15"] = C.box_tags(t, 15)[0]; t["box10"] = C.box_tags(t, 10)[0]
    for a, b in zip(tv, tc):
        b["box15"], b["box10"] = a["box15"], a["box10"]
    R.say("# ☕ 카페 테마 대장 — 대장 규칙별 (매수 = 돌파 고점 눌림 지정가 ret_pull, 1건 100만 기준 '만')")
    R.say(f"매수 자리 {len(tv)}건 (두 규칙 같음). 대장 표시: 대금 1위 {sum(t['lead'] for t in tv)}건 / 등락률 1위 {sum(t['lead'] for t in tc)}건, "
          f"서로 다름 {sum(a['lead'] != b['lead'] for a, b in zip(tv, tc))}건")
    R.say(f"(참고: 10-27 에 만든 data/cafe/trades.pkl 대금 1위 표시 {sum(t['lead'] for t in old)}건 — 그때 테마 목록이라 조금 다름)\n")
    sets = [
        ("[지금 실시간] 대장 & 프리장 시간 규칙 & 눌림 체결 (박스 없음)", lambda t: t["lead"] and t["free"]),
        ("대장 & 눌림 체결만", lambda t: t["lead"]),
        ("[보조] + 10일 고가 박스(30%)", lambda t: t["lead"] and t["free"] and t["box10"]),
        ("[보조] + 15일 고가 박스(30%) (옛 가상 장부·계좌 시뮬 ☕)", lambda t: t["lead"] and t["free"] and t["box15"]),
    ]
    res = {}
    for name, f in sets:
        R.say(f"## {name}")
        for rule, ts in (("대금 1위(지금)", tv), ("등락률 1위", tc)):
            tr = [(t["date"], t["ret_pull"]) for t in ts if t["ret_pull"] is not None and f(t)]
            res[(name, rule)] = R.stats(tr, rule, 20)
        R.say("")
    # 겹침: 지금 실시간 조건에서 두 규칙이 고른 매매
    f = sets[0][1]
    pa = {key(t): t for t in tv if t["ret_pull"] is not None and f(t)}
    pb = {key(t): t for t in tc if t["ret_pull"] is not None and f(t)}
    R.say("## 겹침 ([지금 실시간] 조건)")
    for name, ks in (("둘 다 대장", pa.keys() & pb.keys()), ("대금 1위만 대장 (등락률로 바꾸면 빠짐)", pa.keys() - pb.keys()),
                     ("등락률 1위만 대장 (등락률로 바꾸면 새로 들어옴)", pb.keys() - pa.keys())):
        src = pa if name != "등락률 1위만 대장 (등락률로 바꾸면 새로 들어옴)" else pb
        R.stats([(k[0], src[k]["ret_pull"]) for k in ks], name, 40)
    R.say("")
    return tv, tc


def six(R):
    pv = pickle.load(open(os.path.join(OUT, "playbook_leader_value.pkl"), "rb"))
    pc = pickle.load(open(os.path.join(OUT, "playbook_leader_chg.pkl"), "rb"))
    lv = {(t["date"], t["code"]): bool(t["lead"]) for t in pv}
    lc = {(t["date"], t["code"]): bool(t["lead"]) for t in pc}
    T6 = [t for t in S.T_ALL if t["kind"] == "6️⃣"]
    mism = sum(lv[(t["date"], t["code"])] != t["lead"] for t in T6)
    R.say("# 6️⃣ 주도주 신고가 — 대장 ×2 / 아님 ×0.5 크기, 계좌 시뮬 (data/account_alloc/trades.pkl, 1천만 시작)")
    R.say(f"6️⃣ {len(T6)}건. 다시 계산한 대금 1위 표시가 계좌 입력 표시와 다른 건 {mism}건 (0 이면 원본 재현). "
          f"대장: 대금 1위 {sum(lv.values())}건 / 등락률 1위 {sum(lc.values())}건, 서로 다름 {sum(lv[k] != lc[k] for k in lv)}건 "
          f"(대금→아님 {sum(lv[k] and not lc[k] for k in lv)}, 아님→대장 {sum(lc[k] and not lv[k] for k in lv)})")
    for rule, L in (("대금 1위(지금)", lv), ("등락률 1위", lc)):
        R.stats([(t["date"], t["ret"]) for t in T6 if L[(t["date"], t["code"])]], f"{rule} · 대장", 30)
        R.stats([(t["date"], t["ret"]) for t in T6 if not L[(t["date"], t["code"])]], f"{rule} · 대장 아님", 30)
    for name, ks in (("바뀌는 것: 대금 1위만 대장", [k for k in lv if lv[k] and not lc[k]]),
                     ("바뀌는 것: 등락률 1위만 대장", [k for k in lv if lc[k] and not lv[k]])):
        rr = {(t["date"], t["code"]): t["ret"] for t in T6}
        v = [rr[k] for k in ks]
        R.say(f"   {name:30s} {len(v)}건 건당 {np.mean(v):+.2%} 합계 {sum(v) * 100:+.0f}만")
    T_chg = [dict(t, lead=lc[(t["date"], t["code"])]) if t["kind"] == "6️⃣" else t for t in S.T_ALL]
    R.say("")
    R.say(f"{'배분':10s} {'대장 규칙':14s} {'마감 자산':>10s} {'최대 낙폭':>8s} {'앞 반':>8s} {'뒤 반':>8s}  ★  6️⃣ 손익")
    for cname, cfg in (("지금 배분", {}), ("B6", {"kinds": set(S.KINDS) - {"🔁", "3️⃣"}})):
        for rule, T in (("대금 1위(지금)", None), ("등락률 1위", T_chg)):
            r = S.run(cfg, trades=T)
            R.say(f"{cname:10s} {rule:14s} {r['final'] / 1e4:9,.0f}만 {r['mdd']:8.1%} {r['front']:+8.1%} {r['back']:+8.1%}  {'★' if r['star'] else ' '}  "
                  f"{r['pnl_k'].get('6️⃣', 0) / 1e4:+,.0f}만 ({r['n_k'].get('6️⃣', 0)}건)")
    R.say("")
    return lv, lc


def spot(R, tv, tc, lv, lc):
    """대장이 갈린 매매 2건(☕ 1·6️⃣ 1)에서 그 시각 테마 종목 표를 직접 보여 준다."""
    R.say("# 확인: 대장이 갈린 매매 직접 보기 (그 시각 같은 테마 +4%↑ 종목: 등락률·누적 대금)")
    a = next(t for t, u in zip(tv, tc) if t["lead"] and not u["lead"] and t["free"] and t["ret_pull"] is not None)
    b = next(u for t, u in zip(tv, tc) if u["lead"] and not t["lead"] and u["free"] and u["ret_pull"] is not None)
    k6 = next(k for k in sorted(lv) if lv[k] != lc[k])
    t6 = next(t for t in S.T_ALL if t["kind"] == "6️⃣" and (t["date"], t["code"]) == k6)
    for tag, d, c, tt in (("☕ 대금 1위만 대장", a["date"], a["code"], a["t"]), ("☕ 등락률 1위만 대장", b["date"], b["code"], b["t"]),
                          (f"6️⃣ 대금 {'대장' if lv[k6] else '아님'}/등락률 {'대장' if lc[k6] else '아님'}", t6["date"], t6["code"], t6["t"])):
        p = E.prev_day(d); pd_ = E.daily_day(p)
        U = sorted({x for x, r in E.value_rank(p).items() if r <= 200 and E.is_common(x)} | {c})
        U = [x for x in U if x in pd_]
        B = E.load_day(U, d)
        info = {}
        for x in U:
            reg = E.regular(B[x]); f = E.factor(x, d)
            if len(reg) < 30 or not f: continue
            info[x] = dict(reg=reg, pre=[y for y in B[x] if y[0] < time(9, 0)], pc=pd_[x][3] * f)
        R.say(f"## {tag}: {d} {c} {nm(c)} {tt}  → 대금 규칙 {C.leader_at(c, d, tt, info, 'value')} / 등락률 규칙 {C.leader_at(c, d, tt, info, 'chg')}")
        mine = C.THEME.get(c, set())
        for th in sorted(mine):
            rows = []
            for o, v in info.items():
                if th not in C.THEME.get(o, ()): continue
                upto = [x for x in v["reg"] if x[0] <= tt]
                if upto:
                    ch = upto[-1][4] / v["pc"] - 1
                    if ch >= 0.04:
                        rows.append((o, ch, sum(C.val(x) for x in v["pre"]) + sum(C.val(x) for x in upto)))
            if len(rows) < 2: continue
            rows.sort(key=lambda r: -r[2])
            R.say(f"   테마 {th}: " + ", ".join(f"{nm(o)}{'*' if o == c else ''} {ch:+.1%} {vv / 1e8:,.0f}억" for o, ch, vv in rows))
    R.say("   (* = 그 매매 종목. 대금 순으로 적음 — 첫 번째가 대금 1위, 등락률 가장 큰 것이 등락률 1위, 대장은 +5%↑ 이어야 함)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUT, exist_ok=True)
    R = Rep(os.path.join(OUT, "report.txt"))
    R.say("👑 테마 대장 규칙 비교 — 누적 대금 1위(지금, common/leader.py 기본) vs 등락률 1위 (theme_leaders by='chg'), 1년 "
          f"{E.days()[0]} ~ {E.days()[-1]}")
    R.say("★ = 앞·뒤 반 모두 + & 가장 좋은 5일을 빼도 + (engine Report.stats). 비용 0.25% 포함.\n")
    tv, tc = cafe(R)
    lv, lc = six(R)
    spot(R, tv, tc, lv, lc)


if __name__ == "__main__":
    main()
