select
    symbol,
    window_start,
    count(*) as row_count
from {{ ref('mart_market') }}
group by 1, 2
having count(*) > 1
