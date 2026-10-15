---
name: trading-ops
description: Ellie trading 운영 — 일일 일봉 업데이트/리포트 스케줄(20:00), 장중 스캐너(07:50~20:00), 텔레그램(gooseogi 봇, '멈춰'), PC 깨우기, DB 위치, 키움 REST API 메모, 커밋·PR 절차. 자동 실행 상태 확인, 장애 대응, 재실행할 때 사용.
---

# 운영 (D:\Ellie\trading)

## 일정 (Windows 작업 스케줄러, 평일, WakeToRun, 실행 중 절전 방지)
| 작업 | 시각 | 내용 |
|---|---|---|
| `EllieTrading_ScreenerIntraday` | 07:50 시작, 08:00~20:00 (제한 13시간) | 1분마다 스캔·조기 트리거·매수 신호. 08:50 🌅 프리마켓 주목 |
| `EllieTrading_DailyUpdate` | 20:00 | 일봉 업데이트 → 투자자 수급(ka10066) → 65기법 리포트 → 🔭 다음 거래일 관심 종목 + 😴 쉬는 주도주 → 감시 종목 1분봉 저장 → 📋 포착 복기표 |

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
- 4,000자 단위로 나눠 전송한다(`common/telegram.py`).
  - 일시적 네트워크 오류는 3회 재시도한다(2026-10-15 08:28 🔥 알림이 한 번 실패해 빠졌다).
  - 예외 메시지 URL 에 봇 토큰이 들어가므로 로그에는 `***` 로 가린다.

## 데이터
- `data/daily_ohlcv.duckdb`: daily_ohlcv, stocks(sector, listed_shares), minute_ohlcv, investor_daily(투자자별 일별 순매수, 원), backfill_status, refetch_queue
- `data/screener.duckdb`: rank_snapshots, theme_members, detections(first_ts), buy_signals(reject_reason), rest_leaders, watch_adds, early_alerts, theme_alerts, gate_flow_eval, investor_intraday(장중 외국인·기관 잠정치)
- `data/reports/`: capture_review_YYYYMMDD.csv (포착 복기)
- DuckDB 는 프로세스 간 잠금이 걸린다. DuckDB UI·DBeaver 를 열어 두면 업데이트가 5분 간격으로 최대 6회 재시도한다.

## 키움 REST 메모
- au10001 토큰, ka10081 일봉(수정주가), ka10080 분봉(~1년, 900봉/페이지), ka10099 종목(marketName, listCount, upName), ka10001 시세
- ka10032 거래대금 상위(`stex_tp` 1 = KRX, 3 = 통합; trde_prica 단위는 백만원), ka00198 조회 순위(qry_tp 1 = 1분, 4 = 당일 누적; 현재 스냅샷만 제공), ka90001/90002 테마
- 투자자 수급:
  - ka10059: 종목별 일별, 100일/페이지, 백만원 단위. 부호가 의미 있으므로 공용 `_to_int`(절대값) 를 쓰면 안 된다.
  - ka10066: 장 마감 후 전 종목 한 번에, 100종목/페이지
  - ka10063: 장중 잠정치 전 종목. 외국인 6, 기관계 7. '--288' 처럼 부호가 겹쳐 온다.
  - ka10064: 종목별 장중 시계열, 오늘만
  - 백필: `investor_flow --codes ... --since` (`DAILY_DB_PATH` 로 별도 파일에 받은 뒤 병합하면 본 DB 잠금을 피한다)
- 오래 도는 수집·백필에는 `prevent_sleep_until_exit()` 를 건다. 2026-10-14 새벽 절전으로 수집이 멈춘 적이 있다.
- 종목코드 접미사: `_AL` 통합, `_NX` NXT, 없으면 KRX. 호출 간격 0.25초.

## 모의투자 (키움 모의 서버)
- 키는 `.env.local` 의 `KIWOOM_MOCK_APP_KEY`, `KIWOOM_MOCK_SECRET_KEY`, `KIWOOM_MOCK_BASE_URL=https://mockapi.kiwoom.com` 이다.
  - 실전 키(`KIWOOM_APP_KEY`)와 따로 둔다. `chapter_0/1/config.py` 의 옛 모의 키는 만료됐다(8001).
- 모의 앱키는 허용 IP 를 등록해야 한다. 등록 전에는 8001(키 검증 실패)이 난다. 공인 IP 확인: `curl https://api.ipify.org`.
- 모의 계좌 시작 자금은 1,000만 원이다. `MockClient` 는 주소에 `mockapi` 가 없으면 만들지 않는다(실계좌 주문 방지).
- 장중 스캐너가 자동으로 매매한다(정규장 실주문, NXT 프리·애프터장 가상 체결, 19:55 리포트). `--once` 나 `--no-paper` 로 실행하면 주문하지 않는다. 규칙은 `buy-signals` 스킬 5장에 있다.
- 점검: `python -m kiwoom_trading.screener.paper_trader --status`(잔고), `--report [YYYYMMDD]`(리포트 미리보기)
- 키움 API 메모:
  - kt10000 매수, kt10001 매도(`trde_tp` 3 = 시장가, `dmst_stex_tp` KRX)
  - kt00018 잔고(`acnt_evlt_remn_indv_tot`), kt00001 예수금(`ord_alow_amt`), ka10076 체결(`cntr`), ka10075 미체결(`oso`)
- '멈춰' 로 스캐너를 끄면 손절 감시도 멈춘다. 보유 종목이 있으면 멈춤 알림에 함께 표시한다.

## 커밋 절차 (사용자 요청 "커밋 pr 머지")
1. 새 브랜치 → 커밋 → push → PR → merge → 로컬 main fast-forward
2. 공개 저장소다. push 전에 staged 파일에 비밀값이 없는지 검사한다. `.env*`, `chapter_0/1/config.py`, `data/` 는 ignore 되어 있다.
3. `GH_TOKEN=$(gh auth token --user Justice7Axe) gh pr create/merge -R Justice7Axe/trading-bot` 로 실행한다. 전역 gh 계정(Dev-Expertise-TS)은 바꾸지 않는다.
