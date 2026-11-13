select *
from {{ ref('stg_market_ohlcv_1m') }}
where volume < 0 or trade_count <= 0
