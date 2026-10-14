"""주도주 스크리너 — 장 마감 후 '다음 날 관심 종목' 리포트.

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_daily            # 콘솔 출력
    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.run_daily --send     # 텔레그램 전송

일봉 DB 의 마지막 거래일 확정 봉 + 그날의 실시간 조회 순위(당일 누적) + 테마 등락으로 판정한다.
아래에 '쉬어 가는 주도주'(early_watch.find_rest_leaders) 를 덧붙이고 rest_leaders 테이블에 저장 → 다음 날 매수 신호 감시.
매일 20:00 일봉 업데이트(run_daily_update) 후 자동 실행된다.
"""
import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
from kiwoom_trading.screener.conditions import format_evaluation
from kiwoom_trading.screener.early_watch import active_rest_leaders, find_rest_leaders, format_rest_leaders
from kiwoom_trading.screener.engine import Screener
from kiwoom_trading.screener.gate_flow import evaluate as evaluate_gate_flow, summary as gate_flow_summary
from kiwoom_trading.screener.market_data import KiwoomMarket
from kiwoom_trading.screener.store import ScreenerStore


NEAR_MISS_COUNT = 3


def build_daily_report(save: bool = True, as_of: Optional[date] = None) -> str:
    """as_of: 과거 날짜 점검용. 조회 순위는 과거 데이터가 없어 제외되고, 테마 등락은 '현재' 값이라 참고만 가능."""
    conn = duckdb.connect(DEFAULT_DB_PATH, read_only=True)
    try:
        today = as_of or conn.execute("SELECT max(date) FROM daily_ohlcv").fetchone()[0]
        rest_leaders = find_rest_leaders(conn, today)     # ① 쉬어 가는 주도주 (+3% 미만이라 아래 판정에서 빠지는 종목)
    finally:
        conn.close()

    market = KiwoomMarket(build_client())
    search_day = market.search_rank("4")
    # 조회 순위는 '현재' 기준만 제공 → 일봉 마지막 거래일과 같은 날 데이터일 때만 사용
    if search_day and search_day[0].as_of and search_day[0].as_of != today.strftime("%Y%m%d"):
        logging.info("조회 순위 기준일 %s ≠ 일봉 기준일 %s → 조회 순위 제외", search_day[0].as_of, today)
        search_day = []

    screener = Screener(market, today)
    evaluations = screener.scan_daily(search_day)
    passed = sorted((e for e in evaluations if e.passed(screener.config)), key=lambda e: -e.score)
    near = sorted((e for e in evaluations if not e.passed(screener.config)), key=lambda e: -e.score)[:NEAR_MISS_COUNT]

    carried: dict[str, tuple[str, int]] = {}
    gate_summary = ""
    if save:
        store = ScreenerStore()
        try:
            now = datetime.now(KST)
            store.save_ranks(now, "search_day", search_day)
            for e in passed:
                store.save_detection(today, "daily", now, e)
            store.save_rest_leaders(today, rest_leaders)
            # 다음 거래일에도 계속 감시하는 이전 쉬는 주도주 (오늘 새로 뽑힌 종목 제외)
            new_codes = {x.code for x in rest_leaders}
            carried = {c: v for c, v in active_rest_leaders(store, today + timedelta(days=1)).items() if c not in new_codes}
            # 조기 주도주(09:15 전 관문) × 장중 수급 잠정치 — 그날 평가하고 누적 요약
            try:
                evaluate_gate_flow(store, today)
                gate_summary = gate_flow_summary(store)
            except Exception:
                logging.exception("관문×수급 평가 실패")
        finally:
            store.close()

    lines = [
        f"🔭 주도주 스크리너 — 다음 거래일 관심 종목 (기준 {today})",
        "필수: ①관심(조회 20위·대금 50위 이내) ②대금 500억·+3%·변동성 ⑥손절 1.5~8% 시나리오 | 선택 2개↑: ③테마 동반 ④재료 연속성 ⑤신고가권",
        f"후보 {len(evaluations)}종목 → 통과 {len(passed)}종목",
    ]
    if passed:
        lines += ["", "\n\n".join(format_evaluation(e) for e in passed)]
    else:
        lines.append("통과 종목 없음")
        if near:
            lines += ["", "── 아깝게 탈락 ──", "\n\n".join(format_evaluation(e) for e in near)]
    lines += ["", format_rest_leaders(rest_leaders)]
    if carried:
        lines.append("계속 감시 (이전 쉬는 주도주): " + ", ".join(f"{name}(D+{k})" for _, (name, k) in carried.items()))
    if gate_summary:
        lines += ["", gate_summary]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="주도주 스크리너 장 마감 후 리포트")
    parser.add_argument("--send", action="store_true", help="텔레그램 전송")
    parser.add_argument("--no-save", action="store_true", help="포착 기록 저장 안 함")
    parser.add_argument("--date", help="과거 날짜로 점검 YYYYMMDD (저장 안 함, 조회 순위 제외)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    as_of = datetime.strptime(args.date, "%Y%m%d").date() if args.date else None
    report = build_daily_report(save=not args.no_save and as_of is None, as_of=as_of)
    print(report)
    if args.send:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message(report)


if __name__ == "__main__":
    main()
