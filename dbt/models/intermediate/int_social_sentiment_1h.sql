{{ config(materialized='table', schema='intermediate') }}

with posts as (

    select
        p.post_key,
        p.author_key,
        p.event_ts,
        p.hashtags,
        p.like_count,
        p.repost_count,
        p.reply_count,
        s.sentiment_score,
        s.sentiment_label,
        s.sentiment_model_version
    from {{ ref('stg_social_post') }} p
    join {{ ref('stg_social_sentiment') }} s
        on p.post_key = s.post_key

),

hourly as (

    select
        date_trunc('hour', event_ts) as window_start,
        cast(count(*) as bigint) as post_count,
        cast(count(distinct author_key) as bigint) as unique_authors,
        cast(avg(sentiment_score) as double) as mean_sentiment,
        cast(
            avg(case when sentiment_label = 'positive' then 1.0 else 0.0 end) as double
        ) as positive_share,
        cast(
            avg(case when sentiment_label = 'negative' then 1.0 else 0.0 end) as double
        ) as negative_share,
        cast(
            avg(case when sentiment_label = 'neutral' then 1.0 else 0.0 end) as double
        ) as neutral_share,
        cast(sum(like_count) as bigint) as total_likes,
        cast(sum(repost_count) as bigint) as total_reposts,
        cast(sum(reply_count) as bigint) as total_replies,
        cast(
            cast(sum(like_count + repost_count + reply_count) as double) / count(*)
            as double
        ) as engagement_per_post,
        max(sentiment_model_version) as sentiment_model_version
    from posts
    group by 1

),

hashtags as (

    select
        date_trunc('hour', event_ts) as window_start,
        tag,
        cast(count(*) as bigint) as n
    from (
        select event_ts, unnest(hashtags) as tag
        from {{ ref('stg_social_post') }}
    ) exploded
    where tag is not null and tag <> ''
    group by 1, 2

),

top_hashtags as (

    select
        window_start,
        list(tag order by n desc, tag asc)[1:5] as top_hashtags
    from hashtags
    group by 1

),

bounds as (

    select
        date_trunc('hour', min(event_ts)) as lo,
        date_trunc('hour', max(event_ts)) as hi
    from posts

),

hours as (

    select unnest(generate_series(lo, hi, interval 1 hour)) as window_start
    from bounds

)

select
    h.window_start,
    coalesce(a.post_count, 0) as post_count,
    coalesce(a.unique_authors, 0) as unique_authors,
    a.mean_sentiment,
    a.positive_share,
    a.negative_share,
    a.neutral_share,
    coalesce(a.total_likes, 0) as total_likes,
    coalesce(a.total_reposts, 0) as total_reposts,
    coalesce(a.total_replies, 0) as total_replies,
    a.engagement_per_post,
    coalesce(t.top_hashtags, cast([] as varchar[])) as top_hashtags,
    coalesce(
        a.sentiment_model_version,
        '{{ var("sentiment_model_version", "vaderSentiment-3.3.2") }}'
    ) as sentiment_model_version,
    cast(now() as timestamp with time zone) as updated_at
from hours h
left join hourly a
    on h.window_start = a.window_start
left join top_hashtags t
    on h.window_start = t.window_start
