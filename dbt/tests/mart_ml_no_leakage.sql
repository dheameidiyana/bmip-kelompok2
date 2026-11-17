select *
from {{ ref('mart_ml') }}
where label_start is not null
  and (
      label_start <> window_start
      or label_end <> window_start + interval 1 hour
  )
