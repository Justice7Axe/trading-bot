"""실행 중 Windows 자동 절전 방지.

작업 스케줄러의 WakeToRun 은 '작업 시작 시' 잠든 PC 를 깨우기만 한다. 장중 스캐너처럼 오래 도는 작업은
실행 중에 유휴 절전(이 PC 는 AC 60분)으로 다시 잠들 수 있으므로, 실행하는 동안 SetThreadExecutionState 로
'시스템 사용 중'을 알린다. 프로세스가 끝나면 Windows 가 자동으로 원래 설정으로 되돌린다.
(덮개 닫기 / 수동 절전은 막지 않는다. 화면은 꺼져도 된다.)
"""
import logging
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def prevent_sleep_until_exit() -> bool:
    """이 프로세스가 끝날 때까지 자동 절전 방지 (프로세스 종료 시 Windows 가 자동 해제)."""
    if sys.platform != "win32":
        return False
    import ctypes

    ok = bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    logging.info("절전 방지 %s (프로세스 종료 시 자동 해제)", "켜짐" if ok else "실패")
    return ok
