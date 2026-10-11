create table if not exists public.analysis_signals (
  id bigserial primary key,
  analyzed_at timestamptz not null,
  minute_key text not null,
  stock_code text not null,
  latest_price numeric(18, 4),
  change_1m_pct numeric(12, 6),
  change_5m_pct numeric(12, 6),
  change_20m_pct numeric(12, 6),
  sma_5 numeric(18, 4),
  sma_20 numeric(18, 4),
  rsi_14 numeric(10, 4),
  bb_upper_20_2 numeric(18, 4),
  bb_lower_20_2 numeric(18, 4),
  latest_volume numeric(18, 4),
  avg_volume_20 numeric(18, 4),
  volume_spike_2x boolean not null default false,
  golden_cross boolean not null default false,
  dead_cross boolean not null default false,
  strategy_buy boolean not null default false,
  strategy_sell boolean not null default false,
  strategy_rsi numeric(10, 4),
  source_table text,
  created_at timestamptz not null default now()
);

alter table if exists public.analysis_signals
  add column if not exists golden_cross boolean not null default false;
alter table if exists public.analysis_signals
  add column if not exists dead_cross boolean not null default false;
alter table if exists public.analysis_signals
  add column if not exists strategy_buy boolean not null default false;
alter table if exists public.analysis_signals
  add column if not exists strategy_sell boolean not null default false;
alter table if exists public.analysis_signals
  add column if not exists strategy_rsi numeric(10, 4);

create unique index if not exists uq_analysis_signals_minute_stock
  on public.analysis_signals (minute_key, stock_code);
