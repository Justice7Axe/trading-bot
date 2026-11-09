# 선물 전략 명세 (Fabio Valentini 1순위, Trullas Vila 코드 검증용)

대상: NQ/MNQ (CME, 미 동부시간 RTH 09:30~16:00), 코스피200 선물 K200F / 미니 MK200F (정규 08:45~15:45).
리스크 [S, Fabio]: 트레이드당 0.25% 기본, 하루 3패 중단. 계약 단위라 계좌가 작으면 `qty_lt_1` 로 거래가 스킵된다 -> MNQ·미니 선물 사용 또는 계좌 크기 조정.

---
## FUT-F1 경매이론 오더플로우 근사 (`fut_f1_fabio_amt_proxy`) — Fabio Valentini

데이터 요구: 1분봉 + 가능하면 `buy_volume`/`sell_volume`(체결 주체 구분). 없으면 델타를 캔들 위치로 근사(정확도 낮음, 리포트에 명시).
진짜 풋프린트/흡수(absorption)/체결속도는 틱 데이터가 있어야 한다 -> 틱 데이터 확보 시 `indicators.bar_delta` 와 레벨 탐지를 교체할 것.

| 단계 | 규칙 | 근거 | 파라미터 |
|---|---|---|---|
| 기준 | 전일 세션 볼륨 프로파일: POC, 가치영역 70% (VAL~VAH) | [S] AMT | `value_area`0.7, `bin_ticks`4 |
| 상태 판정 (Direction) | 개장 30분 시점 종가가 VAH 위 + 그때까지 저가가 POC 위 = 상방 불균형, 반대 = 하방 불균형, 그 외 = 균형 | [S] 균형/불균형 먼저 / 30분·조건 [A] | `state_offset_min`30 |
| 위치 (Location) | 불균형: VAH(VAL) 재시험 또는 당일 프로파일 LVN / 균형: VAH·VAL 가장자리 | [S] LVN·가치영역 / LVN 판정 [A] | `lvn_frac`, `touch_tol_ticks` |
| 공격성 (Aggression) | 레벨 터치 바의 델타가 진입 방향이고 최근 60바 |델타| 의 80퍼센타일 이상 | [S] 델타·공격적 주체 확인 / 퍼센타일 [A] | `delta_pctl`, `delta_lookback` |
| 진입 | 다음 1분봉 시가 | [A] | - |
| 손절 | 레벨/터치 바 극값 바깥 4틱 | [A] | `stop_buffer_ticks` |
| 목표 | 추세 모델 1R 전량 (1:1 여러 번) / 균형 모델 POC (POC 까지 1R 미만이면 패스) | [S] 1:1 누적 / POC 회귀 | `target_r` |
| 시간 | 장 종료 30분 전 신규 금지, flat_time 청산 | [A] | `entry_end_offset_min` |

검증 포인트: `tags.model`(trend_vah, trend_lvn, mr_vah, mr_val)별 성과를 따로 본다. `tags.delta_real` 이 false 면 근사 델타.

---
## FUT-F2 다이버전스 + 피보나치 + 거래량 (`fut_f2_trullas_divergence`) — David Trullas Vila

| 단계 | 규칙 | 근거 | 파라미터 |
|---|---|---|---|
| 지표 | 5분봉 RSI(14), MACD(12,26,9) 히스토그램 | [S] MACD·RSI / 기간 [A] | `tf`, `rsi_n`, `macd` |
| 피벗 | 좌3·우3 피벗 저/고점. 우측 3봉이 지나야 확정 (룩어헤드 금지) | [A] | `piv_left`, `piv_right` |
| 일반 다이버전스 | 가격 저점↓ + 지표 저점↑ (롱), 반대 (숏). 2번째 저점 거래량 < 1번째 | [S] 일반 다이버전스·거래량 / 거래량 조건 [A] | `use_regular`, `regular_volume_filter` |
| 히든 다이버전스 | 가격 저점↑ + 지표 저점↓ (롱 추세 지속). 2번째 저점이 직전 상승 레그의 38.2~78.6% 되돌림 | [S] 히든·피보나치 / 구간 [A] | `use_hidden`, `fib_min`, `fib_max` |
| 피벗 간격 | 5~60봉 | [A] | `min_sep`, `max_sep` |
| 진입 | 피벗 확정 봉 다음 봉 시가 | [A] | - |
| 수량 | 다이버전스 1개당 1계약 (RSI·MACD 둘 다면 2계약) | [S] | `sizing`="per_divergence" ("risk" 로 리스크% 사이징) |
| 손절 | 피벗 극값 바깥 4틱 | [A] | `stop_buffer_ticks` |
| 청산 | 1R 50%, 2R 50%, 1R 후 본절 / 장 마감 전 청산 | [A] | `target_r`, `be_after_first` |

검증 포인트: `tags.kind`(regular/hidden)·`n_div`(1/2)별 성과. "2계약(다이버전스 2개) 신호가 더 좋은가?" 가 원문 사이징 논리의 검증이다.
대회 수익률(수백~수천%)은 재현 목표가 아니다. 목적은 '단순 지표 규칙에 비용 차감 후 엣지가 있는가' 확인.
