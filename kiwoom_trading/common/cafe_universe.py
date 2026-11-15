"""☕ 하승훈 카페 '핫이슈 테마 체크' 종목 안에서만 매수 (2026-11-13 사용자).

+ 두 번째 카페 (2026-11-15 사용자): '나는주식트레이더다'(clubid 29798500) 메뉴 279 레드니케 '당일특징주'
  최근 7일 글 (같은 날 사용자 '당일특징주만 쓰게 좁혀줘' → '오전장특징주' 글은 안 씀). 종목은 글자로 있음 → '*종목명 29.87%' 줄 + 인포스탁 '특징 종목' 중 오른 종목(상한가·급등·상승·강세)만.
  두 카페 종목을 합쳐(11-13 기준 약 250종목) 같은 파일·같은 제한에 씀. 한 곳이 실패해도 다른 곳 종목으로 제한함.

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
from datetime import date, datetime, time, timedelta
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


def _headers(club: int, menu: int) -> dict:
    return {**HEADERS, "Referer": f"https://cafe.naver.com/ca-fe/cafes/{club}/menus/{menu}"}


# ------------------------------------------------------------------ 쿠키 자동 갱신 (2026-11-15 사용자 '만료되는 것을 알아서 재갱신')
RENEW_URL = "https://nid.naver.com/user2/help/myInfo?lang=ko_KR"
ENV_PATH = os.path.join(PROJECT_ROOT, ".env.local")


class CookieExpired(RuntimeError):
    """NID_AUT(로그인 유지 쿠키)까지 만료돼 다시 로그인해야 함."""


def save_env(updates: dict[str, str], path: Optional[str] = None) -> None:
    """.env.local 의 KEY=값 줄만 바꿈 (다른 줄·줄바꿈 방식·순서 그대로, 없는 키는 끝에 붙임). 값은 로그에 안 남김."""
    path = path or ENV_PATH
    raw = open(path, "rb").read() if os.path.exists(path) else b""
    nl = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates and "=" in line and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={updates[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write((nl.join(lines) + nl).encode("utf-8"))
    os.replace(tmp, path)
    for k, v in updates.items():
        os.environ[k] = v


def renew_cookies(cookie: dict[str, str], env_path: Optional[str] = None) -> dict[str, str]:
    """네이버 내 정보 화면을 한 번 열어 새 세션 쿠키(NID_SES, 가끔 NID_AUT)를 받아 .env.local 에 저장.
    NID_SES 는 짧게 바뀌는 세션 쿠키라 NID_AUT(로그인 상태 유지, 보통 몇 달)가 살아 있는 한 이렇게 계속 새로 받을 수 있음.
    로그인 화면으로 넘어가면 NID_AUT 까지 만료된 것 → CookieExpired (비밀번호 로그인은 자동으로 안 함)."""
    import requests
    r = requests.get(RENEW_URL, cookies=cookie, headers=HEADERS, timeout=10, allow_redirects=False)
    loc = r.headers.get("location", "")
    if "login" in loc.lower():
        raise CookieExpired("네이버 로그인 쿠키 만료 (로그인 화면으로 넘어감)")
    new = {k: r.cookies.get(k) for k in ("NID_AUT", "NID_SES")}
    updates = {env: new[k] for env, k in (("NAVER_NID_AUT", "NID_AUT"), ("NAVER_NID_SES", "NID_SES"))
               if new[k] and new[k] != cookie.get(k)}
    if updates:
        save_env(updates, env_path)
        logging.info("네이버 쿠키 갱신: %s 새로 받아 .env.local 에 저장", ", ".join(updates))
        cookie = {**cookie, **{k: new[k] for k in ("NID_AUT", "NID_SES") if new[k]}}
    else:
        logging.info("네이버 쿠키 갱신: 새 쿠키 없음 (지금 쿠키 그대로)")
    return cookie


def alert_expired(day: date, path: Optional[str] = None) -> None:
    """쿠키 만료를 하루 한 번 텔레그램(매매 알림 봇)으로 알림."""
    flag = (path or OUT_PATH) + f".expired_{day:%Y%m%d}"
    if os.path.exists(flag):
        return
    try:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message("☕ 네이버 로그인 쿠키가 만료돼 카페 종목을 못 읽음 → 오늘은 카페 제한 없이 매수함.\n"
                              "PC 브라우저에서 네이버에 다시 로그인('로그인 상태 유지' 체크)한 뒤 개발자 도구(F12) → Application → Cookies → "
                              "naver.com 의 NID_AUT·NID_SES 값을 .env.local 의 NAVER_NID_AUT·NAVER_NID_SES 에 넣어 주세요.")
        open(flag, "w").close()
    except Exception:
        logging.exception("쿠키 만료 알림 실패")


def fetch_list(per_page: int = 15, club: int = CLUB_ID, menu: int = MENU_ID) -> list[dict]:
    """카페 메뉴 최근 글 목록 → [{'id', 'subject', 'ts', 'writer'}] (최근 순서)."""
    import requests
    r = requests.get(LIST_URL, params={"search.clubid": club, "search.menuid": menu, "search.queryType": "lastArticle",
                                       "search.page": 1, "search.perPage": per_page}, headers=_headers(club, menu), timeout=10)
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


def fetch_body(aid: int, cookie: dict[str, str], club: int = CLUB_ID, menu: int = MENU_ID) -> str:
    """본문 HTML. 로그인 안 됨(0004)·그 밖 오류는 RuntimeError."""
    import requests
    r = requests.get(BODY_URL.format(club=club, aid=aid), params={"useCafeId": "true", "requestFrom": "A"},
                     headers=_headers(club, menu), cookies=cookie, timeout=10)
    try:
        j = json.loads(r.content.decode("utf-8"))
    except Exception:
        raise RuntimeError(f"본문 응답을 못 읽음 (HTTP {r.status_code})")
    res = j.get("result") or {}
    if res.get("errorCode"):
        if str(res.get("errorCode")) == "0004":
            raise CookieExpired(f"본문 못 읽음 — 로그인 안 됨(0004), 네이버 쿠키 만료")
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


# ------------------------------------------------------------------ 두 번째 카페: 나는주식트레이더다 특징주 (2026-11-15 사용자)
TRADER_CLUB = 29798500             # 카페 '나는주식트레이더다', 메뉴 279 (레드니케 '당일특징주'만)
TRADER_MENU = 279
TRADER_DAYS = 7                    # 최근 7일 안 글 (첫 카페 '일자별 테마주 정리' 7거래일과 맞춤)
TRADER_WORD = "당일특징주"         # 오전장특징주·인포스탁증시요약 글은 안 씀 (2026-11-15 사용자)


def pick_trader(articles: list[dict], now: datetime, days: int = TRADER_DAYS) -> list[dict]:
    """제목(띄어쓰기 무시)에 '당일특징주' 가 든 최근 days 일 안 글. '오전장특징주'·'인포스탁증시요약' 글은 뺌."""
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    return [a for a in articles if TRADER_WORD in a["subject"].replace(" ", "") and a["ts"] >= since]


def trader_source(now: datetime, cookie: dict[str, str], names: dict[str, str],
                  fetch_list_fn=None, fetch_body_fn=None) -> tuple[dict[str, str], list[dict]]:
    """나는주식트레이더다 메뉴 279 최근 7일 '특징주' 글 본문(글자)에서 종목. 이 카페 글은 종목이 글자로 있고
    그림은 '당일 거래대금 상위' 표라 OCR 은 안 함."""
    lst = fetch_list_fn or (lambda: fetch_list(40, TRADER_CLUB, TRADER_MENU))
    body = fetch_body_fn or (lambda aid, ck: fetch_body(aid, ck, TRADER_CLUB, TRADER_MENU))
    codes: dict[str, str] = {}
    arts = pick_trader(lst(), now)
    for a in arts:
        h = body(a["id"], cookie)
        got, miss = trader_picks(h, names)
        codes.update(got)
        a["cafe"], a["n_codes"] = "나는주식트레이더다", len(got)
        logging.info("카페(트레이더) 글 %s '%s': 종목 %s개%s", a["id"], a["subject"], len(got),
                     f" · 못 맞춘 이름 {', '.join(miss[:10])}" if miss else "")
    return codes, arts


_STAR = re.compile(r"^\s*\*\s*([^\n*]+?)\s*(?:[+\-]?\d+(?:\.\d+)?\s*%)?\s*$")


def trader_picks(body: str, names: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """'*종목명 29.87%' 꼴 줄만 종목으로 (당일·오전장 '10% 이상 상승' 정리 목록). 같은 글 뒤쪽 '인포스탁 증시요약'은
    약세·급락 종목과 기사 속 대형주까지 섞여 있어 쓰지 않음. 이름 오타('테크놀러지')는 OCR 과 같은 자모 맞추기로."""
    lines = [x.strip() for x in html_text(body).splitlines() if x.strip()]
    cands = [m.group(1).strip() for line in lines if (m := _STAR.match(line))]
    found, miss = names_from_ocr([f"{c} (0" for c in cands if not c.startswith("-")], names)
    # 인포스탁 '특징 종목': '종목명' / '(종목코드)' / '이슈 한 줄' — 오른 종목(상한가·급등·상승·강세)만, 약세·급락·하락은 뺌
    by_code = {c: n for n, c in names.items()}
    for i in range(1, len(lines) - 1):
        m = _INFO_CODE.match(lines[i])
        if not m:
            continue
        why = lines[i + 1]
        if _UP.search(why) and not _DOWN.search(why):
            code = m.group(1)
            if code in by_code:
                found[code] = by_code[code]
    return found, miss


_INFO_CODE = re.compile(r"^\(\s*([0-9A-Z]{6})\s*\)$")
_UP = re.compile(r"상한가|급등|상승|강세|신고가")
_DOWN = re.compile(r"약세|급락|하락|하한가|부진")


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
            return f"☕ 카페 종목 {len(self.codes)}개 안에서만 매수 (하승훈 카페 핫이슈 테마 체크 + 나는주식트레이더다 당일특징주 7일, 인버스 ETF 는 예외)"
        why = {"no_cookie": "쿠키 없음", "empty": "종목 0개", "fail": "가져오기 실패",
               "expired": "네이버 쿠키 만료 — 다시 로그인해 .env.local 쿠키 넣기"}.get(self.status, self.status)
        return f"☕ 카페 제한 꺼짐({why}) — 모든 종목 매수 가능"


def refresh(now: datetime, path: Optional[str] = None, names: Optional[dict[str, str]] = None,
            fetch_list_fn=fetch_list, fetch_body_fn=fetch_body, cookie: Optional[dict] = None, read_images_fn=None,
            extra_fn=None) -> Universe:
    """카페 두 곳(하승훈 최근 글 2개 + 나는주식트레이더다 당일특징주 7일) 종목을 합쳐 path 에 저장.
    한 곳이 실패해도 다른 곳 종목은 씀. 같은 날 앞서 성공한 결과가 있는데 이번에 둘 다 실패하면 앞 결과를 그대로 둠.
    extra_fn: 두 번째 카페 (시험용으로 바꿔 끼움). fetch_list_fn 을 바꿔 끼운 시험에서는 기본으로 안 부름 (인터넷 안 씀)."""
    path = path or OUT_PATH
    day = now.date()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    cookie = cookies() if cookie is None else cookie
    prev = load(path, day)
    if not cookie:
        u = Universe(day, "no_cookie", f"{' · '.join(COOKIE_KEYS)} 가 .env.local 에 없음", fetched_at=stamp)
        logging.info("카페 종목: 쿠키 없음 → 제한 안 함")
    else:
        codes: dict[str, str] = {}
        arts: list[dict] = []
        images: list[str] = []
        errs: list[str] = []
        expired = False
        if fetch_list_fn is fetch_list:   # 실제로 가져올 때만 (시험은 인터넷 안 씀)
            try:
                cookie = renew_cookies(cookie)
            except CookieExpired as exc:
                expired = True
                errs.append(str(exc))
                logging.warning("카페 종목: %s", exc)
            except Exception as exc:
                logging.warning("네이버 쿠키 갱신 실패 (지금 쿠키로 계속): %s", str(exc)[:150])
        try:
            names = load_names() if names is None else names
            arts = pick_articles(fetch_list_fn())
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
        except Exception as exc:
            expired = expired or isinstance(exc, CookieExpired)
            errs.append(f"하승훈 카페: {str(exc)[:150]}")
            logging.warning("카페 종목(하승훈): 가져오기 실패 (%s)", str(exc)[:200])
        if extra_fn is None and fetch_list_fn is fetch_list:
            extra_fn = trader_source
        if extra_fn is not None and names is not None:
            try:
                c2, a2 = extra_fn(now, cookie, names)
                codes.update(c2)
                arts += a2
            except Exception as exc:
                expired = expired or isinstance(exc, CookieExpired)
                errs.append(f"나는주식트레이더다: {str(exc)[:150]}")
                logging.warning("카페 종목(트레이더): 가져오기 실패 (%s)", str(exc)[:200])
        if codes:
            u = Universe(day, "ok", " · ".join(errs), codes, arts, images, stamp)
            logging.info("카페 종목 %s개 (%s): %s", len(codes), ", ".join(a["subject"] for a in arts), ", ".join(list(codes.values())[:40]))
        elif errs:
            u = Universe(day, "expired" if expired else "fail", " · ".join(errs)[:200], fetched_at=stamp)
            logging.warning("카페 종목: 가져오기 실패 → 제한 안 함 (%s)", " · ".join(errs)[:200])
            if expired and fetch_list_fn is fetch_list:
                alert_expired(day, path)
        else:
            u = Universe(day, "empty", "본문에서 종목을 못 찾음 (이미지뿐이거나 형식이 바뀜)", codes, arts, images, stamp)
            logging.info("카페 종목: 0개 → 제한 안 함")
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
    return f"{TAG} — 하승훈 카페 핫이슈 테마 체크·나는주식트레이더다 특징주 종목({len(u.codes)}개)만 삼"


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
