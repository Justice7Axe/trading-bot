---
name: trading-ops
description: Ellie trading 운영 — 일일 일봉 업데이트/리포트 스케줄(20:00), 장중 스캐너(07:50~20:00), 텔레그램(gooseogi 봇, '멈춰'), PC 깨우기, DB 위치, 키움 REST API 메모, 커밋·PR 절차. 자동 실행 상태 확인, 장애 대응, 재실행할 때 사용.
---

# 운영 (D:\Ellie\trading)

## 일정 (Windows 작업 스케줄러, 평일, WakeToRun, 실행 중 절전 방지)
| 작업 | 시각 | 내용 |
|---|---|---|
| `EllieTrading_ScreenerIntraday` | 07:50 시작, 08:00~20:00 (제한 13시간) | 1분마다 거래대금 상위 200 저장(`rank_snapshots` value_krx)·시장 분위기 판정·매매표 신호·모의투자·💰 10만 원 계좌. **종목 찾기(⚡ 장중 포착·조기 발굴 🏁🚀🌅·🔥🧩 테마·감시 목록 🎯 차트 신호)는 2026-10-25 부터 끔** (`run_intraday.DISCOVERY = False`, 사용자: "수익 나는 종목·타이밍을 못 찾았으니 버리고 매매표 각 매매가 종목을 고른다"). 20:00 📋 포착 복기도 안 보냄 |
| `EllieTrading_DailyUpdate` | 20:00 | 일봉 업데이트 → 투자자 수급(ka10066) → 지수 일봉·1분봉(data/index.duckdb) → 65기법 리포트 → 🧱 매매표 ② 저항 돌파 다음 거래일 대상 (🔭 관심 종목·😴 쉬는 주도주는 2026-10-25 종목 찾기 중단으로 뺌, `run_intraday.DISCOVERY`) → 감시 종목 1분봉 저장(🎯 신호·모의투자 종목 포함) → 📋 포착 복기표 → 📈 모의투자 타점 차트 HTML(`data/reports/paper_chart_YYYYMMDD.html`, 텔레그램 파일 전송) |

- 등록 스크립트: `scripts/register_daily_update_task.ps1`, `scripts/register_screener_task.ps1` (UTF-8 BOM)
- 로그: `data/logs/daily_update_YYYYMMDD.log`, `data/logs/screener_YYYYMMDD.log`
- 수동 재시작: `Start-ScheduledTask -TaskName EllieTrading_ScreenerIntraday`
- 휴장일: 08:10 이후 조회 순위 기준일이 오늘이 아니면 스캐너가 스스로 종료한다.

## 텔레그램
- 항상 **gooseogi 봇**을 쓴다. 토큰과 채팅 ID는 `.env.local` 에 있다. 비밀값은 절대 출력하거나 커밋하지 않는다.
- '멈춰'(중지/정지/stop)를 보내면 5초 안에 스캐너가 멈춘다. getUpdates 는 offset 없이 읽으므로 gooseogi bot.py 에 영향을 주지 않는다.
- **'정리'(요약/현황)** 를 보내면 그때까지의 오늘 결과를 섹션별 고정폭 표로 보낸다(`daily_summary.py`, 스캐너 실행 중 07:50~20:00).
  - 섹션: 🧩 테마(★대장, 포착 → 현재 등락), 🏁/🔥/🚀, ⚡ 장중 포착, 🎯 매수 신호(최근 25건, 진입가 대비 수익)
  - 현재 등락은 매분 받는 순위 데이터(PriceBoard)에서, 없으면 ka10001 시세로 채운다. 같은 메시지에는 한 번만 답한다.
  - HTML `<pre>` 를 쓰므로 섹션마다 따로 보낸다(태그가 잘리지 않게).
