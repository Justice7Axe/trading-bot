"""🧭 장 초 급등 종목 — 09:10·09:30 에 장 초 급등 종목을 주가·대금·수급 기준으로 알리고, 뉴스 공통 단어는 참고로 붙인다.

사용자 원칙(2026-10-23): 뉴스 매매는 한계가 있다. 뉴스는 보조, 주된 판단은 주가·차트·외국인/기관 수급.
- 주도 후보 = 대금 50위 안 · 장 초(첫 스냅샷)보다 위 · 외국인 또는 기관 장중 잠정 순매수 (09:10 엔 잠정치가 없을 수 있음)
- 뉴스 공통 단어 묶음은 맨 아래 참고로만 (처음 버전은 뉴스로 묶었다).


계기 (10-22 데이터센터 테마 역추적, 메모리 theme-datacenter-1022):
- 대장(삼성E&A·엘리스)은 기존 🏁 조기 주도주·🚀 대금 가속이 09:02~09:10 에 잡았다.
- 그러나 테마가 뉴스로만 이어져 있어(키움 테마·평소 함께 오르내림·업종 모두 다름) 🧩 가 따로따로 알렸다.
- 키움 REST 에 뉴스 API 가 없다 → 네이버 증권 종목 뉴스 제목(m.stock.naver.com, 사용자 승인 2026-10-23)을 쓴다.

모으는 종목:
1. 이어질 후보 (전날 기준): 전날 +7%↑ 또는 5일 +20%↑ — 오늘 +3%↑ 일 때
   (10-22: 삼성E&A 전날 +11%, 엘리스 +30%(신규 상장), 비나텍 +7% — 대금 배수·순위 조건을 걸면 셋 다 빠졌다)
2. 지금 KRX 대금 상위 200 중 +7%↑ 주식
3. 오늘 🏁·🚀·🔥·🌅 알림 종목 중 지금 +3%↑
묶기: 전 거래일 15:30 이후 뉴스 제목(네이버 2페이지까지)의 단어(2글자↑, 흔한 말·종목명 제외)를 세어 2종목↑ 이 함께 쓴 단어로 묶는다(많이 겹치는 단어부터).
대장 = 묶음 안 누적 대금 1위. 매수 신호가 아니다 (포착 뒤 따라 사기는 1년·실전 모두 손실).
⚠️ 10-22 재현: 09:30 전 뉴스 제목에 '데이터센터'가 있던 건 삼성E&A 1건뿐(비나텍·유니퀘스트·엘리스는 뉴스 없음) → 그날은 묶지 못했을 것.
   재료가 종목 뉴스 제목에 안 나오는 테마는 놓친다. 사용자 '주도섹터' 캡처와 대조해 쓸모를 판단한다(surge_groups 테이블).
"""
import html
import logging
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

import duckdb
import requests

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH
from kiwoom_trading.screener.market_data import RankItem
from kiwoom_trading.screener.store import ScreenerStore

CHECKS = (time(9, 10), time(9, 30))   # 09:30 은 외국인 잠정치(09:20~27 첫 값)가 들어온 뒤
WINDOW_MIN = 5
MIN_SURGE = 0.07
MIN_CARRY_TODAY = 0.03
NEWS_URL = "https://m.stock.naver.com/api/news/stock/{code}?pageSize=20&page={page}"
NEWS_PAGES = 2
STOP = set("""주가 주식 증시 코스피 코스닥 상승 하락 급등 급락 강세 약세 특징주 종목 오늘 장중 마감 출발 개장 시황 투자 투자자
외국인 기관 개인 순매수 순매도 목표가 상향 하향 전망 실적 영업익 매출 분기 영업이익 순이익 기업 회사 사업 시장 글로벌 국내 해외
대표 회장 사장 신규 확대 계약 공시 발표 공개 관련 관련주 수혜 수혜주 테마 테마주 이유 정체 소식 기대 기대감 우려 효과 반등 거래
거래량 대금 시가총액 신고가 상한가 하한가 억원 조원 만원 달러 연속 하루 이틀 이번 올해 내년 지난해 최대 최고 최근 지난 뉴스 단독
리포트 애프터마켓 프리마켓 서울데이터랩 마감시황 증권 증권사 은행 그룹 계열사 주주 배당 공급 수주 체결 규모 기록 돌파 진입 달성
개장시황 장초반 출발한 뉴욕증시 미국 미국發 훈풍 반전 분위기 차익실현 매물 공방 낙폭 내림세 오름세 약보합 강보합 회복 붕괴 지수
속보 종목 호실적 자사주 취득 쑥""".split())


def _num(x) -> float:
    return float(x or 0)


