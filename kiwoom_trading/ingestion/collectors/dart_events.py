"""DART(전자공시) 사건 공시 수집 — 일정 시나리오 매매(event_scenario) 백테스트용.

python -m kiwoom_trading.ingestion.collectors.dart_events list  [시작 YYYYMMDD] [끝 YYYYMMDD]
python -m kiwoom_trading.ingestion.collectors.dart_events docs  [최대 건수] [일꾼 k] [일꾼 수 n]  → merge_docs

- list: 공시 목록(주요사항보고 B · 거래소공시 I)을 한 달씩 받아 data/events.duckdb `disclosures` 에 쌓는다.
  상장 종목(stock_code 있음)만, 제목으로 사건 종류(kind)를 붙인다. 이미 받은 접수번호는 건너뜀.
- docs: 사건 공시 원문(document.xml, zip)을 받아 `documents` 에 텍스트로 저장 (규모 뽑기는 strategies/event_scenario/parse.py).
DART 목록에는 접수 '날짜'만 있다(시각 없음) → 백테스트는 접수일 다음 날 시가부터 산다.
키: .env.local DART_API_KEY (하루 2만 건 한도).
"""
import html, io, os, re, sys, time, zipfile
from datetime import date, datetime, timedelta

import duckdb
import requests
from dotenv import load_dotenv

load_dotenv(".env.local")
KEY = os.getenv("DART_API_KEY", "").strip().strip('"')
DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
DB = os.path.join(DATA, "events.duckdb")
API = "https://opendart.fss.or.kr/api"

# 제목 → 사건 종류. 앞에서부터 먼저 맞는 것.  '정정'·'철회' 는 따로 표시만 하고 종류는 같게 둔다.
KINDS = [
    ("earn_notice", r"결산실적공시예고"),
    ("ir", r"기업설명회\(IR\)개최(?!결과)"),
    ("earn_prelim", r"영업\(잠정\)실적|매출액또는손익구조"),
    ("div_record", r"배당을위한주주명부폐쇄|배당.*기준일.*결정"),
    ("buyback_trust", r"자기주식취득신탁계약체결"),
    ("buyback", r"자기주식취득결정"),
    ("cancel", r"주식소각결정"),
    ("dividend", r"현금ㆍ현물배당결정|현금·현물배당결정|현금배당결정"),
    ("valueup", r"기업가치제고계획"),
    ("bonus", r"무상증자결정"),
    ("split", r"주식분할결정"),
]


def kind_of(title):
    t = re.sub(r"\s+", "", title)
    for k, p in KINDS:
        if re.search(p, t):
            return k
    return None


def relabel(c):
    """KINDS 를 바꾼 뒤 이미 받은 제목에 종류를 다시 붙인다."""
    for r, t in c.execute("SELECT rcept_no, title FROM disclosures").fetchall():
        c.execute("UPDATE disclosures SET kind=? WHERE rcept_no=?", [kind_of(t), r])