- **포착·신호 알림 끝에 '📍 오늘 시장: …' 한 줄**을 붙인다 (2026-10-25 사용자, `run_intraday._tag` → `MarketRegime.day_label`). 대상: 🔥 특징주·🧩 테마 형성·🌅 프리마켓·🏁/🚀 즉시 알림·감시 추가 요약·🏁✅ 수급 확인·⚡ 장중 포착·🎯 매수 신호·🧭 장 초 급등. 09:10 전엔 '판정 전 · 상승/하락 흐름', 뒤엔 강한 상승장 / 상승 흐름 보통 날 / 하락 흐름 보통 날 / 강한 하락장. 포착 자체는 시장 상황과 무관하게 매일 돈다(모의 매수만 매매표를 따름).
- **📡 오늘의 강세 종목** (2026-10-26 사용자, `screener/strong_list.py`, 알림만): 10:00·13:30·15:20·19:50(애프터 포함) 에 통합(KRX+NXT)·주식만(ETF·ETN·스팩 제외) 거래대금 상위 20 + 상승률 상위 15(대금 100억↑). 그날 🎯 신호가 난 종목은 시각·종류 표시. `strong_list_sent` 표로 하루 한 번씩. 키움 [0184]·[0198] 화면과 같은 기준. 포착 순간 매수 1년 백테스트가 하락 흐름·강한 하락장 날 건당 −1~−2% 라 매수와 잇지 않음.
- **🇺🇸 간밤 미국 지수** (2026-10-27 사용자, `common/us_market.py`, 스킬 `us-overnight`): 스캐너 시작 때 나스닥·다우·나스닥100·선물을 받아 📋 카드 첫머리와 5️⃣ 인버스 매수 알림(🎯·🔴·💰)에 표시, `us_overnight` 표에 기록. 20:00 업데이트가 `index.duckdb` `us_daily` 를 이어 받음. 매수 규칙은 안 바꿈(1년 검증: 매수 전 간밤 방향으로 거르면 나아지는 매매 없음).
- 4,000자 단위로 나눠 전송한다(`common/telegram.py`).
  - 일시적 네트워크 오류는 3회 재시도한다(2026-10-15 08:28 🔥 알림이 한 번 실패해 빠졌다).
  - 예외 메시지 URL 에 봇 토큰이 들어가므로 로그에는 `***` 로 가린다.

## 코드 구조 (2026-10-27 정리, docs/architecture.md)
- `common/` 자료·판단 공용(krx 호가·상한가, leader 👑 테마 대장, market 지수 20일선) · `backtest/` 공통 엔진·매매표 계좌(`python -m kiwoom_trading.backtest.playbook.full_bt`)
- `execution/` 실전(real)·모의(paper)·10만 원(small)·**공용 가상 장부(ledger — 표 `ledger_trades`·`ledger_days`, book 칸으로 장부 구분)**
- `strategies/<이름>/` 매매법마다 rules·live·backtest — regime_plays(①③⑥) · resistance_retest(②) · contra_close(④) · inverse(⑤) · trend_hold(⑦) · danswer(🧭📒🌙) · hamburger(🍔) · bigcap_flow · early_nine · pullback_breakout · leader_shape · sixty_five · testa · hong_limitup · hong_styles · cafe_leader · jeonhwang. 장중 재현: `python -m kiwoom_trading.backtest.replay 날짜…`. 실행기 `screener/run_intraday.py` 는 가상 장부 매매법을 `books` 목록으로 돌림.
- 옛 경로(screener/real_inverse·paper_trader·hong_account …, analysis/run_*_backtest)는 같은 모듈을 가리키는 연결 파일 — 예전 명령 그대로 동작. 백테스트 공통 원칙은 스킬 backtest-rules.

