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

staging as (
    select * from {{ ref('stg_meteo_hourly') }}
    {% if is_incremental() %}
    where ingested_at > (select cutoff from lookback)
    {% endif %}
)

select
    {{ dbt_utils.generate_surrogate_key(['staging.timestamp_utc', 'staging.latitude', 'staging.longitude']) }} as meteo_hourly_key,
    {{ dbt_utils.generate_surrogate_key(['staging.timestamp_utc']) }} as time_key,
    {{ dbt_utils.generate_surrogate_key(['staging.latitude', 'staging.longitude']) }} as location_key,
    staging.timestamp_utc,
    staging.sunshine_duration_s,
    staging.shortwave_radiation_wm2,
    staging.direct_radiation_wm2,
    staging.cloud_cover_pct,
    staging.ingested_at
from staging
