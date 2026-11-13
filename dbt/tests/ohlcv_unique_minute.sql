select symbol, window_start, count(*) as row_count
from {{ ref('stg_market_ohlcv_1m') }}
group by symbol, window_start
having count(*) > 1
