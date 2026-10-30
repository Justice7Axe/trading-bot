"""🔴 실전 계좌 성과 리포트 (2026-10-30 사용자 '실전 투자 성과 리포트가 눈에 안 띄어 보완해줘').

매일 15:45(정규장 마감 뒤) 한 번 따로 보낸다 — 모의·가상 장부 리포트와 섞이지 않게 맨 위에 🔴 굵은 머리말.
  ① 계좌: 시작 시드 → 지금 추정 자산(주문 가능 금액 + 이 매매 보유 평가), 누적 수익률, 실현 손익
  ② 오늘: 산 것·판 것·오늘 실현 손익
  ③ 들고 있는 종목: 매수가·현재가·평가 손익·언제 파는지
  ④ 매매별 누적: 건수·승률·손익
  ⑤ 최근 5거래일 날마다 실현 손익
아침 📋 카드 첫머리에는 `one_line()` 한 줄 (누적 수익률·어제 손익·보유 수).
수동 미리 보기: python -m kiwoom_trading.execution.real_report [--send]
"""
import logging
from collections import defaultdict
from datetime import date, datetime, time
from typing import Optional

REPORT_AT = time(15, 45)
START_DAY, START_CASH = date(2026, 10, 26), 83_897   # 실전 시작 날 09:00 물린 종목 정리 뒤 주문 가능 금액 (메모리 real-trading) — 시드 10만은 이름일 뿐


def _pct(x: float) -> str:
    return f"{x:+.2%}"


def _won(x: float) -> str:
    return f"{x:+,.0f}원"


def _rows(conn, sql, args=()):
    return conn.execute(sql, list(args)).fetchall()


def build(conn, today: date, seed: float, plays: dict, cash: Optional[float] = None, price_of=None) -> str:
    """conn = screener.duckdb (real_trades), plays = real.PLAYS (종류 → (이름, 익절, 손절)), price_of(code) → 현재가."""
    name = lambda k: plays.get(k, (k or "?",))[0]
    closed = _rows(conn, """SELECT date, code, coalesce(name, code), kind, qty, buy_price, sell_price, pnl, sell_ts, reason
                            FROM real_trades WHERE status = 'closed' AND pnl IS NOT NULL ORDER BY sell_ts""")
    held = _rows(conn, """SELECT date, code, coalesce(name, code), kind, qty, buy_price, status FROM real_trades
                          WHERE status IN ('ordered', 'open', 'selling') ORDER BY buy_ts""")
    realized = sum(r[7] for r in closed)
    lines = [f"🔴🔴 실전 계좌 성과 ({today:%m-%d}) 🔴🔴"]

    # ① 계좌
    hold_val = hold_cost = 0.0
    hold_lines = []
    for d, code, nm, kind, qty, bp, st in held:
        px = None
        try:
            px = price_of(code) if price_of else None
        except Exception:
            px = None
        cost = (bp or 0) * (qty or 0)
        val = (px or bp or 0) * (qty or 0)
        hold_val += val; hold_cost += cost
        r = (px / bp - 1) if px and bp else None
        how = ("20일선 이탈까지" if "추세" in (kind or "") else "다음 날 09:00")
        hold_lines.append(f"  · {nm} [{name(kind)}] {qty}주 × {bp or 0:,.0f} → {px or 0:,.0f}"
                          + (f" ({_pct(r)}, {_won(val - cost)})" if r is not None else "") + f" · {how}"
                          + ("" if st == "open" else f" · {st}"))
    if cash is not None:
        asset = cash + hold_val
        lines.append(f"💼 추정 자산 {asset:,.0f}원 · {START_DAY:%m-%d} 시작 {START_CASH:,.0f}원 대비 {_pct(asset / START_CASH - 1)} ({_won(asset - START_CASH)})")
        lines.append(f"   = 주문 가능 {cash:,.0f}원 + 보유 평가 {hold_val:,.0f}원")
    lines.append(f"💰 누적 실현 손익 {_won(realized)} ({_pct(realized / seed)}, {len(closed)}건)"
                 + (f" · 보유 평가 손익 {_won(hold_val - hold_cost)}" if held else ""))

    # ② 오늘
    t_buy = _rows(conn, "SELECT coalesce(name, code), kind, qty, buy_price, status FROM real_trades WHERE date = ? AND status <> 'failed' ORDER BY buy_ts", [today])
    t_sell = [r for r in closed if r[8] and r[8].date() == today]
    t_pnl = sum(r[7] for r in t_sell)
    lines.append(f"\n📅 오늘: 매수 {len(t_buy)}건 · 매도 {len(t_sell)}건 · 실현 {_won(t_pnl)}")
    for nm, kind, qty, bp, st in t_buy:
        lines.append(f"  🟢 {nm} [{name(kind)}] {qty}주 × {bp or 0:,.0f}" + (" (미체결 취소)" if st == "failed" else ""))
    for d, code, nm, kind, qty, bp, sp, pnl, ts, why in t_sell:
        lines.append(f"  {'✅' if pnl > 0 else '❌'} {nm} [{name(kind)}] {bp:,.0f} → {sp:,.0f} {_pct(sp / bp - 1)} {_won(pnl)} — {why or ''}"[:160])

    # ③ 보유
    lines.append(f"\n📦 들고 있는 종목 {len(held)}개" + ("" if held else " — 없음"))
    lines += hold_lines

    # ④ 매매별 누적
    if closed:
        by = defaultdict(list)
        for r in closed:
            by[r[3]].append(r[7])
        lines.append("\n📊 매매별 누적")
        for k, v in sorted(by.items(), key=lambda kv: -sum(kv[1])):
            lines.append(f"  {name(k)}: {len(v)}건 · 승률 {sum(1 for x in v if x > 0) / len(v):.0%} · {_won(sum(v))}")

    # ⑤ 최근 5거래일
    days = defaultdict(float)
    for r in closed:
        if r[8]:
            days[r[8].date()] += r[7]
    if days:
        recent = sorted(days)[-5:]
        lines.append("\n📈 최근 날마다 실현: " + " · ".join(f"{d:%m-%d} {_won(days[d])}" for d in recent))
    return "\n".join(lines)


