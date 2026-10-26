"""시장 판단 공용 (백테스트) — 코스피·코스닥 20일선 (docs/architecture.md 3단계)."""
import numpy as np


def index_below_ma20(ix_conn) -> dict:
    """{날짜: (코스피 전날 종가 < 20일선, 코스닥 전날 종가 < 20일선)} — 그날 판단은 전날 마감 기준. ix_conn = index.duckdb 연결."""
    out = {}
    for code in ("001", "101"):
        rows = ix_conn.execute("SELECT date, close FROM idx_daily WHERE code=? ORDER BY date", [code]).fetchall()
        cl = np.array([r[1] for r in rows], float)
        for i in range(20, len(rows)):
            out.setdefault(rows[i][0], [None, None])[0 if code == "001" else 1] = cl[i - 1] < cl[i - 20:i].mean()
    return {d: tuple(v) for d, v in out.items()}


def ma20_tag(ix_conn) -> dict:
    """{날짜: '둘 다 20일선 아래' / '둘 중 하나↑ 20일선 위'}."""
    return {d: ("둘 다 20일선 아래" if all(v) else "둘 중 하나↑ 20일선 위") for d, v in index_below_ma20(ix_conn).items()}
