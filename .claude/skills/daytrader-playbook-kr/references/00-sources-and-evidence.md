# 출처와 검증 수준 (정리일: 2026-10-24)

이 스킬의 규칙은 아래 공개 자료에서 뽑은 것이다. 트레이더 본인이 공개한 '원칙'을 백테스트 가능한 숫자로 바꾸는 과정에서 많은 가정이 들어갔다.
각 전략 문서와 코드의 **[S] = 출처에 있는 규칙**, **[A] = 구현을 위한 가정(튜닝 대상)** 표시를 지켜라.

## 선정 배경
"실계좌 검증 + 현재 활동 + 기법 공개 + 한국 시장 적용 가능 + 위험 신호 적음" 기준으로 World Cup Trading Championship, US Investing Championship, 중국 期货日报 实盘大赛, 키움 영웅전 등 실계좌 대회와 Market Wizards 인터뷰를 비교해 골랐다.
- 한국 주식 단타: **Lance Breitstein** (메인) + **丁伟锋(沙漠草)** 의 시간/패턴 규칙
- 해외선물·지수선물: **Fabio Valentini** (1순위), **David Trullas Vila** (코드 검증용)

## 1. Lance Breitstein (미국 주식 데이트레이더)
- 실적: Trillium 에서 순이익 $46M, 이후 개인계좌 5년 $71M (Jack Schwager, *Market Wizards: The Next Generation*, 2026 인터뷰 기반 정리)
  - https://www.ft.wtf/p/trading-setups-of-lance-breitstein
- 규칙 출처
  - 재료(뉴스)로 움직이는 in-play 종목만: https://timelessmarkettheory.com/traders/lance-breitstein
  - "VWAP 아래 꾸준히 있으면 롱 금지, 위에 꾸준히 있으면 숏 금지, 단 capitulation 은 예외", 다중 시간대 정렬, 추세 순응: https://traderlion.com/investing-champions/lance-breitsteins-simple-setup-that-made-millions/
  - Capitulation: Day A·B·C 3일 연속 대량 거래 급변 후 Day D 더 큰 거래량의 큰 갭 -> 반전 탐색 (원문은 상승 과열 예시, 하락 투매에도 같은 논리 적용): ft.wtf 위 링크
  - "V자의 오른쪽": 떨어지는 칼을 잡지 말고 소진·반전 확인 후 역추세 진입; A~D 등급과 지수적 비중: timelessmarkettheory 위 링크
- 검증 수준: 높음(Market Wizards 인터뷰). 단, 구체적 숫자 기준(등락률, RVOL 등)은 공개되지 않음 -> 전부 [A].

## 2. 丁伟锋 "沙漠草" (중국 선물 데이트레이더)
- 실적: 期货日报 全国期货实盘交易大赛 제9회 경량조 우승, 반년 순자산가치 2827.57, 최대낙폭 8.31% (대회는 수익+낙폭 종합점수)
- 규칙 출처
  - 큰 그림(일봉)으로 방향, 작은 시간대로 매매 / 개장 첫 5분 범위 위면 롱 우위, 아래면 숏 우위 / 박스·삼각수렴·M·W 패턴 '완성 후' 진입 / 손절은 패턴 고저점 / 반대 패턴 출현 시 청산: https://www.7hcn.com/article/467779-1.html
  - 장 시작 15분·마감 전 15분 매매 회피, 1회 손실 계좌 3% 미만, 장중 움직임의 20% 정도만 읽힌다: http://www.809030.com/futures/68999.html
  - 상승 시 5분봉 거래량은 고르게 늘어야 하고 갑작스런 거대 거래량은 끝의 신호: https://www.sina.cn/news/detail/5152344091394617.html
- 검증 수준: 중간. 우승은 2015년 전후, 이후 기록(4관왕, 무낙폭 200일 등)은 본인 주장.

## 3. Fabio Valentini (나스닥 선물 오더플로우 스캘퍼)
- 실적: World Cup 분기 선물 데이트레이딩 2023 Q4 2위(68.6%), 2024 Q1 3위(89.5%), 2024 Q4 2위(218.3%), 2025 Q1 3위(169.7%)
  - https://www.worldcupchampionships.com/world-cup-trading-championship-historical-standings
- 규칙 출처
  - 경매시장이론(AMT): 균형/불균형 판정 후 Direction·Location·Aggression 3단계, 풋프린트·CVD·가치영역·체결속도·흡수: https://www.chartacademy.com/instructors/fabio-valentini
  - 트레이드당 0.25~0.5%, 하루 최대 3패: https://isyourtraderreal.com/trader/fabervaale
  - 가치 이동으로 방향, 델타·흡수로 공격성 확인, LVN 레벨, '1:1 여러 번 쌓기 > 홈런 1번': https://www.longcut.ai/v/world-s-1-scalper-just-gave-away-his-entire-new-strategy-for-free-live-on-chart-HUYBdYnXUNc
- 검증 수준: 대회 기록은 공식. 단 경력 4년 남짓, Deep Charts 공동창업자(상업적 이해관계).
- **한계**: 진짜 오더플로우(호가 주체별 체결)는 틱 데이터가 필요하다. 1분봉 OHLCV 로는 근사만 가능 -> F1 결과는 '하한 근사치'로 해석.

## 4. David Trullas Vila (선물 데이트레이더)
- 실적: World Cup 분기 선물 데이트레이딩 2025 Q2(712.1%)부터 2026 Q3(1,350.8%, 감사 대기)까지 6분기 연속 1위
  - https://www.worldcupchampionships.com/world-cup-trading-championship-standings
- 규칙 출처: MACD·RSI·거래량·피보나치, 일반/히든 다이버전스, "다이버전스 1개당 1계약": https://www.youtube.com/watch?v=0W7EYXrDRBc (Rankia Markets Valencia 2026 강연)
- **할인 요인**: 분기 대회 최소계좌 $2,500, 여러 계좌 중 최고 계좌만 순위 반영, 수익률만 평가(낙폭 페널티 없음): https://completetradersedge.com/world-cup-trading-championships/
  상위권에 안도라 참가자가 몰려 있으나 관계는 미확인. 계좌 규모·레버리지 비공개.
- 쓰임새: 지표 기반이라 '코드로 검증하기 쉬운' 기준 전략으로 사용.

## 대회 수익률 해석 원칙
- 대회 % 는 소액 계좌·고레버리지·최고 계좌만 반영된 숫자일 수 있다. 실력 근거로는 '반복 입상'과 '낙폭'을 더 중시한다.
- 이 스킬의 어떤 전략도 한국 시장에서 검증된 적이 없다. 백테스트 -> 모의/소액 검증 전에는 실전 금지.
