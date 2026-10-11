# kiwoom_trading

키움 REST/WebSocket 기반 데이터 파이프라인 프로젝트입니다.

- `ingestion`: 실시간 데이터 수집
- `analysis`: 분석 로직 실행 엔트리
- `common`: 공통 설정/저장 유틸

---

## 폴더 구조

```text
kiwoom_trading/
├── ingestion/
│   ├── __init__.py
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── kiwoom_login.py
│   │   ├── realtime_collector.py
│   │   └── scheduler.py
│   ├── run_ingestion.py
│   ├── requirements.txt
│   └── supabase_kiwoom_schema.sql
├── analysis/
│   ├── __init__.py
│   ├── indicators/
│   │   └── __init__.py
│   └── run_analysis.py
└── common/
    ├── __init__.py
    ├── config.py
    └── storage.py
```

---

## 1) 환경 변수(.env.local)

프로젝트 루트 `D:/Ellie/trading/.env.local`에 아래 값이 필요합니다.

- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `KIWOOM_APP_KEY`
- `KIWOOM_SECRET_KEY`

권장 값:

- `KIWOOM_BASE_URL=https://api.kiwoom.com`
- `KIWOOM_WS_URL=wss://api.kiwoom.com:10000/api/dostk/websocket`
- `KIWOOM_STOCK_CODES=005930,000660`
- `KIWOOM_WS_USE_LOGIN_PACKET=true`
- `KIWOOM_WS_USE_AUTH_HEADER=false`
- `KIWOOM_SAVE_INTERVAL_SECONDS=60`
- `KIWOOM_FORCE_RUN=false`
- `SUPABASE_TABLE=kiwoom_realtime_ticks`

---

## 2) Supabase 스키마 적용

Supabase SQL Editor에서 실행:

- `kiwoom_trading/ingestion/supabase_kiwoom_schema.sql`

---

## 3) 실행 방법

### 3-1. 기존 실시간 수집(ingestion)

```powershell
D:\Ellie\trading\.venv\Scripts\python -m pip install -r D:\Ellie\trading\kiwoom_trading\ingestion\requirements.txt
D:\Ellie\trading\.venv\Scripts\python D:\Ellie\trading\kiwoom_trading\ingestion\run_ingestion.py
```

동작 규칙:

- 평일 `09:00~11:00`만 수집
- 삼성전자(`005930`), 하이닉스(`000660`) 대상
- 종목별 최신값을 캐시 후 **1분마다 1건 저장**

### 3-2. 거래대금 상위 100 (09:00~11:00, 1분 스냅샷)

이 수집기는 **조건검색식 없이** REST `ka10032`(거래대금상위요청)를 1분마다 호출합니다.

필수/권장 환경변수:

- `KIWOOM_TOP_VALUE_SUPABASE_TABLE` (권장: `kiwoom_top_value_minute`)
- `KIWOOM_TOP_VALUE_MRKT_TP` (기본값: `000`, 시장구분: 전체)
- `KIWOOM_TOP_VALUE_MANAGEMENT_INCLS` (기본값: `0`, 관리종목 미포함)
- `KIWOOM_TOP_VALUE_STEX_TP` (기본값: `3`, 거래소구분: 통합)
- `KIWOOM_TOP_VALUE_INTERVAL_SECONDS` (기본값: `60`)
- `KIWOOM_TOP_VALUE_LIMIT` (기본값: `100`)
- `KIWOOM_TOP_VALUE_SIGNAL_TABLE` (기본값: `kiwoom_top_value_signals`)
- `KIWOOM_TOP_VALUE_SIGNAL_SCAN_INTERVAL_SECONDS` (기본값: `5`)
- `KIWOOM_TOP_VALUE_SIGNAL_MA_SHORT` (기본값: `5`)
- `KIWOOM_TOP_VALUE_SIGNAL_MA_MID` (기본값: `25`)
- `KIWOOM_TOP_VALUE_SIGNAL_MA_LONG` (기본값: `75`)
- `KIWOOM_TOP_VALUE_SIGNAL_SLOPE_LOOKBACK` (기본값: `3`)
- `SUPABASE_TABLE` (미설정 시 fallback 사용)

Supabase SQL Editor에서 아래 스키마를 먼저 실행하세요.

- `kiwoom_trading/ingestion/supabase_top_value_schema.sql`
- `kiwoom_trading/ingestion/supabase_top_value_signals_schema.sql`

실행:

```powershell
D:\Ellie\trading\.venv\Scripts\python D:\Ellie\trading\kiwoom_trading\ingestion\run_top_value_ingestion.py
```

실행 시 동작:

- `kiwoom_top_value_minute`에 거래대금 상위 스냅샷 저장
- 같은 스냅샷 기준 상위 종목을 이평(5/25/75) 규칙으로 검사
- 조건 충족 시 `kiwoom_top_value_signals`에 즉시 신호 저장

### 3-3. 분석(analysis)

```powershell
D:\Ellie\trading\.venv\Scripts\python D:\Ellie\trading\kiwoom_trading\analysis\run_analysis.py
```

현재 `run_analysis.py`는 `kiwoom_top_value_signals` 테이블의 최근 신호를 요약 출력합니다.

옵션 환경변수(선택):

- `ANALYSIS_SIGNAL_LIMIT` (기본 50)

---

## 4) 이전 실행 파일 관련

기존 경로:

- `.../kiwoom/kiwoom_realtime_to_supabase.py`

현재 경로:

- `.../kiwoom_trading/ingestion/run_ingestion.py`

즉, 앞으로는 `run_ingestion.py`를 실행하면 됩니다.
