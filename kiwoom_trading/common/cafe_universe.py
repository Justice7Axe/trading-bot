"""☕ 하승훈 카페 '핫이슈 테마 체크' 종목 안에서만 매수 (2026-11-13 사용자).

카페: 하승훈의 주식투자 (clubid 26347614), 메뉴 86 '핫이슈 테마 체크'.
  목록  apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json  — 로그인 없이 됨
  본문  apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/26347614/articles/{id} — 로그인 필요 (없으면 401 · 오류코드 0004)
  → .env.local 의 NAVER_NID_AUT · NAVER_NID_SES (네이버 로그인 쿠키 NID_AUT·NID_SES 값) 로 본문을 읽음.

범위 = 가장 최근 게시글 2개. 보통 하루에 '11월 13일 특징테마'(사무장)와 '11월 13일 일자별 테마주 정리'(오연구원)가 16시쯤 올라오고,
낮에 '오전장 특징테마' 가 하나 더 올라옴. 그래서 가장 최근 '특징테마'(오전장 아님) 하나 + 가장 최근 '일자별 테마주 정리' 하나를 고르고,
제목이 바뀌어 못 찾으면 그냥 최근 2개를 씀.
본문에서 6자리 종목코드와 종목 이름(data/daily_ohlcv.duckdb stocks 표)을 찾아 종목 목록을 만듦.
본문이 그림뿐이면 (2026-11-15 사용자 '넣어줘, 일주일 전부') 그림을 받아 윈도우 내장 OCR(Windows.Media.Ocr, 한국어)로 읽고,
'종목명 (등락률%)' 꼴 줄의 이름을 stocks 이름과 맞춤 — 똑같으면 바로, 아니면 가장 비슷한 이름(difflib 비율 ≥ OCR_CUTOFF).
OCR 이 '반도체→반도제', '가온칩스→가온집스' 처럼 글자를 틀리게 읽어서임. 못 맞춘 이름은 로그에 남김.
'일자별 테마주 정리' 그림은 최근 약 7거래일 표라 그 안 종목 전부(약 150개)를 씀 (사용자: 일주일 전부).

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


# ------------------------------------------------------------------ 그림 OCR (윈도우 내장)
OCR_CUTOFF = 0.75                  # OCR 이름 ↔ stocks 이름 비슷한 정도 하한 (difflib 비율)
OCR_TIMEOUT = 90
_OCR_PS1 = r"""
param($p)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$await = [WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | select -First 1
function Await($op, $t) { $task = $await.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(); $task.Result }
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] | Out-Null
$f = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
$s = Await ($f.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s)) ([Windows.Graphics.Imaging.BitmapDecoder])
$b = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$e = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('ko'))
$r = Await ($e.RecognizeAsync($b)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$r.Lines | % { $_.Text }
"""


def fetch_image(url: str, cookie: Optional[dict[str, str]] = None) -> bytes:
    import requests
    r = requests.get(url, headers={**HEADERS, "Referer": "https://cafe.naver.com/"}, cookies=cookie or {}, timeout=20)
    r.raise_for_status()
    return r.content


OCR_VARIANTS = ("orig", "x2", "gray_x2", "x3")   # 같은 그림을 여러 크기로 읽어 합침 — 크기마다 틀리는 글자가 달라 서로 메꿈


def _variants(data: bytes) -> list[tuple[str, bytes]]:
    """그림 바이트 → [(이름, png 바이트)]: 원본·2배·흑백 2배·3배 (Pillow 없으면 원본만)."""
    out = [("orig", data)]
    try:
        import io
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(data)).convert("RGB")
        for name in OCR_VARIANTS[1:]:
            sc = 3 if name.endswith("x3") else 2
            v = ImageOps.grayscale(im) if name.startswith("gray") else im
            if max(im.width, im.height) * sc > 9_000:      # 윈도우 OCR 최대 10,000 픽셀
                continue
            buf = io.BytesIO()
            v.resize((im.width * sc, im.height * sc), Image.LANCZOS).save(buf, "PNG")
            out.append((name, buf.getvalue()))
    except Exception as exc:
        logging.info("카페 그림 키우기 못 함 (%s) — 원본만 OCR", str(exc)[:100])
    return out


def _ocr_once(data: bytes) -> list[str]:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        img = os.path.join(tmp, "img.png")       # 윈도우 경로(역슬래시)여야 StorageFile 이 염
        ps1 = os.path.join(tmp, "ocr.ps1")
        with open(img, "wb") as f:
            f.write(data)
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(_OCR_PS1)
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, img],
                           capture_output=True, timeout=OCR_TIMEOUT)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0 or not out.strip() or "Exception" in out[:300]:
        raise RuntimeError(f"OCR 실패 (코드 {p.returncode}) {p.stderr.decode('cp949', 'replace')[:200]}")
    return [s.strip() for s in out.splitlines() if s.strip()]


def ocr_lines(data: bytes) -> list[str]:
    """그림 바이트 → 윈도우 OCR(한국어) 줄 목록 (여러 크기로 읽은 줄을 모두 이어 붙임). 하나도 못 읽으면 RuntimeError."""
    lines: list[str] = []
    err = None
    for name, v in _variants(data):
        try:
            lines += _ocr_once(v)
        except Exception as exc:
            err = exc
            logging.info("카페 그림 OCR(%s) 실패: %s", name, str(exc)[:120])
    if not lines:
        raise err or RuntimeError("OCR 결과 없음")
    return lines


_OCR_ROW = re.compile(r"^(.+?)\s*\(\s*[\d\-]")      # '종목명 (29.87%)' — 괄호 뒤 숫자 (OCR 이 % 는 자주 틀림)


def _norm(s: str) -> str:
    return re.sub(r"[\s·•.,'`]", "", s).upper()


# 카페 글이 줄여 쓰는 이름 → stocks 이름 (OCR 과 상관없이 이름 자체가 다름)
ALIASES = {"LIGD&A": "LIG디펜스앤에어로스페이스"}

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def jamo(s: str) -> str:
    """한글을 자모로 풀어 씀 ('캡' → 'ㅋㅐㅂ'). OCR 이 '캡→컙', '랩→램', '컨→건' 처럼 자모 하나만 틀리는 일이 많아
    글자 단위보다 자모 단위로 비교해야 비슷한 정도가 제대로 나옴."""
    out = []
    for ch in s:
        o = ord(ch) - 0xAC00
        if 0 <= o < 11172:
            out += [_CHO[o // 588], _JUNG[o % 588 // 28]] + ([_JONG[o % 28]] if o % 28 else [])
        else:
            out.append(ch)
    return "".join(out)


def names_from_ocr(lines: list[str], names: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """OCR 줄 → ({코드: 이름}, 못 맞춘 OCR 이름). '이름 (숫자' 꼴 줄만 봄 (테마 제목·설명 줄은 괄호 숫자가 없음).
    맞추기: 똑같은 이름 → 줄임 이름(ALIASES) → 자모 단위 비슷한 정도 ≥ OCR_CUTOFF 중 가장 높은 이름 (동점이면 버림)."""
    import difflib
    norm = {}
    for n, c in names.items():
        norm.setdefault(_norm(n), (n, c))
    by_jamo = {jamo(k): k for k in norm}
    jkeys = list(by_jamo)
    found: dict[str, str] = {}
    miss: list[str] = []
    for line in lines:
        m = _OCR_ROW.match(line)
        if not m:
            continue
        cand = _norm(m.group(1))
        if len(cand) < 2:
            continue
        hit = norm.get(cand) or norm.get(_norm(ALIASES.get(cand, "")))
        if hit is None:
            cj = jamo(cand)
            close = difflib.get_close_matches(cj, jkeys, n=3, cutoff=OCR_CUTOFF)
            score = [difflib.SequenceMatcher(None, cj, k).ratio() for k in close]
            # 가장 비슷한 이름이 둘 이상 같은 점수면 못 정하므로 버림
            hit = norm[by_jamo[close[0]]] if close and (len(score) < 2 or score[0] > score[1]) else None
        if hit is None:
            miss.append(m.group(1).strip())
        else:
            found[hit[1]] = hit[0]
    return found, list(dict.fromkeys(miss))


def read_images(images: list[str], names: dict[str, str], cookie: Optional[dict[str, str]] = None,
                fetch_fn=fetch_image, ocr_fn=ocr_lines) -> tuple[dict[str, str], list[str]]:
    """그림 주소들 → OCR → ({코드: 이름}, 못 맞춘 이름)."""
    import difflib
    found: dict[str, str] = {}
    miss: list[str] = []
    for url in images:
        got, bad = names_from_ocr(ocr_fn(fetch_fn(url, cookie)), names)
        found.update(got)
        miss += bad
    # 다른 크기로 읽어 이미 맞춘 종목이 깨져 읽힌 것은 '못 맞춤' 로그에서 뺌 (자모 비슷한 정도 0.6 이상이 이미 찾은 이름)
    got_j = [jamo(_norm(n)) for n in found.values()]
    miss = [x for x in dict.fromkeys(miss) if not difflib.get_close_matches(jamo(_norm(x)), got_j, n=1, cutoff=0.6)]
    return found, miss


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
            fetch_list_fn=fetch_list, fetch_body_fn=fetch_body, cookie: Optional[dict] = None, read_images_fn=None) -> Universe:
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
                    try:
                        got, miss = (read_images_fn or read_images)(imgs, names, cookie)
                        codes.update(got)
                        a["n_codes"], a["ocr"] = len(got), True
                        logging.info("카페 글 %s '%s': 그림 %s장 OCR → 종목 %s개%s", a["id"], a["subject"], len(imgs), len(got),
                                     f" · 못 맞춘 이름 {len(miss)}개: {', '.join(miss[:20])}" if miss else "")
                    except Exception as exc:
                        logging.warning("카페 글 %s '%s': 그림 OCR 실패 (%s)", a["id"], a["subject"], str(exc)[:200])
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