def carry_candidates(day: date, db_path: str = DEFAULT_DB_PATH) -> dict[str, str]:
    """day 전 거래일 기준 '이어질 테마' 후보: 코드 → 사유."""
    conn = duckdb.connect(db_path, read_only=True)
    try:
        rows = conn.execute("""
            WITH r AS (SELECT o.code, o.date, o.close, o.value,
                              lag(o.close) OVER k pc, lag(o.close, 5) OVER k pc5,
                              avg(o.value) OVER (k ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) av,
                              rank() OVER (PARTITION BY o.date ORDER BY o.value DESC) vr
                       FROM daily_ohlcv o JOIN stocks s USING (code) WHERE o.date < ? AND o.date >= ?::DATE - 60
                       WINDOW k AS (PARTITION BY o.code ORDER BY o.date))
            SELECT code, close / pc - 1, value / nullif(av, 0), vr, close / pc5 - 1 FROM r
            WHERE date = (SELECT max(date) FROM daily_ohlcv WHERE date < ?)""", [day, day, day]).fetchall()
    finally:
        conn.close()
    out = {}
    for code, chg, vx, vr, r5 in rows:
        if chg is not None and chg >= 0.07:
            out[code] = f"전날 {chg:+.0%}" + (f"·대금 {vx:.1f}배" if vx else "")
        elif r5 is not None and r5 >= 0.20:
            out[code] = f"5일 {r5:+.0%}"
    return out


def news_titles(code: str, since: datetime, session: Optional[requests.Session] = None) -> list[str]:
    s = session or requests
    items = []
    for page in range(1, NEWS_PAGES + 1):
        try:
            js = s.get(NEWS_URL.format(code=code, page=page), headers={"User-Agent": "Mozilla/5.0"}, timeout=8).json()
        except Exception as exc:
            logging.warning("뉴스 조회 실패 %s: %s", code, exc)
            break
        got = [i for blk in js for i in blk.get("items", [])] if isinstance(js, list) else []
        items += got
        if len(got) < 20:
            break
    out = []
    for it in items:
        try:
            ts = datetime.strptime(str(it.get("datetime"))[:12], "%Y%m%d%H%M")
        except ValueError:
            continue
        if ts >= since:
            out.append(html.unescape(str(it.get("title") or "")))
    return out


def keywords(titles: list[str], own_names: set[str]) -> set[str]:
    words = set()
    for t in titles:
        t = re.sub(r"\[[^\]]*\]", " ", t)
        for w in re.findall(r"[A-Za-z][A-Za-z0-9]+|[가-힣]{2,}", t):
            w = w.upper() if w.isascii() else w
            if not w.isascii() and len(w) >= 3 and w[-1] in "와과의에가이은는을를로도만":
                w = w[:-1]                       # 엔비디아와 → 엔비디아
            if not w.isascii() and (w.endswith(("한", "친", "된", "던", "하는", "하며", "해", "했다", "한다")) and len(w) <= 3):
                continue                         # 펼친·확대한 같은 꾸미는 말
            if len(w) < 2 or w in STOP or any(w in n or n in w for n in own_names):
                continue
            words.add(w)
    return words


def group(stocks: dict[str, dict], words: dict[str, set[str]]) -> list[tuple[str, list[str]]]:
    """공통 단어로 묶기: 많은 종목이 함께 쓴 단어부터, 이미 묶인 종목은 다시 묶지 않는다."""
    by_word = defaultdict(set)
    for code, ws in words.items():
        for w in ws:
            by_word[w].add(code)
    used, groups = set(), []
    for w, codes in sorted(by_word.items(), key=lambda x: (-len(x[1]), -sum(_num(stocks[c]["value"]) for c in x[1]))):
        free = [c for c in codes if c not in used]
        if len(free) < 2:
            continue
        # 같은 묶음에 다른 공통 단어도 붙여 이름을 풍부하게
        extra = [w2 for w2, c2 in by_word.items() if w2 != w and set(free) <= c2][:2]
        groups.append((" · ".join([w] + extra), sorted(free, key=lambda c: -_num(stocks[c]["value"]))))
        used.update(free)
    return groups


