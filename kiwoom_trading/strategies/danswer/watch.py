"""📒 [디앤서] 관심종목 2-2-2 + 🛡️ 하락장 헤지주 — 매일 고르고 저장하고 다음 날 결과로 분석한다 (주문 없음).

2026-10-26 사용자:
- "디앤서 종가 매매는 1) 섹터 2) 테마 3) 개별주 세 분류를 2종목씩 관심종목으로 매일 찾고 저장하고 분석함.
  그리고 하락장에는 헤지주를 공략함 → 하락장 헤지주를 리스팅하고 관심종목 관리. 가령 하락장에서 안랩이 종가까지 고가 부근을
  유지한다면 종가 매매 후 다음 날 갭 상승을 노릴 것."
- "키움 [0198] 실시간 종목 조회 순위를 당일 누적으로 20위까지 섹터·테마·개별로 나눠 종가 또는 다음 날 매매 대상 선별에 쓴다."
- "[0186] 거래대금 상위(통합) 창도 같이 관심 종목 추출에 쓴다."
책 근거: 『실전 시황 트레이딩』 3장 — 거래대금 상위와 실시간 조회 순위를 '당일 누적'으로 보고 1~10위의 관계로 강한 섹터·테마 파악,
2-2-2 법칙(섹터 2·테마 2·개별주 2, 79쪽), 삼전·하닉은 항상 관심 종목.

하루 흐름 (장중 스캐너 run_intraday 가 1분마다 tick):
- 14:30~14:35 📒 미리 보기: 종가 매매 후보 2-2-2 알림 (기록 없음)
- 15:15~15:19 🛡️ 하락일(코스피 전일 대비 < 0)이면 헤지주 목록 중 상승 & 고가 부근((현재가−저가)/(고가−저가) ≥ 0.8) 종목 알림.
  ⚠️ 1년 검증(스킬 danswer scripts/t_hedge*.py)에서 이 종가 매수 → 다음 날 09:00 은 0 안팎·손실이라 **알림·기록만** 한다.
- 15:35~15:50 📒 관심종목 2-2-2 기록 + 전 거래일 종목의 오늘 결과(시가 갭·고가·종가) + 분류별 누적 성적.
대상 = 조회 순위 당일 누적(ka00198 qry_tp 4) 20위 ∪ 거래대금 상위 통합(ka10032 stex_tp 3) 20위, 주식만(ETF·우선주 제외),
       삼전·하닉은 따로 '지수 관련'.
분류: 섹터 = 대상 안에 같은 네이버 업종(79개) 2종목↑ / 테마 = 남은 종목 중 같은 네이버 테마(약 260개) 2종목↑ (큰 묶음부터) / 나머지 = 개별.
      (네이버 업종·테마는 naver_groups.py 가 12:00 에 하루 한 번 받음. 없는 종목은 키움 테마·KRX 업종으로 대신)
고르기: 섹터·테마는 오른 종목이 가장 많은(같으면 등락 합이 큰) 묶음의 2종목, 개별은 오른 종목 2개 (둘 다 대상에 든 종목 먼저, 그다음 순위).
기록: screener.duckdb danswer_watch — 대상 전체(kind '대상', grp = 분류:묶음)와 고른 종목(섹터·테마·개별주·헤지주·지수 관련).
"""
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Optional

from kiwoom_trading.screener.market_data import RankItem
from kiwoom_trading.screener import naver_groups
from kiwoom_trading.screener.market_regime import fetch_index_now

PREVIEW_START, PREVIEW_END = time(14, 30), time(14, 35)
HEDGE_START, HEDGE_END = time(15, 15), time(15, 19)
WATCH_START, WATCH_END = time(15, 35), time(15, 50)
TOP_N = 20
NAVER_AT = time(12, 0)
NEAR_HIGH = 0.8
LIMIT_UP = 0.295
INDEX_CODES = {"005930": "삼성전자", "000660": "SK하이닉스"}
EMOJI = {"섹터": "🏭", "테마": "🧩", "개별": "🎯"}
REVIEW_KINDS = ("섹터", "테마", "개별주", "헤지주", "헤지주 알림", "지수 관련", "대상")

