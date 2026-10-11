-- 운영 중 테이블에 컬럼을 추가/보정할 때 사용하세요.
-- 다른 테이블명을 쓰는 경우 아래 table 이름만 변경하면 됩니다.

alter table if exists public.kiwoom_top_value_minute
  add column if not exists collected_at timestamptz not null default now(),
  add column if not exists snapshot_minute text,
  add column if not exists condition_seq text,
  add column if not exists market_type text,
  add column if not exists stock_code text,
  add column if not exists stock_name text,
  add column if not exists current_price integer,
  add column if not exists change_rate numeric(10, 4),
  add column if not exists cum_trade_value bigint,
  add column if not exists trade_value_rank integer,
  add column if not exists raw_item jsonb;

create index if not exists idx_kiwoom_top_value_snapshot
  on public.kiwoom_top_value_minute (snapshot_minute, trade_value_rank);

create index if not exists idx_kiwoom_top_value_code_time
  on public.kiwoom_top_value_minute (stock_code, collected_at desc);

-- 3M 전략 등 종목명 저장용 (kiwoom_top_value_signals)
alter table if exists public.kiwoom_top_value_signals
  add column if not exists stock_name text;
