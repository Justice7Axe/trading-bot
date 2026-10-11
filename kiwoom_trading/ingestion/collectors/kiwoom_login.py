import json

import requests


def fetch_kiwoom_access_token(base_url: str, app_key: str, secret_key: str) -> str:
    url = f"{base_url.rstrip('/')}/oauth2/token"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "api-id": "au10001",
    }
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key,
    }

    response = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
    response.raise_for_status()
    data = response.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"키움 토큰 발급 실패: {data}")
    return token
