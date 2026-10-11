create table if not exists public.kiwoom_top_value_signals (
  id bigserial primary key,
  analyzed_at timestamptz not null default now(),
  snapshot_minute text not null,
  stock_code text not null,
  stock_name text,
  signal_side text not null check (signal_side in ('long', 'short')),
  signal_reason text not null,
  current_price numeric(18, 4),
  ma_5 numeric(18, 4),
  ma_25 numeric(18, 4),
  ma_75 numeric(18, 4),
  ma_75_prev numeric(18, 4),
  trade_value_rank integer,
  cum_trade_value bigint,
  source_table text not null,
  strategy_name text not null
);

create unique index if not exists uq_kiwoom_top_value_signals_unique
  on public.kiwoom_top_value_signals (snapshot_minute, stock_code, signal_side, strategy_name);

create index if not exists idx_kiwoom_top_value_signals_recent
  on public.kiwoom_top_value_signals (analyzed_at desc, stock_code);
