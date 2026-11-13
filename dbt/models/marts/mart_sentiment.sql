{{ config(materialized='table', schema='gold') }}

select
    window_start,
    post_count,
    unique_authors,
    mean_sentiment,
    positive_share,
    negative_share,
    neutral_share,
    total_likes,
    total_reposts,
    total_replies,
    engagement_per_post,
    top_hashtags,
    sentiment_model_version,
    updated_at,
    cast(window_start as date) as event_date
from {{ ref('int_social_sentiment_1h') }}
