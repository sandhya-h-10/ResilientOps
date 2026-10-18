# Public and synthetic data setup

## Source decisions

| Information | Source | Current state |
|---|---|---|
| Manufacturing network, BOM, approvals and transactions | Reproducible synthetic generator | Included and checked |
| Historical weather | NOAA GSOD hosted on Google BigQuery | SQL and importer included; download requires your project and credentials |
| News disruption evidence | GDELT on BigQuery | Bounded candidate importer and SQL included; not executed. Sixteen separately curated official source summaries included |
| Additional gridded historical weather | ECMWF ERA5-Land on Earth Engine | Optional alternative; not implemented |
| Retail data | TheLook / Google Merchandise Store | Omitted because neither supplies our manufacturing relationships |

## Run in Windows PowerShell or VS Code terminal

Open the extracted resilientops_data folder. Install the Google Cloud CLI separately if gcloud is not already available. Choose a Google Cloud project where you can run BigQuery jobs. Enable the BigQuery API if required. The project pays any query charges beyond applicable allowances.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-public-data.txt
gcloud auth application-default login
.\.venv\Scripts\python.exe scripts/import_google_weather.py --project YOUR_PROJECT_ID --execute
```

Keep login tokens and credentials outside the repository. No credential file or token should be sent in chat.

To prepare SQL only, with no cloud access or queries:

```powershell
py -3.12 scripts/import_google_weather.py
```

The importer runs a BigQuery dry run, prints estimated scanned bytes and enforces a default 2,000,000,000-byte maximum before execution. Change --max-bytes only after reviewing the estimate. The SQL is designed from Google's documented GSOD schema but has not been validated by a live BigQuery job in this environment. A schema, permissions, billing or location error must be resolved before claiming the public data is imported.

## Import behavior

1. Reads the three plants and fifteen fictional supplier sites from the generated tables.
2. Finds up to five nearby NOAA stations within 100 km per entity; override with --radius-km.
3. Uses the baseline's 1,004 historical dates, pruning yearly BigQuery tables.
4. Selects one station per entity, prioritizing number of reporting days then distance. It never silently averages different stations.
5. Retains raw station records and maps temperature from Fahrenheit to Celsius, wind from knots to m/s, and precipitation from inches to mm.
6. Converts NOAA sentinel missing values to null. Missing precipitation is not zero rain. Preserves flag_prcp; inspect accumulation/trace flags before using precipitation as a daily disruption feature.
7. Reports coverage per entity, missing sites, retrieval timestamp and BigQuery job ID.

Expected maximum: 18 entities × 1,004 dates = 18,072 mapped observations. The number of distinct station-date source records may be smaller because nearby sites share a station. Actual coverage may be lower and is never padded with invented observations.

Outputs go to public_data/noaa_raw.jsonl, weather_observations.jsonl and import_status.json. Public data is kept separate from the synthetic ERP and its manifest. The source flags distinguish observed NOAA records from their association with fictional entities.

## Interpretation and replay

Historical weather is not a live forecast, a supplier outage record or proof of a delay. Scenario impacts remain explicit simulation assumptions. The importer does not change production orders, shipments or recovery plans. It conservatively sets available_at_utc to retrieval time because original publication times are unknown. Do not present historical analysis as an as-of prediction at the earlier decision timestamp. For strict replay, use publication-time-aware source archives or label the run retrospective.

## Source references

- Google BigQuery public data access: https://docs.cloud.google.com/bigquery/public-data
- Google's NOAA schema/join example: https://cloud.google.com/blog/products/gcp/google-cloud-platform-for-data-scientists-using-r-with-google-bigquery
- NOAA in BigQuery: https://cloud.google.com/blog/products/data-analytics/whats-the-weather-like-using-colab-to-get-more-out-of-bigquery
- Local Google authentication: https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment

Check dataset-specific terms and source attribution before redistribution. This package includes NOAA archive records and short attributed paraphrases of official notices. See EVIDENCE_START_HERE.md for provenance and date boundaries.

## Expanded historical backfill

The requested history is 2024-01-01 through 2026-09-30 inclusive. Weather SQL now covers all three years. Direct NOAA downloads currently contain 2024 and partial 2025 records, with 2026 requests returning HTTP 404. This does not establish availability in other archives. GDELT has 144 seven-day-or-shorter windows in public_data/news/gdelt_backfill_windows.json. Process each through import_google_news.py --start START --end END after configuring your project. The importer writes one window at a time; archive each candidate output in a window-specific directory before the next run. Do not execute all windows without reviewing the cumulative cost and record-limit truncation risk.