def con():
    c = duckdb.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS disclosures(
        rcept_no VARCHAR PRIMARY KEY, rcept_dt DATE, code VARCHAR, corp_code VARCHAR, corp_name VARCHAR,
        corp_cls VARCHAR, title VARCHAR, kind VARCHAR, fixed BOOLEAN, flr_nm VARCHAR, rm VARCHAR)""")
    c.execute("CREATE TABLE IF NOT EXISTS list_done(month VARCHAR, ty VARCHAR, PRIMARY KEY(month, ty))")
    c.execute("CREATE TABLE IF NOT EXISTS documents(rcept_no VARCHAR PRIMARY KEY, text VARCHAR, fetched TIMESTAMP)")
    return c


def get(path, **p):
    """DART 는 1분에 너무 많이 부르면 IP 를 한동안 막는다(연결 끊김) → 일꾼 하나·건당 0.6초 이상, 막히면 5분씩 기다린다."""
    for i in range(30):
        try:
            return requests.get(f"{API}/{path}", params={"crtfc_key": KEY, **p}, timeout=30)
        except requests.RequestException as e:
            w = 5 if i < 3 else 300
            print(f"  재시도 {i + 1} ({w}초 뒤): {str(e)[:80]}", file=sys.stderr, flush=True); time.sleep(w)
    raise SystemExit("DART 연결 실패 (2시간 넘게 막힘)")


def months(a, b):
    d = a.replace(day=1)
    while d <= b:
        n = (d + timedelta(days=32)).replace(day=1)
        yield max(d, a), min(n - timedelta(days=1), b)
        d = n


def run_list(a, b):
    c = con()
    done = {(m, t) for m, t in c.execute("SELECT month, ty FROM list_done").fetchall()}
    today = date.today()
    for s, e in months(a, b):
        for ty in ("B", "I"):
            m = s.strftime("%Y%m")
            if (m, ty) in done and e < today - timedelta(days=3): continue
            page, total, rows = 1, 1, []
            while page <= total:
                j = get("list.json", bgn_de=s.strftime("%Y%m%d"), end_de=e.strftime("%Y%m%d"),
                        pblntf_ty=ty, page_no=page, page_count=100).json()
                if j.get("status") == "013": break                   # 자료 없음
                if j.get("status") != "000": raise SystemExit(f"DART 오류 {j.get('status')} {j.get('message')}")
                total = j["total_page"]
                for x in j["list"]:
                    if not x.get("stock_code"): continue
                    t = x["report_nm"].strip()
                    rows.append((x["rcept_no"], datetime.strptime(x["rcept_dt"], "%Y%m%d").date(), x["stock_code"],
                                 x["corp_code"], x["corp_name"], x["corp_cls"], t, kind_of(t),
                                 bool(re.search(r"\[기재정정\]|\[첨부정정\]|정정", t)), x["flr_nm"], x.get("rm", "")))
                page += 1
                time.sleep(0.15)
            if rows:
                c.executemany("INSERT OR IGNORE INTO disclosures VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            c.execute("INSERT OR IGNORE INTO list_done VALUES (?,?)", [m, ty])
            n = sum(1 for r in rows if r[7])
            print(f"{m} {ty}: {len(rows)}건 (사건 {n})", flush=True)


def doc_text(rcept_no):
    r = get("document.xml", rcept_no=rcept_no)
    if r.headers.get("content-type", "").startswith("application/json") or r.content[:1] == b"{":
        j = r.json()
        if j.get("status") == "020": raise SystemExit("DART 하루 한도 넘음 — 내일 이어서")
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return None
    out = []
    for n in z.namelist():
        raw = z.read(n)
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                s = raw.decode(enc); break
            except UnicodeDecodeError:
                continue
        else:
            s = raw.decode("utf-8", "ignore")
        out.append(s)
    return cells("\n".join(out))


def cells(s):
    """원문 HTML → 칸을 '|' 로 이은 글 (표 칸·줄 하나가 칸 하나)."""
    s = re.sub(r"(?is)<style.*?</style>", " ", s)
    s = re.sub(r"<[^>]+>", "|", s)
    s = html.unescape(s).replace("\xa0", " ")
    parts = [re.sub(r"\s+", " ", p).strip() for p in s.split("|")]
    return "|".join(p for p in parts if p)


def run_docs(limit, k=0, n=1):
    """일꾼 k/n: 목록은 events.duckdb 에서 읽기만 하고, 원문은 events_docs_k.duckdb 에 쓴다 (나중에 merge_docs)."""
    m = duckdb.connect(DB, read_only=True)
    todo = [r for (r,) in m.execute("""SELECT d.rcept_no FROM disclosures d LEFT JOIN documents x USING(rcept_no)
        WHERE d.kind IN ('earn_notice','div_record','earn_prelim','cancel','dividend','buyback','buyback_trust','bonus','split')
          AND (d.rcept_dt >= DATE '2024-10-01' OR d.kind IN ('dividend','div_record'))
          AND NOT d.fixed AND d.title NOT LIKE '%자회사%'
          AND x.rcept_no IS NULL ORDER BY d.rcept_dt DESC""").fetchall()]
    m.close()
    todo = [r for r in todo if int(r) % n == k]
    w = duckdb.connect(os.path.join(DATA, f"events_docs_{k}.duckdb"))
    w.execute("CREATE TABLE IF NOT EXISTS documents(rcept_no VARCHAR PRIMARY KEY, text VARCHAR, fetched TIMESTAMP)")
    have = {r for (r,) in w.execute("SELECT rcept_no FROM documents").fetchall()}
    todo = [r for r in todo if r not in have][:limit]
    print(f"[{k}/{n}] 원문 받을 것 {len(todo)}건", flush=True)
    for i, r in enumerate(todo):
        t = doc_text(r)
        w.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?)", [r, t, datetime.now()])
        if i % 200 == 0: print(f"  [{k}] {i}/{len(todo)}", flush=True)
        time.sleep(0.6)


def merge_docs():
    c = con()
    for f in sorted(os.listdir(DATA)):
        if re.fullmatch(r"events_docs_\d+\.duckdb", f):
            c.execute(f"ATTACH '{os.path.join(DATA, f)}' AS p (READ_ONLY)")
            c.execute("INSERT OR REPLACE INTO documents SELECT * FROM p.documents WHERE text IS NOT NULL")
            c.execute("DETACH p")
    print(c.execute("SELECT count(*), count(text) FROM documents").fetchall())


if __name__ == "__main__":
    if not KEY: raise SystemExit(".env.local 에 DART_API_KEY 없음")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        a = datetime.strptime(sys.argv[2], "%Y%m%d").date() if len(sys.argv) > 2 else date(2023, 9, 1)
        b = datetime.strptime(sys.argv[3], "%Y%m%d").date() if len(sys.argv) > 3 else date.today()
        run_list(a, b)
    elif cmd == "relabel":
        relabel(con())
    elif cmd == "docs":
        run_docs(int(sys.argv[2]) if len(sys.argv) > 2 else 20000,
                 int(sys.argv[3]) if len(sys.argv) > 3 else 0, int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    elif cmd == "merge_docs":
        merge_docs()
