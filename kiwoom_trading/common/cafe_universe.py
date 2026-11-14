"""☕ 하승훈 카페 '핫이슈 테마 체크' 종목 안에서만 매수 (2026-11-13 사용자).

카페: 하승훈의 주식투자 (clubid 26347614), 메뉴 86 '핫이슈 테마 체크'.
  목록  apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json  — 로그인 없이 됨
  본문  apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/26347614/articles/{id} — 로그인 필요 (없으면 401 · 오류코드 0004)
  → .env.local 의 NAVER_NID_AUT · NAVER_NID_SES (네이버 로그인 쿠키 NID_AUT·NID_SES 값) 로 본문을 읽음.

범위 = 가장 최근 게시글 2개. 보통 하루에 '11월 13일 특징테마'(사무장)와 '11월 13일 일자별 테마주 정리'(오연구원)가 16시쯤 올라오고,
낮에 '오전장 특징테마' 가 하나 더 올라옴. 그래서 가장 최근 '특징테마'(오전장 아님) 하나 + 가장 최근 '일자별 테마주 정리' 하나를 고르고,
제목이 바뀌어 못 찾으면 그냥 최근 2개를 씀.
본문에서 6자리 종목코드와 종목 이름(data/daily_ohlcv.duckdb stocks 표)을 찾아 종목 목록을 만듦. 본문이 그림이면 OCR 은 안 하고
그림 주소만 남기고 '이미지라 못 읽음' 로그를 남김.

가져오는 때: 07:50 스캐너 시작 때 한 번 + 08:40 한 번 → data/cafe_universe.json.
적용: 오늘 파일에 종목이 1개 이상 있으면 모든 실전·모의 매수(매매별 가상 계좌 포함)를 그 종목만 허용 (인버스 ETF 같은 지수 상품은 뺌 = 허용).
쿠키 없음·실패·0종목이면 제한하지 않음.

    python -m kiwoom_trading.common.cafe_universe            # 지금 가져와 저장하고 결과 출력
    python -m kiwoom_trading.common.cafe_universe --show     # 저장된 파일만 읽어 출력
"""
from __future__ import annotations

import argparse
import html as _html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.common.daily_store import DEFAULT_DB_PATH, PROJECT_ROOT, load_env

CLUB_ID = 26347614
MENU_ID = 86
LIST_URL = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
BODY_URL = "https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/{club}/articles/{aid}"
OUT_PATH = os.path.join(PROJECT_ROOT, "data", "cafe_universe.json")
COOKIE_KEYS = ("NAVER_NID_AUT", "NAVER_NID_SES")
SECOND_FETCH_AT = time(8, 40)      # 07:50 시작 때 한 번 + 이 시각에 한 번 더
N_ARTICLES = 2
TAG = "카페 종목 아님"               # 건너뜀 이유 앞머리 — paper.RULE_SKIPS 에 들어 있어 알림 없이 기록만
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
           "Referer": f"https://cafe.naver.com/ca-fe/cafes/{CLUB_ID}/menus/{MENU_ID}"}


def _exempt_kinds() -> tuple[set, set]:
    """카페 제한에서 빼는 매매(지수 상품) — 인버스 갭·약세장 인버스, 그리고 인버스 ETF 종목코드."""
    kinds, codes = set(), set()
    try:
        from kiwoom_trading.strategies.inverse.live import CODE, KIND, WEAK_KIND
        kinds |= {KIND, WEAK_KIND}
        codes.add(CODE)
    except Exception:
        kinds |= {"인버스 갭", "약세장 인버스"}
    return kinds, codes


# ------------------------------------------------------------------ 가져오기
def cookies() -> dict[str, str]:
    """.env.local 의 네이버 로그인 쿠키. 둘 중 하나라도 없으면 빈 dict."""
    load_env()
    aut, ses = (os.getenv(k, "").strip() for k in COOKIE_KEYS)
    return {"NID_AUT": aut, "NID_SES": ses} if aut and ses else {}


