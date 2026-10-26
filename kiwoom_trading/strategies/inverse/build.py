"""⑤ 약세장 인버스 백테스트 입력 inv_bars.pkl 다시 만들기 (원래 data/research_archive/f3f6486b/inv_fetch.py, 2026-10-24).

inv_bars.pkl = {날짜: KODEX 인버스(123310) 그날 KRX 1분봉 list[dict(code, exchange, ts, open, high, low, close, volume)]}.
매매표 계좌(`backtest/playbook/events_15.py`)는 조정·약세장(N-) 날 09:11 봉 시가에 사서 +5% 익절 / −3% 손절, 못 닿으면 다음 날 첫 봉 시가에 판다.

⚠ 이 ETF 1분봉은 저장소 DB(minute_history·kang_minute·hamburger_minute_cache·일봉 DB 어디에도) 없다 → 키움 ka10080 으로 받아야 한다.
   그래서 기본 실행은 **API 를 부르지 않고** 받을 날짜 목록만 만들어 보존본(data/backtest/playbook/inv_bars.pkl)과 비교한다.
   실제로 받으려면 `--fetch` 를 붙인다 (키움 키 필요, 하루 1~2번 호출 × 약 250일).

받을 날짜: 1분봉 백필이 끝난 거래일(minute_history.minute_backfill_done) — 원래는 regime_days.pkl(2025-10-15~2026-10-16) + 10-19·10-20 이었고,
  두 목록은 같은 거래일이다 (수능·새해 첫날처럼 늦게 연 날 포함, 다음 날 시가 매도에 모든 거래일이 필요).

실행: python -m kiwoom_trading.strategies.inverse.build [--start 2025-10-15] [--end 2026-10-20] [--fetch]
결과(--fetch): data/backtest/playbook_rebuilt/inv_bars.pkl
"""
import argparse
import os
import pickle
import sys
import time as _time
from datetime import date

from kiwoom_trading.backtest.playbook.paths import MINUTE_DB, PB, open_ro, rebuilt

CODE = "123310"   # KODEX 인버스
EXCHANGE = "KRX"


def trade_days(minute_db=MINUTE_DB, start=date(2025, 10, 15), end=date(2026, 10, 20)):
    m = open_ro(minute_db)
    days = [d for (d,) in m.execute("SELECT DISTINCT date FROM minute_backfill_done WHERE date BETWEEN ? AND ? ORDER BY 1",
                                    [start, end]).fetchall()]
    m.close()
    return days


def fetch(days):
    """키움 API 로 하루씩 받는다 (원래 inv_fetch.py 와 같음)."""
    from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
    from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
    c = build_client(); out = {}
    for d in days:
        try:
            out[d] = fetch_minute_bars(c, CODE, d, EXCHANGE)
        except Exception as e:
            print("실패", d, e)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="⑤ 약세장 인버스 inv_bars.pkl 다시 만들기")
    ap.add_argument("--minute-db", default=MINUTE_DB)
    ap.add_argument("--start", default="2025-10-15")
    ap.add_argument("--end", default="2026-10-20")
    ap.add_argument("--fetch", action="store_true", help="키움 API 로 실제로 받는다 (없으면 날짜 목록만 비교)")
    ap.add_argument("--out", default=rebuilt("inv_bars.pkl"))
    a = ap.parse_args()
    t0 = _time.time()
    days = trade_days(a.minute_db, date.fromisoformat(a.start), date.fromisoformat(a.end))
    print(f"받을 날짜 {len(days)}일 ({days[0]} ~ {days[-1]})")
    old_p = os.path.join(PB, "inv_bars.pkl")
    if os.path.exists(old_p):
        old = pickle.load(open(old_p, "rb"))
        ks = set(old)
        print(f"보존본 {len(ks)}일 · 같은 날 {len(ks & set(days))} · 보존본에만 {sorted(ks - set(days))} · 새 목록에만 {sorted(set(days) - ks)}")
    if not a.fetch:
        print("API 는 부르지 않았다 (--fetch 를 붙이면 받는다)")
        return
    out = fetch(days)
    pickle.dump(out, open(a.out, "wb"))
    print(f"inv_bars {len(out)}일 (봉 있음 {sum(1 for v in out.values() if v)}) → {a.out} ({_time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
