"""📋 오늘의 트레이딩 전략 — 매일 아침 스캐너가 켜질 때 텔레그램으로 먼저 보내는 시장 상황별 매매 전략표
(2026-10-25 사용자: "매일 아침 스캔 돌 때 매매표를 우선 띄워줘", 번호는 원 숫자 대신 크게 보이는 1️⃣~7️⃣, 이름은 '매매표' → '트레이딩 전략').

    .venv\\Scripts\\python.exe -m kiwoom_trading.screener.playbook_card --send     # 지금 한 번 보내기 (시험)
"""
import argparse
import os
import sys
from datetime import date
from typing import Optional

if __package__ is None or __package__ == "":
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

TABLE = """📋 오늘의 트레이딩 전략 — 시장 상황별 ({day:%m-%d})
09:10 시장 판정(코스피 ±1σ · 대금 상위 중앙값) 뒤 그날 상황에 맞는 매매만 산다.
{trend}

🟢 강한 상승장
  1️⃣ 상승장 장 초 — 09:10 대금 40위 시가 위 · 장중 익절 없이 다음 날 시가 매도 (−4% 손절)
  3️⃣ 막힌 고점 돌파 — 5일 고가 09:30 전 돌파 · +7% −5%
  6️⃣ 주도주 신고가 — 대금 10위 & 52주 신고가 · 장중 익절 없이 다음 날 시가 매도 (−4% 손절)
  2️⃣ 저항 돌파 — 🧱 후보 돌파 · +7% −5%
🔵 상승 흐름 보통 날
  3️⃣ 막힌 고점 돌파 (+7% −3%) · 6️⃣ 주도주 신고가 · 2️⃣ 저항 돌파
🟠 하락 흐름 보통 날
  5️⃣ 약세장 인버스 — 09:11 TIGER 인버스 · +5% −3% · 2️⃣ 저항 돌파
🔴 강한 하락장
  4️⃣ 역행 강세 종가 — 15:15 대금 30위 시장보다 +3%p · 다음 날 시가 · 2️⃣ 저항 돌파
⚪ 모든 날
  7️⃣ 주도주 추세 — 52주 신고가 & 대금 5위 & 외인·기관 양매수 → 20일선 이탈까지 (몫 300만)
  🌙 종가 재돌파 — 17~18시 애프터 종가 위 (가상) · 🧭 디앤서 종가 체크리스트 (알림만)
※ 따로 표시 없으면 못 닿으면 다음 날 09:00 매도

💼 계좌
  🔴 실전: {real}
  🧪 모의(1천만): 위 트레이딩 전략 그대로 · 💰 10만 원 가상: 6️⃣→2️⃣→5️⃣ 먼저 온 신호에 전액"""


US_NOTE = ("  간밤 미국 방향 → 코스피 시가 상승 출발 비율(5년): 모두 상승 84% · 혼조 57% · 모두 하락 26%\n"
           "  (시가 이후 흐름과는 무관 — 매매 신호는 그대로, 참고용)")


def build_card(day: date, trend_text: Optional[str] = None, real_mode: str = "", us_text: Optional[str] = None,
               real_line: Optional[str] = None) -> str:
    real = {"combo": "1️⃣2️⃣5️⃣6️⃣7️⃣📕4️⃣🌙 신호마다 종목당 3만 원(넘으면 1주) · 엄격 선정 · 15:45 실전 성과 리포트 (2026-10-30)",
            "inverse": "5️⃣ 약세장 인버스만 (10만 원 + 실현 손익)"}.get(real_mode, "꺼짐")
    trend = f"큰 흐름: {trend_text}" if trend_text else ""
    if us_text:
        trend = (trend + "\n" if trend else "") + us_text + "\n" + US_NOTE
    card = TABLE.format(day=day, trend=trend, real=real).replace("\n\n\n", "\n\n")
    return (real_line + "\n\n" + card) if real_line else card   # 🔴 실전 누적 한 줄을 맨 위에 (2026-10-30 사용자 '실전 성과가 눈에 안 띈다')


def main() -> None:
    from kiwoom_trading.common.config import KST
    from datetime import datetime
    from kiwoom_trading.execution import real as real_inverse
    parser = argparse.ArgumentParser(description="오늘의 트레이딩 전략")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    today = datetime.now(KST).date()
    trend = None
    try:
        from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
        from kiwoom_trading.screener.market_regime import MarketRegime
        trend = MarketRegime([], client=build_client(), today=today).trend_text()
    except Exception:
        pass
    from kiwoom_trading.common import us_market
    ov = us_market.fetch(today)
    card = build_card(today, trend, real_inverse.mode(), ov.text() if ov else None)
    print(card)
    if args.send:
        from kiwoom_trading.common.telegram import send_telegram_message
        send_telegram_message(card)


if __name__ == "__main__":
    main()