def fetch_list(per_page: int = 15) -> list[dict]:
    """메뉴 86 최근 글 목록 → [{'id', 'subject', 'ts', 'writer'}] (최근 순서)."""
    import requests
    r = requests.get(LIST_URL, params={"search.clubid": CLUB_ID, "search.menuid": MENU_ID, "search.queryType": "lastArticle",
                                       "search.page": 1, "search.perPage": per_page}, headers=HEADERS, timeout=10)
    r.raise_for_status()
    rows = json.loads(r.content.decode("utf-8"))["message"]["result"]["articleList"]
    return [{"id": int(a["articleId"]), "subject": str(a.get("subject") or ""), "writer": str(a.get("writerNickname") or ""),
             "ts": datetime.fromtimestamp(a["writeDateTimestamp"] / 1000).strftime("%Y-%m-%d %H:%M") if a.get("writeDateTimestamp") else ""}
            for a in rows]


def pick_articles(articles: list[dict], n: int = N_ARTICLES) -> list[dict]:
    """가장 최근 '특징테마'(오전장 아님) + 가장 최근 '일자별 테마주 정리'. 못 찾으면 최근 n개로 채움."""
    picked = []
    for test in (lambda s: "특징테마" in s and "오전장" not in s, lambda s: "테마주 정리" in s):
        a = next((x for x in articles if test(x["subject"].replace(" ", "")) or test(x["subject"])), None)
        if a is not None and a not in picked:
            picked.append(a)
    for a in articles:
        if len(picked) >= n:
            break
        if a not in picked:
            picked.append(a)
    return picked[:n]


def fetch_body(aid: int, cookie: dict[str, str]) -> str:
    """본문 HTML. 로그인 안 됨(0004)·그 밖 오류는 RuntimeError."""
    import requests
    r = requests.get(BODY_URL.format(club=CLUB_ID, aid=aid), params={"useCafeId": "true", "requestFrom": "A"},
                     headers=HEADERS, cookies=cookie, timeout=10)
    try:
        j = json.loads(r.content.decode("utf-8"))
    except Exception:
        raise RuntimeError(f"본문 응답을 못 읽음 (HTTP {r.status_code})")
    res = j.get("result") or {}
    if res.get("errorCode"):
        raise RuntimeError(f"본문 못 읽음 — 오류코드 {res.get('errorCode')} {res.get('reason') or ''}".strip())
    found = _find_key(res, "contentHtml")
    if not found:
        raise RuntimeError(f"본문에 contentHtml 이 없음 (HTTP {r.status_code})")
    return found


def _find_key(obj, key: str) -> Optional[str]:
    if isinstance(obj, dict):
        if isinstance(obj.get(key), str):
            return obj[key]
        for v in obj.values():
            got = _find_key(v, key)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _find_key(v, key)
            if got:
                return got
    return None


# ------------------------------------------------------------------ 종목 뽑기
def load_names(db_path: str = DEFAULT_DB_PATH) -> dict[str, str]:
    """stocks 표 → {종목 이름: 코드} (상장 폐지 뺌)."""
    import duckdb
    conn = duckdb.connect(db_path, read_only=True)
    try:
        rows = conn.execute("SELECT code, name FROM stocks WHERE NOT coalesce(delisted, false) AND name IS NOT NULL").fetchall()
    finally:
        conn.close()
    return {str(n).strip(): str(c) for c, n in rows if str(n).strip()}


_IMG = re.compile(r"""<img\b[^>]*?\b(?:data-lazy-src|src)\s*=\s*["']([^"']+)["']""", re.I)
_TAG = re.compile(r"<[^>]+>")
_KO_ALNUM = "0-9A-Za-z가-힣"


