"""Parameterized, read-only ERP adapter. No arbitrary SQL tool is exposed."""

import re

from resilientops.models import DomainError


class BigQueryERP:
    def __init__(self, project: str, dataset: str, client=None):
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", project):
            raise ValueError("Invalid Google Cloud project ID")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}", dataset):
            raise ValueError("Invalid BigQuery dataset ID")
        from google.cloud import bigquery

        self.client = client or bigquery.Client(project=project)
        self.prefix = f"{project}.{dataset}"

    def load_dataset(self, reference):
        """Import explicitly provisioned synthetic tables; all queries are fixed in code."""
        from google.cloud import bigquery

        from resilientops.models import Dataset

        selections = {
            "inventory": "plant_id, material_id, on_hand, reserved, quality_hold, safety_stock",
            "recovery_options": "id, action_type, source_id, material_id, destination, capacity, arrival_day, unit_cost_paise, fixed_cost_paise, approved, compatible, route_open",
            "demand": "day, quantity",
            "supplier_history": "period, otif, lead_days, defect_rate, delay_days",
            "dependencies": "source, target",
        }
        rows = {}
        for table, columns in selections.items():
            config = bigquery.QueryJobConfig(
                maximum_bytes_billed=100_000_000,
                query_parameters=[
                    bigquery.ScalarQueryParameter("scenario", "STRING", reference.event.id)
                ],
            )
            rows[table] = [
                dict(row)
                for row in self.client.query(
                    f"SELECT {columns} FROM `{self.prefix}.{table}` WHERE scenario_id=@scenario",
                    job_config=config,
                ).result(timeout=30)
            ]
        data = reference.model_dump(mode="json")
        data.update(
            inventories=rows["inventory"],
            options=rows["recovery_options"],
            daily_demand=[
                row["quantity"] for row in sorted(rows["demand"], key=lambda r: r["day"])
            ],
            supplier_history=[
                [row[c] for c in ["otif", "lead_days", "defect_rate", "delay_days"]]
                for row in sorted(rows["supplier_history"], key=lambda r: r["period"])
            ],
            edges=[(row["source"], row["target"]) for row in rows["dependencies"]],
        )
        return Dataset.model_validate(data)

    def get_inventory(self, plant_id: str, material_id: str) -> dict:
        """Read a single validated balance with query parameters and a scan budget."""
        from google.cloud import bigquery

        from resilientops.models import Inventory

        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("plant", "STRING", plant_id),
                bigquery.ScalarQueryParameter("material", "STRING", material_id),
            ],
            maximum_bytes_billed=100_000_000,
        )
        rows = list(
            self.client.query(
                f"SELECT plant_id, material_id, on_hand, reserved, quality_hold, safety_stock "
                f"FROM `{self.prefix}.inventory` WHERE plant_id=@plant AND material_id=@material LIMIT 2",
                job_config=config,
            ).result(timeout=30)
        )
        if len(rows) != 1:
            raise DomainError("ERP balance is missing or ambiguous")
        item = Inventory.model_validate(dict(rows[0]))
        return item.model_dump() | {"available": item.available, "transferable": item.transferable}
