"""🪜 이평선 재정배열 코인 선물 모의 매매 — 한 번 실행하면 그동안 끝난 15분봉을 모두 판정한다.

작업 스케줄러가 15분마다 부른다 (scripts/register_crypto_align_task.ps1).
    python -m kiwoom_trading.strategies.crypto_align.live              # 판정 + 알림 + 리포트
    python -m kiwoom_trading.strategies.crypto_align.live --no-telegram
    python -m kiwoom_trading.strategies.crypto_align.live --send-report  # 리포트 HTML 을 텔레그램 파일로

실제 주문은 내지 않는다 (가상 장부: data/crypto_paper/<심볼>/state.json·trades.csv).
첫 실행 때는 그 시각 이후 봉부터 모의 매매를 시작한다 (지난 봉은 리포트의 '지난 차트 타점'으로만).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from kiwoom_trading.strategies.crypto_align import core

KST = timezone(timedelta(hours=9))
SEED = 1000.0


def kst(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%m-%d %H:%M")


def _msg(symbol: str, e: dict) -> str:
    name = f"{core.KIND} 모의 {symbol}"
    if e["type"] == "buy":
        return (f"{name} 매수\n"
                f"{kst(e['t'])} 매수가 {e['price']:,.2f} (15분봉 60선 {e['fast']:,.2f} 이 120선 {e['slow']:,.2f} 위로)\n"
                f"손절 {e['stop']:,.2f} (−3%), 안 닿으면 내일 09:00 매도")
    if e["type"] == "sell":
        return (f"{name} 매도 ({e['reason']})\n"
                f"{kst(e['entry_t'])} {e['entry']:,.2f} → {kst(e['exit_t'])} {e['exit']:,.2f}  "
                f"{e['net'] * 100:+.2f}% (수수료 포함)\n"
                f"가상 잔고 {e['cash']:,.1f} USDT (시작 {SEED:,.0f})")
    return ""


def _append_trades(symbol: str, trades: list[dict]) -> None:
    path = os.path.join(core.data_dir(symbol), "trades.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["signal_kst", "entry_kst", "entry", "exit_kst", "exit", "reason", "ret_pct", "net_pct", "cash"])
        for t in trades:
            w.writerow([kst(t["signal_t"]), kst(t["entry_t"]), f"{t['entry']:.4f}", kst(t["exit_t"]),
                        f"{t['exit']:.4f}", t["reason"], f"{t['ret'] * 100:.3f}", f"{t['net'] * 100:.3f}",
                        f"{t['cash']:.2f}"])


def run(symbol: str, telegram: bool = True, send_report: bool = False) -> core.State:
    d = core.data_dir(symbol)
    state_path = os.path.join(d, "state.json")
    bars, forming = core.load_bars(symbol)
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            st = core.State.from_json(json.load(f))
    else:   # 첫 실행: 지금까지 끝난 봉은 판정 끝으로 두고 다음 봉부터 시작
        st = core.State(last_t=bars[-1].t, cash=SEED)
        logging.info("%s 모의 매매 시작 — %s 봉 다음부터", symbol, kst(bars[-1].t))
    trades = core.replay(bars, st, forming)
    if trades:
        _append_trades(symbol, trades)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(st.to_json(), f, ensure_ascii=False, indent=1)

    late_min = (time.time() * 1000 - (bars[-1].t + core.BAR_MS)) / 60000
    for e in st.events:
        logging.info("%s %s", symbol, e)
    if telegram:
        from kiwoom_trading.common.telegram import send_telegram_message
        for e in st.events:
            text = _msg(symbol, e)
            if text:
                if late_min > 20:
                    text += f"\n(판정 {late_min:.0f}분 늦음 — PC 꺼짐·절전)"
                send_telegram_message(text)

    from kiwoom_trading.strategies.crypto_align import report
    path = report.build(symbol, bars)
    if telegram and (send_report or any(e["type"] == "sell" for e in st.events)):
        from kiwoom_trading.common.telegram import send_telegram_document
        send_telegram_document(path, caption=f"{core.KIND} {symbol} 매매 타점 리포트")
    return st


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SOXLUSDT")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--send-report", action="store_true")
    a = ap.parse_args()
    from kiwoom_trading.common.daily_store import PROJECT_ROOT
    log_dir = os.path.join(PROJECT_ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(log_dir, f"crypto_align_{datetime.now():%Y%m}.log"), encoding="utf-8"),
                  logging.StreamHandler()])
    try:
        run(a.symbol, telegram=not a.no_telegram, send_report=a.send_report)
    except Exception:
        logging.exception("crypto_align 실행 실패")
        raise


if __name__ == "__main__":
    main()