## 데이터
- `data/daily_ohlcv.duckdb`: daily_ohlcv, stocks(sector, listed_shares), minute_ohlcv, investor_daily(투자자별 일별 순매수, 원), backfill_status, refetch_queue
- `data/screener.duckdb`: rank_snapshots, theme_members, detections(first_ts), buy_signals(reject_reason), rest_leaders, watch_adds, early_alerts, theme_alerts, gate_flow_eval, investor_intraday(장중 외국인·기관 잠정치, 5분 확인·바뀔 때만), program_intraday(장중 종목별 프로그램 매매 ka90004, 09:00~15:45 10분마다 전 종목 매수·매도·순매수 원, 2026-10-26부터 — 외인 방향 대용)
- `data/index.duckdb`: 지수 idx_daily(일봉 2021-11~)·idx_min(1분봉 2025-10~), code 001 코스피·101 코스닥·201 코스피200 (키움 ka20006·ka20005, 2026-10-25 시장 상황 기준 분석용). 평일 20:00 일일 업데이트가 이어 받음(`ingestion/collectors/index_collector.py`, 수동: `python -m kiwoom_trading.ingestion.collectors.index_collector`). 장중 판정은 이 파일이 아니라 API 로 직접 조회
- `data/minute_history.duckdb`: 통합(AL) 1분봉 1년 백필(날짜별 대금 상위 **500** + 다음 거래일, 2026-10-25 200 → 500: 키움 1분봉은 약 1년치만 주므로 넓게 모아 둠), 평일 20:45 `EllieTrading_MinuteBackfill`(`--top 500 --since 2025-10-15`)가 이어 받음. 07:30~20:40 에는 멈춤. 500 으로 늘린 몫 약 8만 건 ≈ 55시간(평일 밤 4~5번 + 주말), DB 2.5GB → 약 6GB. 매일 늘어나는 몫 약 600건
- `data/daily_regular.duckdb`: **정규장 일봉** (code, date, open·high·low·close·volume·value, bars, has_after). 2026-09-14 NXT 전 종목 확대부터 키움 일봉(ka10081)·일별(ka10086)이 통합(애프터 포함) 값을 줘서 daily_ohlcv 종가 = 20:00 애프터 종가가 됐다 → 1분봉 09:00~15:30 봉으로 정규장 값을 따로 만든다. 1분봉 백필(`EllieTrading_MinuteBackfill`)이 끝날 때 자동(`ingestion/collectors/daily_regular.py`, 수동: `python -m kiwoom_trading.ingestion.collectors.daily_regular [--since 2025-10-15 --all]`). 1분봉 있는 종목(대금 상위 500)만, 가격은 1분봉 받은 날 기준. daily_ohlcv 는 그대로(실전 매매가 쓰는 중)
- `data/reports/`: capture_review_YYYYMMDD.csv (포착 복기)
- **장중 분석은 `data/screener_snapshot.duckdb`(스캐너가 10분마다 만드는 사본, `ScreenerStore.snapshot`, 2026-10-28)를 read_only 로 연다** — 본 DB 는 스캐너가 잠가 복사도 안 됨.
- DuckDB 는 프로세스 간 잠금이 걸린다. DuckDB UI·DBeaver 를 열어 두면 업데이트가 5분 간격으로 최대 6회 재시도한다.

## 키움 REST 메모
- au10001 토큰, ka10081 일봉(수정주가), ka10080 분봉(~1년, 900봉/페이지), ka10099 종목(marketName, listCount, upName), ka10001 시세
- ka10032 거래대금 상위(`stex_tp` 1 = KRX, 3 = 통합; trde_prica 단위는 백만원), ka00198 조회 순위(qry_tp 1 = 1분, 4 = 당일 누적; 현재 스냅샷만 제공), ka90001/90002 테마
- 투자자 수급:
  - ka10059: 종목별 일별, 100일/페이지, 백만원 단위. 부호가 의미 있으므로 공용 `_to_int`(절대값) 를 쓰면 안 된다.
  - ka10066: 장 마감 후 전 종목 한 번에, 100종목/페이지
  - ka10063: 장중 잠정치 전 종목. 외국인 6, 기관계 7. '--288' 처럼 부호가 겹쳐 온다.
  - ka10064: 종목별 장중 시계열, 오늘만
  - ka90004: 종목별 프로그램 매매, 시장(P00101 코스피·P10102 코스닥)별 전 종목, 백만원 단위. dt 를 넣어도 마지막 거래일만 → 장중 스캐너가 program_intraday 로 쌓는다(전 종목 약 74쪽·18초)
  - 백필: `investor_flow --codes ... --since` (`DAILY_DB_PATH` 로 별도 파일에 받은 뒤 병합하면 본 DB 잠금을 피한다)
