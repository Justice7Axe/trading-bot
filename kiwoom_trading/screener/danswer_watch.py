"""📒 [디앤서] 관심종목 2-2-2 + 🛡️ 하락장 헤지주 — 매일 고르고 저장하고 다음 날 결과로 분석한다 (주문 없음).

2026-10-26 사용자: "디앤서 종가 매매는 1) 섹터 2) 테마 3) 개별주 세 분류를 2종목씩 관심종목으로 매일 찾고 저장하고 분석함.
그리고 하락장에는 헤지주를 공략함 → 하락장 헤지주를 리스팅하고 관심종목 관리. 가령 하락장에서 안랩이 종가까지 고가 부근을
유지한다면 종가 매매 후 다음 날 갭 상승을 노릴 것."
책 근거: 『실전 시황 트레이딩』 3장 2-2-2 법칙(섹터 2·테마 2·개별주 2, 79쪽), 일반 종목 +8~10%↑·삼전·하닉 +3%↑ (영상),
4-1 종가 베팅 ③ 개별주 = 지수가 나쁜 날 혼자 오르는 종목.

하루 흐름 (장중 스캐너 run_intraday 가 1분마다 tick):
- 15:15~15:19 🛡️ 하락일(코스피 전일 대비 < 0)이면 헤지주 목록 중 상승 & 고가 부근((현재가−저가)/(고가−저가) ≥ 0.8) 종목 알림.
  ⚠️ 1년 검증(스킬 danswer scripts/t_hedge*.py)에서 이 종가 매수 → 다음 날 09:00 은 0 안팎·손실이라 **알림·기록만** 한다.
- 15:35~15:50 📒 관심종목 2-2-2 (KRX 대금 상위, 주식만):
  섹터 2 = 대금 50위 안 +3%↑ 종목이 가장 많이 모인 업종(stocks.sector)의 대금 상위 2
  테마 2 = 키움 테마(ka90001) 등락률 상위 20개 중 대금 100위 안 +5%↑ 종목이 가장 많은 테마의 대금 상위 2 (섹터 2 와 겹치면 뺌)
  개별주 2 = 그 섹터·테마에 안 드는 대금 100위 안 +8%↑ 종목 중 대금 상위 2
  헤지주 2 = 하락일에만, 헤지주 중 상승 & 고가 부근 마감 종목의 등락률 상위 2
  삼성전자·SK하이닉스는 항상 기록 (+3%↑ 면 ★).
  같은 때 전 거래일 관심종목의 오늘 결과(시가 갭·고가·종가, 전일 15:35 가격 대비)를 채우고 분류별 누적 성적을 보낸다.
기록: screener.duckdb danswer_watch.
"""
import logging
from collections import defaultdict
from datetime import date, datetime, time
from typing import Callable, Optional

from kiwoom_trading.screener.market_data import RankItem
from kiwoom_trading.screener.market_regime import fetch_index_now

HEDGE_START, HEDGE_END = time(15, 15), time(15, 19)
WATCH_START, WATCH_END = time(15, 35), time(15, 50)
NEAR_HIGH = 0.8
LIMIT_UP = 0.295
INDEX_CODES = {"005930": "삼성전자", "000660": "SK하이닉스"}

# 🛡️ 하락장 헤지주 목록 (사람 기준, 2026-10-26). 고치려면 여기와 스킬 danswer 10장을 같이 고친다.
HEDGE = {
    "보안": ["053800", "263860", "042510", "136540", "208350", "150900"],          # 안랩·지니언스·라온시큐어·윈스·지란지교시큐리티·파수
    "방산": ["079550", "012450", "064350", "272210", "047810", "103140"],          # LIG넥스원·한화에어로·현대로템·한화시스템·KAI·풍산
    "통신": ["017670", "030200", "032640"],                                         # SKT·KT·LG유플러스
    "전력·가스": ["015760", "036460", "052690"],                                    # 한국전력·한국가스공사·한전기술
    "음식료·담배": ["033780", "271560", "004370", "003230", "097950", "280360"],    # KT&G·오리온·농심·삼양식품·CJ제일제당·롯데웰푸드
    "비철·금": ["010130"],                                                          # 고려아연
}
HEDGE_GROUP = {c: g for g, cs in HEDGE.items() for c in cs}

