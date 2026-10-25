"""디앤서 후보를 지금 매매표 계좌에 넣었을 때 (1천만, 현금 공유, ⑦ 제외) — 다른 세션의 full_bt.py 계좌 엔진을 그대로 쓴다.

- ①~⑥ 매매 기록은 full_bt.py 가 만든 그대로 (다른 세션 계산).
- 🧭·🌙 는 full_bt.py 가 옛 dans_bars 자료(등락률을 1분봉 종가 ÷ 일봉 전일 종가로 계산 — 수정주가 섞임)로 만든 것이라 뺀다.
- 🌙(바로잡음) = t_closebet_rows.pkl: 그날 대금 10위·일봉 등락률 0~29.5%·애프터 거래, 17:00~17:59 첫 '정규장 종가 위' 봉 종가 → 다음 날 09:00.
- 새 후보 = t_closebet3_picks.pkl 14:30 판단 (그 시각 대금 10위·상승·애프터 거래) + 조건 → 14:31 시가 → 다음 날 09:00.
같은 날 같은 종목은 먼저 온 매매만 (full_bt 규칙).
"""
import os, pickle, sys, io
from datetime import time
sys.stdout.reconfigure(encoding="utf-8")
HERE = r"C:/Users/JUSTIC~1/AppData/Local/Temp/claude/D--Ellie-trading/d9b9b62e-44b0-49b3-ab2f-11c16d6072cf/scratchpad"
DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "danswer")
import shutil, tempfile
_copy = shutil.copy


def _safe_copy(s, d, *a, **k):
    """원본이 백필 등으로 잠겨 있으면 이미 만든 임시 복사본(엔진 복사본 포함)을 쓴다."""
    try:
        return _copy(s, d, *a, **k)
    except PermissionError:
        if os.path.exists(d): return d
        alt = os.path.join(tempfile.gettempdir(), "eng_" + os.path.basename(s))
        if os.path.exists(alt): return _copy(alt, d)
        raise


shutil.copy = _safe_copy
full = open(os.path.join(HERE, "full_bt.py"), encoding="utf-8").read().split('for lab, comp in (("고정')[0]
MARK = "# 같은 날 같은 종목은 먼저 온 매매만"
part1, part2 = full.split(MARK)            # 코드 검토: full_bt 는 옛 🧭·🌙 를 넣은 채 중복을 지워, 그 때문에 빠진 ①~⑥ 매매가 있었다
ns = {"__file__": os.path.join(HERE, "full_bt.py"), "__name__": "x"}
so = sys.stdout; sys.stdout = open(os.devnull, "w", encoding="utf-8")
exec(part1, ns)
ns["EV"] = [e for e in ns["EV"] if e[2] not in ("🧭 디앤서 종가", "🌙 종가 재돌파")]   # 중복 지우기 전에 옛 디앤서 매매를 뺀다
exec(MARK + part2, ns)
sys.stdout = so
KINDS = ns["KINDS"]; base = set(KINDS[:6]); ns["T7c"] = []
EV0 = list(ns["EV"])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import next_day_exits, P0, P1
rows = pickle.load(open(os.path.join(OUT, "t_closebet_rows.pkl"), "rb"))
picks = pickle.load(open(os.path.join(OUT, "t_closebet3_picks.pkl"), "rb"))
MOON, CAND = "🌙 종가 재돌파(바로잡음)", "🧭 14:30 주도주 종가 베팅"
moon = []
for x in rows:
    if x["nxt"] and x["p_rb"]:
        ex = next_day_exits(x["code"], x["date"], x["p_rb"])
        if "09:00 시가" in ex: moon.append((x["date"], (time(17, 30), x["rk"]), MOON, 1_000_000, ex["09:00 시가"], x["code"]))
CONDS = {"신고가": lambda p: p["newhi"], "신고가 또는 라운드": lambda p: p["newhi"] or p["rnd"],
         "고가 근처 + 신고가": lambda p: p["pos"] >= 0.8 and p["newhi"], "전부": lambda p: True}


def cand(cond):
    return [(p["date"], (time(14, 31), p["rank"]), CAND, 1_000_000, p["ex"]["09:00 시가"], p["code"])
            for p in picks if p["t"].startswith("14:30") and CONDS[cond](p) and "09:00 시가" in p["ex"]]


def run(extra, only, label):
    EV = sorted(EV0 + extra, key=lambda e: (e[0], e[1]))
    got, dedup = set(), []
    for e in EV:
        if e[5] is not None:
            if (e[0], e[5]) in got: continue
            got.add((e[0], e[5]))
        dedup.append(e)
    ns["EV"] = dedup
    out = []
    for comp in (False, True):
        eq, dd, curve, kinds, n, skip = ns["account"](comp, only)
        out.append(f"{'복리' if comp else '고정'} {eq / 1e4:6,.0f}만 낙폭 {dd * 100:4.1f}%")
        if comp: extra_txt = " · ".join(f"{k.split()[0]} {kinds[k] / 1e4:+.0f}만({n[k]})" for k in (MOON, CAND) if n[k])
    print(f"  {label:44s} {' | '.join(out)} | {extra_txt}")


print("계좌 1천만 (①~⑥ + 디앤서), ⑦ 제외, 다른 세션 full_bt 계좌 엔진")
run([], base, "①~⑥")
run(moon, base | {MOON}, "①~⑥ + 🌙(바로잡음)")
for c in CONDS:
    run(cand(c), base | {CAND}, f"①~⑥ + 14:30 {c}")
    run(moon + cand(c), base | {MOON, CAND}, f"①~⑥ + 🌙 + 14:30 {c}")
