"""점검: 다음 날 시가에 팔았다고 친 매매 중 다음 날 거래량 0(거래정지 등, 실제로 못 팖) 인 건수 — book_trades.pkl.
    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_check_halts.py
"""
import os
import pickle
import shutil
import tempfile

import duckdb

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TR = pickle.load(open(os.path.join(ROOT, "data", "yoonta", "book_trades.pkl"), "rb"))
p = os.path.join(tempfile.gettempdir(), "yoonta_daily_ohlcv.duckdb")
d = duckdb.connect(p, read_only=True)
cal = [r[0] for r in d.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
nxt = {a: b for a, b in zip(cal, cal[1:])}
vol = {(c, x): v for c, x, v in d.execute("SELECT code, date, volume FROM daily_ohlcv WHERE date >= '2025-10-01'").fetchall()}
tot = halt = 0
bad = set()
for k, tr in TR.items():
    for dd, r, code, t_in, t_out, *_ in tr:
        if t_out is None:
            tot += 1
            if vol.get((code, nxt.get(dd))) in (0, None):
                halt += 1; bad.add((code, dd))
print(f"다음 날 시가 매도 {tot}건 중 다음 날 거래량 0 또는 자료 없음 {halt}건 ({halt / max(tot, 1):.2%}), 종목·날짜 {len(bad)}개: {sorted(bad)[:20]}")
