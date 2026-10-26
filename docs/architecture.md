# 매매 시스템 구조 설계 — 역할별 분리·공통화 (2026-10-27)

사용자 요청(2026-10-27): "매매 전략·실행 코드·스킬 문서를 역할별로 분리하고, 공통으로 쓸 것은 공통화하고,
개별 매매 전략은 계속 업데이트하면서 실행·백테스트·개선하도록 개별 코드와 스킬로 지식화하자."

## 1. 왜 바꾸나 — 지금 구조에서 실제로 생긴 문제

| 문제 | 예 |
|---|---|
| 검증 자료가 저장소 밖에 있음 | 매매표 계좌 백테스트(`full_bt.py`·`compound.py`·`swing3.py`)와 그 입력(`np_cands.pkl` 등)이 세션 임시 폴더 5곳(`%TEMP%/claude/D--Ellie-trading/<세션>/scratchpad`)에 흩어져 있다. 몇몇 입력 파일은 만든 스크립트도 남아 있지 않다. 임시 폴더가 지워지면 재현 불가 |
| 공통 엔진이 스킬 폴더 안에 있음 | 백테스트 공통 엔진이 `.claude/skills/danswer/scripts/engine.py` 에 있어, 다른 매매법 백테스트가 `sys.path` 를 억지로 붙여 불러온다 |
| 가상 장부가 매매법마다 따로 | 💰 `small_account` · 📘 `jeonhwang_account` · 📕 `hong_account` · ☕ `cafe_leader` · 📕 `hong_styles` 가 각자 표·잔고·매도·요약 코드를 가진다 |
| 장중 실행 파일이 너무 큼 | `screener/run_intraday.py` 770줄, `run_once` 인자 30개 넘음. 감시를 하나 넣을 때마다 import·생성·인자·호출 네 곳을 손으로 고친다 (CRLF 가 깨지는 일도 반복) |
| 같은 판단이 여러 벌 | 지수 20일선, 시장 분위기(U/N+/N-/D), 테마 대장, 상한가 계산이 백테스트·실시간·스크래치에 따로 구현돼 있다 |
| 스킬 형식이 제각각 | 매매법 스킬마다 장 구성이 달라 "지금 무엇이 실전·모의·가상인지", "결과 숫자가 어디서 왔는지" 찾기 어렵다 |

## 2. 원칙

1. **매매법 하나 = 규칙 하나.** 같은 규칙 함수를 백테스트와 실시간이 함께 쓴다 (지금 `indicators/hong.py` 처럼).
2. **매매법은 "신호 + 매도 계획"만 만든다.** 어느 계좌(실전·모의·가상 장부)로 보낼지, 얼마를 살지는 실행 계층이 정한다.
3. **공통은 한 곳.** 자료 읽기, 시장 분위기, 테마 대장, 비용·매도 규칙, 결과 집계(★ 판정)는 `common`·`backtest` 에 하나만 둔다.
4. **결과는 재현 가능해야 한다.** 스킬에 적힌 숫자는 저장소 안의 명령 하나로 다시 나와야 한다 (스크래치 파일 경로 금지).
5. **바꿀 때마다 '전과 같은 결과'를 확인한다.** 백테스트 숫자와 장중 재현 매매가 바뀌지 않아야 다음 단계로 간다.
6. **장중(07:50~20:00)에는 실행 코드(`screener/`)를 바꾸지 않는다.** 스캐너가 이 폴더 코드로 실전 주문을 낸다.

## 3. 목표 구조

```
kiwoom_trading/
  common/                 # 이미 있음: config, daily_store, telegram, keep_awake …
    data/                 # (새) 자료 읽기 — 일봉(9-14 통합 보정), 1분봉(minute_history+kang_minute), 수급, 지수, 네이버 테마
    market.py             # (새) 시장 분위기 판정(U/N+/N-/D)·지수 20일선 — 백테스트·실시간 공용
    leader.py             # (새) 테마 대장 판단 (지금 cafe_leader.leaders + run_cafe_leader_backtest.leader_at)
    krx.py                # (새) 호가 단위·상한가 계산 (지금 indicators/hong.py 의 tick_size·upper_limit)
  backtest/               # (새)
    engine.py             # 공통 엔진 (지금 .claude/skills/danswer/scripts/engine.py) — 1분봉·체결·다음 날 시가·비용
    report.py             # 결과 집계 (★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +), 표 출력
    account.py            # 계좌 시뮬레이터 (지금 full_bt.account — 현금 나눠 쓰기, 복리)
    playbook/             # 매매표 전체 1년 백테스트 (지금 스크래치 full_bt·compound·swing3) — 입력은 data/backtest/playbook/
  execution/              # (새)
    real.py               # 실전 (지금 screener/real_inverse.py)
    paper.py              # 키움 모의 (지금 screener/paper_trader.py)
    ledger.py             # 가상 장부 하나 (표 하나 + book 칸) — 지금 다섯 벌을 합침
    router.py             # 신호 → 계좌 (실전 '그날 먼저 온 하나', 모의 금액 규칙·👑 배수, 가상 장부)
  strategies/             # (새) 매매법마다 폴더 하나
    <이름>/
      rules.py            # 규칙 (순수 함수, 숫자는 params)
      live.py             # 실시간: prepare(전날 마감 자료) · on_minute(시세) → 신호 [+ 매도 계획]
      backtest.py         # 1년 백테스트 (backtest.engine 사용) → data/<이름>/backtest.txt
      README → 스킬로 대신
  screener/               # 장중 실행기 — 포착·알림·순위 저장 등 '매매법이 아닌 것' + 얇은 run_intraday
  ingestion/              # 그대로 (수집)
  analysis/               # 옮기는 동안 남는 옛 백테스트, 다 옮기면 비움
.claude/skills/
  (공통) trading-ops      # 운영·스케줄·키움·커밋
  (공통) backtest-rules   # (새) 자료 함정·매도 규칙·★ 판정·엄밀성 체크리스트 (지금 메모리·각 스킬에 흩어진 것)
  (매매법) <이름>/SKILL.md # 아래 틀
```

