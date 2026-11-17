"""👑 테마 1등(등락률) 판정 시험 — 2026-11-17 남북경협 같은 경우 (pytest 없으면 파일 직접 실행)."""
from kiwoom_trading.strategies.cafe_leader.live import top_by_chg

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


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