# 🛡️ 하락장 헤지주 목록 (2026-10-26 사용자 '보안·방산·유가 관련 등' + 기사 조사: 중동전쟁 급락 때 방산·정유·해운 급등,
# 은행·보험·통신·필수소비재가 피난처 — fnnews 2026-03-04, 다음 2026-03-04, 아시아경제 2026-04-14). 고치려면 스킬 danswer 10장도 같이.
HEDGE = {
    "보안": ["053800", "263860", "042510", "136540", "208350", "150900",       # 안랩·지니언스·라온시큐어·윈스테크넷·지란지교시큐리티·파수AI
             "411080", "203650", "356680", "434480", "067920"],                # 샌즈랩·드림시큐리티·엑스게이트·모니터랩·이글루 (2026-10-26 사용자 추가)
    "방산": ["079550", "012450", "064350", "272210", "047810", "103140", "003570", "010820", "065450"],   # LIG넥스원·한화에어로·현대로템·한화시스템·KAI·풍산·SNT다이내믹스·퍼스텍·빅텍
    "유가": ["010950", "096770", "024060", "004090", "000440", "014530"],          # S-Oil·SK이노베이션·흥구석유·한국석유·중앙에너비스·극동유화
    "해운": ["011200", "028670", "005880"],                                         # HMM·팬오션·대한해운
    "금융": ["105560", "055550", "086790", "316140", "032830"],                     # KB금융·신한지주·하나금융·우리금융·삼성생명
    "통신": ["017670", "030200", "032640"],                                         # SKT·KT·LG유플러스
    "전력·가스": ["015760", "036460", "052690"],                                    # 한국전력·한국가스공사·한전기술
    "음식료·담배": ["033780", "271560", "004370", "003230", "097950", "280360"],    # KT&G·오리온·농심·삼양식품·CJ제일제당·롯데웰푸드
    "금": ["010130"],                                                               # 고려아연
}
# 네이버 테마 중 헤지 테마 — 이 구성 종목이 그날 대금 100위 안이면 헤지주로 같이 본다
HEDGE_THEMES = {"보안주(정보)": "보안", "보안주(물리)": "보안", "방위산업/전쟁 및 테러": "방산", "정유": "유가", "주유소": "유가",
                "윤활유": "유가", "해운": "해운", "귀금속(금/은)": "금", "은행": "금융", "통신": "통신"}
HEDGE_GROUP = {c: g for g, cs in HEDGE.items() for c in cs}

# 섹터(산업) = 키움 테마 중 산업형(앞부분이 아래 이름)과 좁은 KRX 업종. 나머지 키움 테마(로봇_지능형·우주항공·원자력·방위산업 …)는 '테마'.
INDUSTRY_PREFIX = {
    "반도체": "반도체", "2차전지": "2차전지", "AMOLED": "디스플레이", "LCD": "디스플레이", "LED": "디스플레이", "PCB(인쇄회로기판)": "전자부품",
    "FPCB(연성회로기판)": "전자부품", "휴대폰": "휴대폰 부품", "조선": "조선", "자동차": "자동차", "타이어": "자동차", "바이오": "바이오",
    "신약개발/기술수출": "바이오", "의료기기": "의료기기", "은행": "은행", "증권": "증권", "보험": "보험", "창투": "증권", "건설": "건설",
    "시멘트": "건설", "기계": "기계", "게임": "게임", "컨텐츠": "엔터·컨텐츠", "화장품": "화장품", "운송": "운송", "제지": "제지",
    "합성수지": "화학", "합성고무": "화학", "합성섬유": "화학", "엔지니어링 플라스틱": "화학", "강관": "철강", "합금철": "철강",
    "비철금속주": "비철금속", "희소금속": "비철금속", "통신장비": "통신장비", "네트워크/광통신": "통신장비", "태양광": "태양광",
    "풍력": "풍력", "백화점": "유통", "홈쇼핑": "유통", "식자재유통": "유통", "라면": "음식료", "제과스낵": "음식료", "주류": "음식료",
    "유가공": "음식료", "빙과": "음식료", "육계": "음식료", "곡물가공품": "음식료", "수산물/수산가공품": "음식료", "배합사료": "음식료",
    "도시가스": "가스", "LPG(액화석유가스)": "가스", "부탄가스": "가스", "의복": "의류", "가구": "가구",
}
# KRX 업종 중 좁은 것만 섹터로 (전기/전자·기계/장비·IT 서비스·일반서비스·화학·유통 같은 넓은 업종은 섹터로 안 묶음)
KRX_SECTOR = {"제약": "바이오", "의료/정밀기기": "의료기기", "운송장비/부품": "자동차", "은행": "은행", "증권": "증권", "보험": "보험",
              "건설": "건설", "음식료/담배": "음식료", "섬유/의류": "의류", "통신": "통신", "전기/가스": "전력·가스", "운송/창고": "운송",
              "비금속": "건설", "종이/목재": "제지", "오락/문화": "엔터·컨텐츠", "부동산": "부동산"}


