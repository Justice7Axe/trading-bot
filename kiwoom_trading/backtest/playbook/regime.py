"""시장 상황 4구분(U/N+/N-/D) — 매매표 백테스트용 (원래 8623875b/u_common.py, regime-redefine 메모리).

U  강한 상승장: 09:10 코스피 ≥ +1σ(K1z) 또는 대금 상위 중앙값 ≥ +2%(M0)
D  강한 하락장: K1z ≤ −1 또는 M0 ≤ −1.5%
N+ / N- 보통 날: 코스피 52주 고점 대비 −10% 안이면 N+, 밖이면 N- (약세장)
특징값은 93a48a29/regime_cmp.py 가 만든 regime_feat.pkl.
"""
import pickle
from datetime import date

from kiwoom_trading.backtest.playbook.paths import pb

feat = pickle.load(open(pb("regime_feat.pkl"), "rb"))
BAD = pickle.load(open(pb("mismatch.pkl"), "rb"))      # 1분봉·일봉 가격이 안 맞는 (code, date) — 뺀다
SPLIT = date(2026, 4, 20)


def cls(d):
    x = feat.get(d)
    if not x:
        return None
    if x["K1z"] <= -1 or x["M0"] <= -0.015:
        return "D"
    if x["K1z"] >= 1 or x["M0"] >= 0.02:
        return "U"
    return "N+" if x["dd52"] > -0.10 else "N-"
