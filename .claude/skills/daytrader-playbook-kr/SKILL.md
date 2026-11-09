---
name: daytrader-playbook-kr
description: 글로벌 검증 데이트레이더(Lance Breitstein, 丁伟锋, Fabio Valentini, David Trullas Vila)의 기법을 한국 주식 단타·지수선물·해외선물(NQ)용 규칙으로 정리하고 1분봉 백테스트하는 스킬. 데이트레이딩 전략 백테스트, 전략 규칙 설명, 파라미터 민감도·표본외 검증, 백테스트 리포트 작성, 매매 계획을 이 규칙에 맞춰 점검할 때 사용. 키워드: Breitstein, VWAP 눌림, 투매 반등, capitulation, 丁伟锋, 개장 5분 범위, 박스 돌파, W바닥, Fabio, 오더플로우, 볼륨 프로파일, Trullas, 다이버전스, 피보나치, 코스피200 선물, MNQ.
---

# 데이트레이더 플레이북 (한국 시장 적용 + 백테스트)

이 스킬은 투자 자문이 아니다. 공개된 트레이더 기법을 **검증 가능한 규칙**으로 바꾸고, 한국 시장 비용·제도를 넣어 **백테스트로 반증**하는 도구다.
모든 전략은 한국 시장에서 미검증 상태다. 합격 기준을 통과하기 전에는 실전 매매를 권하지 마라.

## 전략 지도

| 시장 | 역할 | 전략 ID | 트레이더 | 명세 문서 |
|---|---|---|---|---|
| 한국 주식 | 메인 | `kr_s1_inplay_vwap_pullback` | Breitstein (재료주 VWAP 추세 눌림) | references/10-kr-stock-strategies.md |
| 한국 주식 | 메인 보조 | `kr_s2_capitulation_reversal` | Breitstein (투매 후 V자 오른쪽) | 같은 문서 |
| 한국 주식 | 시간·패턴 규칙 | `kr_s3_orb5_pattern` | 丁伟锋 (개장 5분 방향 + 패턴 완성 돌파) | 같은 문서 |
| 선물 (NQ/MNQ, K200F) | 1순위 | `fut_f1_fabio_amt_proxy` | Fabio Valentini (경매이론 오더플로우, 1분봉 근사) | references/20-futures-strategies.md |
| 선물 | 코드 검증용 | `fut_f2_trullas_divergence` | Trullas Vila (MACD/RSI 다이버전스 + 피보나치) | 같은 문서 |

한국 주식 단타의 공통 규칙: 09:00~09:15·15:05 이후 신규 진입 금지(丁伟锋), 트레이드당 0.5%, 하루 3패 중단(Fabio), 롱 전용, 15:15 전량 청산.
출처와 검증 수준: references/00-sources-and-evidence.md. 제도·비용: references/30-kr-market-structure.md.

## 반드시 지킬 규칙
1. 작업 전에 해당 전략 명세 문서와 references/40-backtest-protocol.md 를 읽는다.
2. 표시 규칙: **[S]** 는 트레이더 출처 규칙(바꾸지 않음), **[A]** 는 구현 가정(튜닝 가능). 코드 `DEFAULTS` 주석과 문서 표가 같은 표시를 쓴다. [S] 를 바꾸면 "원 기법이 아닌 변형"이라고 리포트에 명시.
3. 룩어헤드 금지, 비용 포함, 보수적 체결 (engine.py 상단 주석). 엔진이나 전략 코드를 고치면 `python scripts/selftest.py <작업폴더>` 를 다시 통과시킨다.
4. IS/OOS 경계를 먼저 정하고 기록. 그리드 탐색은 IS 에서만 (`--grid` 는 자동으로 IS 만 사용). OOS 는 최종 1회.
5. 합성 데이터(`make_sample_data.py`) 결과로 수익성을 말하지 않는다.
6. 데이터에 없는 정보(catalyst, VI, buy/sell volume)는 근사했다고 리포트에 명시한다.

## 작업 절차
1. **데이터 점검**: 컬럼(datetime, symbol, OHLCV + 선택 컬럼), 타임스탬프 라벨(시작/종료 -> `--label`), 세션 시간, 수정주가, 상장폐지 종목 포함 여부, 결측 분. 문제를 먼저 사용자에게 보고.
2. **엔진 확인**: `python scripts/selftest.py <작업폴더>`.
3. **기준선**: 전략별 기본 파라미터로 `run_backtest.py --split <IS 종료일>` 실행, `results/<전략>_base/` 저장.
4. **민감도**: IS 에서 2~3개 [A] 파라미터 그리드. 평평한 구간을 고른다.
5. **확정 실행**: 고른 값으로 IS+OOS 1회, `--slippage 2`, `--slippage 3` 비용 민감도.
6. **분해 분석**: trades.csv 로 등급(S1)·패턴(S3)·모델(F1)·다이버전스 종류/개수(F2)·시간대·요일별 기대값 R.
7. **리포트**: references/40-backtest-protocol.md 4절 형식으로 사용자에게 한국어 보고. 합격이면 모의투자 계획, 불합격이면 원인 가설.