- 오래 도는 수집·백필에는 `prevent_sleep_until_exit()` 를 건다. 2026-10-14 새벽 절전으로 수집이 멈춘 적이 있다.
- 종목코드 접미사: `_AL` 통합, `_NX` NXT, 없으면 KRX. 호출 간격 0.25초.

## 🔴 실전 매매 (키움 실계좌, 2026-10-26 부터) — `execution/real.py` `RealTrader`
- 사용자 2026-10-25: "10만 원 시드로 실전 매매, 내일 시초에 물려 있던 종목 모두 손절 매도하고 시작" → 처음 5️⃣ 만, 같은 날 "인버스 타이밍이 아니면 다른 기법도 → 6️⃣2️⃣5️⃣ 로".
- 켜기: `.env.local` `KIWOOM_REAL_TRADING=combo` (6️⃣ 주도주 신고가 · 2️⃣ 저항 돌파 · 5️⃣ 약세장 인버스) / `inverse` (5️⃣ 만) / 지우거나 다른 값 = 주문 안 함. 실전 키(`KIWOOM_APP_KEY`, api.kiwoom.com)가 실계좌에 묶여 있다 (2026-10-25 조회: 주문 가능 639원, KODEX 삼성전자SK하이닉스채권혼합50 3주).
- 한 번 전체 정리: `KIWOOM_REAL_LIQUIDATE_DATE=2026-10-26` → 그날 09:00 첫 확인 때 계좌 보유 종목 전체 시장가 매도(`real_liquidations`). 끝나면 지워도 된다.
- 매수: **2026-10-30 사용자 '하루 1종목 규칙을 없애줘, 3만 원 안에서는 1주 이상, 3만 원 넘으면 1주만' (11-02 부터)** — 하루 종목 수 제한·1️⃣ 4칸 규칙 없음. 신호마다 같은 종목을 들고 있지 않고(같은 날 같은 종목 한 번) 예수금이 되면 현재가 +1% 지정가로 산다. 수량 = 지정가 ≤ 3만 원이면 3만 원 안에서 최대(9천 원 → 3주), 3만 원 넘으면 1주(가격 상한 없음), 예수금 안에서. 1주도 못 사면 ⏭ 알림, 신호가 +1% 넘으면 추격 안 함(1️⃣ 은 전일 대비 +15%). (옛 규칙: 첫 신호 하나에 min(10만 + 실현 손익, 주문 가능, 20만) 전부, 1️⃣ 은 4종목 1/4씩)
  - 주문 가능 금액 = kt00001 `100stk_ord_alow_amt`(증거금 100% 종목, 정산 전 매도 대금 포함·빌리는 돈 없음). `ord_alow_amt` 는 예수금만이라 그날 판 돈이 안 잡힘 (2026-10-26 09:06 639원 vs 83,897원).
  - 시장가 매수는 상한가 기준 증거금이라 '[2000] 매수증거금이 부족합니다. N주 매수가능' 이 나올 수 있다 → 그 N주로 한 번 다시 주문 (10-26 TIGER 인버스 61주 거절 → 46주 가능).
  - 사용자가 직접 산 종목을 규칙대로 팔게 하려면 스캐너를 잠깐 멈추고 `real_trades` 에 status='open' 으로 넣는다 (10-26 TIGER 인버스 10주 1,376원 → 5️⃣).