# 네이버 테마 중 묶음 뜻이 약한 것 (상장 시기·지수 편입·대표주 모음)
SKIP_THEMES = ("신규상장", "SPAC", "밸류업", "지주사", "대표주", "S7(", "코리아 밸류업")


def industry_of(theme_name: str) -> Optional[str]:
    if theme_name in INDUSTRY_PREFIX:
        return INDUSTRY_PREFIX[theme_name]
    head = theme_name.split("_")[0]
    return INDUSTRY_PREFIX.get(head)


SCHEMA = """
CREATE TABLE IF NOT EXISTS danswer_watch (   -- 📒 디앤서 관심종목 2-2-2·🛡️ 헤지주 (주문 없음, 다음 날 결과로 분석)
    date DATE, kind VARCHAR, grp VARCHAR, slot INTEGER, code VARCHAR, name VARCHAR,
    chg DOUBLE, value_rank INTEGER, price DOUBLE, pos DOUBLE, note VARCHAR,
    next_gap DOUBLE, next_high DOUBLE, next_close DOUBLE,
    PRIMARY KEY (date, kind, code)
)"""


def close_pos(price: float, high: float, low: float) -> Optional[float]:
    return (price - low) / (high - low) if high > low else None


@dataclass
class Cand:
    code: str
    name: str
    chg: float
    price: float
    search: Optional[int]      # 조회 순위 당일 누적
    value: Optional[int]       # 거래대금 상위(통합) 순위 (주식·ETF 섞인 원래 순위)

    @property
    def order(self) -> tuple:
        both = self.search is not None and self.value is not None
        return (not both, min(x for x in (self.search, self.value) if x is not None))

    @property
    def where(self) -> str:
        return " · ".join(s for s in (f"조회 {self.search}위" if self.search else "", f"대금 {self.value}위" if self.value else "") if s)


