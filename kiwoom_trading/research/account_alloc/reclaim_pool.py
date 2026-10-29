"""🔁 시가 탈환 전용 몫 크기 시험 (2026-10-29 사용자 '모의에는 🔁 만 쓰는 몫') → data/account_alloc/reclaim_pool.txt

기준 = 지금 모의 (🔁·3️⃣ 뺌, B6). 🔁 를 몫 안에서만 사게 넣고(동시 한도 칸 안 씀), 몫·종목당 금액을 바꿔 본다.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.account_alloc.reclaim_pool
"""
import os
import sys

from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.account_alloc.experiments import BACK, FRONT

OUT = os.path.join(S.OUT, "reclaim_pool.txt")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(OUT, "w", encoding="utf-8")
    say = lambda s="": (print(s, flush=True), f.write(s + "\n"))
    base_k = set(S.KINDS) - {"🔁", "3️⃣"}
    rows = [("지금 모의 (🔁·3️⃣ 뺌)", {"kinds": base_k})]
    for per in (0.10, 0.05):
        for pool in (0.05, 0.10, 0.20, 0.30):
            if pool < per: continue
            rows.append((f"🔁 몫 {pool*1e3:.0f}만 · 종목당 {per*1e3:.0f}만", {"kinds": base_k | {"🔁"}, "rpool": pool,
                                                                          "amt": S.NOW["amt"] | {"🔁": per}}))
    rows.append(("(참고) 🔁 몫 없이 그냥 넣음", {"kinds": base_k | {"🔁"}}))
    say(f"기간 {S.DAYS[0]} ~ {S.DAYS[-1]}, 시드 1천만 복리, 비용 주식 0.25%")
    say(f"{'배분':28s} | 1년 최종 · 낙폭 | 앞 반기 | 뒤 반기 | +0.3% 미끄러짐 | 🔁 산 건수·손익 | 다른 매매 손익")
    for lab, cfg in rows:
        y = S.run(cfg); a = S.window(cfg, *FRONT); b = S.window(cfg, *BACK); sl = S.run({**cfg, "slip": 0.003})
        r_p = y["pnl_k"].get("🔁", 0); other = sum(v for k, v in y["pnl_k"].items() if k != "🔁")
        say(f"{lab:28s} | {y['final']/1e4:7,.0f}만 · {y['mdd']*100:4.1f}% | {a['ret']*100:+5.0f}% | {b['ret']*100:+5.0f}% | "
            f"{sl['final']/1e4:6,.0f}만 | {y['n_k'].get('🔁', 0):4d}건 {r_p/1e4:+6,.0f}만 | {other/1e4:+7,.0f}만")
    f.close()


if __name__ == "__main__":
    main()