## 명령 요약
```
python scripts/selftest.py results/_selftest
python scripts/run_backtest.py --strategy kr_s1_inplay_vwap_pullback --instrument KRX_STOCK --data "data/kr_1m/*.csv" --out results/s1_base --split 2025-12-31
python scripts/run_backtest.py --strategy kr_s1_inplay_vwap_pullback --instrument KRX_STOCK --data "data/kr_1m/*.csv" --out results/s1_grid --split 2025-12-31 --grid pullback_atr=0.3,0.5,0.8 --grid min_rvol=2,3,5
python scripts/run_backtest.py --strategy fut_f1_fabio_amt_proxy --instrument MNQ --data data/mnq_1m.csv --out results/f1_base --split 2025-12-31
python scripts/run_backtest.py --strategy fut_f2_trullas_divergence --instrument K200F --data data/k200f_1m.csv --out results/f2_risk --set sizing='"risk"'
```
옵션: `--set key=value`(JSON 값), `--params file.json`, `--equity`, `--risk`(%), `--slippage`, `--fee-rate`, `--label end`, `--criteria file.json`,
`--daily daily.csv`(일봉으로 hist·전일 종가), `--universe universe.csv`(날짜별 매매 대상, 장 전에 알 수 있는 목록만), `--per-file`(월별 CSV 를 하나씩 읽어 메모리 절약).
1분봉 CSV 에 `rvol_base` 컬럼이 있으면 같은 시각 RVOL 기준을 1분봉 이력 대신 그 값으로 쓴다.

### Ellie trading 저장소 데이터로 돌리기
1분봉이 '그날·전날 대금 상위 200' 만 있어 띄엄띄엄하므로 변환 스크립트가 일봉·대상 종목·RVOL 기준을 따로 만든다.
```
.venv\Scripts\python.exe -m kiwoom_trading.analysis.playbook_export          # data/playbook_kr/ 에 월별 CSV·daily.csv·universe.csv
python scripts/run_backtest.py --strategy kr_s1_inplay_vwap_pullback --instrument KRX_STOCK --data "data/playbook_kr/minute/kr_1m_*.csv" --per-file --daily data/playbook_kr/daily.csv --universe data/playbook_kr/universe.csv --split 2026-04-30 --out data/playbook_kr/results/s1_base
```
- 매매 대상 = 전날 대금 상위 200 (그날 상위를 섞으면 결과가 부푼다). 통합(AL) 1분봉, 09:00~15:19.
- 전일 종가 = 전날 15:30 종가 단일가 봉 (일봉 종가가 애프터마켓 가격인 날이 있음).
- RVOL 기준 = 20일 평균 정규장 거래량 × 시장 평균 시각별 누적 비중 [A] (비중은 전체 기간 평균이라 리포트에 근사라고 적는다).
- 학습/검증 경계 2026-04-30 (2026-10-25 첫 실행 전에 정함).
- 재료(catalyst)·VI 컬럼 없음 → S1 은 가격·거래량 근사, VI 는 정적 VI 근사.
- Windows 터미널 한글 출력은 `PYTHONIOENCODING=utf-8` 을 붙여 실행.
출력: `report.md`, `trades.csv`, `summary_in_sample.json`, `summary_out_of_sample.json`, (그리드) `grid_in_sample.json`.

## 파일 구조
- `config/instruments.json` 상품별 호가·승수·수수료·세금·세션 (가정값은 `_verify` 표시)
- `config/backtest_defaults.json` 포트폴리오 규칙 (리스크%, 최대 포지션, 하루 3패, 일 손실 한도)
- `scripts/data.py` 로더·일자 컨텍스트(전일종가, 일봉 히스토리, 같은 시각 RVOL 기준, 전일 세션 바)
- `scripts/indicators.py` VWAP, ATR, RSI, MACD, 피벗, 델타, 볼륨 프로파일
- `scripts/engine.py` 체결 시뮬레이션, 포트폴리오, 지표, 합격 판정, 리포트
- `scripts/strategies.py` 5개 전략 (`REGISTRY`)
- `scripts/run_backtest.py` CLI, `scripts/selftest.py` 스모크 테스트, `scripts/make_sample_data.py` 합성 데이터

## 확장 가이드
- 새 전략: `Strategy` 상속, `DEFAULTS` 에 [S]/[A] 주석, `plans_for_day` 에서 `simulate_exit` 사용, `REGISTRY` 등록, 명세 문서에 표 추가, selftest 통과.
- 틱 데이터가 생기면 F1 의 `bar_delta` 를 실제 체결 주체 델타로, LVN/흡수 판정을 틱 기반으로 교체.
- 실시간 신호/주문 연동은 이 스킬 범위 밖. 백테스트 합격 + 모의투자 검증 후 별도 설계.
