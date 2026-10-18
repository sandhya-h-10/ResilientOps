-- Replace PROJECT.DATASET explicitly before running. No remote SQL is executed by local setup.
CREATE TABLE IF NOT EXISTS `PROJECT.DATASET.inventory` (
  scenario_id STRING, plant_id STRING, material_id STRING, on_hand INT64,
  reserved INT64, quality_hold INT64, safety_stock INT64
);
CREATE TABLE IF NOT EXISTS `PROJECT.DATASET.recovery_options` (
  scenario_id STRING, id STRING, action_type STRING, source_id STRING,
  material_id STRING, destination STRING, capacity INT64, arrival_day INT64,
  unit_cost_paise INT64, fixed_cost_paise INT64, approved BOOL,
  compatible BOOL, route_open BOOL
);
CREATE TABLE IF NOT EXISTS `PROJECT.DATASET.demand` (
  scenario_id STRING, day INT64, quantity INT64
);
CREATE TABLE IF NOT EXISTS `PROJECT.DATASET.supplier_history` (
  scenario_id STRING, period INT64, otif FLOAT64, lead_days FLOAT64,
  defect_rate FLOAT64, delay_days FLOAT64
);
CREATE TABLE IF NOT EXISTS `PROJECT.DATASET.dependencies` (
  scenario_id STRING, source STRING, target STRING
);