- 📕 홍인기 상한가 풀림 (2026-10-27 사용자 "바로 실전, 6️⃣2️⃣5️⃣ 와 하나로"): `strategies/hong_limitup/live.py` 수급 없이 장부가 사는 순간 실전 신호로 넘김(`on_real`) — 지금가가 상한가면 안 삼 (스킬 hong 5장).
- 1️⃣ 상승장 장 초 (2026-10-27 사용자 "1 을 실전에도"): 강한 상승장 09:10 대금 40위·시가 위 신호를 실전에도 — **2026-10-28 사용자 '옛 방식으로'**: 익절 없음 · −4% 손절 · 못 닿으면 다음 날 09:00 (10-27 'B 방식' +7% 절반·4% 트레일링은 1천만/일 +332만 < 옛 방식 +412만이라 되돌림, `regime_plays.live.UP_HALF_TP = None`) (`execution/real.py` PLAYS). (10-30 까지: 실전은 하루 1종목이라 09:10 에 1️⃣ 을 사면 그날 6️⃣·2️⃣ 는 못 샀다 — 11-02 부터 종목 수 제한 없음, 위 '매수') **2026-10-28 사용자 'B'**: 1️⃣ 은 4종목까지(종목당 시드+손익의 1/4, `real.UP_SLOTS`), 1️⃣ 을 산 날 다른 신호는 안 삼. 매수는 현재가 +1% 지정가(시장가는 상한가 기준 증거금이라 10-28 네오셈 2주→1주), 2분 미체결 잔량 취소. **1️⃣ 추격 규칙(10-28 사용자 '+1%는 단편적')**: 신호가 대비 +1% 제한을 없애고 전일 종가 대비 +15% 넘게 오른 종목만 안 삼(`UP_MAX_PREV_GAIN`, 모의·실전·잔고 밖 가상). **1️⃣ 손절 −6% (10-28 사용자 승인, `UP_STOP = 0.06`)**, 모의 손절도 신호가가 아니라 매수가 기준. 1년: +1% 규칙이 거른 종목이 오히려 +1.0~1.5%, +15%가 거른 것은 −0.33~+0.36%. 1️⃣ 신호는 09:10 시장 분위기 판정 바로 뒤 실전 → 모의 순서로 즉시 주문 (10-28 신호 09:10 → 실전 주문 09:12:33 이던 지연 제거, 1분 늦으면 건당 −0.27%p). 시드 10만 원이라 1주 > 10만 원 종목은 건너뛰고 다음 신호.
- **당일 매매 엄격 선정 (2026-10-30 사용자 '데이 트레이딩은 엄격한 종목 선정으로 줄여줘' → 모의 A안·실전 B안, `execution/strict_select.py`)** — 매수 전에 아는 정보만. 1️⃣ 신호 순간 대금 20위 안 · 2️⃣ 시총 3천억↑ & 전날 기관 + · ☕ 전날 대금 50위 안 · 🔁 전날 기관 + (A·B), 6️⃣ 전날 기관 + · 📕 전날 외인 + (B=실전만). 걸리면 '엄격 선정 —' 이유로 기록만(알림 없음). 1년: 모의 A 1억 1,871만 → 1억 3,792만(낙폭 15→18%), 실전 B 68.9만 → 91.5만(낙폭 18→13%). research/strict_select, data/strict_select/choose.txt.
- **7️⃣ 주도주 추세 실전 추가 (2026-10-30 사용자 '며칠 들고 가는 매매 중 검증된 7번을 실전으로', 11-02 부터)** — 09:00~09:30 신호에 종목당 3만 원 규칙(넘으면 1주)으로 매수, 손절·익절 없이 전날 종가가 20일선 아래면 09:00 매도 (`real.trend_exit`, 스캐너 시작 때 `ma_breaks`). 다른 실전 매매처럼 다음 날 바로 안 팖. 2026 신호 78건 중 1주 9만 원 이하 25건 — 실전 예수금이 작아 비싼 대형주는 못 삼(⏭).
- **4️⃣ 역행 강세 종가 · 🌙 종가 재돌파 실전 추가 (2026-10-30 사용자 '제안대로', 11-02 부터)** — `real.PLAYS`. 4️⃣ 는 강한 하락장 15:15~15:19 KRX 지정가, 🌙 는 17:00~18:00 NXT 애프터마켓 지정가(`dmst_stex_tp=NXT`, 통합 현재가 +1%, 2분 미체결 취소도 NXT). 둘 다 익절·손절 없이 다음 날 09:00 KRX 시가 매도. NXT 거래 안 되는 종목은 애프터 시세가 안 움직여 🌙 신호가 거의 안 남(주문 거부되면 ⚠️ 알림). 1년: 4️⃣ 422건 +0.85%, 🌙 554건 +0.79%.
- ☕ 매수 조건에서 ④ 일봉 박스를 뺌 (2026-10-30 사용자, 스킬 cafe-leader) — ①③⑥ 이면 가상 장부·모의·실전.
- 🔁 시가 탈환 · ☕ 카페 테마 대장 (2026-10-27 사용자 "모의·실전 모두"): 실전 신호 종류 7개(1️⃣6️⃣2️⃣5️⃣📕🔁☕) 중 그날 먼저 온 1종목. 나눠 팔기는 `execution/split_exit.py`.
- 매도(체결가 기준, 1분마다): 6️⃣ 익절 없음 −4% / 2️⃣ +7% −5% / 5️⃣ +5% −3% / 📕 익절·손절 없음, 못 닿으면 다음 날 09:00. 그날 신호로 받은 종목만 주문(`RealClient.allowed`), 팔 때는 이 매매로 산 수량만. `real_trades`, 🔴 텔레그램.
- ⚠️ '멈춰'로 스캐너를 끄면 실전 손절·익절 감시도 멈춘다. 들고 넘어간 종목은 다음 날 스캐너가 09:00 에 판다(스캐너가 안 켜지면 안 팔림).