SCHEMA = """
CREATE TABLE IF NOT EXISTS danswer_watch (   -- 📒 디앤서 관심종목 2-2-2·🛡️ 헤지주 (주문 없음, 다음 날 결과로 분석)
    date DATE, kind VARCHAR, grp VARCHAR, slot INTEGER, code VARCHAR, name VARCHAR,
    chg DOUBLE, value_rank INTEGER, price DOUBLE, pos DOUBLE, note VARCHAR,
    next_gap DOUBLE, next_high DOUBLE, next_close DOUBLE,
    PRIMARY KEY (date, kind, code)
)"""


def close_pos(price: float, high: float, low: float) -> Optional[float]:
    return (price - low) / (high - low) if high > low else None


class DanswerWatch:
    def __init__(self, store, market, client, today: date, names: dict[str, str], sectors: dict[str, str], regime=None,
                 notify: Optional[Callable[[str], object]] = None) -> None:
        self.store, self.market, self.client, self.today = store, market, client, today
        self.names, self.sectors, self.regime = names, sectors, regime
        self.notify = notify or (lambda text: None)
        store.conn.execute(SCHEMA)
        kinds = {k for (k,) in store.conn.execute("SELECT DISTINCT kind FROM danswer_watch WHERE date = ?", [today]).fetchall()}
        self.hedge_done = "헤지주 알림" in kinds or "헤지주 없음" in kinds
        self.watch_done = bool(kinds - {"헤지주 알림", "헤지주 없음"})
        self.down: Optional[bool] = None
        self.hedge_hits: list[tuple] = []

    # ------------------------------------------------------------------ 하락일 판단
    def _is_down(self, value_top: list[RankItem]) -> tuple[bool, str]:
        idx = getattr(self.regime, "index", None)
        if idx is not None:
            try:
                now = fetch_index_now(self.client, self.today)
                if now:
                    k = now / idx.prev_close - 1
                    return k < 0, f"코스피 {k:+.2%}"
            except Exception:
                logging.warning("헤지주: 코스피 현재값 조회 실패 → 대금 상위 중앙값으로 판단")
        xs = sorted(i.change_rate for i in value_top if i.code in self.names and i.change_rate is not None)
        med = xs[len(xs) // 2] if xs else 0.0
        return med < 0, f"대금 상위 주식 중앙 {med:+.2%}"

    def _hedge_scan(self) -> list[tuple]:
        """헤지주 [(code, name, group, chg, price, pos)] — 상승 & 고가 부근 & 상한가 아님."""
        out = []
        for code, grp in HEDGE_GROUP.items():
            try:
                q = self.market.quote(code, integrated=False)      # KRX 정규장 시세
            except Exception:
                q = None
            if not q or not q.base_price:
                continue
            chg = q.price / q.base_price - 1
            pos = close_pos(q.price, q.high, q.low)
            if 0 < chg < LIMIT_UP and pos is not None and pos >= NEAR_HIGH:
                out.append((code, self.names.get(code, q.name), grp, chg, float(q.price), pos))
        return sorted(out, key=lambda x: -x[3])

    def _save(self, rows: list[tuple]) -> None:
        if rows:
            self.store.conn.executemany(
                "INSERT OR REPLACE INTO danswer_watch (date, kind, grp, slot, code, name, chg, value_rank, price, pos, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def tick(self, now: datetime, value_top: list[RankItem]) -> None:
        t = now.time()
        if not self.hedge_done and HEDGE_START <= t <= HEDGE_END and len(value_top) >= 50:
            self.hedge_done = True
            self._hedge_alert(value_top)
        if not self.watch_done and WATCH_START <= t <= WATCH_END and len(value_top) >= 50:
            self.watch_done = True
            self._watch(value_top)

    def _hedge_alert(self, value_top: list[RankItem]) -> None:
        self.down, why = self._is_down(value_top)
        if not self.down:
            logging.info("🛡️ 헤지주: 하락일 아님 (%s)", why)
            self._save([(self.today, "헤지주 없음", why, 0, "-", "-", None, None, None, None, "하락일 아님")])
            return
        hits = self._hedge_scan()
        self.hedge_hits = hits
        rank = {i.code: i.rank for i in value_top}
        self._save([(self.today, "헤지주 알림", g, n + 1, c, nm, ch, rank.get(c), p, pos, why)
                    for n, (c, nm, g, ch, p, pos) in enumerate(hits)] or
                   [(self.today, "헤지주 없음", why, 0, "-", "-", None, None, None, None, "고가 부근 상승 헤지주 없음")])
        lines = [f"[디앤서] 🛡️ 하락장 헤지주 15:15 ({why}) — 알림만, 매수 안 함",
                 "상승 & 고가 부근(80%↑) 유지: " + (f"{len(hits)}종목" if hits else "없음")]
        for c, nm, g, ch, p, pos in hits:
            lines.append(f"  {nm}({c}) [{g}] {ch:+.1%} · 고가 부근 {pos:.0%} · {p:,.0f}")
        lines.append("⚠️ 1년 검증: 하락일 헤지주 고가 부근 종가 매수 → 다음 날 09:00 건당 −0.3% 안팎 (스킬 danswer 10장). 다음 날 결과는 15:35 관심종목 정리 때 기록")
        self.notify("\n".join(lines))

    # ------------------------------------------------------------------ 관심종목 2-2-2
    def _themes(self, top100: dict[str, RankItem], taken: set[str]) -> tuple[str, list[RankItem]]:
        try:
            groups = [g for g in self.market.theme_groups() if g.change_rate is not None and g.members >= 3]
        except Exception:
            logging.exception("📒 테마 목록(ka90001) 조회 실패")
            return "", []
        best, best_score = ("", []), (0, 0.0)
        for g in sorted(groups, key=lambda g: -g.change_rate)[:20]:
            try:
                members = self.market.theme_members(g.code)
            except Exception:
                continue
            strong = sorted((top100[c] for c in members if c in top100 and c not in taken and (top100[c].change_rate or 0) >= 0.05),
                            key=lambda i: i.rank)
            score = (len(strong), g.change_rate)
            if len(strong) >= 2 and score > best_score:
                best, best_score = (f"{g.name} {g.change_rate:+.1%}", strong), score
        return best

    def _watch(self, value_top: list[RankItem]) -> None:
        stocks = sorted((i for i in value_top if i.code in self.names and i.code[-1] not in "579K" and i.change_rate is not None and i.price),
                        key=lambda i: i.rank)
        top100 = {i.code: i for i in stocks[:100]}
        rows, lines = [], []
        review = self._review(stocks)

        # 섹터 2
        by = defaultdict(list)
        for i in stocks[:50]:
            if i.change_rate >= 0.03 and self.sectors.get(i.code):
                by[self.sectors[i.code]].append(i)
        sec, picks_s = "", []
        if by:
            sec = max(by, key=lambda s: (len(by[s]), sum(i.trade_value or 0 for i in by[s])))
            picks_s = by[sec][:2]
        taken = {i.code for i in picks_s}
        # 테마 2
        theme, strong = self._themes(top100, taken)
        picks_t = strong[:2]
        taken |= {i.code for i in picks_t}
        theme_codes = {i.code for i in strong}
        # 개별주 2
        picks_i = [i for i in stocks[:100] if i.change_rate >= 0.08 and i.code not in taken and i.code not in theme_codes
                   and self.sectors.get(i.code) != sec][:2]
        # 헤지주 2 (하락일만, 15:15 판단 결과를 종가로 다시 확인)
        if self.down is None:
            self.down, _ = self._is_down(value_top)
        picks_h = self._hedge_scan()[:2] if self.down else []

        def add(kind, grp, items):
            for n, i in enumerate(items):
                q_pos = None
                try:
                    q = self.market.quote(i.code, integrated=False)
                    q_pos = close_pos(q.price, q.high, q.low) if q else None
                except Exception:
                    pass
                rows.append((self.today, kind, grp, n + 1, i.code, i.name, i.change_rate, i.rank, float(i.price), q_pos, None))
                lines.append(f"  {i.name}({i.code}) {i.change_rate:+.1%} · 대금 {i.rank}위" + (f" · 고가 부근 {q_pos:.0%}" if q_pos is not None else ""))

        lines.append(f"🏭 섹터 2 — {sec or '없음'}" + (f" (대금 50위 안 +3%↑ {len(by[sec])}종목)" if sec else ""))
        add("섹터", sec, picks_s)
        lines.append(f"🧩 테마 2 — {theme or '없음 (대금 100위 안 +5%↑ 2종목 이상 모인 테마 없음)'}")
        add("테마", theme, picks_t)
        lines.append("🎯 개별주 2" + ("" if picks_i else " — 없음 (+8%↑ 종목 없음)"))
        add("개별주", "", picks_i)
        if self.down:
            lines.append("🛡️ 헤지주 2 (하락일)" + ("" if picks_h else " — 고가 부근 상승 헤지주 없음"))
            for n, (c, nm, g, ch, p, pos) in enumerate(picks_h):
                rows.append((self.today, "헤지주", g, n + 1, c, nm, ch, top100[c].rank if c in top100 else None, p, pos, None))
                lines.append(f"  {nm}({c}) [{g}] {ch:+.1%} · 고가 부근 {pos:.0%}")
        idx = []
        for c, nm in INDEX_CODES.items():
            i = next((x for x in stocks if x.code == c), None)
            if i:
                rows.append((self.today, "지수 관련", "", 0, c, nm, i.change_rate, i.rank, float(i.price), None, "★ +3%↑" if i.change_rate >= 0.03 else None))
                idx.append(f"{'★' if i.change_rate >= 0.03 else ''}{nm} {i.change_rate:+.1%}")
        self._save(rows)
        head = f"[디앤서] 📒 관심종목 2-2-2 {self.today:%m-%d} 마감 — 기록만 (매수 안 함)"
        self.notify("\n".join([head] + lines + (["📌 " + " · ".join(idx)] if idx else []) + review))
        logging.info("📒 디앤서 관심종목 %s종목 저장", len(rows))

    # ------------------------------------------------------------------ 분석
    def _review(self, stocks: list[RankItem]) -> list[str]:
        """전 거래일 관심종목의 오늘 결과를 채우고, 분류별 누적 성적 줄을 돌려준다."""
        conn = self.store.conn
        prev = conn.execute("SELECT max(date) FROM danswer_watch WHERE date < ? AND kind IN ('섹터','테마','개별주','헤지주','헤지주 알림','지수 관련')",
                            [self.today]).fetchone()[0]
        out = []
        if prev:
            todo = conn.execute("SELECT kind, code, name, price FROM danswer_watch WHERE date = ? AND next_close IS NULL "
                                "AND kind IN ('섹터','테마','개별주','헤지주','헤지주 알림','지수 관련')", [prev]).fetchall()
            got = []
            for kind, code, name, price in todo:
                try:
                    q = self.market.quote(code, integrated=False)
                except Exception:
                    q = None
                if not q or not price:
                    continue
                gap, hi, cl = q.open / price - 1, q.high / price - 1, q.price / price - 1
                conn.execute("UPDATE danswer_watch SET next_gap = ?, next_high = ?, next_close = ? WHERE date = ? AND kind = ? AND code = ?",
                             [gap, hi, cl, prev, kind, code])
                got.append(f"{name} 갭 {gap:+.1%} 고가 {hi:+.1%} 종가 {cl:+.1%}")
            if got:
                out.append(f"\n📊 어제({prev:%m-%d}) 관심종목 오늘: " + " / ".join(got))
        stats = conn.execute("""SELECT kind, count(*), avg(next_gap), avg(next_high), avg(next_close), avg(CASE WHEN next_gap > 0 THEN 1.0 ELSE 0 END)
                                FROM danswer_watch WHERE next_close IS NOT NULL GROUP BY kind ORDER BY 1""").fetchall()
        if stats:
            out.append("📈 누적 (다음 날, 전일 마감가 대비): " + " / ".join(
                f"{k} {n}건 갭 {g:+.2%}(+ {w:.0%}) 고가 {h:+.2%} 종가 {c:+.2%}" for k, n, g, h, c, w in stats))
        return out
