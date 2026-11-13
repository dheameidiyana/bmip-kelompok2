{{ config(materialized='table', schema='intermediate') }}

with bars as (

    select * from {{ ref('stg_market_ohlcv_1m') }}

),

returns as (

    select
        *,
        ln(close / lag(close) over (partition by symbol order by window_start)) as ret_1m
    from bars

),

hourly as (

    select
        symbol,
        date_trunc('hour', window_start) as window_start,
        arg_min(open, window_start) as open,
        max(high) as high,
        min(low) as low,
        arg_max(close, window_start) as close,
        sum(volume) as volume,
        sum(quote_volume) as quote_volume,
        sum(trade_count) as trade_count,
        sum(quote_volume) / nullif(sum(volume), 0) as vwap,
        stddev_samp(ret_1m) as realized_vol_1h,
        count(*) as minute_bars,
        max(updated_at) as updated_at
    from returns
    group by 1, 2

),

with_return as (

    select
        *,
        ln(close / lag(close) over (partition by symbol order by window_start)) as log_return_1h
    from hourly

),

ewma as (

    with recursive base as (

        select
            symbol,
            window_start,
            row_number() over (partition by symbol order by window_start) as rn,
            realized_vol_1h
        from with_return

    ),

    calc (symbol, window_start, rn, rv_ewma_24h) as (

        select symbol, window_start, rn, realized_vol_1h
        from base
        where rn = 1

        union all

        select
            b.symbol,
            b.window_start,
            b.rn,
            (2.0 / 25.0) * b.realized_vol_1h + (23.0 / 25.0) * c.rv_ewma_24h
        from base b
        join calc c
            on b.symbol = c.symbol
            and b.rn = c.rn + 1

    )

    select symbol, window_start, rv_ewma_24h from calc

),

sources as (

    select
        symbol,
        date_trunc('hour', event_ts) as window_start,
        case when count(distinct source) = 1 then min(source) else 'mixed' end as source
    from {{ ref('stg_market_trades') }}
    group by 1, 2

)

select
    h.symbol,
    h.window_start,
    cast(h.open as decimal(18, 8)) as open,
    cast(h.high as decimal(18, 8)) as high,
    cast(h.low as decimal(18, 8)) as low,
    cast(h.close as decimal(18, 8)) as close,
    cast(h.volume as decimal(18, 8)) as volume,
    cast(h.quote_volume as decimal(18, 8)) as quote_volume,
    cast(h.trade_count as bigint) as trade_count,
    cast(h.vwap as decimal(18, 8)) as vwap,
    cast(h.log_return_1h as double) as log_return_1h,
    cast(h.realized_vol_1h as double) as realized_vol_1h,
    cast(e.rv_ewma_24h as double) as rv_ewma_24h,
    coalesce(s.source, 'binance_ws') as source,
    h.updated_at,
    cast(h.window_start as date) as event_date
from with_return h
left join ewma e
    on h.symbol = e.symbol
    and h.window_start = e.window_start
left join sources s
    on h.symbol = s.symbol
    and h.window_start = s.window_start