### 3-1. 매매법 공통 틀 (`strategies/<이름>/live.py`)
```python
class Strategy(Protocol):
    name: str                       # 'hong_limitup'
    tag: str                        # '📕 상한가 풀림' — 알림·표에 쓰는 이름
    def prepare(self, ctx: DayContext) -> None: ...          # 장 전: 전날 마감 자료(대상 종목·기준값)
    def on_minute(self, now, snap: MarketSnapshot) -> list[Signal]: ...   # 매분: 대금 순위·시세·수급·테마 대장
    def exit_plan(self, signal) -> ExitPlan: ...             # 익절·손절·시간·다음 날 09:00
```
- `MarketSnapshot` = 그 분의 대금 상위 200·조회 순위·장중 수급·프로그램·👑 테마 대장·시장 분위기 (run_intraday 가 한 번 만들어 모든 매매법에 나눠 줌).
- `Signal` 에 매도 계획을 함께 실어 보내면 실전·모의·가상 장부가 같은 매도 규칙을 쓴다.
- `run_intraday` 는 `STRATEGIES = [...]` 목록을 돌기만 한다. 매매법 추가 = 폴더 하나 + 목록 한 줄.

### 3-2. 가상 장부 하나 (`execution/ledger.py`)
- 표 `ledger_trades(id, book, date, code, name, buy_ts, buy_price, qty, plan, partial…, sell_ts, sell_price, reason, pnl, status, note)`, `ledger_days(book, date, reported)`.
- 장부 = 이름·시작 금액·하루 종목 수·건당 비율. 매도(손절·익절·절반·다음 날 09:00·애프터)와 마감 요약은 한 곳.
- 옮기는 동안 옛 표(`small_trades`, `jh_trades`, `hg_trades`, `cafe_trades`, `hs_trades`)는 읽기 전용으로 남기고 잔고를 넘겨받는다.

### 3-3. 매매법 스킬 틀 (`.claude/skills/<이름>/SKILL.md`)
1. 한 줄 요약 · 출처(책·영상·일지) · 사용자 요청 기록
2. **지금 상태** — 실전 / 모의 / 가상 장부 / 알림만 / 중단 (날짜·PR)
3. 규칙 (숫자는 `rules.py`·params 와 같게)
4. 1년 결과 표 — **재현 명령**과 결과 파일 경로를 반드시 함께
5. 운영 (표 이름, 알림, 점검 명령)
6. 결정 기록 (날짜·사용자 말·근거 숫자)
- 공통 내용(자료 함정, 매도 규칙, ★ 판정)은 `backtest-rules` 스킬을 가리키고 되풀이하지 않는다.

## 4. 옮기는 순서 (단계마다 확인 통과해야 다음)

| 단계 | 내용 | 실행 코드 영향 | 확인 |
|---|---|---|---|
| **1** | 스크래치 검증 자료 보존: 임시 폴더 5곳의 스크립트·입력 파일을 `data/research_archive/`(로컬, git 제외)로, 매매표 계좌 백테스트를 `kiwoom_trading/backtest/playbook/` 로 옮겨 저장소 경로로 실행 | 없음 | 옛 결과 `full_bt.txt` 와 숫자 같음 |
| **2** | 공통 엔진을 `kiwoom_trading/backtest/engine.py` 로, 옛 경로는 같은 모듈을 가리키게 남김 | 없음 | 디앤서·홍인기·카페 백테스트 결과 같음 |
| 3 | `common/krx.py`·`market.py`·`leader.py` 로 공통 판단 모으기 (옛 함수는 새 함수를 부름) | 있음 (장 밖) | 장중 기록 재현(10-19~10-26) 신호·매매 같음 |
| 4 | `execution/ledger.py` 가상 장부 하나로 합치기, 옛 장부 하나씩 옮김 | 있음 (장 밖) | 재현 매매·잔고 같음 |
| 5 | `Strategy` 틀 + `run_intraday` 목록 방식, 매매법 하나씩 `strategies/` 로 | 있음 (장 밖) | 매매법마다 재현 같음 |
| 6 | 스킬을 틀에 맞추고 `backtest-rules` 공통 스킬 만들기 | 없음 | 스킬 숫자 = 재현 명령 결과 |

