# Simulated supplier audit SUP_007

Document AUD_SUP_007 | Version 1.0 | Effective 2026-10-01

Fictional internal document for the ResilientOps simulation. This is not an actual supplier audit, legal policy or certification.

## 1. Audit scope and basis

Simulated desk-review profile for SUP_007, site SUP_007_SITE, country CN, coordinates 22.58, 114.06. Findings are derived from synthetic dataset v2_2024-01-01_2026-10-01_seed42. No physical inspection occurred.

## 2. Approved supply relationships

- SRC_PLT_MUM_MAT_002_A_1: MAT_002_A to PLT_MUM, APPROVED, alternate, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_MUM_MAT_007_A_0: MAT_007_A to PLT_MUM, APPROVED, primary, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_MUM_MAT_022_A_0: MAT_022_A to PLT_MUM, APPROVED, primary, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_TYO_MAT_002_A_1: MAT_002_A to PLT_TYO, APPROVED, alternate, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_TYO_MAT_007_A_0: MAT_007_A to PLT_TYO, APPROVED, primary, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_TYO_MAT_022_A_0: MAT_022_A to PLT_TYO, APPROVED, primary, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_BJS_MAT_002_A_1: MAT_002_A to PLT_BJS, APPROVED, alternate, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_BJS_MAT_007_A_0: MAT_007_A to PLT_BJS, APPROVED, primary, 10.00 CNY/EA, minimum 10, multiple 10.
- SRC_PLT_BJS_MAT_022_A_0: MAT_022_A to PLT_BJS, APPROVED, primary, 10.00 CNY/EA, minimum 10, multiple 10.

## 3. Lead time and capacity

Configured processing lead time is three days, excluding transport. supplier_capacity_daily specifies a shared order-release capacity of 10000 units per material per UTC day before commitments. This is a simulation configuration, not an independently verified equipment capacity. Read date-specific commitments before planning.

## 4. Logistics dependency

Configured outbound hub dependencies: HUB_CN. Other suppliers can share these hubs; alternate supply may therefore remain exposed. The hub coordinates are simulated and do not establish a connection to a real named airport.

## 5. Historical delivery findings

715 shipment lines were received across 34 historical reporting periods (up to 30 days each). The baseline reports 100 percent OTIF for periods with deliveries because it was constructed without disruptions. This metric is not a real-world reliability estimate.

## 6. Evidence gaps and follow-up

No real financial statements, quality certification, inspection results, legal attestations or confirmed future capacity reservations are supplied. Escalate requests for these facts. Use POL_001, POL_004 and SOP_005 for candidate assessment.
