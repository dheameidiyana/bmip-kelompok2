select *
from {{ ref('stg_market_ohlcv_1m') }}
where ohlc_state <> 'valid'
