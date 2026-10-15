"""텔레그램 '정리' 명령 → 오늘 포착 종목·테마·매수 신호를 표로 한눈에.

알림(🎯 🧩 🔥 …)이 계속 쌓여 스크롤이 길어지므로, 요청할 때 그때까지의 결과를 섹션별 고정폭 표(<pre>)로 보낸다.
현재 등락은 스캐너가 매분 받는 순위 데이터(PriceBoard)에서, 없으면 종목 시세(ka10001 통합)로 채운다.

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.daily_summary          # 콘솔로 미리보기 (현재가 조회 포함)
"""
import html
import logging
import re
import sys
import unicodedata
from datetime import date, datetime
from typing import Optional

from kiwoom_trading.screener.market_data import KiwoomMarket, RankItem
from kiwoom_trading.screener.store import ScreenerStore


SUMMARY_WORDS = {"정리", "요약", "현황"}
NAME_WIDTH = 14          # 한글 7자
MAX_ROWS = 25            # 섹션당


class PriceBoard:
    """매분 받는 순위 목록(조회·대금·등락률 상위)의 마지막 가격/등락."""

    def __init__(self) -> None:
        self.change: dict[str, float] = {}
        self.price: dict[str, int] = {}

    def update(self, items: list[RankItem]) -> None:
        for i in items:
            if i.change_rate is not None:
                self.change[i.code] = i.change_rate
            if i.price:
                self.price[i.code] = i.price

    def fill(self, codes: set[str], market: Optional[KiwoomMarket]) -> None:
        """보드에 없는 종목만 시세 조회로 채운다."""
        if market is None:
            return
        for code in codes - set(self.change):
            try:
                q = market.quote(code)
            except Exception as exc:
                logging.warning("정리용 시세 조회 실패 %s: %s", code, exc)
                continue
            if q and q.base_price:
                self.change[code] = q.price / q.base_price - 1
                self.price[code] = q.price


