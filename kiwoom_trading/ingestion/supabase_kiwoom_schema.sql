create table if not exists public.kiwoom_realtime_ticks (
  id bigserial primary key,
  collected_at timestamptz not null default now(),
  event_time text,
  stock_code text not null,
  current_price integer,
  price_change integer,
  change_rate numeric(10, 4),
  trade_volume integer,
  cum_trade_volume bigint,
  cum_trade_value bigint,
  open_price integer,
  high_price integer,
  low_price integer,
  best_ask integer,
  best_bid integer,
  market_type text,
  trade_strength numeric(10, 4),
  raw_values jsonb not null
);

create index if not exists idx_kiwoom_realtime_ticks_code_time
  on public.kiwoom_realtime_ticks (stock_code, collected_at desc);
