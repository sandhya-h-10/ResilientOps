# External causes and conditional operational impacts

Scope: historical evidence dated within January 2024–September 2026. Seven categories retain cultural factors separately from social factors. These are source-backed examples and conditional impact designs, not a completed event-impact dataset.

| Category | Signals | Conditional business impact | Included source examples |
|---|---|---|---|
| Political | conflict, border restrictions, trade policy | altered routes, sourcing constraints, longer lead time | WTO April 2025 outlook; Maersk 2026 Hormuz advisory |
| Economic | FX, commodity prices, inflation, demand | landed cost, margins, working capital, order volume | World Bank October 2024 commodity report; WTO outlook |
| Social | strikes, labor availability, public-health restrictions | fewer capacity hours, transport backlog | ILA/USMX October 2024 recovery statement |
| Cultural | public holidays, festivals, planned closures | available workdays, dispatch dates, prebuild needs | China State Council 2026 calendar, including make-up days |
| Technological | software outage, cyber incident, equipment failure, obsolescence | processing interruptions, lost production hours | CrowdStrike July 2024 incident report |
| Environmental | storms, floods, earthquake, heat, drought | physical site/route disruption, delayed supply | NOAA observations, HKO/JMA and official transport notices |
| Legal | export controls, customs, compliance, binding sanctions | blocked options or clearance delay | BIS December 2024 semiconductor announcement |

The signal list is the intended monitoring scope; the included sample does not cover every listed signal. No risk is inferred from nationality, culture, protected traits, or general country-level news.

## Files

- public_data/news/curated_evidence.jsonl: 16 reviewed source summaries with primary/secondary categories. Short paraphrases only; no full article bodies.
- public_data/external_risk/source_registry.json: 19 source entries and their ingestion status. URLs and publishers are recorded explicitly.
- public_data/external_risk/impact_pathways.jsonl: seven conditional causal pathways with input requirements, metrics, calculation guidance and guardrails.
- public_data/external_risk/calendar_reference.jsonl: nine Spring Festival holiday dates and two make-up workdays. This is a government calendar reference, not a confirmed factory schedule.
- public_data/external_risk/event_schema.json: proposed entity-exposure and calculated-impact record contract.
- public_data/external_risk/validation.json: category and reference integrity results.

## Evidence versus calculated impact

Source evidence describes the public event. Exposure assessment links that event to a particular route, site, component, system or contract. The Impact agent then uses verified inputs or explicitly labeled scenario assumptions to calculate consequences. The current update adds source context and calculation designs; it applies no new operational impacts and computes no new losses.

Example: a storm notice does not imply five days of supplier delay. A scenario may assume a five-day delay, but that duration must be stored as a synthetic assumption, not as a source fact. Similarly, a macroeconomic forecast is not a customer-order forecast, and commodity prices do not transfer one-for-one into controller component prices.

A single event may have several categories. Use its event_cluster_id and affected operation/time interval to prevent charging the same delay or lost output twice. Distinguish announcement, effective date, event onset, suspension/restoration, publication and retrieval. Do not use today's knowledge as if known during a 2024 decision replay.

## Agent operating rules

1. Sentinel collects signals in all seven categories, preserving dates, source and event identity. News search discovers candidates; it does not certify facts or legal applicability.
2. Investigator checks the source, geography, transport mode, time, entity identity, component/contract scope and software dependency. It may conclude unrelated, possible, confirmed, or insufficient evidence. Retrieve the original notice or effective rule for high-consequence decisions.
3. Impact uses structured operational data. Report baseline, scenario value, delta, unit, time horizon and assumption IDs. If required inputs are missing, return an unquantified exposure rather than invent a number.
4. Recovery evaluates permitted sourcing, transfer, rescheduling or transport options subject to capacity, calendars and verified compliance constraints.
5. Commander presents evidence, assumptions, unresolved applicability, cost/production consequences and approval requirements. Existing action boundaries remain in force.

## Sources and coverage status

Actual source URLs are in source_registry.json. World Bank monthly prices, market FX histories, broad labor/public-health feeds, full calendars for all three countries and binding legal rule texts have not been ingested. UNCTAD was identified as a relevant political/shipping source, but full-page retrieval returned 403; its search metadata is catalogued separately and not promoted into a reviewed evidence record. NOAA remains partial with the previously reported 2025/2026 gaps.

The ILA example concerns US ocean ports, absent from the fictional Asia air/road network: it is useful for rejecting irrelevant alerts. Maersk ocean evidence has the same mode-applicability limitation. The legal example concerns specific advanced-semiconductor controls, not all automotive chips. The technology example is a software-update failure, not a cyberattack. Cultural calendars must be matched to confirmed site shifts; current baseline calendars still use weekdays only.

## Remaining implementation/data

- Asset/software-to-site dependency inventory and actual outage telemetry.
- HS/ECCN classification, origin, legal entity identifiers, license status and versioned applicable rule records.
- Contract currency, commodity exposure weights and pass-through terms; verified market histories.
- Confirmed supplier calendars, shifts, closures and make-up workdays for 2024–September 2026.
- Event-to-operational-entity mappings and independently labeled applied scenarios.
- Quantified outcome/evaluation records and RAG embeddings/indexing.

Rebuild the curated extension with `python scripts/build_external_risk_context.py`, then `python scripts/report_period_coverage.py` and `python scripts/validate_evidence.py`. Source verification is a human-reviewed preparation step; the build script does not re-fetch or update legal rules automatically.
