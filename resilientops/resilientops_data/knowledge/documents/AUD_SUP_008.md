# Simulated supplier audit SUP_008

Document AUD_SUP_008 | Version 1.0 | Effective 2026-10-01

Fictional internal document for the ResilientOps simulation. This is not an actual supplier audit, legal policy or certification.

## 1. Audit scope and basis

Simulated desk-review profile for SUP_008, site SUP_008_SITE, country JP, coordinates 34.73, 135.5. Findings are derived from synthetic dataset v2_2024-01-01_2026-10-01_seed42. No physical inspection occurred.

## 2. Approved supply relationships

- SRC_PLT_MUM_MAT_003_A_1: MAT_003_A to PLT_MUM, APPROVED, alternate, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_MUM_MAT_008_A_0: MAT_008_A to PLT_MUM, APPROVED, primary, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_MUM_MAT_023_A_0: MAT_023_A to PLT_MUM, APPROVED, primary, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_TYO_MAT_003_A_1: MAT_003_A to PLT_TYO, APPROVED, alternate, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_TYO_MAT_008_A_0: MAT_008_A to PLT_TYO, APPROVED, primary, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_TYO_MAT_023_A_0: MAT_023_A to PLT_TYO, APPROVED, primary, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_BJS_MAT_003_A_1: MAT_003_A to PLT_BJS, APPROVED, alternate, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_BJS_MAT_008_A_0: MAT_008_A to PLT_BJS, APPROVED, primary, 210.00 JPY/EA, minimum 10, multiple 10.
- SRC_PLT_BJS_MAT_023_A_0: MAT_023_A to PLT_BJS, APPROVED, primary, 210.00 JPY/EA, minimum 10, multiple 10.

## 3. Lead time and capacity

Configured processing lead time is three days, excluding transport. supplier_capacity_daily specifies a shared order-release capacity of 10000 units per material per UTC day before commitments. This is a simulation configuration, not an independently verified equipment capacity. Read date-specific commitments before planning.

## 4. Logistics dependency

Configured outbound hub dependencies: HUB_JP. Other suppliers can share these hubs; alternate supply may therefore remain exposed. The hub coordinates are simulated and do not establish a connection to a real named airport.

## 5. Historical delivery findings

715 shipment lines were received across 34 historical reporting periods (up to 30 days each). The baseline reports 100 percent OTIF for periods with deliveries because it was constructed without disruptions. This metric is not a real-world reliability estimate.

## 6. Evidence gaps and follow-up

No real financial statements, quality certification, inspection results, legal attestations or confirmed future capacity reservations are supplied. Escalate requests for these facts. Use POL_001, POL_004 and SOP_005 for candidate assessment.