## 📋 오늘의 트레이딩 전략 (매일 아침, 옛 이름 '매매표')
- 스캐너가 켜질 때 하루 한 번 시장 상황별 트레이딩 전략 + 큰 흐름 + 계좌(실전·모의·💰) 를 텔레그램으로 먼저 보낸다 (`screener/playbook_card.py`, `playbook_sent` 표). 지금 한 번 보내기: `python -m kiwoom_trading.screener.playbook_card --send`.
- 번호는 원 숫자(①②…) 대신 크게 보이는 1️⃣~7️⃣, 이름은 '매매표' 대신 '트레이딩 전략' (2026-10-25 사용자).
- 1️⃣·6️⃣ 매도 문구는 '장중 익절 없이 다음 날 시가 매도 (−4% 손절)' — 1분봉 1년 비교에서 절반 익절·트레일링·전량 익절 모두 이보다 나빴다(6️⃣ +2.18% vs +0.3~2.0%).

## 모의투자 (키움 모의 서버)
- 키는 `.env.local` 의 `KIWOOM_MOCK_APP_KEY`, `KIWOOM_MOCK_SECRET_KEY`, `KIWOOM_MOCK_BASE_URL=https://mockapi.kiwoom.com` 이다.
  - 실전 키(`KIWOOM_APP_KEY`)와 따로 둔다. `chapter_0/1/config.py` 의 옛 모의 키는 만료됐다(8001).
