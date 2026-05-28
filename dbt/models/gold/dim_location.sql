with locations as (
    select distinct
        latitude,
        longitude
    from {{ ref('stg_meteo_hourly') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['latitude', 'longitude']) }} as location_key,
    latitude,
    longitude
from locations
