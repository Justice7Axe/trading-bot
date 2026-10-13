"""후보 수집 → 조건 판정. 장중(intraday)과 장 마감 후(daily) 모드가 공유한다."""
import logging
import time
from datetime import date
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.screener.conditions import Candidate, Evaluation, ScreenerConfig, evaluate
from kiwoom_trading.screener.history import HistStats, load_history, stock_names
from kiwoom_trading.screener.market_data import KiwoomMarket, RankItem, Theme
from kiwoom_trading.screener.store import ScreenerStore


THEME_CACHE_SECONDS = 300
PEER_MIN_VALUE = 30_000_000_000  # 장 마감 후 업종 동반 판단 시 대상 종목 최소 거래대금(300억)


class Screener:
    def __init__(self, market: KiwoomMarket, today: date, config: Optional[ScreenerConfig] = None, db_path: str = DEFAULT_DB_PATH) -> None:
        self.market = market
        self.today = today
        self.config = config or ScreenerConfig()
        self.db_path = db_path
        conn = duckdb.connect(db_path, read_only=True)
        try:
            self.hist: dict[str, HistStats] = load_history(conn, today)
            self.names: dict[str, str] = stock_names(conn)
            self.sectors: dict[str, str] = dict(conn.execute("SELECT code, sector FROM stocks WHERE sector IS NOT NULL").fetchall())
        finally:
            conn.close()
        self.theme_map = self._load_theme_mapping(today)
        self._groups: dict[str, Theme] = {}
        self._groups_at = 0.0
        logging.info("스크리너 준비: 기준일 %s, 이력 %s종목, 테마 매핑 %s종목", today, len(self.hist), len(self.theme_map))

    def _load_theme_mapping(self, day: date) -> dict[str, list[str]]:
        """종목→테마 매핑. 그날 저장된 것이 있으면 재사용, 없으면 전체 테마 구성 종목을 받아 저장(약 40초)."""
        store = ScreenerStore()
        try:
            mapping = store.theme_mapping(day)
            if mapping:
                return mapping
            rows = []
            try:
                for theme in self.market.theme_groups():
                    rows += [(theme.code, theme.name, code) for code in self.market.theme_members(theme.code)]
            except Exception as exc:
                logging.warning("테마 매핑 구성 실패 (업종 동반으로만 판정): %s", exc)
                return {}
            store.save_theme_mapping(day, rows)
            return store.theme_mapping(day)
        finally:
            store.close()

    def themes(self, code: str) -> list[Theme]:
        """종목이 속한 테마의 현재 등락률 (테마 목록은 5분마다 갱신)."""
        if time.monotonic() - self._groups_at > THEME_CACHE_SECONDS:
            try:
                self._groups = {t.code: t for t in self.market.theme_groups()}
                self._groups_at = time.monotonic()
            except Exception as exc:
                logging.warning("테마 등락 조회 실패: %s", exc)
        return [self._groups[t] for t in self.theme_map.get(code, []) if t in self._groups]

    def peers(self, code: str, movers: dict[str, float]) -> list[str]:
        """같은 업종에서 함께 강하게 오른 종목 이름 (movers: 코드→등락률, 자기 제외)."""
        sector = self.sectors.get(code)
        if not sector:
            return []
        return [
            self.names.get(other, other) for other, rate in sorted(movers.items(), key=lambda x: -x[1])
            if other != code and self.sectors.get(other) == sector and rate >= self.config.peer_min_change
        ]

    # ---------------------------------------------------------------- 장중
    def scan_intraday(self, search_1m: list[RankItem], search_day: list[RankItem], value_top: list[RankItem]) -> list[Evaluation]:
        cfg = self.config
        search_rank: dict[str, int] = {}
        for item in search_1m + search_day:
            search_rank[item.code] = min(item.rank, search_rank.get(item.code, item.rank))
        value_by_code = {i.code: i for i in value_top}
        movers = {i.code: i.change_rate for i in value_top if i.change_rate is not None and i.code in self.names}

        codes = [c for c in dict.fromkeys(list(search_rank) + list(value_by_code)) if c in self.names]
        evaluations = []
        for code in codes:
            v = value_by_code.get(code)
            # 1차 거름: 거래대금 상위 목록에 있으면 그 값으로 등락률/대금을 먼저 본다 (불필요한 시세 조회 줄이기)
            if v and v.change_rate is not None and (v.change_rate < cfg.min_change_rate or (v.trade_value or 0) < cfg.min_trade_value):
                continue
            quote = self.market.quote(code)                      # 가격: KRX+NXT 통합
            if not quote or quote.base_price <= 0:
                continue
            if v and v.trade_value is not None:                  # 거래대금: KRX 기준 (일봉 DB 와 동일)
                trade_value = v.trade_value
            else:
                krx = self.market.quote(code, integrated=False)
                trade_value = krx.volume * krx.price if krx else 0
            if quote.price / quote.base_price - 1 < cfg.min_change_rate or trade_value < cfg.min_trade_value:
                continue
            cand = Candidate(
                code=code, name=self.names.get(code, quote.name), price=quote.price, open=quote.open, high=quote.high,
                low=quote.low, prev_close=quote.base_price, trade_value=trade_value, hist=self.hist.get(code),
                search_rank=search_rank.get(code), value_rank=v.rank if v else None, themes=self.themes(code),
                sector=self.sectors.get(code), peers=self.peers(code, movers),
            )
            evaluations.append(evaluate(cand, cfg))
        return evaluations

    # ---------------------------------------------------------- 장 마감 후
    def scan_daily(self, search_day: list[RankItem]) -> list[Evaluation]:
        """일봉 DB 의 '오늘' 확정 봉으로 판정 (다음 날 관심 종목)."""
        cfg = self.config
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            rows = conn.execute(
                """
                SELECT o.code, o.open, o.high, o.low, o.close, o.value,
                       rank() OVER (ORDER BY o.value DESC) AS vrank
                FROM daily_ohlcv o JOIN stocks s USING (code)
                WHERE o.date = ? AND NOT s.delisted
                """,
                [self.today],
            ).fetchall()
        finally:
            conn.close()
        bars = {r[0]: r for r in rows}
        movers = {
            code: close / self.hist[code].last_close - 1
            for code, _, _, _, close, value, _ in rows
            if value >= PEER_MIN_VALUE and code in self.hist and self.hist[code].last_close
        }
        search_rank = {i.code: i.rank for i in search_day}
        codes = {code for code, *_, vrank in rows if vrank <= cfg.max_value_rank} | {c for c in search_rank if c in bars}

        evaluations = []
        for code in sorted(codes):
            _, o, h, l, close, value, vrank = bars[code]
            hist = self.hist.get(code)
            if not hist or close / hist.last_close - 1 < cfg.min_change_rate or value < cfg.min_trade_value:
                continue
            cand = Candidate(
                code=code, name=self.names.get(code, code), price=close, open=o, high=h, low=l,
                prev_close=hist.last_close, trade_value=value, hist=hist,
                search_rank=search_rank.get(code), value_rank=vrank, themes=self.themes(code),
                sector=self.sectors.get(code), peers=self.peers(code, movers),
            )
            evaluations.append(evaluate(cand, cfg))
        return evaluations
