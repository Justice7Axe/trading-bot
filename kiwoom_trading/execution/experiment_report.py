"""🧪 실험 모의 매매 리포트 — 매일 15:42 가상 장부 마감 묶음에 붙여 보낸다 (2026-10-27 사용자: "실험 모의 매매는 계속하되 결과 리포팅도 매일").

실험 = 1년 검증에서 아직 근거가 없거나 약한데 모의로 계속 돌려 보는 매매:
  🎯 주도주 모양 (1년 −0.46%) · 🎯 장 초 공통점 (뒤 기간 −) · 🎯 대형주 수급 (11-06 판단) · 🍔 햄버거 · 🎯 인버스 갭 (가설)
오늘 끝난 매매와 처음부터 누적(건수·이긴 건·합계 원·건당), 오늘 못 산 이유 상위를 보인다. 손익 = 매도가 − 매수가 (먼저 판 절반 포함) − 매수 금액 × 0.25%.
"""
from datetime import date

KINDS = ("주도주 모양", "장 초 공통점", "대형주 수급", "햄버거", "인버스 갭")
COST = 0.0025


def _pnl(q, b, s, pq, pp) -> float:
    return (s - b) * (q - pq) + ((pp or s) - b) * pq - q * b * COST


def build(conn, day: date) -> str:
    lines = [f"🧪 실험 모의 매매 {day:%m-%d} (모의 계좌 안, 1년 근거 약함 — 계속 지켜봄)"]
    for k in KINDS:
        rows = conn.execute("""SELECT date, name, qty, buy_price, sell_price, coalesce(part_qty, 0), part_price, sell_reason
                               FROM paper_trades WHERE kind = ? AND status = 'closed' AND buy_price IS NOT NULL AND sell_price IS NOT NULL""",
                            [k]).fetchall()
        allp = [_pnl(q, b, s, pq, pp) for _, _, q, b, s, pq, pp, _ in rows]
        today = [(n, _pnl(q, b, s, pq, pp), s / b - 1, why) for d, n, q, b, s, pq, pp, why in rows if d == day]
        held = conn.execute("SELECT count(*) FROM paper_trades WHERE kind = ? AND status IN ('open', 'ordered', 'selling')", [k]).fetchone()[0]
        skip = conn.execute("""SELECT count(*) FROM paper_trades WHERE kind = ? AND date = ? AND status IN ('skipped', 'failed')""",
                            [k, day]).fetchone()[0]
        cum = (f"누적 {len(allp)}건 · 이긴 {sum(p > 0 for p in allp)} · 합계 {sum(allp):+,.0f}원 · 건당 {sum(allp) / len(allp):+,.0f}원"
               if allp else "누적 끝난 매매 없음")
        lines.append(f"• {k}: {cum}" + (f" · 보유 {held}" if held else "") + (f" · 오늘 못 삼 {skip}" if skip else ""))
        for n, p, r, why in today:
            lines.append(f"    오늘 {n} {r:+.1%} ({p:+,.0f}원, {why})")
    return "\n".join(lines)
