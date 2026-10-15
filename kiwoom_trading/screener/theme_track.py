"""테마 특징주 트랙 — 거래대금 상위권 밖의 중소형 테마 급등주를 장 초반에 잡는다 (대형 주도주 트랙 🏁·🚀 와 별도).

배경 (2026-10-14 사용자 특징주 정리표 대조):
  특징주 30종목 중 대금 50위 안에 든 것은 9개뿐(중앙 약 160위, 25억~600억). 기존 스크리너(500억/50위) 포착 7개.
  반면 1분 조회 순위 20위 안에는 25개가 들어왔고 대부분 장 초반(08:01~09:44) → 조회 순위 + 급등 + 중간 대금으로 잡는다.

🔥 테마 특징주: 1분 조회 순위 20위 이내(최근 10분 안) + 등락 +7%↑ + 누적 대금 100억↑ (순위 제한 없음)
🧩 테마 형성: +10%↑ 급등주(대장 후보)를 씨앗으로, 씨앗과 '같은 테마'로 직접 연결된 급등주(+5%↑, 대금 30억↑)가 1개↑ 이면 알림
   (연쇄 연결 금지 — 처음 버전은 A-B, B-C 가 이어져 50종목 거대 묶음이 됐다)
   같은 테마 = ① 평소 함께 오르내림: 과거 120일 수익률이 시장 전체 영향을 빼고도 함께 움직임(상관 ≥ 0.25 — 무작위 쌍 2%, 정리표 기존 테마 쌍 50~100%)
              ② 키움 테마 공유 ③ 오늘 처음 생긴 테마(예: 알래스카LNG, 과거 상관 없음)는 같은 업종 + 둘 다 +10%↑
   대장 = 묶음 안에서 누적 대금 1위
급등주 목록: ka10027 등락률 상위(통합 KRX+NXT, ETF·ETN 제외, 대금 30억↑) 매분 1회.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb
import numpy as np

from kiwoom_trading.screener.market_data import RankItem


@dataclass(frozen=True)
class ThemeConfig:
    # 🔥 테마 특징주
    feature_search_rank: int = 20
    feature_change: float = 0.07
    feature_value: int = 10_000_000_000          # 100억
    search_memory_minutes: int = 10              # 최근 10분 안에 조회 20위 안에 든 적
    # 🧩 테마 형성
    member_change: float = 0.05
    member_value: int = 3_000_000_000            # 30억
    lead_change: float = 0.10
    min_members: int = 2
    peer_corr: float = 0.25
    same_sector_change: float = 0.10             # 새 테마: 같은 업종 + 둘 다 +10%↑
    realert_new_members: int = 3                 # 같은 대장 묶음에 새 종목이 3개↑ 붙으면 다시 알림


def build_peer_graph(conn: duckdb.DuckDBPyConnection, before: date, threshold: float = 0.25,
                     window: int = 120, min_avg_value: float = 3e8) -> dict[str, set[str]]:
    """잔차 수익률 상관(시장 평균 수익률 × 베타를 뺀 나머지) ≥ threshold 인 종목 쌍. before 이전 데이터만 사용."""
    df = conn.execute("""
        SELECT date, code, close / lag(close) OVER (PARTITION BY code ORDER BY date) - 1 r, value
        FROM daily_ohlcv WHERE date < ? AND date >= ?::DATE - 200""", [before, before]).df()
    R = df.pivot(index="date", columns="code", values="r").sort_index().astype(float).iloc[-window:]
    V = df.pivot(index="date", columns="code", values="value").sort_index().astype(float).iloc[-20:]
    ok = (R.notna().sum() >= window * 0.8) & (V.mean() >= min_avg_value)
    R = R.loc[:, ok].fillna(0).clip(-0.3, 0.3)
    mkt = R.mean(axis=1)
    beta = (R.apply(lambda s: np.cov(s, mkt)[0, 1]) / mkt.var()).values
    E = R.values - np.outer(mkt.values, beta)
    E = (E - E.mean(0)) / (E.std(0) + 1e-12)
    C = (E.T @ E) / len(E)
    np.fill_diagonal(C, 0)
    cols = R.columns.values
    graph: dict[str, set[str]] = {}
    for i, j in zip(*np.where(C >= threshold)):
        graph.setdefault(cols[i], set()).add(cols[j])
    logging.info("평소 함께 오르내리는 종목 쌍: %s종목, %s쌍", len(graph), sum(len(v) for v in graph.values()) // 2)
    return graph


PEER_LINK = "평소 함께 오르내림"      # 과거 120일 수익률이 (시장 전체 영향을 빼고도) 함께 움직인 종목끼리
SECTOR_SUFFIX = "업종 동시 급등"


def display_label(label: str) -> str:
    """예전에 저장된 묶음 이름('동조', '업종 X 동반 급등')을 쉬운 말로."""
    if label == "동조":
        return "평소 함께 오르내리는 종목"
    if label.startswith("업종 ") and label.endswith(" 동반 급등"):
        return f"{label[3:-6]} 업종 동시 급등"
    return label


@dataclass
class ThemeCluster:
    members: dict[str, RankItem]
    label: str
    leader: RankItem

    def describe(self) -> str:
        rows = sorted(self.members.values(), key=lambda x: -(x.change_rate or 0))
        return ", ".join(f"{m.name} {m.change_rate:+.1%}" + ("(대장)" if m.code == self.leader.code else "") for m in rows)


@dataclass(frozen=True)
class ThemeHit:
    code: str
    name: str
    source: str      # '테마 특징주' | '테마 형성'
    reason: str


class ThemeTracker:
    def __init__(self, names: dict[str, str], sectors: dict[str, str], peers: dict[str, set[str]],
                 theme_map: dict[str, list[str]], theme_names: dict[str, str], config: Optional[ThemeConfig] = None) -> None:
        self.names = names
        self.sectors = sectors
        self.peers = peers
        self.theme_map = theme_map            # 코드 → 키움 테마코드들
        self.theme_names = theme_names        # 테마코드 → 이름
        self.config = config or ThemeConfig()
        self.recent_search: dict[str, datetime] = {}
        self.search_rank: dict[str, int] = {}          # 최근 조회 순위 (알림 표시용)
        self.featured: set[str] = set()
        self.clusters_alerted: list[set[str]] = []

    def _linked(self, a: RankItem, b: RankItem) -> Optional[str]:
        cfg = self.config
        if b.code in self.peers.get(a.code, ()):
            return PEER_LINK
        shared = set(self.theme_map.get(a.code, ())) & set(self.theme_map.get(b.code, ()))
        if shared:
            return self.theme_names.get(sorted(shared)[0], "키움 테마")
        sa, sb = self.sectors.get(a.code), self.sectors.get(b.code)
        if sa and sa == sb and (a.change_rate or 0) >= cfg.same_sector_change and (b.change_rate or 0) >= cfg.same_sector_change:
            return f"{sa} 업종 동시 급등"
        return None

    def clusters(self, movers: list[RankItem]) -> list[ThemeCluster]:
        """대장 중심 묶음: +10%↑ 급등주를 씨앗으로, 씨앗과 '직접' 연결된 급등주만 묶는다 (연쇄 연결 금지 → 거대 묶음 방지).

        씨앗은 등락률 순으로 처리하고, 이미 다른 묶음에 들어간 종목은 새 씨앗이 되지 않는다.
        """
        cfg = self.config
        pool = [m for m in movers if m.code in self.names and (m.change_rate or 0) >= cfg.member_change
                and (m.trade_value or 0) >= cfg.member_value]
        pool.sort(key=lambda m: -(m.change_rate or 0))
        assigned: set[str] = set()
        out = []
        for seed in pool:
            if seed.code in assigned or (seed.change_rate or 0) < cfg.lead_change:
                continue
            members = {seed.code: seed}
            reasons = []
            for m in pool:
                if m.code == seed.code or m.code in assigned:
                    continue
                why = self._linked(seed, m)
                if why:
                    members[m.code] = m
                    reasons.append(why)
            if len(members) < cfg.min_members:
                continue
            assigned |= set(members)
            leader = max(members.values(), key=lambda m: m.trade_value or 0)
            named = [w for w in reasons if w != PEER_LINK and not w.endswith(SECTOR_SUFFIX)]
            if named:                                     # 키움 테마 이름이 있으면 그것을
                label = max(set(named), key=named.count)
            elif any(w.endswith(SECTOR_SUFFIX) for w in reasons):
                label = next(w for w in reasons if w.endswith(SECTOR_SUFFIX))
            else:                                         # 과거에 함께 오르내린 종목끼리 → 대장 이름으로 부른다
                label = f"{leader.name} 관련주 · 평소 함께 오르내림"
            out.append(ThemeCluster(members, label, leader))
        return out

    def update(self, now: datetime, search_1m: list[RankItem], movers: list[RankItem]) -> tuple[list[ThemeHit], list[ThemeCluster]]:
        """반환: (새 🔥 테마 특징주, 새로/크게 바뀐 🧩 테마 묶음)"""
        cfg = self.config
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        for item in search_1m:
            if item.rank <= cfg.feature_search_rank:
                self.recent_search[item.code] = minute
                self.search_rank[item.code] = item.rank
        hits = []
        for m in movers:
            if m.code in self.featured or m.code not in self.names:
                continue
            seen = self.recent_search.get(m.code)
            if (seen and minute - seen <= timedelta(minutes=cfg.search_memory_minutes)
                    and (m.change_rate or 0) >= cfg.feature_change and (m.trade_value or 0) >= cfg.feature_value):
                self.featured.add(m.code)
                hits.append(ThemeHit(m.code, self.names[m.code], "테마 특징주",
                                     f"조회 {self.search_rank.get(m.code, '-')}위 · {m.change_rate:+.1%} · 대금 {m.trade_value / 1e8:,.0f}억"))
        new_clusters = []
        for c in self.clusters(movers):
            codes = set(c.members)
            # 같은 테마 판정: 대장 후보(씨앗)가 이미 알린 묶음에 있었거나, 절반 이상 겹치면 같은 테마 (씨앗만 바뀐 중복 알림 방지)
            seed = max(c.members.values(), key=lambda m: m.change_rate or 0).code
            prev = next((p for p in self.clusters_alerted
                         if seed in p or len(p & codes) * 2 >= min(len(p), len(codes))), None)
            if prev is None:
                self.clusters_alerted.append(set(codes))
                new_clusters.append(c)
            elif len(codes - prev) >= cfg.realert_new_members:
                prev |= codes
                new_clusters.append(c)
        return hits, new_clusters


def format_features(now: datetime, hits: list[ThemeHit]) -> str:
    return (f"🔥 테마 특징주 {now:%H:%M}\n" + "\n".join(f"· {h.name}({h.code}) {h.reason}" for h in hits)
            + "\n(진입 신호 아님 — 감시 목록에 추가, 매수 타점은 🎯)")


def format_clusters(now: datetime, clusters: list[ThemeCluster]) -> str:
    lines = [f"🧩 테마 형성 {now:%H:%M}"]
    for c in clusters:
        lines.append(f"· [{c.label}] 대장 {c.leader.name}({c.leader.code}) 대금 {c.leader.trade_value / 1e8:,.0f}억 — {c.describe()}")
    lines.append("(묶인 종목은 감시 목록에 추가, 매수 타점은 🎯)")
    return "\n".join(lines)
