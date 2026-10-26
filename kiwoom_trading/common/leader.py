"""👑 테마 대장 판단 — 백테스트·실시간 공용 (docs/architecture.md 3단계).

규칙 (☕ 카페 '수학은직관력' 관점, 2026-10-27): 네이버 테마(data/naver_groups.duckdb) 안에서 지금 +4%↑ 종목이 2개↑ 이면 '형성',
그중 오늘 누적 거래대금 1위이고 +5%↑ 인 종목이 그 테마의 대장. 한 종목이 여러 테마 대장이면 +4%↑ 종목이 가장 많은 테마로 표시.
1년: ⑥ 주도주 신고가 대장 +3.20% / 아님 +1.39%, 🧭 디앤서 종가 +1.06% / +0.15% (스킬 hong 8장).
"""
from collections import defaultdict
from typing import Iterable

UP_MIN, LEAD_MIN = 0.04, 0.05


def theme_leaders(rows: Iterable[tuple[str, float, float]], themes: dict, up_min: float = UP_MIN,
                  lead_min: float = LEAD_MIN) -> dict[str, tuple[str, int, float]]:
    """rows = [(종목코드, 등락률, 오늘 누적 대금)] → {대장 코드: (테마, +4%↑ 종목 수, 등락률)}."""
    by_theme = defaultdict(list)
    for code, chg, value in rows:
        if chg is not None and chg >= up_min and value:
            for th in themes.get(code, ()):
                by_theme[th].append((code, chg, value))
    out = {}
    for th, mem in by_theme.items():
        if len(mem) < 2:
            continue
        code, chg, _ = max(mem, key=lambda m: m[2])
        if chg >= lead_min and (code not in out or len(mem) > out[code][1]):
            out[code] = (th, len(mem), chg)
    return out


def load_themes(naver_db: str) -> dict[str, set]:
    """네이버 테마 최신 목록 → {종목코드: {테마 이름}} (DB 가 잠겨 있으면 임시 복사본으로 읽음)."""
    import os, shutil, tempfile
    import duckdb
    copy = os.path.join(tempfile.gettempdir(), f"leader_{os.getpid()}_naver_groups.duckdb")
    shutil.copy(naver_db, copy)
    con = duckdb.connect(copy, read_only=True)
    try:
        out = defaultdict(set)
        for name, c in con.execute("SELECT name, code FROM naver_groups WHERE kind='테마' AND date=(SELECT max(date) FROM naver_groups)").fetchall():
            out[c].add(name)
        return dict(out)
    finally:
        con.close()
