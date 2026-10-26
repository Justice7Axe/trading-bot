"""매매표 전체 1년 백테스트 (2026-10-27, 세션 임시 폴더 스크래치에서 옮김 — docs/architecture.md 4장 1단계).

원래 위치 (data/research_archive/ 에 보존):
  d9b9b62e/full_bt.py · compound.py · swing.py · swing3.py, 8623875b/u_common.py · nm_common.py
입력 (git 제외, data/backtest/playbook/):
  regime_feat.pkl · mismatch.pkl · resbo2.pkl · g2g_filter.pkl (93a48a29), u_cands.pkl (8623875b), closebet.pkl (ea0dc09b),
  inv_bars.pkl (f3f6486b), np_cands.pkl (d9b9b62e), inv_daily_ohlcv.duckdb, daily_ohlcv_20261025.duckdb (검증용 스냅샷)
실행: python -m kiwoom_trading.backtest.playbook.full_bt
      (원래 결과와 맞춰 보기: PLAYBOOK_DAILY_DB=data/backtest/playbook/daily_ohlcv_20261025.duckdb)
"""