def html_text(body: str) -> str:
    """본문 HTML → 글자만 (줄 바꿈 유지)."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", t)
    t = _TAG.sub(" ", t)
    t = _html.unescape(t).replace("​", " ").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t)


def extract(body: str, names: dict[str, str]) -> tuple[dict[str, str], list[str], int]:
    """본문 HTML → ({코드: 이름}, 그림 주소 목록, 글자 수).
    6자리 숫자 중 stocks 표에 있는 코드 + stocks 이름이 앞뒤로 글자·숫자 없이 나온 것 (긴 이름부터 찾아 '삼성전자우' 안의 '삼성전자' 를 따로 안 셈)."""
    text = html_text(body)
    by_code = {c: n for n, c in names.items()}
    found: dict[str, str] = {}
    for m in re.finditer(rf"(?<![{_KO_ALNUM}])(\d{{6}})(?!\d)", text):
        if m.group(1) in by_code:
            found[m.group(1)] = by_code[m.group(1)]
    masked = text
    for name in sorted(names, key=len, reverse=True):
        if len(name) < 2 or name not in masked:
            continue
        pat = re.compile(rf"(?<![{_KO_ALNUM}&]){re.escape(name)}(?![{_KO_ALNUM}])")
        if pat.search(masked):
            found.setdefault(names[name], name)
            masked = pat.sub(" ", masked)
    images = list(dict.fromkeys(m.group(1) for m in _IMG.finditer(body)))
    return found, images, len(text.strip())


# ------------------------------------------------------------------ 저장·읽기
@dataclass
class Universe:
    day: Optional[date]
    status: str                       # 'ok' | 'no_cookie' | 'fail' | 'empty'
    reason: str = ""
    codes: dict[str, str] = field(default_factory=dict)
    articles: list[dict] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    fetched_at: str = ""

    @property
    def active(self) -> bool:
        return self.status == "ok" and bool(self.codes)

    def to_json(self) -> dict:
        return {"date": self.day.isoformat() if self.day else None, "status": self.status, "reason": self.reason, "codes": self.codes,
                "articles": self.articles, "images": self.images, "fetched_at": self.fetched_at}

    @classmethod
    def from_json(cls, j: dict) -> "Universe":
        d = j.get("date")
        return cls(date.fromisoformat(d) if d else None, j.get("status", "fail"), j.get("reason", ""), dict(j.get("codes") or {}),
                   list(j.get("articles") or []), list(j.get("images") or []), j.get("fetched_at", ""))

    def card_line(self) -> str:
        if self.active:
            return f"☕ 카페 종목 {len(self.codes)}개 안에서만 매수 (하승훈 카페 핫이슈 테마 체크 최근 글 2개, 인버스 ETF 는 예외)"
        why = {"no_cookie": "쿠키 없음", "empty": "종목 0개", "fail": "가져오기 실패"}.get(self.status, self.status)
        return f"☕ 카페 제한 꺼짐({why}) — 모든 종목 매수 가능"


def refresh(now: datetime, path: Optional[str] = None, names: Optional[dict[str, str]] = None,
            fetch_list_fn=fetch_list, fetch_body_fn=fetch_body, cookie: Optional[dict] = None) -> Universe:
    """카페 최근 글 2개 본문에서 종목을 뽑아 path 에 저장. 같은 날 앞서 성공한 결과가 있는데 이번에 실패하면 앞 결과를 그대로 둠."""
    path = path or OUT_PATH
    day = now.date()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    cookie = cookies() if cookie is None else cookie
    prev = load(path, day)
    if not cookie:
        u = Universe(day, "no_cookie", f"{' · '.join(COOKIE_KEYS)} 가 .env.local 에 없음", fetched_at=stamp)
        logging.info("카페 종목: 쿠키 없음 → 제한 안 함")
    else:
        try:
            arts = pick_articles(fetch_list_fn())
            names = load_names() if names is None else names
            codes: dict[str, str] = {}
            images: list[str] = []
            for a in arts:
                body = fetch_body_fn(a["id"], cookie)
                got, imgs, n_text = extract(body, names)
                codes.update(got)
                images += imgs
                a["n_codes"], a["n_images"] = len(got), len(imgs)
                if not got and imgs:
                    logging.info("카페 글 %s '%s': 이미지라 못 읽음 (그림 %s장, 글자 %s자) — OCR 안 함", a["id"], a["subject"], len(imgs), n_text)
                else:
                    logging.info("카페 글 %s '%s': 종목 %s개 · 그림 %s장", a["id"], a["subject"], len(got), len(imgs))
            u = Universe(day, "ok" if codes else "empty", "" if codes else "본문에서 종목을 못 찾음 (이미지뿐이거나 형식이 바뀜)",
                         codes, arts, images, stamp)
            if codes:
                logging.info("카페 종목 %s개 (%s): %s", len(codes), ", ".join(a["subject"] for a in arts), ", ".join(list(codes.values())[:40]))
            else:
                logging.info("카페 종목: 0개 → 제한 안 함")
        except Exception as exc:
            u = Universe(day, "fail", str(exc)[:200], fetched_at=stamp)
            logging.warning("카페 종목: 가져오기 실패 → 제한 안 함 (%s)", str(exc)[:200])
    if not u.active and prev is not None and prev.active:
        logging.info("카페 종목: 이번(%s)엔 못 가져와 %s 에 가져온 %s개를 그대로 씀", stamp, prev.fetched_at, len(prev.codes))
        prev.reason = f"{stamp} 다시 가져오기 실패({u.reason[:80]}) — 앞 결과 유지"
        prev.fetched_at, u = stamp, prev
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(u.to_json(), f, ensure_ascii=False, indent=1)
    except Exception:
        logging.exception("카페 종목 저장 실패 %s", path)
    _CACHE.clear()
    return u


def load(path: Optional[str] = None, day: Optional[date] = None) -> Optional[Universe]:
    """저장된 파일 (day 를 주면 그날 것만)."""
    path = path or OUT_PATH
    try:
        with open(path, encoding="utf-8") as f:
            u = Universe.from_json(json.load(f))
    except FileNotFoundError:
        return None
    except Exception:
        logging.exception("카페 종목 파일 읽기 실패 %s", path)
        return None
    return u if day is None or u.day == day else None


def maybe_refresh(now: datetime, path: Optional[str] = None) -> Optional[Universe]:
    """스캐너가 매분 부름: 오늘 파일이 없으면 가져오고, 08:40 이 지났는데 마지막으로 가져온 게 08:40 전이면 한 번 더."""
    u = load(path, now.date())
    if u is None:
        return refresh(now, path)
    if now.time() >= SECOND_FETCH_AT and u.fetched_at < f"{now:%Y-%m-%d} {SECOND_FETCH_AT:%H:%M}":
        return refresh(now, path)
    return None


_CACHE: dict = {}


def current(day: Optional[date] = None, path: Optional[str] = None) -> Optional[Universe]:
    """오늘 적용할 카페 종목 (파일이 바뀌면 다시 읽음). 오늘 것이 아니거나 제한이 꺼져 있으면 None."""
    day = day or date.today()
    path = path or OUT_PATH
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, mtime, day)
    if _CACHE.get("key") != key:
        u = load(path, day)
        _CACHE.clear()
        _CACHE.update(key=key, u=u if (u is not None and u.active) else None)
    return _CACHE["u"]


def skip_reason(code: str, kind: str = "", day: Optional[date] = None, universe: Optional[Universe] = None) -> Optional[str]:
    """카페 제한에 걸리면 이유, 아니면 None. 제한이 꺼져 있거나(쿠키 없음·실패·0종목) 지수 상품(인버스)이면 None."""
    u = universe if universe is not None else current(day)
    if u is None or not u.active:
        return None
    kinds, codes = _exempt_kinds()
    if kind in kinds or code in codes or code in u.codes:
        return None
    return f"{TAG} — 하승훈 카페 핫이슈 테마 체크 최근 글 2개 종목({len(u.codes)}개)만 삼"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="하승훈 카페 핫이슈 테마 체크 종목 가져오기")
    ap.add_argument("--show", action="store_true", help="저장된 파일만 읽기")
    a = ap.parse_args()
    u = load() if a.show else refresh(datetime.now())
    if u is None:
        print("저장된 파일 없음")
        return
    print(u.card_line())
    print(json.dumps(u.to_json(), ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