- 모의 앱키는 허용 IP 를 등록해야 한다. 등록 전에는 8001(키 검증 실패)이 난다. 공인 IP 확인: `curl https://api.ipify.org`.
- 모의 계좌 시작 자금은 1,000만 원이다. `MockClient` 는 주소에 `mockapi` 가 없으면 만들지 않는다(실계좌 주문 방지).
- 장중 스캐너가 자동으로 매매한다(정규장 실주문, NXT 프리·애프터장 가상 체결, 15:40·19:55 리포트). `--once` 나 `--no-paper` 로 실행하면 주문하지 않는다. 규칙은 `buy-signals` 스킬 5장에 있다.
- **3️⃣ 막힌 고점 돌파는 모의 주문에서 뺌, 🔁 시가 탈환은 실전에서 뺌 (2026-10-29 사용자 '권장대로')** — `paper.MOCK_OFF`, `real.REAL_OFF`. 계좌 1년 시험(research/account_alloc, data/account_alloc/report.txt): 두 매매가 09:0x 에 먼저 와 아침 현금·실전 하루 1칸을 차지해 6️⃣(+2.33%)·📕(+1.93%)·1️⃣ 를 못 삼. 빼면 모의 1천만 7,837만 → 2.2억(앞 +285→+548%, 뒤 +109→+240%), 실전 10만 34만 → 562만. 실전 시드는 10만 그대로(사용자). 신호 기록(buy_signals)은 계속.
- **🔁 모의는 전용 몫 100만 (2026-10-29 사용자 '모의에는 🔁 만 쓰는 몫, 가상에는 🔁 전부')** — `paper.RECLAIM_POOL`: 🔁 는 몫(종목당 100만 → 동시 1종목) 안에서만 모의로 사고 보유 한도 10칸은 안 씀. 몫을 넘거나 현금이 모자라 못 산 🔁 는 잔고 밖 가상(🟣)으로 전부 기록. 09:00 에 파는 중인 전날 🔁 는 몫에서 뺌. 1년 시험(research/account_alloc/reclaim_pool → data/account_alloc/reclaim_pool.txt): 🔁 뺀 2억 2,192만 대비 몫 100만 2억 367만(−8%, 낙폭 20.5%, 뒤 반기 +240→+264%), 200만 1억 9,768만, 300만 1억 8,381만 — 몫이 클수록 나빠짐. 몫 없이 그냥 넣으면 1억 2,209만.
- **📍 중심선 모의 매매 (2026-10-30 사용자 '모의 매매로 해줘', 스킬 centerline)** — `strategies/centerline/live.py`: 스캐너 시작 때 지난 10거래일 기준봉(+10%·거래량 3배·대금 20위·평소 대금 10배) 중 아직 중심선을 안 깬 후보를 KRX 1분봉으로 고르고, 장중 저가가 중심선에 닿으면 모의 매수. 전용 몫 300만(`CENTER_POOL`)·종목당 50만, 보유 한도 칸 안 씀, 몫 넘으면 잔고 밖 가상. 매도 = 장중 중심선 −3% 손절 · 전날 종가가 중심선 아래면 09:00 · 5거래일 끝나면 09:00 (`paper.center_exit`, 시작 때 계산). 09:10 강한 하락장 뒤엔 안 삼. 실전은 안 함. 1년 계좌 시험은 ±2% (보탬 거의 없음) → 모의로 쌓아 보고 판단.
- **잔고 밖 가상 매매 (2026-10-28 사용자 "가상 매매는 잔고와 무관하게 포착된 종목 모두")**: 정규장 신호를 모의 계좌가 주문 가능 금액 부족·보유 한도(최대 N종목)·7️⃣ 몫·하루 손실 한도 때문에 못 사면, 같은 금액·같은 매도 규칙으로 주문 없이 KRX 시세로 가상 매매한다 (`paper._overflow_buy`, paper_trades.overflow=true, 리포트 ◆). 규칙상 대상 아님(시장 분위기·전날 수급 등)·추격(+1%↑)·이미 보유는 그대로 건너뜀. 보유 한도·⑦ 몫·하루 손익(Nada) 계산에서는 빼고, ⏭ 대신 🟣 가상 매수 알림을 보낸다.
- 점검: `python -m kiwoom_trading.screener.paper_trader --status`(잔고), `--report [YYYYMMDD]`(리포트 미리보기)
- 모의 계좌와 따로 도는 **가상 계좌**(주문 없음, screener.duckdb 에 기록): 💰 10만 원 계좌 `execution/small.py`(small_trades), 📒 [디앤서] 관심종목 2-2-2·🛡️ 하락일 헤지주 `strategies/danswer/watch.py`(danswer_watch, 12:00 네이버 업종·테마 받기 → data/naver_groups.duckdb, 14:30 미리 보기·15:15 헤지주 알림·15:35 관심종목+전날 결과 — 스킬 danswer 10장), 📘 [전황] 1천만 계좌 `strategies/jeonhwang/live.py`(ledger_trades(book '전황 11시')·jh_days, 11:00 매수·다음 날 09:00 매도, 코스피 1구간 날만 — 스킬 jeonhwang 0장), 📕 [홍인기] 상한가 풀림 두 장부(수급 확인·수급 없이) `strategies/hong_limitup/live.py`(ledger_trades(book)·hg_events, 5분↑ 잠김 뒤 풀리면 매수·다시 상한가 절반·다음 날 09:00 — 스킬 hong 4장), ☕ [카페] 테마 대장 체크리스트·가상 장부 `strategies/cafe_leader/live.py`(cafe_checks·ledger_trades(book '카페 대장'), 09:00~10:30 — 스킬 cafe-leader 3장), 📕 [홍인기·상따 밖] 돌파·대장/돌파/강한 쪽/애프터 급락 `strategies/hong_styles/live.py`(ledger_trades(book), 19:58 요약 — 스킬 hong 7장). 📅 [일정] 공시 사건 가상 장부 4개(무상 권리락·무상증자·자사주 신탁·고배당) `strategies/event_scenario/live.py`(ledger_trades(book '일정 …'), 08:00 DART 최근 공시 받기(`data/events.duckdb`)·09:00 매수·5거래일 또는 권리락일 09:00 매도 — 스킬 event-scenario 0장).
- 키움 API 메모:
  - kt10000 매수, kt10001 매도(`trde_tp` 3 = 시장가, `dmst_stex_tp` KRX)
  - kt00018 잔고(`acnt_evlt_remn_indv_tot`), kt00001 예수금(`ord_alow_amt`), ka10076 체결(`cntr`), ka10075 미체결(`oso`)
