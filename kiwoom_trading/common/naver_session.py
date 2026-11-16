"""네이버 로그인 쿠키를 '우리 전용 크롬 프로필'에서 저절로 받아 오기 (2026-11-16 사용자 '쿠키를 알아서 갱신하도록').

왜: .env.local 에 손으로 넣은 NID_AUT·NID_SES 는 평소 쓰는 브라우저와 같은 로그인이라, 그쪽에서 로그아웃하거나
네이버가 세션을 정리하면 끊김 (2026-11-16 07:50 하루도 안 돼 끊김). 그래서 카페 읽기 전용 크롬 프로필
(data/naver_profile, 평소 크롬과 따로)을 하나 두고, 사용자가 처음 한 번만 그 창에서 직접 로그인('로그인 상태 유지' 체크)하면
그 뒤로는 매일 이 프로필을 화면 없는 크롬으로 열어 네이버를 한 번 둘러보고 쿠키를 받아 .env.local 에 저장함.
크롬이 진짜 브라우저처럼 세션을 이어 가므로 손으로 넣은 쿠키보다 오래 감.

비밀번호는 코드가 다루지 않음 — 처음 로그인은 사용자가 크롬 창에서 직접 함 (자동 입력·저장 없음).
쿠키 값은 로그에 남기지 않음.

    python -m kiwoom_trading.common.naver_session --login     # 처음 한 번: 크롬 창이 뜨면 직접 로그인 (10분 기다림)
    python -m kiwoom_trading.common.naver_session             # 지금 쿠키 받아 .env.local 에 저장 (화면 없음)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Optional

from kiwoom_trading.common.daily_store import PROJECT_ROOT

PROFILE_DIR = os.path.join(PROJECT_ROOT, "data", "naver_profile")
LOGIN_URL = "https://nid.naver.com/nidlogin.login?mode=form&url=https%3A%2F%2Fwww.naver.com"
CHECK_URL = "https://nid.naver.com/user2/help/myInfo?lang=ko_KR"
CHROME_PATHS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class NoLogin(RuntimeError):
    """전용 프로필에 로그인이 안 돼 있음 → `--login` 한 번 필요."""


def chrome_path() -> str:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return found
    raise RuntimeError("크롬(또는 엣지)을 못 찾음")


def has_profile() -> bool:
    return os.path.isdir(os.path.join(PROFILE_DIR, "Default"))


class _Chrome:
    """전용 프로필로 크롬을 띄우고 개발자 도구 연결(CDP)로 쿠키를 읽음."""

    def __init__(self, url: str, headless: bool):
        os.makedirs(PROFILE_DIR, exist_ok=True)
        port_file = os.path.join(PROFILE_DIR, "DevToolsActivePort")
        try:
            os.remove(port_file)
        except OSError:
            pass
        args = [chrome_path(), f"--user-data-dir={PROFILE_DIR}", "--remote-debugging-port=0", "--no-first-run",
                "--no-default-browser-check", "--disable-sync"]
        if headless:
            args += ["--headless=new", "--window-size=1200,900"]
        self.proc = subprocess.Popen(args + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):                       # 크롬이 포트 파일을 쓸 때까지 (최대 10초)
            if os.path.exists(port_file):
                try:
                    self.port = int(open(port_file).read().split()[0])
                    break
                except Exception:
                    pass
            time.sleep(0.1)
        else:
            self.close()
            raise RuntimeError("크롬 개발자 도구 포트를 못 받음 (같은 프로필 크롬이 이미 떠 있는지 확인)")
        ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=5))
        import websocket
        self.ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
        self._id = 0

    def call(self, method: str, **params) -> dict:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                return msg.get("result") or {}

    def cookies(self) -> dict[str, str]:
        res = self.call("Storage.getCookies")
        return {c["name"]: c["value"] for c in res.get("cookies", [])
                if c.get("domain", "").endswith("naver.com") and c["name"] in ("NID_AUT", "NID_SES")}

    def page_url(self) -> str:
        try:
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=5))
            return next((p.get("url", "") for p in pages if p.get("type") == "page"), "")
        except Exception:
            return ""

    def close(self) -> None:
        try:
            self.call("Browser.close")
        except Exception:
            pass
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def _save(ck: dict[str, str]) -> None:
    from kiwoom_trading.common.cafe_universe import save_env
    save_env({"NAVER_NID_AUT": ck["NID_AUT"], "NAVER_NID_SES": ck["NID_SES"]})


def refresh(wait: float = 6.0) -> dict[str, str]:
    """화면 없는 크롬으로 전용 프로필을 열어 네이버 내 정보 화면을 둘러본 뒤 쿠키를 받아 .env.local 에 저장.
    로그인 안 돼 있으면 NoLogin."""
    if not has_profile():
        raise NoLogin("전용 크롬 프로필이 없음 — `python -m kiwoom_trading.common.naver_session --login` 한 번 필요")
    ch = _Chrome(CHECK_URL, headless=True)
    try:
        time.sleep(wait)                           # 페이지가 열리며 세션 쿠키가 새로 써질 시간
        ck, url = ch.cookies(), ch.page_url()
    finally:
        ch.close()
    if "login" in url.lower() or not (ck.get("NID_AUT") and ck.get("NID_SES")):
        raise NoLogin("전용 크롬 프로필 로그인이 풀림 — `--login` 으로 다시 로그인 필요")
    _save(ck)
    logging.info("네이버 쿠키: 전용 크롬 프로필에서 받아 .env.local 에 저장")
    return ck


def login(timeout: float = 600.0) -> dict[str, str]:
    """크롬 창(전용 프로필)을 띄워 사용자가 직접 로그인할 때까지 기다림 ('로그인 상태 유지' 체크 권장). 비밀번호는 코드가 안 봄."""
    ch = _Chrome(LOGIN_URL, headless=False)
    print("크롬 창에서 네이버에 직접 로그인해 주세요 ('로그인 상태 유지' 체크). 로그인되면 창이 저절로 닫힙니다.", flush=True)
    try:
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(3)
            ck = ch.cookies()
            if ck.get("NID_AUT") and ck.get("NID_SES") and "nidlogin" not in ch.page_url():
                time.sleep(2)
                ck = ch.cookies()
                _save(ck)
                print("로그인 확인 — 쿠키를 .env.local 에 저장함", flush=True)
                return ck
        raise NoLogin("로그인을 기다리다 시간이 지남")
    finally:
        ch.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="네이버 쿠키를 전용 크롬 프로필에서 받기")
    ap.add_argument("--login", action="store_true", help="처음 한 번: 크롬 창에서 직접 로그인")
    a = ap.parse_args()
    try:
        login() if a.login else refresh()
        print("완료")
    except NoLogin as exc:
        print(f"로그인 필요: {exc}")


if __name__ == "__main__":
    main()
