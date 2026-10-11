"""텔레그램 봇 메시지 전송.

.env.local 에 아래 두 값이 필요하다 (upbit/upbit_trend_alert-*.py 템플릿과 같은 이름).
    TELEGRAM_TOKEN=123456:ABC...   # @BotFather 에서 발급
    TELEGRAM_CHAT_ID=123456789     # 봇에게 메시지를 보낸 뒤 https://api.telegram.org/bot<TOKEN>/getUpdates 에서 확인
"""
import logging
import os

import requests

from kiwoom_trading.common.daily_store import load_env


MAX_MESSAGE_LENGTH = 4000  # 텔레그램 한도 4096자, 여유를 둔다


def _split(text: str) -> list[str]:
    """줄 단위로 4,000자 이하 조각으로 나눈다."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > MAX_MESSAGE_LENGTH and current:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def is_configured() -> bool:
    load_env()
    return bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_telegram_message(text: str) -> bool:
    """전송 성공 시 True. 설정이 없거나 실패하면 로그만 남기고 False (수집 작업을 멈추지 않는다)."""
    load_env()
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logging.warning("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID 가 .env.local 에 없어 텔레그램 전송을 건너뜀")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        for chunk in _split(text):
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"},
                timeout=15,
            )
            if not response.ok:
                logging.error("텔레그램 전송 실패: status=%s body=%s", response.status_code, response.text[:300])
                return False
    except requests.RequestException as exc:
        logging.error("텔레그램 전송 오류: %s", exc)
        return False
    logging.info("텔레그램 전송 완료 (%s자)", len(text))
    return True
