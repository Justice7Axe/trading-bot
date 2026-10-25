"""네이버 증권 업종(79개)·테마(약 260개)와 구성 종목 — 📒 디앤서 관심종목의 섹터·테마 분류에 쓴다 (2026-10-26).

키움 테마(ka90001·ka90002)는 142개·638종목뿐이고 오래돼(로보티즈·주성엔지니어링 같은 종목이 빠짐) 섹터·테마 묶음이 거의 안 된다.
KRX 업종(stocks.sector)은 26개라 너무 넓다(전기/전자·기계/장비). → 네이버 증권(m.stock.naver.com) 업종 = 섹터, 테마 = 테마.
하루 한 번 받아 data/naver_groups.duckdb 에 저장하고, 그날 것이 있으면 다시 받지 않는다 (약 350번 요청, 1~2분).
수동: python -m kiwoom_trading.screener.naver_groups
"""
import json
import logging
import os
import time as _time
import urllib.request
from collections import defaultdict
from datetime import date
from typing import Optional

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT

DB = os.path.join(PROJECT_ROOT, "data", "naver_groups.duckdb")
API = "https://m.stock.naver.com/api/stocks/{kind}{tail}?page={page}&pageSize=100"
KINDS = {"industry": "업종", "theme": "테마"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _pages(kind: str, tail: str, key: str) -> list[dict]:
    out, page = [], 1
    while True:
        d = _get(API.format(kind=kind, tail=tail, page=page))
        rows = d.get(key) or []
        out += rows
        if not rows or len(out) >= (d.get("totalCount") or 0) or page >= 30:
            return out
        page += 1
        _time.sleep(0.05)


def fetch() -> list[tuple[str, int, str, str]]:
    """[(구분 '업종'/'테마', 번호, 이름, 종목코드)]"""
    rows = []
    for kind, label in KINDS.items():
        for g in _pages(kind, "", "groups"):
            try:
                stocks = _pages(kind, f"/{g['no']}", "stocks")
            except Exception as exc:
                logging.warning("네이버 %s %s 구성 종목 실패: %s", label, g.get("name"), exc)
                continue
            rows += [(label, int(g["no"]), g["name"], s["itemCode"]) for s in stocks if s.get("stockEndType") == "stock"]
            _time.sleep(0.05)
    return rows


def load(today: date, refresh: bool = True) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(종목 → 업종 이름, 종목 → [테마 이름]). 오늘 것이 없으면 받는다(refresh), 실패하면 가장 최근 저장분."""
    conn = duckdb.connect(DB)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS naver_groups (date DATE, kind VARCHAR, no INTEGER, name VARCHAR, code VARCHAR)")
        have = conn.execute("SELECT count(*) FROM naver_groups WHERE date = ?", [today]).fetchone()[0]
        if not have and refresh:
            try:
                rows = fetch()
                if len(rows) > 1000:
                    conn.execute("DELETE FROM naver_groups WHERE date = ?", [today])
                    conn.executemany("INSERT INTO naver_groups VALUES (?, ?, ?, ?, ?)", [(today, *r) for r in rows])
                    logging.info("네이버 업종·테마 %s줄 저장", len(rows))
            except Exception:
                logging.exception("네이버 업종·테마 받기 실패 — 최근 저장분 사용")
        last: Optional[date] = conn.execute("SELECT max(date) FROM naver_groups WHERE date <= ?", [today]).fetchone()[0]
        ind, th = {}, defaultdict(list)
        if last:
            for kind, name, code in conn.execute("SELECT kind, name, code FROM naver_groups WHERE date = ?", [last]).fetchall():
                if kind == "업종":
                    ind[code] = name
                else:
                    th[code].append(name)
        return ind, dict(th)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    i, t = load(date.today())
    print(f"업종 {len(set(i.values()))}개 {len(i)}종목, 테마 {len({x for v in t.values() for x in v})}개 {len(t)}종목")
