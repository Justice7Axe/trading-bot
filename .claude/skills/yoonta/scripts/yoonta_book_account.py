"""윤타 『주식 단타 특공대』 책 운영 그대로 계좌 모의 — yoonta_book_bt.py 의 data/yoonta/book_trades.pkl 사용.

책의 하루 운영 (1장 36~44쪽, 2장 117·142쪽, 3장 149~167쪽):
  · 100만 원으로 시작, 그날 장전 관심 종목(3~5종목)에서 나온 신호만, 신호 시각 순서대로 한 번에 한 종목(전액)
  · 앞 매매가 끝나야 다음 매매, 다음 날로 넘긴 종목이 있으면 그날 새로 안 삼
  · 2번 연속 손절(손실)이면 그날 매매 중단 (142쪽 선언)
  · 수익금 인출: 계좌가 200만 원을 넘으면 넘는 만큼 인출 (41~44쪽 '목표 200만, 수익금은 반드시 인출'), 다 잃으면(10만 원 미만) 중단
  · 기법: 책 4장 타점 전부(저돌·지지저항·변비·분돌·시가) 또는 저돌만(199쪽 '10번 중 9번은 저돌')
    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_book_account.py > data/yoonta/book_account.txt
"""
import os
import pickle
from collections import defaultdict

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TR = pickle.load(open(os.path.join(ROOT, "data", "yoonta", "book_trades.pkl"), "rb"))

ALL_TECH = ("[R36] 저돌", "[R29] 지지저항", "[R30] 변비", "[R41] 분돌", "[R39] 시가")
JEODOL = ("[R36] 저돌",)
UNIVS = ["장전 3~5종목 (책 대상 ∩ 주도 테마·평소 함께)", "장전 3~5종목 (책 대상 ∩ 주도 테마·같은 업종)", "책 대상 대금 상위 5", "책 대상"]
EXITS = sorted({k[2] for k in TR if not k[2].startswith("[R40]") and not k[2].startswith("[R07]") and not k[2].startswith("[R30] 20선")
                and not k[2].startswith("[R24]") and not k[2].startswith("[R17]") and not k[2].startswith("[R50] 김보선 이탈")
                and k[2] != "다음 날 시가"})


def is_base(name, techs):
    """기법의 기본형만 (필터 갈래·분할·막시무스·갭 제외 등은 같은 신호의 중복이라 뺀다). 변비는 9~10시 1분봉(책 174쪽)."""
    base = (name.startswith("[R36] 저돌") and name.endswith("09:00~10:00")) or         name == "[R29] 지지저항 타점: 분봉 지지 3번째 반등 · 한 번에 매수" or         (name.startswith("[R30] 변비 1분봉") and name.endswith("09:00~10:00")) or         name == "[R41] 분돌 당일 고점 재돌파 (+5%↑)" or name.startswith("[R39] 시가")
    return base and name.startswith(techs)


def collect(techs, univ, exit_, end, regime=None):
    rows = {}
    for (name, u, x, e), tr in TR.items():
        if u != univ or x != exit_ or e != end or not is_base(name, techs):
            continue
        for d, r, code, t_in, t_out, breg, up1 in tr:
            if regime and breg != regime:
                continue
            k = (d, t_in, code)
            if k not in rows:
                rows[k] = (r, t_out)
    by = defaultdict(list)
    for (d, t_in, code), (r, t_out) in sorted(rows.items()):
        by[d].append((t_in, code, r, t_out))
    return by


def run(by, withdraw=True):
    acct = 1.0; out = 0.0; n = 0; curve = []; dead = False
    for d in sorted(by):
        if dead:
            break
        free = None; streak = 0; seen = set()
        for t_in, code, r, t_out in by[d]:
            if code in seen or free == "overnight" or (free is not None and t_in < free) or streak >= 2:
                continue
            seen.add(code)
            acct *= 1 + r; n += 1
            streak = streak + 1 if r < 0 else 0
            free = "overnight" if t_out is None else t_out
        if withdraw and acct > 2.0:
            out += acct - 2.0; acct = 2.0
        if acct < 0.1:
            dead = True
        curve.append(acct + out)
    c = np.array(curve) if curve else np.array([1.0])
    mdd = (1 - c / np.maximum.accumulate(c)).max()
    return n, len(by), acct, out, mdd


if __name__ == "__main__":
    print("윤타 책 운영 그대로 계좌 모의 — 100만 시작, 한 번에 한 종목, 2연속 손실이면 그날 중단, 200만 넘으면 인출")
    print("표기: 남은 계좌 + 인출 합계 (최대 낙폭은 계좌+인출 기준)")
    for techs, tl in ((ALL_TECH, "4장 타점 전부"), (JEODOL, "저돌만")):
        for univ in UNIVS:
            print(f"\n=== {tl} · {univ}")
            for exit_ in EXITS:
                for end in ("15:00 정리(책)", "다음 날 시가"):
                    for regime in (None, "상승장"):
                        by = collect(techs, univ, exit_, end, regime)
                        if not by:
                            continue
                        n, days, acct, out, mdd = run(by)
                        print(f"  {exit_[:46]:46s} [{end}]{' 책 상승장만' if regime else ''}: {n}건 {days}일 | 계좌 {acct * 100:.0f}만 + 인출 {out * 100:.0f}만"
                              f" = {(acct + out) * 100:.0f}만 (최대 낙폭 {mdd:.0%})")
