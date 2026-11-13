{{ config(materialized='table', schema='gold') }}

select
    symbol,
    window_start,
    open,
    high,
    low,
    close,
    volume,
    quote_volume,
    trade_count,
    vwap,
    log_return_1h,
    realized_vol_1h,
    rv_ewma_24h,
    source,
    updated_at,
    cast(window_start as date) as event_date
from {{ ref('int_market_ohlcv_1h') }}
