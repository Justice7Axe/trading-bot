"""일봉 일일 업데이트 진입점 (Windows 작업 스케줄러가 평일 20:00에 실행).

    .venv\\Scripts\\python.exe -m kiwoom_trading.ingestion.run_daily_update
    .venv\\Scripts\\python.exe -m kiwoom_trading.ingestion.run_daily_update --force   # 주말에도 실행

- 마지막 저장일 다음 날부터 오늘까지 채운다 (PC가 꺼져 있어 며칠 밀려도 자동 보충).
- 종목 마스터(신규 상장/상장폐지/상장주식수)도 함께 갱신된다.
- 외국인·기관 등 투자자별 순매수(그날 확정치, ka10066)를 investor_daily 에 저장.
- 코스피·코스닥·코스피200 지수 일봉·1분봉을 data/index.duckdb 에 저장 (index_collector).
- DuckDB가 다른 프로그램(DuckDB UI, DBeaver 등)에 잠겨 있으면 5분 간격으로 재시도.
- 완료 후 65기법 일일 리포트(오늘 포착/매수 대기/보유 중/오늘 청산)와 주도주 스크리너 다음날 관심 종목을
  텔레그램으로 전송, 실패 시 실패 알림 전송.
- 마지막으로 그날 매수 신호 감시 종목의 1분봉(KRX/통합/NXT)을 minute_ohlcv 에 저장.
- 로그: data/logs/daily_update_YYYYMMDD.log
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime

import duckdb

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from kiwoom_trading.common.config import KST
from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT
from kiwoom_trading.common.keep_awake import prevent_sleep_until_exit
from kiwoom_trading.common.telegram import send_telegram_message
from kiwoom_trading.ingestion.collectors import daily_krx_update


LOCK_RETRY_COUNT = 6
LOCK_RETRY_WAIT_SECONDS = 300


def _setup_logging(now: datetime) -> str:
    log_dir = os.path.join(PROJECT_ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"daily_update_{now:%Y%m%d}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    return log_path


def main() -> int:
    parser = argparse.ArgumentParser(description="일봉 일일 업데이트")
    parser.add_argument("--force", action="store_true", help="주말에도 실행")
    parser.add_argument("--no-telegram", action="store_true", help="텔레그램 전송 안 함")
    args = parser.parse_args()

    now = datetime.now(KST)
    log_path = _setup_logging(now)
    if now.weekday() >= 5 and not args.force:
        logging.info("주말이라 건너뜀")
        return 0

    logging.info("=== 일봉 일일 업데이트 시작 (로그: %s) ===", log_path)
    prevent_sleep_until_exit()  # 업데이트·리포트·1분봉 저장(약 15분) 중 절전 방지
    started = time.monotonic()
    for attempt in range(1, LOCK_RETRY_COUNT + 1):
        try:
            daily_krx_update.main([])
            break
        except duckdb.IOException as exc:
            if attempt == LOCK_RETRY_COUNT:
                logging.error("DB 잠김으로 실패 (%s회 시도): %s", attempt, exc)
                _notify_failure(args, f"DB 잠김으로 실패 ({attempt}회 시도). DuckDB UI/DBeaver 등을 닫아주세요.", log_path)
                return 1
            logging.warning("DB가 다른 프로그램에 잠겨 있음 → %s초 후 재시도 (%s/%s)", LOCK_RETRY_WAIT_SECONDS, attempt, LOCK_RETRY_COUNT)
            time.sleep(LOCK_RETRY_WAIT_SECONDS)
        except Exception as exc:
            logging.exception("일일 업데이트 실패")
            _notify_failure(args, f"{type(exc).__name__}: {exc}", log_path)
            return 1
    elapsed = (time.monotonic() - started) / 60
    logging.info("=== 완료 (%.1f분) ===", elapsed)

    # 외국인·기관 등 투자자별 순매수 (그날 확정치, 전 종목 약 10초)
    try:
        from kiwoom_trading.ingestion.collectors.investor_flow import update_today

        update_today()
    except Exception:
        logging.exception("투자자 수급 저장 실패")

    # 코스피·코스닥·코스피200 지수 일봉·1분봉 → data/index.duckdb (분석·검증용, 1분봉은 키움이 1년치만 줘서 매일 이어 받음)
    try:
        from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
        from kiwoom_trading.ingestion.collectors.index_collector import update_index

        update_index(build_client())
    except Exception:
        logging.exception("지수 저장 실패")
    try:   # 🇺🇸 미국 지수(나스닥·다우·나스닥100·선물) 일봉 → index.duckdb us_daily (2026-10-27)
        from kiwoom_trading.common.us_market import backfill
        from kiwoom_trading.ingestion.collectors.index_collector import INDEX_DB

        backfill(INDEX_DB, rng="1mo")
    except Exception:
        logging.exception("미국 지수 저장 실패")

    if not args.no_telegram:
        try:
            from kiwoom_trading.strategies.sixty_five.report import build_report

            send_telegram_message(build_report() + f"\n\n(일봉 업데이트 {elapsed:.0f}분 소요)")
        except Exception:
            logging.exception("65기법 리포트 생성/전송 실패")  # 수집은 성공했으므로 종료코드는 0
        try:
            from kiwoom_trading.screener.run_daily import build_daily_report

            send_telegram_message(build_daily_report())
        except Exception:
            logging.exception("주도주 스크리너 리포트 생성/전송 실패")

    # 오늘 매수 신호 감시 종목(전일 관심 + 장중 포착)의 1분봉 저장 (KRX / 통합 / NXT)
    try:
        from kiwoom_trading.ingestion.collectors.minute_collector import collect_minutes, watchlist_codes

        conn = duckdb.connect(DEFAULT_DB_PATH, read_only=True)
        try:
            trading_day = conn.execute("SELECT max(date) FROM daily_ohlcv").fetchone()[0]  # 자정을 넘겨 실행돼도 그날 기준
        finally:
            conn.close()
        codes = watchlist_codes(trading_day)
        if codes:
            saved = collect_minutes(codes, trading_day, ["KRX", "AL", "NX"])
            logging.info("감시 종목 1분봉 저장: %s종목, %s봉", len(codes), saved)
    except Exception:
        logging.exception("감시 종목 1분봉 저장 실패")

    # 오늘 포착 종목 복기표 (포착 시점 이후 차트상 수익 여부) — 1분봉 저장 뒤에 실행
    # 장중 종목 찾기를 끈 동안(run_intraday.DISCOVERY = False, 2026-10-25)은 포착이 없으므로 보내지 않는다
    from kiwoom_trading.screener.run_intraday import DISCOVERY
    if not args.no_telegram and DISCOVERY:
        try:
            from kiwoom_trading.screener.capture_review import build_capture_review

            send_telegram_message(build_capture_review())
        except Exception:
            logging.exception("포착 복기표 생성/전송 실패")

    # 오늘 모의투자 매매 타점 차트 (1분봉 + 매수·매도 자리) — 1분봉 저장 뒤에 만들어 텔레그램으로 파일 전송
    try:
        from kiwoom_trading.screener.paper_chart import write_chart

        path, n = write_chart(trading_day)
        logging.info("모의투자 타점 차트: %s (매매 %s건)", path, n)
        if n and not args.no_telegram:
            from kiwoom_trading.common.telegram import send_telegram_document

            send_telegram_document(path, f"📈 {trading_day:%m-%d} 모의투자 매매 타점 차트 ({n}건) — 받아서 브라우저로 여세요")
    except Exception:
        logging.exception("모의투자 타점 차트 생성 실패")

    # 모의투자 하루 복기 — 한도로 못 산 신호까지 같은 규칙으로 가상 매매 (1분봉 저장 뒤), paper_review 에 누적
    try:
        from kiwoom_trading.screener.paper_review import build_review, review
        from kiwoom_trading.screener.store import ScreenerStore

        store = ScreenerStore()
        try:
            if review(store, trading_day) and not args.no_telegram:
                send_telegram_message(build_review(store, trading_day))
        finally:
            store.close()
    except Exception:
        logging.exception("모의투자 복기 실패")
    return 0


def _notify_failure(args: argparse.Namespace, reason: str, log_path: str) -> None:
    if not args.no_telegram:
        send_telegram_message(f"⚠️ 일봉 일일 업데이트 실패\n{reason[:500]}\n로그: {log_path}")


if __name__ == "__main__":
    sys.exit(main())
