{{ config(materialized='view', schema='silver') }}

select
    symbol,
    window_start,
    window_end,
    open,
    high,
    low,
    close,
    volume,
    quote_volume,
    trade_count,
    vwap,
    event_date,
    ingest_ts,
    updated_at,
    symbol || '|' || cast(window_start as varchar) as market_bar_key,
    high - low as hl_range,
    case
        when low <= open
            and open <= high
            and low <= close
            and close <= high
            and high >= low
            and volume >= 0
            and trade_count > 0
        then 'valid'
        else 'invalid'
    end as ohlc_state
from {{ source('silver_market', 'market_ohlcv_1m') }}
