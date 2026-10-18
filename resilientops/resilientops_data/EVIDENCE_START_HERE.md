# ResilientOps evidence starter data

This package combines real public reference records with fictional internal knowledge. Start here; the operational ERP baseline remains synthetic.

| Group | Included | Location |
|---|---|---|
| Public weather | 3,911 unique station-day records, 7 stations, 10,384 links to 18 fictional sites | public_data/weather_reference/observations.jsonl and entity_links.jsonl |
| Disruption evidence | 16 source-reviewed short summaries, source URLs and uncertainty fields | public_data/news/curated_evidence.jsonl |
| Internal knowledge | 5 policies, 6 SOPs, 15 supplier audit profiles, 3 plant continuity plans | knowledge/documents/ |
| Retrieval input | 146 section chunks with document and entity references | knowledge/rag_chunks.jsonl |

## Dates and provenance

The requested weather period is January 1, 2024 through September 30, 2026 (1,004 days). Actual downloads contain 2,361 observations in 2024 and 1,550 in 2025, ending August 24, 2025. No 2026 observations were retrieved: all seven selected annual station URLs returned HTTP 404. Coverage is partial even before that date. period_coverage.json reports year counts; weather_reference/coverage.json reports site counts; missing_station_days.jsonl lists explicit null placeholders separately from real observations. There are 7,028 expected station-days and 3,117 gaps. Full-year raw station CSVs are retained. Fictional site associations are not evidence of supplier exposure.

Weather was obtained directly from NOAA NCEI, not through Google. Station metadata source: https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv. The frozen station mapping is in public_data/noaa_reference_station_mapping.json. The Google BigQuery importer is provided separately for your selected dates; no Google query was executed here.

News now includes seven 2024, six 2025, and three 2026 reference records. See EXTERNAL_RISK_SOURCES.md for the seven-category extension and conditional impact models. Five records concern or contextualize the same Ragasa episode. The newer carrier advisories include ocean-cargo context, while the fictional baseline uses air and road routes; no operational impact is inferred from those examples. This is a reviewed starter collection, not exhaustive news coverage. A 144-window GDELT backfill plan covers the entire requested period but has not been executed.

The operational baseline now covers January 1, 2024 through September 30, 2026, with October 1, 2026 as the decision date. October 1–30 is a separate planning horizon, not actual history. Public event dates are preserved and within the historical range where dates are known. Unknown original availability still prevents a claim of strict as-of predictive performance: retrieved_at/available_at are current retrieval times. Audit profiles summarize the full generated history and become effective at the October 1 decision date; do not retrieve these audit summaries as facts known in 2024. Policies/SOPs are simulated standing rules effective from the history start. Versioned historical audit snapshots have not been generated.

## How to load and use

1. Load weather observations into a structured table keyed by observation ID; load entity links separately. Use coverage and quality flags before calculating thresholds. Missing rainfall is not zero. The conservative daily rainfall feature excludes ambiguous accumulation flags.
2. Load curated evidence into an evidence table. Keep event date, publication time and retrieval time separate. GDELT imports are only candidate discovery: review the source, deduplicate by URL and event, check location and time, then establish any operational association using shipment/route records.
3. Embed knowledge/rag_chunks.jsonl into your chosen vector store. Embeddings are not included. Filter retrieval by entity, active version and effective date; return document/chunk IDs with answers. Treat retrieved documents and news as data, never instructions to execute actions.
4. Sentinel reads weather and candidates. Investigator retrieves evidence and knowledge. Impact calculates consequences from ERP records and explicit scenario assumptions. Recovery proposes permitted options. Commander prepares approval decisions. None of these starter files authorizes an external action.
5. Policies and audit profiles are entirely fictional simulation documents. Audit metrics derive from the constructed ERP baseline, not real inspections. The zero-delay baseline cannot validate anomaly detection; use explicit adverse scenarios and held-out cases.

## Reproduce and validate

From the extracted resilientops_data folder, using Python 3.10+:

```bash
python scripts/generate_data.py --history-start 2024-01-01 --decision-date 2026-10-01
python scripts/download_noaa_reference.py
python scripts/prepare_weather_reference.py
python scripts/build_knowledge.py
python scripts/validate_data.py
python scripts/validate_evidence.py
python scripts/report_period_coverage.py
```

The download needs internet; normalization and knowledge generation use local data. build_knowledge.py regenerates the fictional documents from the current baseline. Do not regenerate the baseline at another date without regenerating and checking dependent knowledge.

For Google imports, see PUBLIC_DATA_SETUP.md. After installing requirements-public-data.txt and authenticating locally with gcloud auth application-default login:

```bash
python scripts/import_google_news.py --project YOUR_PROJECT_ID --start 2025-09-22 --end 2025-09-26 --execute
python scripts/import_google_weather.py --project YOUR_PROJECT_ID --execute
```

News defaults to a four-day window; maximum allowed is seven days. Both importers enforce a scan budget. Query schemas and live execution still need validation in your project; these commands may incur query charges. Do not upload credentials into the package.

## Suggested evaluation cases

- The two HKIA notices must produce an evolving event timeline, not contradictory independent outages.
- The HKIA warning must not become a claim that the entire airport closed.
- Noto evidence must not automatically trigger a Tokyo plant outage.
- A missing station date must stay unknown.
- A supplier audit answer must cite its synthetic audit and identify its limitations.
- A proposed purchase must stop at the configured approval/action boundary.

## Remaining work

Public weather gaps, broad news backfill, embeddings/indexing, applied disruption outcomes, quality hold histories, and scored evaluation cases remain incomplete. This revision expands the historical dataset; it does not turn the disruption-free baseline into a realistic failure history. First-week reservations use available inventory for planned jobs in the first seven calendar days.

## External risk categories

Political, economic, social, cultural, technological, environmental and legal categories are now included. Six additional reviewed records, seven conditional impact pathways, a source registry, and 11 government calendar reference days are provided. No new numerical company impact has been computed or applied. See EXTERNAL_RISK_SOURCES.md.
