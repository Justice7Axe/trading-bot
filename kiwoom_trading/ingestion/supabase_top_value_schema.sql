create table if not exists public.kiwoom_top_value_minute (
  id bigserial primary key,
  collected_at timestamptz not null default now(),
  snapshot_minute text not null,
  condition_seq text not null,
  market_type text not null,
  stock_code text not null,
  stock_name text,
  current_price integer,
  change_rate numeric(10, 4),
  cum_trade_value bigint not null,
  trade_value_rank integer not null,
  raw_item jsonb not null
);

create index if not exists idx_kiwoom_top_value_snapshot
  on public.kiwoom_top_value_minute (snapshot_minute, trade_value_rank);

create index if not exists idx_kiwoom_top_value_code_time
  on public.kiwoom_top_value_minute (stock_code, collected_at desc);