def one_line(conn, seed: float) -> str:
    """아침 카드용 한 줄."""
    closed = _rows(conn, "SELECT pnl, sell_ts FROM real_trades WHERE status = 'closed' AND pnl IS NOT NULL")
    held = _rows(conn, "SELECT count(*) FROM real_trades WHERE status IN ('ordered', 'open', 'selling')")[0][0]
    realized = sum(p for p, _ in closed)
    last = max((ts.date() for _, ts in closed if ts), default=None)
    last_pnl = sum(p for p, ts in closed if ts and ts.date() == last) if last else 0
    return (f"🔴 실전 누적 실현 {_won(realized)} ({_pct(realized / seed)}, {len(closed)}건)"
            + (f" · 지난 거래일({last:%m-%d}) {_won(last_pnl)}" if last else "") + f" · 보유 {held}종목")


class RealReporter:
    """하루 한 번 REPORT_AT 뒤 보냄 (real_reports 표로 중복 방지)."""

    def __init__(self, trader, notify) -> None:
        self.t, self.notify = trader, notify
        self.t.conn.execute("CREATE TABLE IF NOT EXISTS real_reports (date DATE PRIMARY KEY)")

    def tick(self, now: datetime) -> None:
        if now.time() < REPORT_AT:
            return
        if self.t.conn.execute("SELECT count(*) FROM real_reports WHERE date = ?", [self.t.today]).fetchone()[0]:
            return
        try:
            from kiwoom_trading.execution import real as R
            try:
                cash = float(self.t.client.cash())
            except Exception:
                cash = None
            q = lambda c: float(self.t.market.quote(c, integrated=False).price)
            text = build(self.t.conn, self.t.today, R.SEED, R.PLAYS, cash, q)
            self.notify(text)
            self.t.conn.execute("INSERT INTO real_reports VALUES (?)", [self.t.today])
            logging.info("실전 성과 리포트 보냄")
        except Exception:
            logging.exception("실전 성과 리포트 실패")


def main() -> None:
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--db", default=None, help="screener DB (기본: 장중엔 잠기므로 screener_snapshot.duckdb)")
    a = ap.parse_args()
    import duckdb
    from kiwoom_trading.common.daily_store import PROJECT_ROOT
    import os
    from kiwoom_trading.execution import real as R
    db = a.db or os.path.join(PROJECT_ROOT, "data", "screener_snapshot.duckdb")
    conn = duckdb.connect(db, read_only=True)
    text = build(conn, date.today(), R.SEED, R.PLAYS, None, None)
    print(text); print(); print(one_line(conn, R.SEED))
    if a.send:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message(text)


if __name__ == "__main__":
    main()
