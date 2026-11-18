"""👑 테마 1등(등락률) 판정 시험 — 2026-11-17 남북경협 같은 경우 (pytest 없으면 파일 직접 실행)."""
from types import SimpleNamespace

from kiwoom_trading.strategies.cafe_leader.live import CafeContext, CafeLeaderWatcher, CafeStock, top_by_chg

THEMES = {"A": {"남북경협"}, "B": {"남북경협"}, "C": {"남북경협"}, "D": {"백화점"}, "E": {"백화점"}, "F": {"혼자"}}


def test_chg_first_not_value_first():
    # 대금은 C 가 가장 크지만 등락률 1등은 A → A 가 대장
    rows = [("A", 0.25, 10e8), ("B", 0.20, 9e8), ("C", 0.13, 300e8)]
    assert list(top_by_chg(rows, THEMES)) == ["A"]


def test_limit_tie_by_value():
    # 둘 다 상한가 근처(+29.5%↑) → 대금 큰 B
    rows = [("A", 0.2999, 10e8), ("B", 0.2960, 90e8), ("C", 0.10, 5e8)]
    assert list(top_by_chg(rows, THEMES)) == ["B"]


def test_needs_two_members_and_lead_min():
    assert top_by_chg([("F", 0.30, 50e8)], THEMES) == {}                       # 테마에 혼자
    assert top_by_chg([("D", 0.045, 50e8), ("E", 0.041, 50e8)], THEMES) == {}  # 1등이 +5% 안 됨
    out = top_by_chg([("D", 0.0795, 50e8), ("E", 0.0558, 60e8)], THEMES)
    assert out == {"D": ("백화점", 2, 0.0795)}


def test_eligible_only_picks_ranked_but_counts_all_for_theme():
    # A(+25%) 는 대금 순위권 밖 → 순위권 B(+20%)가 1등. 테마 형성(+4%↑ 2종목↑)은 A 까지 세서 3종목
    rows = [("A", 0.25, 10e8), ("B", 0.20, 9e8), ("C", 0.13, 300e8)]
    assert top_by_chg(rows, THEMES, eligible={"B", "C"}) == {"B": ("남북경협", 3, 0.20)}
    # 순위권 종목이 테마에 하나도 없으면 대장 없음
    assert top_by_chg(rows, THEMES, eligible={"D"}) == {}
    # 순위권 1등이 +5% 안 되면 대장 아님 (순위권 밖 A 가 +25% 여도)
    assert top_by_chg([("A", 0.25, 10e8), ("B", 0.045, 9e8)], THEMES, eligible={"B"}) == {}


def _watcher(prev_rank):
    w = CafeLeaderWatcher.__new__(CafeLeaderWatcher)    # DB 없이 순위 판단만 시험
    stocks = {c: CafeStock(c, c, None, None, None) for c in "ABCDE"}
    w.ctx = CafeContext(None, stocks, set(), THEMES, set(), prev_rank)
    return w


def R(code, rank, chg=None, tv=None):
    return SimpleNamespace(code=code, rank=rank, change_rate=chg, trade_value=tv)


def test_today_rank_skips_non_stocks_and_eligible_union():
    w = _watcher({"A": 1, "B": 150})
    top = [R("ETF1", 1), R("C", 2), R("ETF2", 3), R("D", 4)]          # ETF 는 stocks 에 없어 순위에서 빠짐
    assert w.today_rank(top) == {"C": 1, "D": 2}
    assert w.eligible(top, n=1) == {"A", "C"}                        # 전날 1위 A ∪ 당일 1위 C
    assert w.eligible(top, n=200) == {"A", "B", "C", "D"}


def test_tops_uses_rank_filter():
    # 인디에프 같은 경우: 전날 대금 순위 없음, 당일 대금 상위 200 밖(등락률 상위로만 보임) → 1등 후보 아님
    w = _watcher({"B": 30})
    top = [R("B", 5, 0.20, 90e8), R("C", 6, 0.13, 300e8)]
    risers = [R("A", 0, 0.299, 12e8)]
    assert list(w.tops(top, risers, n=100)) == ["B"]
    # 당일 순위에 들어오면 A 가 1등
    top2 = [R("A", 7, 0.299, 50e8)] + top
    assert list(w.tops(top2, risers, n=100)) == ["A"]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
