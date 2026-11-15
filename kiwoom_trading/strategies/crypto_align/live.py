"""🪜 이평선 재정배열 코인 선물 모의 매매 — 한 번 실행하면 그동안 끝난 15분봉을 모두 판정한다.

작업 스케줄러가 15분마다 부른다 (scripts/register_crypto_align_task.ps1).
    python -m kiwoom_trading.strategies.crypto_align.live              # 판정 + 알림 + 리포트 (+ 09시 뒤 첫 실행이면 매매일지)
    python -m kiwoom_trading.strategies.crypto_align.live --no-telegram
    python -m kiwoom_trading.strategies.crypto_align.live --send-report  # 리포트 HTML 을 텔레그램 파일로

실제 주문은 내지 않는다 (가상 장부: data/crypto_paper/<심볼>/state.json·trades.csv).
같은 매매를 1배·2배 두 가상 잔고로 적는다. 첫 실행 때는 그 시각 이후 봉부터 모의 매매를 시작한다.
매일 한국 09:00(00:00 UTC) 하루가 끝나면 그 뒤 첫 실행에서 매매일지(journal.py)를 쓰고 리포트와 함께 텔레그램으로 보낸다.
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
TRADE_COLS = ["signal_t", "entry_t", "entry", "exit_t", "exit", "reason", "ret", "fund", "net", "net2",
              "cash", "cash2", "fast", "slow", "stop", "low", "high", "logged_t"]


def kst(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%m-%d %H:%M")


def _msg(symbol: str, e: dict) -> str:
    name = f"{core.KIND} 모의 {symbol}"
    if e["type"] == "buy":
        return (f"{name} 매수\n"
                f"{kst(e['t'])} 매수가 {e['price']:,.2f} (15분봉 60선 {e['fast']:,.2f} 이 120선 {e['slow']:,.2f} 위로)\n"
                f"손절 {e['stop']:,.2f} (−3%, 2배면 잔고 −6%), 안 닿으면 내일 09:00 매도")
    if e["type"] == "sell":
        return (f"{name} 매도 ({e['reason']})\n"
                f"{kst(e['entry_t'])} {e['entry']:,.2f} → {kst(e['exit_t'])} {e['exit']:,.2f}\n"
                f"1배 {e['net'] * 100:+.2f}% · 2배 {e['net2'] * 100:+.2f}% (수수료·펀딩 포함)\n"
                f"가상 잔고 1배 {e['cash']:,.1f} · 2배 {e['cash2']:,.1f} USDT (시작 각 {SEED:,.0f})")
    return ""


def trades_path(symbol: str) -> str:
    return os.path.join(core.data_dir(symbol), "trades.csv")


def load_trades(symbol: str) -> list[dict]:
    path = trades_path(symbol)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = {}
            for k, v in r.items():
                if k == "reason":
                    d[k] = v
                elif k.endswith("_t"):
                    d[k] = int(v)
                else:
                    d[k] = float(v)
            out.append(d)
    return out


def _append_trades(symbol: str, trades: list[dict]) -> None:
    path = trades_path(symbol)
    new = not os.path.exists(path)
    now = int(time.time() * 1000)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(TRADE_COLS)
        for t in trades:
            t = {**t, "logged_t": now}
            w.writerow([t[k] for k in TRADE_COLS])


def run(symbol: str, telegram: bool = True, send_report: bool = False) -> core.State:
    d = core.data_dir(symbol)
    state_path = os.path.join(d, "state.json")
    bars, forming = core.load_bars(symbol)
    rates = core.load_funding(symbol)
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            st = core.State.from_json(json.load(f))
    else:   # 첫 실행: 지금까지 끝난 봉은 판정 끝으로 두고 다음 봉부터 시작
        st = core.State(last_t=bars[-1].t, cash=SEED, cash2=SEED)
        logging.info("%s 모의 매매 시작 — %s 봉 다음부터", symbol, kst(bars[-1].t))
    if not st.journal_day:   # 일지는 모의 시작한 날(한국 09시 기준 하루)부터
        st.journal_day = (datetime.fromtimestamp(st.last_t / 1000, timezone.utc).date() - timedelta(days=1)).isoformat()
    trades = core.replay(bars, st, forming, rates)
    if trades:
        _append_trades(symbol, trades)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(st.to_json(), f, ensure_ascii=False, indent=1)

    late_min = (time.time() * 1000 - (bars[-1].t + core.BAR_MS)) / 60000
    for e in st.events:
        logging.info("%s %s", symbol, {k: v for k, v in e.items() if k != "type"} | {"type": e["type"]})
    if telegram:
        from kiwoom_trading.common.telegram import send_telegram_message
        for e in st.events:
            text = _msg(symbol, e)
            if text:
                if late_min > 20:
                    text += f"\n(판정 {late_min:.0f}분 늦음 — PC 꺼짐·절전)"
                send_telegram_message(text)

    from kiwoom_trading.strategies.crypto_align import journal, report
    path = report.build(symbol, bars)

    # 매매일지: 끝난 하루(00:00~24:00 UTC = 한국 09:00~다음 날 09:00)마다 한 번씩, 빠진 날도 차례로
    sent_report = False
    last_done = datetime.fromisoformat(st.journal_day).date()
    # 09:00 매도는 00:00 UTC 봉이 끝나야(한국 09:15) 확정 → 마지막 끝난 봉의 날짜보다 앞선 날만 씀
    today_utc = datetime.fromtimestamp(bars[-1].t / 1000, timezone.utc).date()
    day = last_done + timedelta(days=1)
    while day < today_utc:
        jpath = journal.write_day(symbol, day, bars, st, rates, send=telegram)
        logging.info("%s 매매일지 %s → %s", symbol, day, jpath)
        st.journal_day = day.isoformat()
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(st.to_json(), f, ensure_ascii=False, indent=1)
        day += timedelta(days=1)
        sent_report = sent_report or telegram
    if telegram and sent_report:
        from kiwoom_trading.common.telegram import send_telegram_document
        send_telegram_document(path, caption=f"{core.KIND} {symbol} 매매 타점 리포트 (1배·2배)")
    elif telegram and send_report:
        from kiwoom_trading.common.telegram import send_telegram_document
        send_telegram_document(path, caption=f"{core.KIND} {symbol} 매매 타점 리포트 (1배·2배)")
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
