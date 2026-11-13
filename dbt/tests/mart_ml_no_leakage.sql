-- T-09: every feature must be computable from data at or before window_start,
-- and the label window must start exactly at window_start.
-- Unlabelled rows (the newest hour) are excluded; coverage is a separate check.
select *
from {{ ref('mart_ml') }}
where label_start is not null
  and (
      label_start <> window_start
      or label_end <> window_start + interval 1 hour
  )
