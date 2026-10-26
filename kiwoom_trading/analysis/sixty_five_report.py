"""옛 경로 — kiwoom_trading.strategies.sixty_five.report 로 옮겼다 (2026-10-27, docs/architecture.md 5단계). 예전 import·실행 명령이 그대로 돌도록 같은 모듈을 가리킨다."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("kiwoom_trading.strategies.sixty_five.report", run_name="__main__", alter_sys=True)
else:
    sys.modules[__name__] = importlib.import_module("kiwoom_trading.strategies.sixty_five.report")
