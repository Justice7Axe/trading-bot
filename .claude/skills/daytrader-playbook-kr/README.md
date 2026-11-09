# daytrader-playbook-kr 설치·사용 안내 (사용자용)

## 무엇인가
Claude Code 용 스킬 폴더다. 넣어두면 Claude Code 가 "데이트레이딩 백테스트", "Breitstein 전략", "Fabio 오더플로우" 같은 요청에서 자동으로 `SKILL.md` 를 읽고 규칙·코드를 사용한다.
- 한국 주식 단타: Breitstein 메인(S1 VWAP 눌림, S2 투매 반등) + 丁伟锋 시간·패턴 규칙(S3)
- 해외선물/지수선물: Fabio Valentini(F1, 1순위), Trullas Vila(F2, 코드 검증용)
- 백테스트 엔진: 파이썬 표준 라이브러리만 사용 (pandas 불필요). 비용·VI·가격제한·보수적 체결 반영.

## 설치
1. 이 폴더(`daytrader-playbook-kr`) 전체를 복사한다.
   - 모든 프로젝트에서 쓰기: `%USERPROFILE%\.claude\skills\daytrader-playbook-kr\`
   - 특정 프로젝트에서만: `<프로젝트>\.claude\skills\daytrader-playbook-kr\`
2. Claude Code 를 다시 시작한다.
3. 확인: Claude Code 에 "daytrader-playbook-kr 스킬의 selftest 실행해줘" 라고 요청 -> `SELFTEST PASSED` 가 나오면 정상.

## Claude Code 에 줄 첫 요청 예시
- "daytrader-playbook-kr 스킬 읽고, 전략 5개를 내 말로 요약해줘. [S]/[A] 구분해서."
- "data/kr_1m 폴더 1분봉으로 kr_s1 기준선 백테스트 돌려줘. IS 는 2025-12-31까지. 데이터 점검부터."
- "kr_s1 을 IS 에서 pullback_atr, min_rvol 그리드로 민감도 보고 평평한 구간 골라서 OOS 1회 돌려줘. 슬리피지 2·3틱도."
- "키움(또는 KIS) API 로 코스닥 1분봉 받아서 이 스킬 CSV 형식으로 저장하는 스크립트 만들어줘. 상장폐지 종목 포함."
- "MNQ 1분봉으로 F1, F2 돌려서 모델별/다이버전스 종류별로 쪼개서 보여줘."

## 준비해야 할 데이터
- 1분봉 CSV: `datetime,symbol,open,high,low,close,volume` (+ 선택: value, catalyst, vi, buy_volume, sell_volume, prev_close)
- 한국 주식은 수정주가, 상장폐지 종목 포함 권장. 재료(catalyst) 시각 데이터가 있으면 S1 이 원 기법에 더 가까워진다.
- 선물은 가능하면 체결 주체(buy/sell) 거래량 포함. 없으면 F1 은 근사치.

## 꼭 알아둘 것
- 모든 전략은 한국 시장에서 검증된 적 없다. 합격 기준(OOS 기대값 +0.1R 이상, PF 1.2 이상, MDD 15% 이하, 상위 5개 제외해도 흑자)을 넘기 전엔 실전 금지.
- 수수료(편도 0.015%)와 미니 선물 명세는 가정값이다. `config/instruments.json` 에서 본인 값으로 바꿔라.
- 증권거래세 0.20%(2026년~), VI·호가단위는 2026-10-24 확인 기준.
- 합성 데이터 결과는 의미 없다. 실제 데이터로만 판단.
