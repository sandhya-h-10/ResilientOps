-- NOAA observations mapped to fictional sites; this mapping does not prove disruption.
WITH entities AS (
 SELECT JSON_VALUE(e, '$.entity_id') entity_id,
 SAFE_CAST(JSON_VALUE(e, '$.latitude') AS FLOAT64) latitude,
 SAFE_CAST(JSON_VALUE(e, '$.longitude') AS FLOAT64) longitude
 FROM UNNEST(JSON_QUERY_ARRAY(@entities_json)) e
), stations AS (
 SELECT CAST(usaf AS STRING) usaf, CAST(wban AS STRING) wban, name,
 SAFE_CAST(lat AS FLOAT64) latitude, SAFE_CAST(lon AS FLOAT64) longitude
 FROM `bigquery-public-data.noaa_gsod.stations`
), nearest AS (
 SELECT e.entity_id, s.usaf, s.wban, s.name station_name,
 ST_DISTANCE(SAFE.ST_GEOGPOINT(e.longitude,e.latitude), SAFE.ST_GEOGPOINT(s.longitude,s.latitude))/1000 distance_km
 FROM entities e CROSS JOIN stations s
 WHERE s.latitude BETWEEN -90 AND 90 AND s.longitude BETWEEN -180 AND 180
 AND ST_DWITHIN(SAFE.ST_GEOGPOINT(e.longitude,e.latitude), SAFE.ST_GEOGPOINT(s.longitude,s.latitude), @radius_km * 1000)
 QUALIFY ROW_NUMBER() OVER(PARTITION BY e.entity_id ORDER BY distance_km,usaf,wban) <= 5
), observations AS (
 SELECT CAST(stn AS STRING) stn, CAST(wban AS STRING) wban,
 SAFE_CAST(CONCAT(year,'-',mo,'-',da) AS DATE) observation_date,
 temp, wdsp, prcp, flag_prcp
 FROM `bigquery-public-data.noaa_gsod.gsod*`
 WHERE _TABLE_SUFFIX BETWEEN '2024' AND '2026'
 AND SAFE_CAST(CONCAT(year,'-',mo,'-',da) AS DATE) BETWEEN @start_date AND @end_date
), candidate_data AS (
 SELECT n.*, o.observation_date,o.temp,o.wdsp,o.prcp,o.flag_prcp
 FROM nearest n JOIN observations o ON n.usaf=o.stn AND n.wban=o.wban
), ranked AS (
 SELECT entity_id,usaf,wban,COUNT(*) reporting_days,MIN(distance_km) distance_km
 FROM candidate_data GROUP BY entity_id,usaf,wban
 QUALIFY ROW_NUMBER() OVER(PARTITION BY entity_id ORDER BY reporting_days DESC,distance_km,usaf,wban)=1
)
SELECT c.* FROM candidate_data c JOIN ranked r USING(entity_id,usaf,wban)
ORDER BY entity_id,observation_date
