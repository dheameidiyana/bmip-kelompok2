{{ config(materialized='view', schema='staging') }}

select
    symbol,
    trade_id,
    event_ts,
    ingest_ts,
    source,
    payload_hash,
    event_date
from {{ source('silver_market_trades', 'market_trades') }}
