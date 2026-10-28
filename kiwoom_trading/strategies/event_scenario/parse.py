"""DART 공시 원문(칸을 '|' 로 이은 글) → 사건 규모 칸. data/events.duckdb `event_details` 를 다시 만든다.

python -m kiwoom_trading.strategies.event_scenario.parse

칸 (없으면 NULL):
- earn_prelim : op(영업이익 당해, 백만원), op_yoy(전년 같은 분기 대비 %), op_turn('흑자전환'·'적자전환'·''), sales_yoy(%)
- earn_notice : due(결산실적 공시 예정일)
- cancel      : ratio(소각 주식 ÷ 발행주식), pre_owned(기취득 자기주식이면 True)
- buyback     : amount(취득 예정 금액, 원), shares(취득 예정 주식)
- buyback_trust: amount(계약 금액, 원)
- dividend    : dps(보통주 1주당 배당금), yield_pct(시가배당률 %), record(배당 기준일), div_type(결산·분기·중간)
- div_record  : record(기준일)
- bonus       : per_share(1주당 신주배정 주식수), record(신주배정 기준일), listing(신주 상장 예정일)
- split       : record(효력 발생일 또는 신주 상장 예정일)
"""
import os, re
from datetime import datetime

import duckdb

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
DB = os.path.join(DATA, "events.duckdb")
NUM = re.compile(r"^-?[\d,]+(\.\d+)?$")
DAY = re.compile(r"(\d{4})[-.년\s]+(\d{1,2})[-.월\s]+(\d{1,2})")


def num(s):
    s = s.replace(" ", "")
    return float(s.replace(",", "")) if NUM.match(s) else None


def day(s):
    m = DAY.search(s or "")
    if not m: return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).date()
    except ValueError:
        return None


def after(t, label, k=0, n=12, want=num, stop=None):
    """label 칸 뒤 n칸 안에서 want 가 값을 내는 k번째 값. stop 칸을 만나면 멈춤."""
    for i, x in enumerate(t):
        if re.search(label, x):
            got = 0
            for y in t[i + 1:i + 1 + n]:
                if stop and re.search(stop, y): break
                v = want(y)
                if v is not None:
                    if got == k: return v
                    got += 1
            return None
    return None


def earn(t):
    # 영업이익 → 당해실적 → [당기, 전기, 전기대비%, 전환, 전년동기, 전년동기대비%, 전환]
    for i, x in enumerate(t):
        if re.fullmatch(r"영업이익(\(손실\))?", x.replace(" ", "")) and i + 1 < len(t) and "당해" in t[i + 1]:
            row = t[i + 1:i + 10]
            if row and "당해" in row[0]: row = row[1:]
            if len(row) < 7: return {}
            v = [num(y) for y in row[:7]]
            turn = row[6] if row[6] in ("흑자전환", "적자전환") else (row[3] if row[3] in ("흑자전환", "적자전환") else "")
            out = dict(op=v[0], op_yoy=v[5], op_turn=turn)
            for j, y in enumerate(t):
                if y.replace(" ", "") == "매출액":
                    r2 = t[j + 1:j + 10]
                    if r2 and "당해" in r2[0]: r2 = r2[1:]
                    if len(r2) >= 6: out["sales_yoy"] = num(r2[5])
                    break
            return out
    # '매출액또는손익구조 30% 변경' 형식: '- 영업이익' | 당해사업연도 | 직전사업연도 | 증감금액 | 증감비율(%) | 흑자적자전환
    op = after(t, r"^-?\s*영업이익$", n=5); yoy = after(t, r"^-?\s*영업이익$", k=3, n=5)
    turn = after(t, r"^-?\s*영업이익$", n=6, stop=r"^-\s", want=lambda s: s if s in ("흑자전환", "적자전환") else None)
    return dict(op=op, op_yoy=yoy, op_turn=turn or "")


