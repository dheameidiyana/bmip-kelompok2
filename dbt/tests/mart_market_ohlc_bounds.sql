-- OHLC invariants and non-negative volume at the gold layer.
select *
from {{ ref('mart_market') }}
where not (
    low <= open
    and open <= high
    and low <= close
    and close <= high
    and high >= low
    and volume >= 0
    and trade_count > 0
)
