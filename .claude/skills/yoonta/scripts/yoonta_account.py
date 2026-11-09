"""윤타 『주식 단타 특공대』 계좌 모의 — yoonta_minute_bt.py 가 남긴 data/yoonta/minute_trades.pkl 로
책의 하루 규칙을 얹어 본다 (1장 36~43쪽, 2장 142쪽):
  100만 원으로 시작, 한 번에 한 종목(전액), 신호 시각 순서대로, 앞 매매가 끝나야 다음 매매,
  2번 연속 손절이면 그날 끝, (선택) 하루 목표 수익 닿으면 그날 끝, 다음 날로 넘긴 종목이 있으면 그날 새로 안 삼.
  수익금 인출(책: 200만 넘으면 인출)은 '복리 없음(늘 100만)' 줄로 본다.

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_account.py "<기법 이름 일부>" "<매도 이름 일부>" [...]
"""
import os
import pickle
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TR = pickle.load(open(os.path.join(ROOT, "data", "yoonta", "minute_trades.pkl"), "rb"))


def pick(sig, ex):
    keys = [k for k in TR if sig in k[0] and ex in k[1]]
    return keys


def run(keys, target=None, max_loss_streak=2):
    rows = sorted({(d, t_in, code): (r, t_out) for k in keys for d, r, code, t_in, t_out in TR[k]}.items())
    by = defaultdict(list)
    for (d, t_in, code), (r, t_out) in rows:
        by[d].append((t_in, code, r, t_out))
    eq = 1.0; flat = 0.0; curve = []; n = 0; days = 0
    for d in sorted(by):
        free = None; streak = 0; day = 0.0; took = False
        for t_in, code, r, t_out in by[d]:
            if free == "overnight" or (free is not None and t_in < free) or streak >= max_loss_streak:
                continue
            if target is not None and day >= target:
                break
            eq *= 1 + r; flat += r; day += r; n += 1; took = True
            streak = streak + 1 if r < 0 else 0
            free = "overnight" if t_out is None else t_out
        days += took
        curve.append((d, eq, flat))
    if not curve:
        return None
    e = np.array([c[1] for c in curve]); f = np.array([c[2] for c in curve])
    mdd = (1 - e / np.maximum.accumulate(e)).max()
    half = len(curve) // 2
    return dict(n=n, days=days, eq=eq, flat=flat, mdd=mdd, fmdd=(np.maximum.accumulate(f) - f).max(),
                a=curve[half][2], b=f[-1] - curve[half][2])


if __name__ == "__main__":
    args = sys.argv[1:]
    pairs = list(zip(args[::2], args[1::2]))
    keys = [k for s, x in pairs for k in pick(s, x)]
    for k in keys:
        print("  ·", k[0], "/", k[1], len(TR[k]), "건")
    for tg in (None, 0.02, 0.05):
        for ls in (2, 99):
            r = run(keys, tg, ls)
            if r:
                print(f"하루 목표 {'없음' if tg is None else f'+{tg:.0%}'} · 연속 손절 {'2번에 중단' if ls == 2 else '제한 없음'}: "
                      f"{r['n']}건 {r['days']}일 | 복리 100만 → {r['eq'] * 100:.0f}만 (최대 낙폭 {r['mdd']:.0%}) | "
                      f"복리 없음 합계 {r['flat'] * 100:+.0f}만 (앞 {r['a'] * 100:+.0f} 뒤 {r['b'] * 100:+.0f}, 낙폭 {r['fmdd'] * 100:.0f}만)")
