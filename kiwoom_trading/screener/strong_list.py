"""📡 오늘의 강세 종목 — 거래대금 상위·상승률 상위 (알림만, 매수 없음).

2026-10-26 사용자: 키움 [0184] 대금 상위·[0198] 조회 순위 화면의 주요 종목(루닛·빅웨이브로보틱스·브릴스·JYP 등)이
포착됐는지 물음 → 14종목 중 10개는 🎯 신호로 잡혔지만(하락 흐름 날이라 안 삼) 브릴스(오후 급등)·JYP(애프터 급등)·
샌즈랩·AP위성은 알림이 없었다. 포착 순간 매수 1년 백테스트는 하락 흐름·강한 하락장 날 건당 −1~−2% 라
매수와는 잇지 않고 보여 주기만 한다.

기준: 키움 화면과 같게 통합(KRX+NXT), 주식만(ETF·ETN·스팩 제외, 우선주 포함).
- 거래대금 상위: ka10032 stex_tp 3 → 주식만 상위 TOP_VALUE
- 상승률 상위: ka10027 stex_tp 3, 대금 100억↑ → 상위 TOP_RISE
보내는 시각: 10:00 · 13:30 · 15:20 · 19:50(애프터 포함). 그날 🎯 신호가 난 종목은 표시한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any, Callable, Optional

SLOTS = (time(10, 0), time(13, 30), time(15, 20), time(19, 50))
TOP_VALUE = 20
TOP_RISE = 15
RISE_MIN_VALUE = "1000"      # ka10027 거래대금 조건 100억↑


def _won(v: Optional[int]) -> str:
    if not v:
        return "-"
    return f"{v / 1e12:,.1f}조" if v >= 1e12 else f"{v / 1e8:,.0f}억"


class StrongListWatcher:
    def __init__(self, store, market, today: date, names: dict, notify: Optional[Callable[[str], Any]] = None) -> None:
        self.store, self.market, self.today, self.names, self.notify = store, market, today, names, notify
        self.conn = store.conn
        self.conn.execute("CREATE TABLE IF NOT EXISTS strong_list_sent (date DATE, slot VARCHAR, ts TIMESTAMP, PRIMARY KEY (date, slot))")

    def _sent(self, slot: str) -> bool:
        return bool(self.conn.execute("SELECT count(*) FROM strong_list_sent WHERE date = ? AND slot = ?", [self.today, slot]).fetchone()[0])

    def _stock(self, code: str, name: str) -> bool:
        return code in self.names and "스팩" not in name

    def _signals(self) -> dict[str, str]:
        rows = self.conn.execute("""SELECT code, kind, min(ts) FROM buy_signals WHERE date = ? GROUP BY code, kind ORDER BY 3""",
                                 [self.today]).fetchall()
        out: dict[str, str] = {}
        for code, kind, ts in rows:
            out.setdefault(code, f"{ts:%H:%M} {kind}")
        return out

    def tick(self, now: datetime) -> None:
        t = now.time()
        due = [s for s in SLOTS if t >= s and (datetime.combine(self.today, t) - datetime.combine(self.today, s)).seconds < 600]
        if not due:
            return
        slot = due[-1].strftime("%H:%M")
        if self._sent(slot):
            return
        try:
            text = self.build(now)
        except Exception:
            logging.exception("📡 강세 종목 목록 만들기 실패")
            return
        self.conn.execute("INSERT INTO strong_list_sent VALUES (?, ?, ?)", [self.today, slot, now.replace(tzinfo=None)])
        logging.info("📡 강세 종목 %s 보냄", slot)
        if self.notify:
            self.notify(text)

    def build(self, now: datetime) -> str:
        sig = self._signals()
        value = [i for i in self.market.value_rank(pages=1, stex_tp="3") if self._stock(i.code, i.name)][:TOP_VALUE]
        rise = [i for i in self.market.risers(min_value_cond=RISE_MIN_VALUE, stex_tp="3") if self._stock(i.code, i.name)][:TOP_RISE]
        after = " (애프터 포함)" if now.time() >= time(15, 30) else ""
        lines = [f"📡 오늘의 강세 종목 {now:%H:%M}{after} — 통합(KRX+NXT)·주식만, 알림만(매수 없음)"]
        lines.append(f"\n💰 거래대금 상위 {len(value)}")
        for n, i in enumerate(value, 1):
            mark = f"  🎯{sig[i.code]}" if i.code in sig else ""
            lines.append(f"{n:>2}. {i.name} {(i.change_rate or 0) * 100:+.1f}% {_won(i.trade_value)}{mark}")
        lines.append(f"\n🚀 상승률 상위 (대금 100억↑) {len(rise)}")
        for n, i in enumerate(rise, 1):
            mark = f"  🎯{sig[i.code]}" if i.code in sig else "  · 신호 없음"
            lines.append(f"{n:>2}. {i.name} {(i.change_rate or 0) * 100:+.1f}% 약 {_won(i.trade_value)}{mark}")
        lines.append("\n※ 1년 백테스트: 포착 순간 매수는 강한 상승장만 +0.1~0.5%, 하락 흐름·강한 하락장 날 건당 −1~−2% → 보기만 하세요.")
        return "\n".join(lines)
