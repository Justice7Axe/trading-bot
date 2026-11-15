"""☕ 카페 과거 글 모으기 → data/cafe_history.duckdb (카페 종목 제한 백테스트용, 2026-11-15).

- 하승훈 카페(26347614/86): '특징테마'(오전장 제외)·'일자별 테마주 정리' 글 → 본문 글자에 종목 없으면 그림 OCR
- 나는주식트레이더다(29798500/279): '당일특징주' 글 → trader_picks (글자)
cafe_universe.py 함수만 가져다 씀 (수정 안 함). 쿠키 값은 출력·저장 안 함.

    python -m kiwoom_trading.research.cafe_universe.collect --since 2025-08-20 [--workers 6] [--variants orig,x2]
이어 받기: posts.status='done' 인 글은 건너뜀. 실패 글은 다시 돌리면 재시도.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import duckdb

from kiwoom_trading.common import cafe_universe as cu
from kiwoom_trading.common.daily_store import PROJECT_ROOT

DB = os.path.join(PROJECT_ROOT, "data", "cafe_history.duckdb")
HASUNG, TRADER = "하승훈", "나는주식트레이더다"
CAFES = {HASUNG: (cu.CLUB_ID, cu.MENU_ID), TRADER: (cu.TRADER_CLUB, cu.TRADER_MENU)}

_lock = threading.Lock()
_last = [0.0]


def throttle(gap: float = 0.5) -> None:
    """모든 네이버 요청 사이 gap 초 이상."""
    with _lock:
        wait = _last[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def retry(fn, *a, tries: int = 4, **k):
    for i in range(tries):
        try:
            throttle()
            return fn(*a, **k)
        except cu.CookieExpired:
            raise
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def kind_of(cafe: str, subject: str) -> str | None:
    s = subject.replace(" ", "")
    if cafe == HASUNG:
        if "특징테마" in s and "오전장" not in s:
            return "특징테마"
        if "테마주정리" in s:
            return "일자별"
        return None
    return "당일특징주" if cu.TRADER_WORD in s else None


def init(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS posts (post_id BIGINT, cafe VARCHAR, subject VARCHAR, posted_ts TIMESTAMP, kind VARCHAR,
                    status VARCHAR, n_images INT, n_codes INT, ocr BOOLEAN, miss VARCHAR, err VARCHAR, PRIMARY KEY (cafe, post_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cafe_history (post_id BIGINT, cafe VARCHAR, subject VARCHAR, posted_ts TIMESTAMP,
                    code VARCHAR, name VARCHAR)""")


def list_posts(conn, cafe: str, since: str, per_page: int = 50) -> int:
    import requests
    club, menu = CAFES[cafe]
    n = 0
    for page in range(1, 400):
        def get():
            r = requests.get(cu.LIST_URL, params={"search.clubid": club, "search.menuid": menu, "search.queryType": "lastArticle",
                                                  "search.page": page, "search.perPage": per_page}, headers=cu._headers(club, menu), timeout=15)
            r.raise_for_status()
            return json.loads(r.content.decode("utf-8"))["message"]["result"]["articleList"]
        rows = retry(get)
        if not rows:
            break
        oldest = None
        for a in rows:
            ts = datetime.fromtimestamp(a["writeDateTimestamp"] / 1000)
            oldest = ts
            subj = str(a.get("subject") or "")
            k = kind_of(cafe, subj)
            if ts.strftime("%Y-%m-%d") < since:
                continue
            conn.execute("INSERT INTO posts (post_id, cafe, subject, posted_ts, kind, status) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                         [int(a["articleId"]), cafe, subj, ts, k, "todo" if k else "skip"])
            n += 1
        if oldest is not None and oldest.strftime("%Y-%m-%d") < since:
            break
    logging.info("%s 목록 %s건 (since %s)", cafe, n, since)
    return n


def process(post: tuple, cookie: dict, names: dict) -> dict:
    pid, cafe, subject, kind = post
    club, menu = CAFES[cafe]
    out = {"post_id": pid, "cafe": cafe, "codes": {}, "n_images": 0, "ocr": False, "miss": [], "err": None}
    try:
        body = retry(cu.fetch_body, pid, cookie, club, menu)
        if cafe == TRADER:
            got, miss = cu.trader_picks(body, names)
            out["codes"], out["miss"] = got, miss
            return out
        got, imgs, _ = cu.extract(body, names)
        out["n_images"] = len(imgs)
        if got or not imgs:
            out["codes"] = got
            return out
        found, miss = {}, []
        for url in imgs:
            data = retry(cu.fetch_image, url, cookie)
            g, b = cu.names_from_ocr(cu.ocr_lines(data), names)
            found.update(g)
            miss += b
        import difflib
        got_j = [cu.jamo(cu._norm(n)) for n in found.values()]
        miss = [x for x in dict.fromkeys(miss) if not difflib.get_close_matches(cu.jamo(cu._norm(x)), got_j, n=1, cutoff=0.6)]
        out.update(codes=found, miss=miss, ocr=True)
    except cu.CookieExpired:
        raise
    except Exception as exc:
        out["err"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-08-20")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--variants", default="orig,x2", help="OCR 크기 변형 (cafe_universe.OCR_VARIANTS 중)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-list", action="store_true")
    a = ap.parse_args()
    cu.OCR_VARIANTS = tuple(a.variants.split(","))
    conn = duckdb.connect(DB)
    init(conn)
    if not a.no_list:
        for cafe in CAFES:
            list_posts(conn, cafe, a.since)
    cookie = cu.cookies()
    if not cookie:
        raise SystemExit("쿠키 없음")
    try:
        cookie = cu.renew_cookies(cookie)
    except cu.CookieExpired:
        raise SystemExit("네이버 쿠키 만료")
    except Exception as exc:
        logging.warning("쿠키 갱신 실패 (지금 쿠키로): %s", str(exc)[:100])
    names = cu.load_names()
    todo = conn.execute("SELECT post_id, cafe, subject, kind FROM posts WHERE kind IS NOT NULL AND status <> 'done' "
                        "ORDER BY posted_ts DESC").fetchall()
    if a.limit:
        todo = todo[:a.limit]
    logging.info("처리할 글 %s건", len(todo))
    ts_of = {(r[1], r[0]): r for r in conn.execute("SELECT post_id, cafe, subject, posted_ts FROM posts").fetchall()}
    done = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(process, p, cookie, names) for p in todo]
        for f in as_completed(futs):
            r = f.result()
            pid, cafe, subj, ts = ts_of[(r["cafe"], r["post_id"])]
            conn.execute("DELETE FROM cafe_history WHERE cafe=? AND post_id=?", [cafe, pid])
            if r["err"]:
                fail += 1
                conn.execute("UPDATE posts SET status='fail', err=? WHERE cafe=? AND post_id=?", [r["err"], cafe, pid])
            else:
                done += 1
                for code, name in r["codes"].items():
                    conn.execute("INSERT INTO cafe_history VALUES (?,?,?,?,?,?)", [pid, cafe, subj, ts, code, name])
                conn.execute("UPDATE posts SET status='done', n_images=?, n_codes=?, ocr=?, miss=?, err=NULL WHERE cafe=? AND post_id=?",
                             [r["n_images"], len(r["codes"]), r["ocr"], ", ".join(r["miss"])[:2000], cafe, pid])
            if (done + fail) % 20 == 0:
                logging.info("진행 %s/%s (실패 %s) %.0fs", done + fail, len(todo), fail, time.time() - t0)
    logging.info("끝: 성공 %s · 실패 %s · %.0fs", done, fail, time.time() - t0)
    conn.close()


if __name__ == "__main__":
    main()
