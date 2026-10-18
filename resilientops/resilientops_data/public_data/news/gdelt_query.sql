SELECT GKGRECORDID, CAST(DATE AS STRING) AS gdelt_date,
DocumentIdentifier AS source_url, SourceCommonName AS publisher,
V2Themes AS themes, V2Locations AS locations
FROM `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE _PARTITIONTIME >= TIMESTAMP(@start_date)
AND _PARTITIONTIME < TIMESTAMP(@end_date)
AND REGEXP_CONTAINS(LOWER(IFNULL(V2Locations,'')), @location_pattern)
AND REGEXP_CONTAINS(LOWER(CONCAT(IFNULL(V2Themes,''),' ',IFNULL(DocumentIdentifier,''))), @topic_pattern)
AND STARTS_WITH(DocumentIdentifier,'http')
QUALIFY ROW_NUMBER() OVER(PARTITION BY DocumentIdentifier ORDER BY DATE DESC, GKGRECORDID)=1
ORDER BY DATE DESC, GKGRECORDID
LIMIT @max_records