- '멈춰' 로 스캐너를 끄면 손절 감시도 멈춘다. 보유 종목이 있으면 멈춤 알림에 함께 표시한다.

## 커밋 절차 (사용자 요청 "커밋 pr 머지")
1. 새 브랜치 → 커밋 → push → PR → merge → 로컬 main fast-forward
2. 공개 저장소다. push 전에 staged 파일에 비밀값이 없는지 검사한다. `.env*`, `chapter_0/1/config.py`, `data/` 는 ignore 되어 있다.
3. `GH_TOKEN=$(gh auth token --user Justice7Axe) gh pr create/merge -R Justice7Axe/trading-bot` 로 실행한다. 전역 gh 계정(Dev-Expertise-TS)은 바꾸지 않는다.

## 텔레그램 알림 원칙 (2026-10-27 사용자)
- **실전·모의·가상 매매 대상이 아닌 포착은 알림 안 함** — buy_signals·cafe_checks·danswer_watch 등 기록과 로그만. 꺼진 알림: 🎯 신호 묶음, 🧭 급등 묶음, 📡 강세 종목, 📒 2-2-2·🛡️ 헤지주, 🧭 디앤서 14:30, ☕ 체크리스트(①③④⑥ 미달), 🎯 눌림 돌파 감시 자체.
- 매매가 되면 🟢 모의 / 🟣 가상 / 🔴 실전 매수 알림에 '포착:' 이유가 붙는다.
- **대상인데 못 샀으면** 이유 + 포착 이유를 알림·로그: 모의 `⏭ 모의 매수 못 함`(잔고·보유 한도·추격·시세 등 — 규칙상 대상 아님 `paper.RULE_SKIPS` 은 로그만), 실전 `⏭ 실전 매수 못 함 N건`(하루 1종목·1주가 시드보다 비쌈·추격, 한 번에 묶음), ☕ ①③④⑥ 인데 3종목 다 참 / 10분 안 안 눌림.
- 2026-10-27 사용자: 💰 10만 원 가상 계좌 끔(실전과 같은 일, 기록은 남음) · 15:40 가상 장부 마감 요약(📘 전황·📕 홍인기·☕ 카페)을 15:42 '📒 가상 장부 마감' 한 통으로 묶고 🧪 실험 모의 매매(주도주 모양·장 초 공통점·대형주 수급·햄버거·인버스 갭 — 오늘·누적 손익) 리포트를 붙임 (`execution/experiment_report.py`). 📕 상따 밖 장부는 19:58 따로. 20:00 65기법 리포트는 유지.
