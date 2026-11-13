{{ config(materialized='table', schema='intermediate') }}

with bars as (

    select * from {{ ref('stg_market_ohlcv_1m') }}

),

returns as (

    select
        *,
        ln(close / lag(close) over w) as ret_1m
    from bars
    window w as (partition by symbol order by window_start)

),

windowed as (

    select
        symbol,
        window_start,
        close,
        high,
        low,
        volume,
        quote_volume,
        trade_count,
        vwap,
        ret_1m,
        ln(close / lag(close, 5) over w) as ret_5m,
        ln(close / lag(close, 15) over w) as ret_15m,
        ln(close / lag(close, 60) over w) as ret_60m,
        stddev_samp(ret_1m) over (
            partition by symbol order by window_start rows between 4 preceding and current row
        ) as rv_5m,
        stddev_samp(ret_1m) over (
            partition by symbol order by window_start rows between 14 preceding and current row
        ) as rv_15m,
        stddev_samp(ret_1m) over (
            partition by symbol order by window_start rows between 59 preceding and current row
        ) as rv_60m,
        (high - low) / nullif(close, 0) as hl_range_1m,
        sum(quote_volume) over (
            partition by symbol order by window_start rows between 59 preceding and current row
        ) / nullif(sum(volume) over (
            partition by symbol order by window_start rows between 59 preceding and current row
        ), 0) as vwap_60m,
        sum(trade_count) over (
            partition by symbol order by window_start rows between 59 preceding and current row
        ) as trade_count_60m,
        avg(volume) over (
            partition by symbol order by window_start rows between 59 preceding and current row
        ) as vol_mean_60m,
        stddev_samp(volume) over (
            partition by symbol order by window_start rows between 59 preceding and current row
        ) as vol_std_60m
    from returns
    window w as (partition by symbol order by window_start)

),

boundary as (

    select
        *,
        date_trunc('hour', window_start) + interval 1 hour as feature_window_start,
        row_number() over (
            partition by symbol, date_trunc('hour', window_start)
            order by window_start desc
        ) as rn
    from windowed

)

select
    symbol,
    feature_window_start as window_start,
    cast(ret_5m as double) as ret_5m,
    cast(ret_15m as double) as ret_15m,
    cast(ret_60m as double) as ret_60m,
    cast(rv_5m as double) as rv_5m,
    cast(rv_15m as double) as rv_15m,
    cast(rv_60m as double) as rv_60m,
    cast((volume - vol_mean_60m) / nullif(vol_std_60m, 0) as double) as volume_z_60m,
    cast(trade_count_60m as bigint) as trade_count_60m,
    cast(hl_range_1m as double) as hl_range_1m,
    cast((close - vwap_60m) / nullif(vwap_60m, 0) as double) as vwap_dev
from boundary
where rn = 1
