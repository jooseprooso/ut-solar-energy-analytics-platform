with source as (
    select
        timestamp_utc,
        latitude,
        longitude,
        variable_name,
        value
    from bronze.meteo_raw
    where value is not null
),

pivoted as (
    select
        timestamp_utc,
        latitude,
        longitude,
        max(case when variable_name = 'sunshine_duration' then value end) as sunshine_duration_s,
        max(case when variable_name = 'shortwave_radiation' then value end) as shortwave_radiation_wm2,
        max(case when variable_name = 'direct_radiation' then value end) as direct_radiation_wm2,
        max(case when variable_name = 'cloud_cover' then value end) as cloud_cover_pct
    from source
    group by timestamp_utc, latitude, longitude
)

select
    {{ dbt_utils.generate_surrogate_key(['timestamp_utc', 'latitude', 'longitude']) }} as meteo_hourly_key,
    timestamp_utc,
    latitude,
    longitude,
    sunshine_duration_s,
    shortwave_radiation_wm2,
    direct_radiation_wm2,
    cloud_cover_pct
from pivoted