def _w(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _fit(text: str, width: int) -> str:
    out = ""
    for ch in text:
        if _w(out + ch) > width:
            break
        out += ch
    return out + " " * (width - _w(out))


def _pct(x: Optional[float]) -> str:
    return f"{x * 100:+.1f}" if x is not None else "  -"


def _first_pct(reason: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, reason or "")
    return float(m.group(1)) / 100 if m else None


ALERT_PATTERNS = {   # early_alerts.reason 에서 포착 시 등락 추출
    "테마 특징주": r"· ([+-][\d.]+)% ·",
    "조기 주도주": r", ([+-][\d.]+)%",
    "대금 가속": r"당일 ([+-][\d.]+)%",
}
ALERT_ICON = {"테마 특징주": "🔥", "조기 주도주": "🏁", "대금 가속": "🚀"}


def _rfit(text: str, width: int) -> str:
    return " " * max(0, width - _w(text)) + text


def _table(rows: list[tuple], header: tuple, widths: tuple = (5, NAME_WIDTH, 6, 6), latest: bool = False) -> str:
    """고정폭 표. 첫 두 열 왼쪽 정렬, 나머지 오른쪽 정렬 (한글은 2칸으로 계산). latest=True 면 많을 때 최근 것만."""
    def line(cells) -> str:
        return " ".join(_fit(str(c), w) if k < 2 else _rfit(str(c), w) for k, (c, w) in enumerate(zip(cells, widths)))
    shown = rows[-MAX_ROWS:] if latest else rows[:MAX_ROWS]
    lines = [line(header)] + [line(r) for r in shown]
    if len(rows) > MAX_ROWS:
        lines.append(f"… {'앞선' if latest else '외'} {len(rows) - MAX_ROWS}건 생략")
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


def build_summary(store: ScreenerStore, day: date, board: PriceBoard, market: Optional[KiwoomMarket] = None,
                  now: Optional[datetime] = None) -> list[str]:
    """섹션별 HTML 메시지 목록 (각각 4,000자 이하)."""
    c = store.conn
    now = now or datetime.now()
    themes = c.execute("""SELECT ts, label, leader, code, name, change_rate FROM theme_alerts WHERE date = ? ORDER BY ts""", [day]).fetchall()
    alerts = c.execute("SELECT source, code, ts, name, reason FROM early_alerts WHERE date = ? ORDER BY ts", [day]).fetchall()
    detections = c.execute("""SELECT code, name, coalesce(first_ts, ts) t FROM detections WHERE date = ? AND mode = 'intraday' ORDER BY t""", [day]).fetchall()
    signals = c.execute("""SELECT ts, code, name, kind, price FROM buy_signals WHERE date = ? AND reject_reason IS NULL AND alerted ORDER BY ts""", [day]).fetchall()
    rejected = c.execute("SELECT count(*) FROM buy_signals WHERE date = ? AND reject_reason IS NOT NULL", [day]).fetchone()[0]
    watch_n = c.execute("SELECT count(*) FROM watch_adds WHERE date = ?", [day]).fetchone()[0]
    board.fill({r[3] for r in themes} | {r[1] for r in alerts} | {r[0] for r in detections} | {r[1] for r in signals}, market)
    cur = board.change.get

    msgs = [f"📊 오늘 정리 {now:%m-%d %H:%M} — 🧩 테마 {len({(r[1], r[2]) for r in themes})} · 🔥🏁🚀 {len(alerts)} · "
            f"⚡ {len(detections)} · 🎯 {len(signals)} (필터 제외 {rejected}) · 👀 감시 추가 {watch_n}\n(등락: 포착 시 → 현재, %)"]

    # 🧩 테마: 대장(leader) 기준으로 묶음별 마지막 구성, 처음 알린 시각
    groups: dict[str, dict] = {}
    for ts, label, leader, code, name, chg in themes:
        g = groups.setdefault(leader, {"t": ts, "label": label, "members": {}})
        g["members"].setdefault(code, (name, chg))
    if groups:
        blocks = []
        for leader, g in sorted(groups.items(), key=lambda x: x[1]["t"]):
            rows = [(g["t"].strftime("%H:%M") if code == leader else "", ("★" if code == leader else "") + name, _pct(chg), _pct(cur(code)))
                    for code, (name, chg) in sorted(g["members"].items(), key=lambda x: -(x[1][1] or 0))]
            blocks.append(f"[{html.escape(g['label'])}]\n" + _table(rows, ("시각", "종목 (★대장)", "포착", "현재")))
        text = "🧩 테마 형성"
        for b in blocks:                                  # 4,000자 넘으면 나눠 보냄
            if len(text) + len(b) > 3800:
                msgs.append(text); text = "🧩 테마 형성 (계속)"
            text += "\n" + b
        msgs.append(text)

    for source in ("조기 주도주", "테마 특징주", "대금 가속"):
        rows = [(ts.strftime("%H:%M"), name, _pct(_first_pct(reason, ALERT_PATTERNS[source])), _pct(cur(code)))
                for src, code, ts, name, reason in alerts if src == source]
        if rows:
            msgs.append(f"{ALERT_ICON[source]} {source} {len(rows)}\n" + _table(rows, ("시각", "종목", "포착", "현재")))
    if detections:
        rows = [(t.strftime("%H:%M"), name, _pct(cur(code))) for code, name, t in detections]
        msgs.append(f"⚡ 장중 포착 {len(rows)}\n" + _table(rows, ("시각", "종목", "현재"), (5, NAME_WIDTH, 6)))
    if signals:
        rows = []
        for ts, code, name, kind, price in signals:
            px = board.price.get(code)
            rows.append((ts.strftime("%H:%M"), name, "지지" if kind == "지지 반등" else "돌파",
                         f"{price:,.0f}", _pct(px / price - 1) if px and price else "-"))
        msgs.append(f"🎯 매수 신호 {len(rows)} (관찰용, 수익 = 진입가 대비 현재 %)\n"
                    + _table(rows, ("시각", "종목", "종류", "진입가", "수익"), (5, NAME_WIDTH, 4, 9, 6), latest=True))
    if len(msgs) == 1:
        msgs.append("아직 오늘 포착된 종목이 없습니다.")
    return msgs


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from kiwoom_trading.common.config import KST
    from kiwoom_trading.ingestion.collectors.daily_backfill import build_client

    day = datetime.strptime(sys.argv[1], "%Y%m%d").date() if len(sys.argv) > 1 else datetime.now(KST).date()
    store = ScreenerStore()
    try:
        for m in build_summary(store, day, PriceBoard(), KiwoomMarket(build_client())):
            print(m, "\n")
    finally:
        store.close()


if __name__ == "__main__":
    main()
