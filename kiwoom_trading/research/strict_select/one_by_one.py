"""엄격 규칙을 매매 하나씩만 켜서 계좌에 주는 효과 (모의 3️⃣ 뺌·B6·새 실전). 출력 data/strict_select/one_by_one.txt"""
import os, pickle, sys
from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select.choose import CAND, PICK, ALT, apply, real_sim, OUT
from kiwoom_trading.research.strict_select.filters import Rep

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = pickle.load(open(os.path.join(OUT, "trades_feat.pkl"), "rb"))
    R = Rep(os.path.join(OUT, "one_by_one.txt"))
    M = {"kinds": set(S.KINDS) - {"3️⃣"}}; B6 = {"kinds": set(S.KINDS) - {"🔁", "3️⃣"}}
    def show(lab, X):
        a, b, c = S.run(M, trades=X), S.run(B6, trades=X), real_sim(X)
        R.say(f" {lab:44s} 모의 {a['final']/1e4:8,.0f}만 낙폭 {a['mdd']:.1%} | B6 {b['final']/1e4:8,.0f}만 낙폭 {b['mdd']:.1%} | 실전10만 {c['final']:9,.0f}원 낙폭 {c['mdd']:.1%}")
        return a
    a = show("기준", T)
    R.say("  모의 매매별 손익(만): " + str({k: round(v / 1e4) for k, v in a["pnl_k"].items()}))
    for k in PICK:
        for nm, _ in CAND[k][1:]:
            show(f"{k} {nm}", apply(T, {k: nm}))
    a = show("추천 전부", apply(T, PICK))
    R.say("  모의 매매별 손익(만): " + str({k: round(v / 1e4) for k, v in a["pnl_k"].items()}))

if __name__ == "__main__":
    main()