class SurgeGroups:
    def __init__(self, store: ScreenerStore, today: date, names: dict[str, str], notify: Optional[Callable[[str], None]] = None,
                 carry: Optional[dict[str, str]] = None) -> None:
        self.store = store
        self.today = today
        self.names = names
        self.notify = notify or (lambda text: None)
        self.carry = carry if carry is not None else carry_candidates(today)
        self.done: set[time] = set()
        self.session = requests.Session()
        self.store.conn.execute("""CREATE TABLE IF NOT EXISTS surge_groups (date DATE, ts TIMESTAMP, label VARCHAR, code VARCHAR, name VARCHAR,
                                   change_rate DOUBLE, value_rank INTEGER, trade_value BIGINT, carry VARCHAR, alerts VARCHAR)""")

    def step(self, now: datetime, value_top: list[RankItem]) -> Optional[str]:
        mins = now.hour * 60 + now.minute
        due = [c for c in CHECKS if c not in self.done and c.hour * 60 + c.minute <= mins < c.hour * 60 + c.minute + WINDOW_MIN]
        if not due:
            return None
        self.done.update(due)
        alerted = defaultdict(list)
        for ts, code, src in self.store.conn.execute("SELECT ts, code, source FROM early_alerts WHERE date = ? AND ts <= ? ORDER BY ts",
                                                     [self.today, now.replace(tzinfo=None)]).fetchall():
            alerted[code].append(f"{src} {ts:%H:%M}")
        stocks = {}
        for it in value_top:
            if it.code not in self.names or it.change_rate is None:
                continue
            take = (it.change_rate >= MIN_SURGE or (it.code in self.carry and it.change_rate >= MIN_CARRY_TODAY)
                    or (it.code in alerted and it.change_rate >= MIN_CARRY_TODAY))
            if take:
                stocks[it.code] = dict(name=it.name, chg=it.change_rate, rank=it.rank, value=it.trade_value or 0)
        if not stocks:
            return None
        prev_close_time = datetime.combine(self.today - timedelta(days=4), time(15, 30))
        last = self.store.conn.execute("SELECT max(date) FROM rank_snapshots WHERE date < ?", [self.today]).fetchone()[0]
        if last:
            prev_close_time = datetime.combine(last, time(15, 30))
        own = {v["name"] for v in stocks.values()}
        words = {c: keywords(news_titles(c, prev_close_time, self.session), own) for c in stocks}
        groups = group(stocks, words)
        grouped = {c for _, cs in groups for c in cs}
        label_of = {c: lbl for lbl, cs in groups for c in cs}
        ts = now.replace(tzinfo=None)
        for c, v in stocks.items():
            self.store.conn.execute("INSERT INTO surge_groups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    [self.today, ts, label_of.get(c, ""), c, v["name"], v["chg"], v["rank"], v["value"],
                                     self.carry.get(c, ""), ", ".join(alerted.get(c, []))])

        # 주된 판단 = 주가·대금·수급 (사용자 2026-10-23: 뉴스는 보조). 장 초 대비는 그날 첫 순위 스냅샷 가격 기준(근사).
        first_px = dict(self.store.conn.execute(
            """SELECT code, arg_min(price, ts) FROM rank_snapshots WHERE date = ? AND source = 'value_krx' AND ts::TIME >= TIME '09:00'
               AND code IN (SELECT unnest(?)) GROUP BY code""", [self.today, list(stocks)]).fetchall())
        price_now = {it.code: it.price for it in value_top}
        flow: dict = {}
        for inv in ("foreign", "institution"):
            snap = self.store.conn.execute("SELECT max(ts) FROM investor_intraday WHERE date = ? AND investor = ? AND ts <= ?",
                                           [self.today, inv, ts]).fetchone()[0]
            if snap:
                for code, amt in self.store.conn.execute("SELECT code, net_amount FROM investor_intraday WHERE ts = ? AND investor = ?",
                                                         [snap, inv]).fetchall():
                    flow.setdefault(code, {})[inv] = amt

        def facts(c: str) -> dict:
            fp, pn = first_px.get(c), price_now.get(c)
            f = flow.get(c, {})
            return dict(from_open=(pn / fp - 1) if fp and pn else None, foreign=f.get("foreign"), inst=f.get("institution"))

        def line(c: str) -> str:
            v, f = stocks[c], facts(c)
            tags = [f"대금 {v['rank']}위 {v['value'] / 1e8:,.0f}억"]
            if f["from_open"] is not None:
                tags.append(f"장 초 대비 {f['from_open']:+.1%}")
            fl = [f"{n} {a / 1e8:+,.0f}억" for n, a in (("외국인", f["foreign"]), ("기관", f["inst"])) if a]
            if fl:
                tags.append("잠정 " + " ".join(fl))
            if c in self.carry:
                tags.append("이어짐: " + self.carry[c])
            if alerted.get(c):
                tags.append(alerted[c][0])
            return f"  {v['name']} {v['chg']:+.1%} · " + " · ".join(tags)

        def leader(c: str) -> bool:
            f = facts(c)
            up = f["from_open"] is None or f["from_open"] > 0
            if not flow:
                return stocks[c]["rank"] <= 50 and up
            return stocks[c]["rank"] <= 50 and up and ((f["foreign"] or 0) > 0 or (f["inst"] or 0) > 0)

        order = sorted(stocks, key=lambda c: -_num(stocks[c]["value"]))
        lead = [c for c in order if leader(c)]
        lines = [f"🧭 장 초 급등 종목 {now:%H:%M} — 주가·대금·수급 기준 (뉴스는 참고, 매수 신호 아님)"]
        lines.append("\n[주도 후보: 대금 50위 안 · 장 초보다 위 · 외국인/기관 잠정 순매수]" if flow else
                     "\n[주도 후보: 대금 50위 안 · 장 초보다 위] (수급 잠정치 아직 없음)")
        lines += [line(c) for c in lead] or ["  없음"]
        rest = [c for c in order if c not in lead]
        if rest:
            lines.append("\n[그 밖 급등]")
            lines += [line(c) for c in rest[:12]]
        if groups:
            lines.append("\n참고 — 뉴스 제목 공통 단어: " + " / ".join(f"{lbl}({'·'.join(stocks[c]['name'] for c in cs)})" for lbl, cs in groups))
        text = "\n".join(lines)
        logging.info("급등 묶음 %s: %s종목, 묶음 %s", f"{now:%H:%M}", len(stocks), "; ".join(f"{l}: {len(cs)}" for l, cs in groups) or "없음")
        self.notify(text)
        return text
