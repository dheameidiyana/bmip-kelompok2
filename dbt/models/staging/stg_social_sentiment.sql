{{ config(materialized='view', schema='staging') }}

select
    post_key,
    event_ts,
    window_start,
    ingest_ts,
    sentiment_score,
    sentiment_pos,
    sentiment_neu,
    sentiment_neg,
    sentiment_label,
    sentiment_model_version,
    event_date
from {{ source('silver_social', 'social_sentiment') }}