class DanswerWatch:
    def __init__(self, store, market, client, today: date, names: dict[str, str], sectors: dict[str, str], regime=None,
                 notify: Optional[Callable[[str], object]] = None, theme_map: Optional[dict[str, list[str]]] = None,
                 theme_names: Optional[dict[str, str]] = None) -> None:
        self.store, self.market, self.client, self.today = store, market, client, today
        self.names, self.sectors, self.regime = names, sectors, regime
        self.theme_map, self.theme_names = theme_map or {}, theme_names or {}
        self.notify = notify or (lambda text: None)
        store.conn.execute(SCHEMA)
        kinds = {k for (k,) in store.conn.execute("SELECT DISTINCT kind FROM danswer_watch WHERE date = ?", [today]).fetchall()}
        self.preview_done = False
        self.hedge_done = "헤지주 알림" in kinds or "헤지주 없음" in kinds
        self.watch_done = bool(kinds - {"헤지주 알림", "헤지주 없음"})
        self.down: Optional[bool] = None
        self.naver_ind: dict[str, str] = {}          # 종목 → 네이버 업종 (섹터)
        self.naver_th: dict[str, list[str]] = {}     # 종목 → 네이버 테마
        self.naver_at: Optional[date] = None

    # ------------------------------------------------------------------ 하락일 판단·헤지주
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

    def hedge_universe(self, value_top: Optional[list[RankItem]] = None) -> dict[str, str]:
        """고정 목록 + 네이버 헤지 테마 종목 중 그날 대금 100위 안 & 상승 → {코드: 묶음}."""
        out = dict(HEDGE_GROUP)
        for i in sorted(value_top or [], key=lambda i: i.rank)[:100]:
            if i.code in out or (i.change_rate or 0) <= 0:
                continue
            g = next((HEDGE_THEMES[t] for t in self.naver_th.get(i.code, []) if t in HEDGE_THEMES), None)
            if g:
                out[i.code] = g
        return out

    def _hedge_scan(self, value_top: Optional[list[RankItem]] = None) -> list[tuple]:
        """헤지주 [(code, name, group, chg, price, pos)] — 상승 & 고가 부근 & 상한가 아님."""
        out = []
        for code, grp in self.hedge_universe(value_top).items():
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

    def _naver(self) -> None:
        if self.naver_at != self.today:
            self.naver_at = self.today
            try:
                self.naver_ind, self.naver_th = naver_groups.load(self.today)
                logging.info("📒 네이버 업종 %s종목·테마 %s종목", len(self.naver_ind), len(self.naver_th))
            except Exception:
                logging.exception("📒 네이버 업종·테마 불러오기 실패 — 키움 테마·KRX 업종으로")

    def tick(self, now: datetime, value_top: list[RankItem], search_day: Optional[list[RankItem]] = None) -> None:
        t = now.time()
        if t >= NAVER_AT:
            self._naver()        # 점심(12:00) 때 하루 한 번 받음 (1~2분)
        search_day = search_day or []
        if not self.preview_done and PREVIEW_START <= t <= PREVIEW_END and len(search_day) >= TOP_N:
            self.preview_done = True
            self._preview(search_day)
        if not self.hedge_done and HEDGE_START <= t <= HEDGE_END and len(value_top) >= 50:
            self.hedge_done = True
            self._hedge_alert(value_top)
        if not self.watch_done and WATCH_START <= t <= WATCH_END and len(value_top) >= 50 and len(search_day) >= TOP_N:
            self.watch_done = True
            self._watch(value_top, search_day)

    def _hedge_alert(self, value_top: list[RankItem]) -> None:
        self.down, why = self._is_down(value_top)
        if not self.down:
            logging.info("🛡️ 헤지주: 하락일 아님 (%s)", why)
            self._save([(self.today, "헤지주 없음", why, 0, "-", "-", None, None, None, None, "하락일 아님")])
            return
        self._naver()
        hits = self._hedge_scan(value_top)
        rank = {i.code: i.rank for i in value_top}
        self._save([(self.today, "헤지주 알림", g, n + 1, c, nm, ch, rank.get(c), p, pos, why)
                    for n, (c, nm, g, ch, p, pos) in enumerate(hits)] or
                   [(self.today, "헤지주 없음", why, 0, "-", "-", None, None, None, None, "고가 부근 상승 헤지주 없음")])
        lines = [f"[디앤서] 🛡️ 하락장 헤지주 15:15 ({why}) — 알림만, 매수 안 함",
                 "상승 & 고가 부근(80%↑) 유지: " + (f"{len(hits)}종목" if hits else "없음")]
        for c, nm, g, ch, p, pos in hits:
            lines.append(f"  {nm}({c}) [{g}] {ch:+.1%} · 고가 부근 {pos:.0%} · {p:,.0f}")
        lines.append("⚠️ 1년 검증: 헤지주라서 오르지는 않았다 (강한 하락장 판정일 헤지주 고가 부근 종가 매수 → 다음 날 09:00 −0.25%). "
                     "대금 30위·시장 대비 +3%p 종목(④)이 +0.90%, 그중 고가 부근 +1.48%. 다음 날 결과는 15:35 에 기록")
        self.notify("\n".join(lines))

    # ------------------------------------------------------------------ 대상 모으기·분류
    def candidates(self, search_day: list[RankItem]) -> list[Cand]:
        """조회 순위 당일 누적 20위 ∪ 거래대금 상위(통합) 20위 — 주식만, 삼전·하닉 제외."""
        def ok(i):
            return i.code in self.names and i.code[-1] not in "579K" and i.change_rate is not None and i.code not in INDEX_CODES
        out: dict[str, Cand] = {}
        for i in [x for x in sorted(search_day, key=lambda x: x.rank) if ok(x)][:TOP_N]:
            out[i.code] = Cand(i.code, i.name, i.change_rate, float(i.price or 0), i.rank, None)
        try:
            vt = self.market.value_rank(pages=1, stex_tp="3")      # [0186] 거래대금 상위 통합
        except Exception:
            logging.exception("📒 거래대금 상위(통합) 조회 실패 — 조회 순위만 씀")
            vt = []
        for i in [x for x in sorted(vt, key=lambda x: x.rank) if ok(x)][:TOP_N]:
            if i.code in out:
                out[i.code].value = i.rank
            else:
                out[i.code] = Cand(i.code, i.name, i.change_rate, float(i.price or 0), None, i.rank)
        return sorted(out.values(), key=lambda c: c.order)

    def industry(self, code: str) -> Optional[str]:
        """섹터 = 네이버 업종(79개). 없으면 키움 산업형 테마, 그것도 없으면 좁은 KRX 업종."""
        if code in self.naver_ind:
            return self.naver_ind[code]
        for t in self.theme_map.get(code, []):
            ind = industry_of(self.theme_names.get(t, ""))
            if ind:
                return ind
        return KRX_SECTOR.get(self.sectors.get(code, ""))

    def themes(self, code: str) -> list[str]:
        """테마 = 네이버 테마(묶음 뜻이 없는 것 제외). 없으면 키움 테마 중 산업형이 아닌 것."""
        if code in self.naver_th:
            return [t for t in self.naver_th[code] if not any(x in t for x in SKIP_THEMES)]
        return [self.theme_names.get(t, t) for t in self.theme_map.get(code, []) if not industry_of(self.theme_names.get(t, ""))]

    def classify(self, cands: list[Cand]) -> list[tuple[Cand, str, str]]:
        """[(종목, 분류, 묶음)] — 업종(섹터)·테마 묶음 중 남은 종목이 가장 많이 모인 것부터 차례로 붙인다(2종목↑).
        같은 크기면 섹터 먼저, 그다음 등락 합이 큰 쪽. 어디에도 2종목↑ 로 못 묶이면 개별."""
        rest, out = list(cands), []
        while True:
            groups = defaultdict(list)
            for c in rest:
                ind = self.industry(c.code)
                if ind:
                    groups[("섹터", ind)].append(c)
                for t in self.themes(c.code):
                    groups[("테마", t)].append(c)
            if not groups:
                break
            (kind, g), items = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0][0] == "섹터", sum(c.chg for c in kv[1])))
            if len(items) < 2:
                break
            out += [(c, kind, g) for c in items]
            rest = [c for c in rest if c not in items]
        out += [(c, "개별", "") for c in rest]
        return sorted(out, key=lambda x: x[0].order)

    @staticmethod
    def picks(cls: list[tuple[Cand, str, str]]) -> dict[str, tuple[str, list[Cand]]]:
        """분류마다 가장 강한 묶음(오른 종목 수, 같으면 등락 합)의 2종목 — 오른 종목 먼저, 그다음 둘 다 든 종목·순위."""
        out = {}
        for kind in ("섹터", "테마"):
            groups = defaultdict(list)
            for c, k, g in cls:
                if k == kind:
                    groups[g].append(c)
            if groups:
                g, items = max(groups.items(), key=lambda kv: (sum(c.chg > 0 for c in kv[1]), sum(c.chg for c in kv[1])))
                out[kind] = (g, sorted(items, key=lambda c: (c.chg <= 0, c.order))[:2])
            else:
                out[kind] = ("", [])
        out["개별"] = ("", [c for c, k, g in cls if k == "개별" and c.chg > 0][:2])
        return out

    def _pos(self, code: str) -> Optional[float]:
        try:
            q = self.market.quote(code, integrated=False)
            return close_pos(q.price, q.high, q.low) if q else None
        except Exception:
            return None

    def _pick_lines(self, picks, rows: Optional[list] = None) -> list[str]:
        lines = []
        for kind, (g, items) in picks.items():
            lines.append(f"{EMOJI[kind]} {kind} 2" + (f" — {g}" if g else "") + ("" if items else " — 없음"))
            for n, c in enumerate(items):
                pos = self._pos(c.code)
                lines.append(f"  {c.name}({c.code}) {c.chg:+.1%} · {c.where}" + (f" · 고가 부근 {pos:.0%}" if pos is not None else ""))
                if rows is not None and c.price:
                    rows.append((self.today, "개별주" if kind == "개별" else kind, g, n + 1, c.code, c.name, c.chg, c.value, c.price, pos, c.where))
        return lines

    @staticmethod
    def _detail(cls) -> str:
        groups = defaultdict(list)
        for c, k, g in cls:
            groups[f"{k}:{g}" if g else k].append(f"{c.name} {c.chg:+.0%}")
        return "📋 대상 분류: " + " / ".join(f"{g} — {', '.join(v)}" for g, v in groups.items())

    def _preview(self, search_day: list[RankItem]) -> None:
        """14:30 종가 매매 후보 미리 보기 — 기록 없이 알림만."""
        cls = self.classify(self.candidates(search_day))
        if not cls:
            return
        head = "[디앤서] 📒 14:30 관심종목 미리 보기 (조회 순위 당일 누적 20위 + 거래대금 상위 20위) — 종가 매매 후보, 알림만"
        self.notify("\n".join([head] + self._pick_lines(self.picks(cls)) + [self._detail(cls)]))

    def _watch(self, value_top: list[RankItem], search_day: list[RankItem]) -> None:
        cls = self.classify(self.candidates(search_day))
        review = self._review()
        rows = [(self.today, "대상", f"{k}:{g}" if g else k, n + 1, c.code, c.name, c.chg, c.value, c.price, None, c.where)
                for n, (c, k, g) in enumerate(cls) if c.price]      # 대상 전체 (다음 날 결과로 분류별 성적 분석)
        lines = self._pick_lines(self.picks(cls), rows)
        if self.down is None:
            self.down, _ = self._is_down(value_top)
        vrank = {i.code: i.rank for i in value_top}
        if self.down:
            hs = self._hedge_scan(value_top)[:2]
            lines.append("🛡️ 헤지주 2 (하락일)" + ("" if hs else " — 고가 부근 상승 헤지주 없음"))
            for n, (c, nm, g, ch, p, pos) in enumerate(hs):
                rows.append((self.today, "헤지주", g, n + 1, c, nm, ch, vrank.get(c), p, pos, None))
                lines.append(f"  {nm}({c}) [{g}] {ch:+.1%} · 고가 부근 {pos:.0%}")
        idx = []
        for c, nm in INDEX_CODES.items():
            i = next((x for x in list(value_top) + list(search_day) if x.code == c and x.change_rate is not None and x.price), None)
            if i:
                rows.append((self.today, "지수 관련", "", 0, c, nm, i.change_rate, vrank.get(c), float(i.price), None,
                             "★ +3%↑" if i.change_rate >= 0.03 else None))
                idx.append(f"{'★' if i.change_rate >= 0.03 else ''}{nm} {i.change_rate:+.1%}")
        self._save(rows)
        cnt = defaultdict(int)
        for _, k, _ in cls:
            cnt[k] += 1
        head = (f"[디앤서] 📒 관심종목 2-2-2 {self.today:%m-%d} 마감 — 조회 순위 당일 누적 20위 + 거래대금 상위 20위 {len(cls)}종목 "
                f"(섹터 {cnt['섹터']} · 테마 {cnt['테마']} · 개별 {cnt['개별']}), 기록만")
        self.notify("\n".join([head] + lines + (["📌 " + " · ".join(idx)] if idx else []) + [self._detail(cls)] + review))
        logging.info("📒 디앤서 관심종목 %s줄 저장", len(rows))

    # ------------------------------------------------------------------ 분석
    def _review(self) -> list[str]:
        """전 거래일 관심종목의 오늘 결과를 채우고, 분류별 누적 성적 줄을 돌려준다."""
        conn = self.store.conn
        ph = ",".join("?" * len(REVIEW_KINDS))
        prev = conn.execute(f"SELECT max(date) FROM danswer_watch WHERE date < ? AND kind IN ({ph})", [self.today, *REVIEW_KINDS]).fetchone()[0]
        out = []
        if prev:
            todo = conn.execute(f"SELECT kind, code, name, price FROM danswer_watch WHERE date = ? AND next_close IS NULL AND kind IN ({ph})",
                                [prev, *REVIEW_KINDS]).fetchall()
            got, seen = [], {}
            for kind, code, name, price in todo:
                if code not in seen:
                    try:
                        seen[code] = self.market.quote(code, integrated=False)
                    except Exception:
                        seen[code] = None
                q = seen[code]
                if not q or not price:
                    continue
                gap, hi, cl = q.open / price - 1, q.high / price - 1, q.price / price - 1
                conn.execute("UPDATE danswer_watch SET next_gap = ?, next_high = ?, next_close = ? WHERE date = ? AND kind = ? AND code = ?",
                             [gap, hi, cl, prev, kind, code])
                if kind != "대상":
                    got.append(f"{name} 갭 {gap:+.1%} 고가 {hi:+.1%} 종가 {cl:+.1%}")
            if got:
                out.append(f"\n📊 어제({prev:%m-%d}) 관심종목 오늘: " + " / ".join(dict.fromkeys(got)))
        stats = conn.execute("""SELECT CASE WHEN kind = '대상' THEN '대상·' || split_part(grp, ':', 1) ELSE kind END AS k, count(*),
                                       avg(next_gap), avg(next_high), avg(next_close), avg(CASE WHEN next_gap > 0 THEN 1.0 ELSE 0 END)
                                FROM danswer_watch WHERE next_close IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall()
        if stats:
            out.append("📈 누적 (다음 날, 전일 15:35 가격 대비): " + " / ".join(
                f"{k} {n}건 갭 {g:+.2%}(+ {w:.0%}) 고가 {h:+.2%} 종가 {c:+.2%}" for k, n, g, h, c, w in stats))
        return out