- 단계마다 PR 하나, 바로 머지 (다른 세션과 충돌 줄이기). 3~5 는 장 밖(15:45 뒤·주말)에만.
- 다른 세션 작업(윤타·데이트레이더 등)은 옮기는 동안 새 구조 위에서 하도록 이 문서를 가리킨다.

## 5. 장중 기록 재현 시험 (3~5 단계 확인 방법)
- 입력: `screener.duckdb` 의 `rank_snapshots`(매분 대금 순위), `investor_intraday`, `program_intraday`, 일봉 DB 의 `minute_ohlcv`(그날 1분봉).
- 시세 조회를 1분봉으로 흉내 내는 가짜 market 으로 그날을 매분 다시 돌려, 바꾸기 전·후의 신호·가상 매매 목록이 같은지 본다.
- 오늘(10-27) 쓴 재현 스크립트(스크래치 `cafe_replay.py`·`hs_replay.py`)를 `kiwoom_trading/backtest/replay.py` 로 정리해 공용으로 쓴다.

## 6. 진행 기록
- 2026-10-27 05:40 설계 문서 작성. 사용자: "실행 코드 역시 수정 — 제안한 내용 모두 실행, 장 시작 전 시간 충분".
- 같은 날 장 전(07:30 전) 진행 — 별도 worktree 에서 단계마다 '전과 같은 결과' 확인 후 main 에 머지:
  1. ✅ 매매표 계좌 백테스트 → `kiwoom_trading/backtest/playbook/` (옛 full_bt.txt 와 숫자 완전히 같음), 스크래치 보존 `data/research_archive/`
  2. ✅ 공통 엔진 → `kiwoom_trading/backtest/engine.py` (사흘치 매매 82건 같음)
  3. ✅ `common/krx.py`·`leader.py`·`market.py` (카페·상따 밖 장중 재현 같음, 테마 대장 판단 512건 같음)
  4. ✅ `execution/ledger.py` 공용 가상 장부 — 📕 상한가 풀림·📕 상따 밖·☕ 카페·📘 전황 (루닛·컨텍·삼성E&A 등 매매·잔고 같음)
  5. ✅ `strategies/{hong_limitup,hong_styles,cafe_leader,jeonhwang}/` + `execution/{real,paper,small}.py`, 실행기 `books` 목록
     (실전 끔·복사 DB 로 실행기 6회 실행 오류 없음). 옛 경로는 모두 같은 모듈을 가리키는 연결 파일로 남김.
  6. ✅ 스킬 경로 갱신, 공통 스킬 `backtest-rules` 신설
- 같은 날 06:00~07:10 사용자 "남은 것도 지금 다 옮겨줘" (PR #99):
  - ✅ 매매법 코드 전부 `strategies/` 로 — ①③⑥ regime_plays · ② resistance_retest · ④ contra_close · ⑤ inverse · ⑦ trend_hold ·
    🧭📒🌙 danswer(close·watch·rebreak) · 🍔 hamburger(rules·live·backtest) · bigcap_flow · early_nine · pullback_breakout · leader_shape ·
    65기법 sixty_five · 테스타 testa (옛 경로는 연결 파일, 모듈 53개 불러오기 확인)
  - ✅ 💰 10만 원 계좌 → 공용 장부 book '10만 원' (small_trades 거래·보유 인버스 넘겨받음, 예전·새 코드 매매·잔고 같음)
  - ✅ 장중 재현 도구 `kiwoom_trading/backtest/replay.py`
  - ✅ 스킬·문서 경로 갱신
- 남은 일:
  - 매매표 계좌 백테스트 입력 pkl(①②③④·mismatch) 재생성 — 만든 스크립트가 없어 매매법마다 `strategies/<이름>/backtest.py` 를 새로 짜고
    보존본(data/backtest/playbook)과 같은 매매가 나오는지 확인해야 함 (몇 시간 작업, 장 밖에서 하나씩)
  - ①③⑥ 은 한 파일(regime_plays) 안에 있음 — 매매법별 폴더로 더 나눌지는 위 백테스트 작업 때 함께
  - 디앤서 스킬 폴더의 백테스트 스크립트(.claude/skills/danswer/scripts/t_*.py)를 strategies/danswer/ 로
  - 옛 경로 연결 파일은 다른 세션 코드까지 새 경로로 바뀐 뒤 지움
