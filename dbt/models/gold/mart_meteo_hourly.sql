{{
  config(
    materialized='incremental',
    unique_key='meteo_hourly_key',
    incremental_strategy='delete+insert'
  )
}}

with
{% if is_incremental() %}
lookback as (
    select max(ingested_at) - interval '1 hour' as cutoff from {{ this }}
),
{% endif %}

fact as (
    select * from {{ ref('fct_meteo_hourly') }}
    {% if is_incremental() %}
    where ingested_at > (select cutoff from lookback)
    {% endif %}
),

time_dim as (
    select * from {{ ref('dim_time') }}
)

select
    fact.meteo_hourly_key,
    fact.timestamp_utc,
    fact.sunshine_duration_s,
    fact.shortwave_radiation_wm2,
    fact.direct_radiation_wm2,
    fact.cloud_cover_pct,
    time_dim.season,
    time_dim.is_daytime,
    fact.ingested_at
from fact
inner join time_dim on fact.time_key = time_dim.time_key