def parse(kind, text):
    t = text.split("|")
    if kind == "earn_prelim": return earn(t)
    if kind == "earn_notice": return dict(due=after(t, r"공시\s*예정일", want=day))
    if kind == "cancel":
        a = after(t, r"소각할 주식의 종류와 수"); b = after(t, r"발행주식\s*총수")
        return dict(ratio=a / b if a and b else None, pre_owned=any("기취득" in x for x in t))
    if kind == "buyback":
        return dict(amount=after(t, r"취득예정금액"), shares=after(t, r"취득예정주식"))
    if kind == "buyback_trust": return dict(amount=after(t, r"계약금액"))
    if kind == "dividend":
        ty = after(t, r"배당구분", want=lambda s: s if s in ("결산배당", "분기배당", "중간배당") else None)
        return dict(dps=after(t, r"1주당\s*배당금", stop=r"종류주식"), yield_pct=after(t, r"시가배당율|시가배당률", stop=r"종류주식"),
                    record=after(t, r"배당기준일", want=day), div_type=ty)
    if kind == "div_record": return dict(record=after(t, r"^기준일$", want=day, n=3))
    if kind == "bonus":
        return dict(per_share=after(t, r"1주당\s*신주배정\s*주식수"), record=after(t, r"신주배정기준일", want=day),
                    listing=after(t, r"신주의\s*상장\s*예정일", want=day))
    if kind == "split":
        return dict(record=after(t, r"신주의\s*상장\s*예정일|효력\s*발생일|신주권\s*교부\s*예정일", want=day))
    return {}


COLS = ["op", "op_yoy", "op_turn", "sales_yoy", "due", "ratio", "pre_owned", "amount", "shares",
        "dps", "yield_pct", "record", "div_type", "per_share", "listing"]


DDL = """CREATE TABLE IF NOT EXISTS event_details(rcept_no VARCHAR PRIMARY KEY, op DOUBLE, op_yoy DOUBLE, op_turn VARCHAR, sales_yoy DOUBLE,
         due DATE, ratio DOUBLE, pre_owned BOOLEAN, amount DOUBLE, shares DOUBLE, dps DOUBLE, yield_pct DOUBLE,
         record DATE, div_type VARCHAR, per_share DOUBLE, listing DATE)"""


def _rows(c, where="", args=()):
    out = []
    for r, k, text in c.execute(f"""SELECT d.rcept_no, d.kind, x.text FROM disclosures d JOIN documents x USING(rcept_no)
                                    WHERE x.text IS NOT NULL {where}""", list(args)).fetchall():
        try:
            p = parse(k, text)
        except Exception as e:
            print("파싱 실패", r, k, e); p = {}
        out.append([r] + [p.get(k2) for k2 in COLS])
    return out


def upsert_details(c, rcepts):
    """새로 받은 원문만 규모를 뽑아 넣는다 (장중 스캐너)."""
    c.execute(DDL)
    if not rcepts: return
    rows = _rows(c, f"AND d.rcept_no IN ({','.join('?' * len(rcepts))})", rcepts)
    c.executemany(f"INSERT OR REPLACE INTO event_details VALUES ({','.join('?' * (len(COLS) + 1))})", rows)


def build():
    c = duckdb.connect(DB)
    out = _rows(c)
    c.execute("DROP TABLE IF EXISTS event_details")
    c.execute(DDL)
    c.executemany(f"INSERT INTO event_details VALUES ({','.join('?' * (len(COLS) + 1))})", out)
    print(c.sql("""SELECT d.kind, count(*) n, count(op) op, count(op_yoy) yoy, count(due) due, count(ratio) ratio, count(amount) amt,
                   count(dps) dps, count(yield_pct) yld, count(record) rec, count(per_share) ps
                   FROM event_details e JOIN disclosures d USING(rcept_no) GROUP BY 1 ORDER BY 2 DESC"""))


if __name__ == "__main__":
    build()
