"""옛 경로 — 백테스트 공통 엔진은 kiwoom_trading/backtest/engine.py 로 옮겼다 (2026-10-27, docs/architecture.md 2단계).
디앤서 스크립트의 `from engine import *` · `from engine import _min_codes` 가 그대로 돌도록 같은 모듈을 가리킨다."""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from kiwoom_trading.backtest import engine as _engine  # noqa: E402

sys.modules[__name__] = _engine
