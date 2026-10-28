"""2026-10-28 주도주 포착 복기용 1분봉(KRX) 받기 → data/leader_capture/bars_krx.pkl  {(code, date): [(ts, o, h, l, c, v)]}

대상: 10-28 대금 상위 200(value_krx, 09:00 뒤)에 한 번이라도 든 종목 + 조회 순위 당일 20위 + 사용자 16종목
     + paper_trades '추격 안 함' 건너뜀 (그날과 다음 거래일).
키움 ka10080 (minute_collector.fetch_minute_bars, 호출 간격은 클라이언트가 0.25초 지킴). 이미 받은 것은 건너뜀.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.leader_capture.fetch_today
"""
import os, pickle, sys
from datetime import date
import duckdb

from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.join(ROOT, "data", "leader_capture"); os.makedirs(OUT, exist_ok=True)
PKL = os.path.join(OUT, "bars_krx.pkl")
SNAP = os.path.join(ROOT, "data", "screener_snapshot.duckdb")
D = date(2026, 10, 28)
TARGETS = ["460940", "030530", "125490", "277810", "069540", "072950", "010170", "218410",
           "179880", "195870", "059090", "003160", "443670", "263860", "053800", "356680"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = duckdb.connect(SNAP, read_only=True)
    days = [d for (d,) in s.execute("SELECT DISTINCT date FROM rank_snapshots ORDER BY 1").fetchall()]
    nxt = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    want = set()
    for (c,) in s.execute("SELECT DISTINCT code FROM rank_snapshots WHERE date=? AND ts::time >= '09:00' AND "
                          "(source='value_krx' OR (source='search_day' AND rank<=20))", [D]).fetchall():
        want.add((c, D))
    want |= {(c, D) for c in TARGETS}
    for d, c in s.execute("SELECT DISTINCT date, code FROM paper_trades WHERE note LIKE '%추격%'").fetchall():
        want.add((c, d))
        if d in nxt:
            want.add((c, nxt[d]))
    have = pickle.load(open(PKL, "rb")) if os.path.exists(PKL) else {}
    need = sorted(k for k in want if k not in have)
    print(f"받을 것 {len(need)} / 전체 {len(want)}", flush=True)
    cl = build_client()
    for i, (c, d) in enumerate(need):
        try:
            b = fetch_minute_bars(cl, c, d, "KRX")
        except Exception as e:
            print("실패", c, d, e, flush=True); continue
        have[(c, d)] = [(x["ts"], x["open"], x["high"], x["low"], x["close"], x["volume"]) for x in b]
        if i % 50 == 0:
            print(i, c, d, len(b), flush=True)
            pickle.dump(have, open(PKL, "wb"))
    pickle.dump(have, open(PKL, "wb"))
    print("끝", len(have))


if __name__ == "__main__":
    main()
