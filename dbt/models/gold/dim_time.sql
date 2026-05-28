with hours as (
    select distinct timestamp_utc
    from {{ ref('stg_meteo_hourly') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['timestamp_utc']) }} as time_key,
    timestamp_utc,
    timestamp_utc::date as date_day,
    extract(hour from timestamp_utc) as hour_of_day,
    extract(dow from timestamp_utc) as day_of_week,
    extract(month from timestamp_utc) as month,
    case
        when extract(month from timestamp_utc) in (12, 1, 2) then 'winter'
        when extract(month from timestamp_utc) in (3, 4, 5) then 'spring'
        when extract(month from timestamp_utc) in (6, 7, 8) then 'summer'
        else 'autumn'
    end as season,
    case
        when extract(hour from timestamp_utc) between 6 and 20 then true
        else false
    end as is_daytime
from hours
