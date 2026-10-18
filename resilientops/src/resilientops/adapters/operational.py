"""Read the operational JSONL export without modifying its source database."""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from pathlib import Path
from zoneinfo import ZoneInfo

from resilientops.adapters.disruptions import signals_for
from resilientops.adapters.showcase import load_showcase
from resilientops.models import Dataset, Document, DomainError, Event, Inventory, Option


def is_operational(root: Path) -> bool:
    return (root / "manifest.json").is_file() and (root / "data/scenarios.jsonl").is_file()


class OperationalData:
    reference_paths = {
        "weather_observations": "public_data/weather_reference/observations.jsonl",
        "weather_entity_links": "public_data/weather_reference/entity_links.jsonl",
        "curated_news": "public_data/news/curated_evidence.jsonl",
        "external_risk_pathways": "public_data/external_risk/impact_pathways.jsonl",
        "calendar_reference": "public_data/external_risk/calendar_reference.jsonl",
    }

    def __init__(self, root: Path):
        self.root = root
        self.manifest = json.loads((root / "manifest.json").read_text())
        self._tables = {}
        self.showcase = load_showcase(root)

    def rows(self, table):
        # Names must originate in the manifest, never arbitrary request paths.
        if table not in self.manifest["table_counts"]:
            raise DomainError("Unknown operational table", 404)
        if table not in self._tables:
            self._tables[table] = [
                json.loads(line)
                for line in (self.root / "data" / f"{table}.jsonl").read_text().splitlines()
                if line.strip()
            ]
        return self._tables[table]

    def catalog(self):
        return [
            {
                "id": "baseline",
                "title": "Operational baseline",
                "description": "Undisrupted snapshot; first shipment scenario's plant and revision.",
                "supported": True,
            },
            *[
                {
                    "id": row["scenario_id"],
                    "title": row["scenario_name"],
                    "description": row["description"],
                    "type": row["scenario_type"],
                    "supported": row["scenario_type"] == "SHIPMENT_DELAY",
                    "limitation": ""
                    if row["scenario_type"] == "SHIPMENT_DELAY"
                    else "Requires supply/production replanning or timed lot-hold support; not applied by this planner.",
                }
                for row in self.rows("scenarios")
            ],
            *[
                {
                    "id": case.id,
                    "title": case.title,
                    "description": case.description,
                    "type": "SHIPMENT_DELAY",
                    "supported": True,
                    "showcase": True,
                    "plant": case.plant,
                    "material": case.material,
                    "category": case.category,
                    "demonstrates": case.demonstrates,
                    "questions": case.questions,
                    "synthetic": True,
                }
                for case in self.showcase
            ],
        ]

    def reference_rows(self, name):
        if name not in self.reference_paths:
            raise DomainError("Unknown reference source", 404)
        return [
            json.loads(line)
            for line in (self.root / self.reference_paths[name]).read_text().splitlines()
            if line.strip()
        ]

    def documents(self):
        result = []
        chunks = defaultdict(list)
        for line in (self.root / "knowledge/rag_chunks.jsonl").read_text().splitlines():
            chunk = json.loads(line)
            chunks[chunk["document_id"]].append(chunk["text"])
        for doc in json.loads((self.root / "knowledge/document_catalog.json").read_text()):
            kind = doc["document_type"]
            result.append(
                Document(
                    id=doc["document_id"],
                    title=doc["title"],
                    text="\n\n".join(chunks[doc["document_id"]]),
                    document_type=kind if kind in {"POLICY", "AUDIT", "SOP", "INCIDENT"} else "SOP",
                    version=int(doc["version"].split(".")[0]),
                    active=doc["status"] == "ACTIVE_SIMULATED",
                )
            )
        return result

    def inventories(self):
        lots = {row["lot_id"]: row for row in self.rows("inventory_lots")}
        totals = defaultdict(lambda: [0, 0])
        for row in self.rows("inventory_balances"):
            lot = lots[row["lot_id"]]
            total = totals[(lot["plant_id"], lot["material_revision_id"])]
            total[0] += row["physical_qty"]
            total[1] += row["quality_hold_qty"] + row["other_blocked_qty"]
        policies = {
            (row["plant_id"], row["material_revision_id"]): row["minimum_protected_qty"]
            for row in self.rows("inventory_policies")
        }
        # Reserved demand is already in material_requirements. Do not subtract it twice.
        return [
            Inventory(
                plant_id=plant,
                material_id=revision,
                on_hand=qty,
                quality_hold=held,
                reserved=0,
                safety_stock=policies[(plant, revision)],
            )
            for (plant, revision), (qty, held) in sorted(totals.items())
        ]

    def snapshot(self, scenario_id="baseline"):
        case = next((c for c in self.showcase if c.id == scenario_id), None)
        if case:
            # Build through the same shipment adapter, in a separate in-memory reader.
            base = OperationalData(self.root)
            base.showcase = []
            base._tables["scenarios"] = [
                *self.rows("scenarios"),
                {
                    "scenario_id": case.id,
                    "scenario_name": case.title,
                    "scenario_type": "SHIPMENT_DELAY",
                    "description": case.description,
                },
            ]
            base._tables["scenario_changes"] = [
                *self.rows("scenario_changes"),
                {
                    "scenario_id": case.id,
                    "change_id": case.id,
                    "change_type": "SHIPMENT_DELAY",
                    "target_id": case.shipment_id,
                    "parameters": {"delay_days": case.delay_days},
                },
            ]
            dataset = base.snapshot(case.id)
            if dataset.event.plant_id != case.plant or dataset.event.material_id != case.material:
                raise ValueError("Showcase plant/material does not match shipment")
            dataset.max_cost_paise = case.max_cost_paise
            dataset.latest_arrival_day = case.latest_arrival_day
            dataset.updates = case.updates
            dataset.event.source = f"resilientops_data/showcase/scenarios.json:{case.id}"
            dataset.source_metadata.update(
                showcase=True,
                narrative=case.description,
                demonstrates=case.demonstrates,
                suggested_questions=case.questions,
            )
            signals = signals_for(self.root, case.id, dataset.event.planning_start)
            if signals:
                dataset.source_metadata["disruption_signals"] = signals
                dataset.source_metadata["disruption_family"] = signals[0]["family"]
                dataset.event.source = f"resilientops_data/disruptions/scenarios.json:{case.id}"
                for signal in signals:
                    if signal["plant"] != case.plant or signal["material"] != case.material:
                        raise ValueError("Signal entity does not match scenario")
                    dataset.documents.append(
                        Document(
                            id=signal["id"],
                            title=signal["subtype"] + " monitoring notice",
                            text=signal["source_text"],
                            document_type="INCIDENT",
                            version=1,
                        )
                    )
            if case.demand_multiplier != 1:
                dataset.daily_demand = [
                    ceil(v * case.demand_multiplier) for v in dataset.daily_demand
                ]
                dataset.source_metadata["demand_multiplier"] = case.demand_multiplier
                dataset.source_metadata["limitations"].append(
                    "Demand shock is a synthetic aggregate overlay. Existing customer orders do not value additional demand."
                )
            dataset.documents.append(
                Document(
                    id=case.id,
                    title=case.title,
                    text="Synthetic demonstration scenario. " + case.description,
                    document_type="INCIDENT",
                    version=1,
                )
            )
            return Dataset.model_validate(dataset.model_dump())
        spec = next((row for row in self.catalog() if row["id"] == scenario_id), None)
        if spec is None:
            raise DomainError("Unknown operational scenario", 404)
        if not spec["supported"]:
            raise DomainError(spec["limitation"], 422)
        first = next(s for s in self.rows("scenarios") if s["scenario_type"] == "SHIPMENT_DELAY")
        selected = first["scenario_id"] if scenario_id == "baseline" else scenario_id
        changes = [r for r in self.rows("scenario_changes") if r["scenario_id"] == selected]
        if len(changes) != 1 or changes[0]["change_type"] != "SHIPMENT_DELAY":
            raise DomainError("Expected one shipment-delay overlay", 422)
        change = changes[0]
        shipments = {r["shipment_id"]: r for r in self.rows("shipments")}
        lines = {r["po_line_id"]: r for r in self.rows("purchase_order_lines")}
        sources = {r["sourcing_id"]: r for r in self.rows("sourcing_agreements")}
        target = [r for r in self.rows("shipment_lines") if r["shipment_id"] == change["target_id"]]
        if len(target) != 1:
            raise DomainError("Multi-line shipment replanning is not supported", 422)
        source = sources[lines[target[0]["po_line_id"]]["sourcing_id"]]
        plant_id, revision = source["destination_plant_id"], source["material_revision_id"]
        plant = next(r for r in self.rows("plants") if r["plant_id"] == plant_id)
        site = next(
            r
            for r in self.rows("supplier_sites")
            if r["supplier_site_id"] == source["supplier_site_id"]
        )
        start = date.fromisoformat(self.manifest["decision_date"])
        horizon = self.manifest["planning_days"]
        zone = ZoneInfo(plant["timezone"])
        demand, receipts = [0] * horizon, [0] * horizon

        def day(timestamp):
            return (datetime.fromisoformat(timestamp).astimezone(zone).date() - start).days

        production_days = {}
        for row in self.rows("material_requirements"):
            index = day(row["required_at_utc"])
            if (
                row["plant_id"] == plant_id
                and row["material_revision_id"] == revision
                and 0 <= index < horizon
            ):
                demand[index] += row["required_qty"]
                production_days[row["production_order_id"]] = index + 1
        delay = 0 if scenario_id == "baseline" else change["parameters"]["delay_days"]
        affected = []
        for row in self.rows("shipment_lines"):
            shipment = shipments[row["shipment_id"]]
            agreement = sources[lines[row["po_line_id"]]["sourcing_id"]]
            if (agreement["destination_plant_id"], agreement["material_revision_id"]) != (
                plant_id,
                revision,
            ):
                continue
            if shipment["status"] == "RECEIVED":
                continue
            arrival = datetime.fromisoformat(shipment["original_eta_utc"])
            if shipment["shipment_id"] == change["target_id"]:
                arrival += timedelta(days=delay)
                affected.append(shipment["shipment_id"])
            index = day(arrival.isoformat())
            if 0 <= index < horizon:
                receipts[index] += row["planned_qty"]
        customer_lines = {r["customer_order_line_id"]: r for r in self.rows("customer_order_lines")}
        orders = {r["customer_order_id"]: r for r in self.rows("customer_orders")}
        rates = {
            r["from_currency"]: Decimal(r["rate"])
            for r in self.rows("exchange_rates")
            if r["rate_date"] == start.isoformat() and r["to_currency"] == "INR"
        }
        rates["INR"] = Decimal(1)
        related_orders, edges = [], [(site["supplier_id"], revision), (revision, plant_id)]
        for allocation in self.rows("order_allocations"):
            production = allocation["production_order_id"]
            if production not in production_days:
                continue
            line = customer_lines[allocation["customer_order_line_id"]]
            currency = orders[line["customer_order_id"]]["currency"]
            rate = rates.get(currency)
            related_orders.append(
                {
                    "order_line_id": line["customer_order_line_id"],
                    "production_order_id": production,
                    "required_day": production_days[production],
                    "allocated_product_units": allocation["allocated_qty"],
                    "allocated_order_value_paise": int(
                        Decimal(line["selling_price_per_unit"])
                        * allocation["allocated_qty"]
                        * rate
                        * 100
                    )
                    if rate is not None
                    else None,
                }
            )
            edges.extend([(revision, production), (production, line["customer_order_line_id"])])
        return Dataset(
            event=Event(
                id=f"OPS-{self.manifest['dataset_version']}-{scenario_id}",
                supplier_id=site["supplier_id"],
                material_id=revision,
                plant_id=plant_id,
                event_type="BASELINE" if scenario_id == "baseline" else "SHIPMENT_DELAY",
                source=f"resilientops_data/data/scenario_changes.jsonl:{change['change_id']}",
                latitude=plant["latitude"],
                longitude=plant["longitude"],
                severity=0,
                planning_days=horizon,
                planning_start=start,
                delay_min_days=0,
                delay_mode_days=delay,
                delay_max_days=max(1, delay),
            ),
            inventories=self.inventories(),
            daily_demand=demand,
            scheduled_receipts=receipts,
            options=self.recovery_options(plant_id, revision),
            supplier_history=[],
            edges=list(dict.fromkeys(edges)),
            unit_shortage_cost_paise=0,
            documents=self.documents(),
            required_policy_ids=["POL_001", "POL_002"],
            source_metadata={
                "dataset": "resilientops_data",
                "version": self.manifest["dataset_version"],
                "decision_time_utc": self.manifest["decision_time_utc"],
                "scenario_id": scenario_id,
                "target_shipments": affected,
                "related_orders": related_orders,
                "scope": "One plant/material revision, daily buckets; scheduled receipts are planning assumptions, not confirmed deliveries.",
                "limitations": [
                    "Procurement costs cover material price only; unquoted freight and taxes are excluded. Senior review of these assumptions is required for simulated purchases.",
                    "Supplier history lacks the legacy four-feature vector; anomaly detection is not fitted.",
                    "No calibrated delay probability or per-component financial exposure model is supplied.",
                    "Daily aggregation assumes receipts precede consumption; intraday feasibility is not certified.",
                ],
            },
        )

    def recovery_options(self, plant_id, revision, release_day=1):
        start = (
            date.fromisoformat(self.manifest["decision_date"]) + timedelta(days=release_day - 1)
        ).isoformat()
        routes = {r["route_id"]: r for r in self.rows("transport_routes")}
        hours = defaultdict(int)
        for leg in self.rows("route_legs"):
            hours[leg["route_id"]] += (
                leg["transit_hours"] + leg["handling_hours"] + leg["clearance_hours"]
            )
        rates = {
            r["from_currency"]: Decimal(r["rate"])
            for r in self.rows("exchange_rates")
            if r["rate_date"] == start and r["to_currency"] == "INR"
        }
        rates["INR"] = Decimal(1)

        def paise(value, currency):
            return int(
                (Decimal(value) * rates[currency] * 100).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )

        capacities = {
            (r["supplier_site_id"], r["material_revision_id"]): r
            for r in self.rows("supplier_capacity_daily")
            if r["capacity_date"] == start
        }
        options = []
        for agreement in self.rows("sourcing_agreements"):
            if (agreement["destination_plant_id"], agreement["material_revision_id"]) != (
                plant_id,
                revision,
            ):
                continue
            capacity = capacities.get((agreement["supplier_site_id"], revision))
            route = routes[agreement["route_id"]]
            if not capacity or agreement["currency"] not in rates:
                continue
            arrival = release_day + ceil(
                agreement["processing_lead_time_days"] + hours[route["route_id"]] / 24
            )
            if arrival > self.manifest["planning_days"]:
                continue
            options.append(
                Option(
                    id=agreement["sourcing_id"],
                    action_type="ALTERNATE_SUPPLIER",
                    source_id=agreement["supplier_site_id"],
                    material_id=revision,
                    destination=plant_id,
                    capacity=max(0, capacity["total_capacity_qty"] - capacity["committed_qty"]),
                    capacity_group=capacity["capacity_id"],
                    arrival_day=arrival,
                    unit_cost_paise=paise(agreement["unit_price"], agreement["currency"]),
                    fixed_cost_paise=0,
                    approved=agreement["approval_status"] == "APPROVED"
                    and agreement["valid_from"] <= start
                    and (not agreement["valid_to"] or agreement["valid_to"] >= start),
                    route_open=route["active"],
                    minimum_order_qty=agreement["minimum_order_qty"],
                    order_multiple=agreement["order_multiple"],
                    provenance={
                        "sourcing_id": agreement["sourcing_id"],
                        "route_id": route["route_id"],
                        "capacity_id": capacity["capacity_id"],
                        "rate_date": start,
                        "cost_scope": "Material purchase only; freight/taxes unquoted. Simulated action under OPS-SIMULATION-1.",
                    },
                )
            )
        revision_row = next(
            r for r in self.rows("material_revisions") if r["material_revision_id"] == revision
        )
        inventory = {(i.plant_id, i.material_id): i for i in self.inventories()}
        projections = defaultdict(list)
        for row in self.rows("inventory_projection_daily"):
            if row["material_revision_id"] == revision:
                projections[row["plant_id"]].append(row["projected_physical_qty"])
        permissions = {
            (r["source_plant_id"], r["destination_plant_id"]): r
            for r in self.rows("transfer_permissions")
            if r["material_revision_id"] == revision
        }
        for offer in self.rows("transport_offers"):
            route = routes[offer["route_id"]]
            if (
                route["destination_node_id"] != plant_id
                or offer["material_id"] != revision_row["material_id"]
            ):
                continue
            donor = inventory.get((route["origin_node_id"], revision))
            permission = permissions.get((route["origin_node_id"], plant_id))
            if not donor or not permission or offer["currency"] not in rates:
                continue
            surplus = max(
                0, min([donor.available, *projections[donor.plant_id]]) - donor.safety_stock
            )
            arrival = release_day + ceil(
                (
                    offer["dispatch_prep_hours"]
                    + hours[route["route_id"]]
                    + permission["receiving_release_hours"]
                )
                / 24
            )
            if arrival > self.manifest["planning_days"]:
                continue
            options.append(
                Option(
                    id=offer["offer_id"],
                    action_type="TRANSFER",
                    source_id=donor.plant_id,
                    material_id=revision,
                    destination=plant_id,
                    capacity=min(surplus, offer["capacity_qty_per_day"]),
                    arrival_day=arrival,
                    unit_cost_paise=paise(offer["cost_per_base_unit"], offer["currency"]),
                    fixed_cost_paise=paise(offer["fixed_cost"], offer["currency"]),
                    approved=permission["permitted"],
                    route_open=route["active"],
                    provenance={
                        "offer_id": offer["offer_id"],
                        "permission_id": permission["permission_id"],
                        "donor_projection_floor": min(projections[donor.plant_id]),
                        "rate_date": start,
                    },
                )
            )
        return options

    def summary(self):
        return {
            "dataset": "resilientops_data",
            "version": self.manifest["dataset_version"],
            "decision_time_utc": self.manifest["decision_time_utc"],
            "row_count": self.manifest["row_count"],
            "table_counts": self.manifest["table_counts"],
            "plants": self.rows("plants"),
            "scenarios": self.catalog(),
            "documents": [
                {"id": d.id, "title": d.title, "type": d.document_type} for d in self.documents()
            ],
            "synthetic": True,
            "showcase_count": len(self.showcase),
            "reference_sources": {
                name: len(self.reference_rows(name)) for name in self.reference_paths
            },
            "reference_scope": "Archived public reference evidence; coverage is incomplete and entity links do not establish disruption causality. No live Google imports are claimed.",
        }


def load_dataset(root: Path) -> Dataset:
    if is_operational(root):
        return OperationalData(root).snapshot()
    return Dataset.model_validate_json((root / "scenario.json").read_text())
