"""종목 일별 프로그램 매매(ka90013, KRX) 1년치 받기 — 종가배팅 대상(dans_bars.pkl 의 D일 대금 30위·상승) 종목만.

ka90013 은 date 를 주면 그날부터 과거로 20거래일을 준다 (ka90008 시간별은 날짜를 무시하고 마지막 거래일만 줌, 2026-10-25 확인).
하루 프로그램 순매수 합계는 장 마감과 함께 확정 → 17시 이후 매수 판단에 써도 미래 정보가 아니다.
결과: data/closing_bet/program_daily.pkl  {(code, date): (net_amt 원, buy_amt 원, sell_amt 원, net_qty)}
"""
import os, pickle, sys, time as _t
from collections import defaultdict
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
from kiwoom_trading.common.daily_store import load_env
load_env()
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client

S = os.path.join(ROOT, "data", "closing_bet")
OUT = os.path.join(S, "program_daily.pkl")
R = pickle.load(open(os.path.join(S, "dans_bars.pkl"), "rb"))["rows"]
need = defaultdict(set)
for r in R:
    need[r["code"]].add(r["date"])
data = pickle.load(open(OUT, "rb")) if os.path.exists(OUT) else {}
num = lambda x: int(float(str(x or "0").replace(",", "").replace("--", "-").replace("+", "") or 0))
c = build_client()
codes = sorted(need)
for n, code in enumerate(codes):
    todo = sorted(d for d in need[code] if (code, d) not in data)
    while todo:
        d = todo[-1]
        pl, _, _ = c._post("/api/dostk/mrkcond", "ka90013", {"amt_qty_tp": "1", "stk_cd": code, "date": d.strftime("%Y%m%d")})
        rows = pl.get("stk_daly_prm_trde_trnsn") or []
        got = set()
        for x in rows:
            dt = datetime.strptime(x["dt"], "%Y%m%d").date()
            data[(code, dt)] = (num(x["prm_netprps_amt"]) * 1_000_000, num(x["prm_buy_amt"]) * 1_000_000,
                                num(x["prm_sell_amt"]) * 1_000_000, num(x["prm_netprps_qty"]))
            got.add(dt)
        oldest = min(got) if got else d
        todo = [x for x in todo if x < oldest and (code, x) not in data]
        if not got:
            break
    if n % 20 == 0:
        pickle.dump(data, open(OUT, "wb"))
        print(f"{n}/{len(codes)} {code} {len(data)}", file=sys.stderr, flush=True)
pickle.dump(data, open(OUT, "wb"))
print("done", len(data), file=sys.stderr)
