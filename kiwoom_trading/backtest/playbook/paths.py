"""매매표 백테스트 입력 경로 — 임시 폴더 glob 대신 고정 경로."""
import os
import shutil

from kiwoom_trading.common.daily_store import PROJECT_ROOT

DATA = os.environ.get("TRADING_DATA", os.path.join(PROJECT_ROOT, "data"))
PB = os.path.join(DATA, "backtest", "playbook")
# 일봉 DB: 기본은 운영 DB, 원래 결과와 맞춰 볼 땐 PLAYBOOK_DAILY_DB 로 스냅샷 지정
DAILY_DB = os.environ.get("PLAYBOOK_DAILY_DB") or os.path.join(DATA, "daily_ohlcv.duckdb")
INV_DAILY_DB = os.path.join(PB, "inv_daily_ohlcv.duckdb")   # ② 저항 돌파 시총 계산용 (2026-10-24 스냅샷)


def pb(name: str) -> str:
    p = os.path.join(PB, name)
    if not os.path.exists(p):
        raise FileNotFoundError(f"매매표 백테스트 입력 없음: {p} (data/research_archive/INDEX.md 참고)")
    return p


def patch_copy() -> None:
    """디앤서 select_bt 가 data/*.duckdb 를 임시 폴더로 복사할 때:
    잠긴 파일(백필 중인 minute_history 등)은 전에 복사한 것을 쓰고, PLAYBOOK_DAILY_DB 가 있으면 일봉은 그 스냅샷을 복사한다."""
    if getattr(shutil.copy, "_playbook", False):
        return
    orig = shutil.copy

    def copy(src, dst, *a, **k):
        if os.environ.get("PLAYBOOK_DAILY_DB") and os.path.basename(str(src)) == "daily_ohlcv.duckdb":
            src = os.environ["PLAYBOOK_DAILY_DB"]
        try:
            return orig(src, dst, *a, **k)
        except PermissionError:
            if os.path.exists(dst):
                return dst
            raise

    copy._playbook = True
    shutil.copy = copy
