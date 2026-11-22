---
name: bulgaemi
description: Ellie trading 🍔 불개미 트레이드 위키 (햄버거 = 불개미 매매) — 햄버거 기법 요약(docs/wiki/bulgaemi/hamburger.md, 원본 스킬 hamburger)과 불개미 매매 영상(F:\트레이딩녹화)에서 종목별로 뽑은 '왜 사는지·어디서 사는지·왜 안 샀는지' 사례집(docs/wiki/bulgaemi)과 공통 원칙(근거 칸 세기·같은 환경 햄버거 비교·햄버거 압도 돌파·시간 매물 소화 돌파·첫날 윗꼬리 회피·추격 안 함). 불개미 영상의 특정 구간·종목 매매 관점 분석을 요청받거나, 종목이 '반드시 해야 할 종목'인지 판단하거나, 불개미 관점을 매매 전략에 쓸 때 사용. 분석 결과는 항상 위키에 저장.
---

# 불개미 트레이드 매매 관점 (D:\Ellie\trading)

## 1. 먼저 읽을 것
- `docs/wiki/bulgaemi/README.md` — 공통 원칙과 종목 사례 목록 (판단 전에 항상 읽음)
- `docs/wiki/bulgaemi/hamburger.md` — 햄버거 기법 요약 (불개미와 햄버거는 같은 매매, 2026-11-17 사용자)
- `docs/wiki/bulgaemi/cases/*.md` — 종목별 사례
- 햄버거(1분봉 거래대금) 숫자 규칙: 스킬 `hamburger`

## 2. 영상 구간 분석 순서
1. 구간 음성 추출: `ffmpeg -ss <시작-2초> -to <끝+2초> -i <영상> -vn -ac 1 -ar 16000 seg.wav`
2. 화면 추출: `ffmpeg -ss <시작> -to <끝> -i <영상> -vf "fps=1/6,scale=1600:-1" frames/f_%03d.jpg`
3. 받아쓰기: faster-whisper `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, CPU int8, `language="ko"`, 종목명·매매 용어를 `initial_prompt`로 줌. 2026-11-22 부터 프로젝트 `.venv`에 설치됨 — 이 환경의 `av` 와 버전이 안 맞아 파일 경로를 주면 오류 → 16kHz mono wav 를 `wave`+numpy 로 읽어 배열로 넘김. 96분 영상 CPU 약 40분. Windows 출력은 `PYTHONIOENCODING=utf-8`
   - 4K·60fps 영상은 `fps=1/6` 필터가 모든 프레임을 풀어 매우 느림 → `ffmpeg -skip_frame nokey -i 영상 -vf scale=1920:-1 -fps_mode passthrough k_%04d.jpg` (키프레임 약 4.2초 간격, k_N 시각 = (N−1)×4.1667초)
4. 화면은 말이 바뀌는 지점(사는 자리·비교 봉·동그라미 그린 순간) 위주로 열어 가격·시각·대금을 읽음. 받아쓰기의 종목명·숫자 오류는 화면으로 바로잡음
5. 날짜는 파일 이름보다 화면 속 차트 날짜를 따름

## 3. 저장 (항상)
- 종목 매매 관점을 분석하면 **항상** `docs/wiki/bulgaemi/cases/YYYY-MM-DD_종목명.md`로 저장함 (2026-11-17 사용자 요청)
- 항목: 출처·판정·태그 / 그날 숫자 / 고른 이유 / 햄버거 판정 / 사는 자리 / 안 산 이유 / 매매 전략으로 쓸 점
- `docs/wiki/bulgaemi/README.md`의 사례 목록 표에 한 줄 추가함. 새 원칙이 나오면 공통 원칙도 고침
- 문서 문체는 "임·됨·함"을 쓰고, 페이지 끝에 약어 풀이를 넣음
- 받아쓰기 원문은 `data/lectures/`(git 제외)에 둠
- 커밋은 사용자가 요청할 때 trading-ops 커밋 절차대로 함

## 4. 매매 판단에 쓰는 법
- 종목 근거를 **재료 · 일봉 신고가 · 끼 · 햄버거 · 프로그램** 칸으로 세어 4개 이상이면 '반드시' 후보로 봄
- 사는 자리 A(햄버거 압도 돌파) / B(시간 매물 소화 돌파) 중 어디에 해당하는지 확인함
- 피할 자리(첫날 윗꼬리 거래량, 약한 햄버거의 장 초 돌파, 놓친 돌파 추격)를 먼저 걸러 냄
- 사는 자리 D(낮은 구간 돌파 햄버거)·E(뉴스빵 → 수급주 전환 뒤 눌림)·F(상한가 → 쉼 → 더 센 햄버거)·G(빈집털이 일봉)도 확인함 (README 1-3)
- 고르기에서 먼저 거르는 것: 주도 섹터 밖(하루 최대 4개, 체급 비교), 테마 전체 프로그램 대량 매도, 신규주 상장 첫날, 끼를 다 쓴 뒤 눌림, 뉴스빵 첫 봉
- 사례 18건(2026-11-22). **2026-10-28 VOD 규칙을 숫자로 옮긴 영상 전략 V 는 1년 백테스트 3,653건 건당 −0.30%, ★ 없음** (`docs/wiki/bulgaemi/bulgaemi_1028_strategy.md`, 코드 `kiwoom_trading/backtest/bulgaemi_1028_bt.py`, 백테스트 전용). 영상 종목은 잘 잡지만 사람 판단 없이 기계로 쓰면 손실 → 실전·모의 규칙으로 바꾸지 않음. 바꾸려면 사용자 결정이 필요함 (executor-role)

## 5. 영상 전략 V 다시 돌리기
```bash
.venv\Scripts\python.exe -m kiwoom_trading.backtest.bulgaemi_1028_bt                 # 전 기간 H4·V·변형·조건식 필터 (약 1시간, 결과 data/bulgaemi_1028/)
.venv\Scripts\python.exe -m kiwoom_trading.backtest.bulgaemi_1028_bt --report        # 저장된 결과로 요약·재현율만
.venv\Scripts\python.exe -m kiwoom_trading.backtest.bulgaemi_1028_bt --day 2026-10-28  # 하루 신호·매매
```
- 새 VOD 를 분석하면 그날 영상 종목을 `VIDEO_TARGETS` 처럼 적어 재현율(영상 종목·시각을 규칙이 잡나)부터 봄. 영상 날 재현율이 높아도 1년 결과는 따로 확인함 (V 사례: 이틀 +19%, 1년 −1,098만)
