{{ config(materialized='view', schema='staging') }}

select
    post_key,
    author_key,
    event_ts,
    ingest_ts,
    lang,
    text,
    hashtags,
    like_count,
    repost_count,
    reply_count,
    quote_count,
    source,
    payload_hash,
    event_date,
    date_trunc('hour', event_ts) as event_hour,
    like_count + repost_count + reply_count as engagement
from {{ source('silver_social', 'social_post') }}
