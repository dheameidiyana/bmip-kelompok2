{{ config(materialized='table', schema='gold') }}

with features as (

    select * from {{ ref('int_market_features_1h') }}

),

sentiment_previous_hour as (

    select
        window_start + interval 1 hour as window_start,
        mean_sentiment as sent_mean_1h,
        positive_share as sent_pos_share,
        negative_share as sent_neg_share,
        post_count as post_count_1h,
        engagement_per_post as engagement_1h
    from {{ ref('int_social_sentiment_1h') }}

),

minute_returns as (

    select
        symbol,
        window_start,
        ln(close / lag(close) over (partition by symbol order by window_start)) as ret_1m
    from {{ ref('stg_market_ohlcv_1m') }}

),

labels as (

    select
        symbol,
        date_trunc('hour', window_start) as window_start,
        cast(stddev_samp(ret_1m) as double) as label_rv_next_1h,
        date_trunc('hour', min(window_start)) as label_start,
        date_trunc('hour', min(window_start)) + interval 1 hour as label_end
    from minute_returns
    group by 1, 2

)

select
    f.symbol,
    f.window_start,
    f.ret_5m,
    f.ret_15m,
    f.ret_60m,
    f.rv_5m,
    f.rv_15m,
    f.rv_60m,
    f.volume_z_60m,
    f.trade_count_60m,
    f.hl_range_1m,
    f.vwap_dev,
    s.sent_mean_1h,
    s.sent_pos_share,
    s.sent_neg_share,
    s.post_count_1h,
    s.engagement_1h,
    l.label_rv_next_1h,
    l.label_start,
    l.label_end,
    '{{ var("feature_snapshot_id", "dev") }}' as feature_snapshot_id,
    case
        when f.ret_60m is not null
            and f.rv_60m is not null
            and l.label_rv_next_1h is not null
        then 'pass'
        else 'warn'
    end as dq_status,
    cast(f.window_start as date) as event_date,
    f.window_start as event_hour,
    '{{ var("feature_snapshot_id", "dev") }}' as snapshot_id
from features f
left join sentiment_previous_hour s
    on f.window_start = s.window_start
left join labels l
    on f.symbol = l.symbol
    and f.window_start = l.window_start
