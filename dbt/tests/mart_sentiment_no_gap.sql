-- Every hour between the first and last observation must appear exactly once.
with bounds as (

    select
        min(window_start) as lo,
        max(window_start) as hi,
        count(*) as actual
    from {{ ref('mart_sentiment') }}

),

expected as (

    select count(*) as expected
    from (
        select unnest(generate_series(lo, hi, interval 1 hour)) as window_start
        from bounds
    ) hours

)

select b.lo, b.hi, b.actual, e.expected
from bounds b
cross join expected e
where b.actual <> e.expected
