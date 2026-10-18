"""Validated domain contracts. Money is integer INR paise; time is UTC."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Status(StrEnum):
    DRAFT = "DRAFT"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    PLANNING_BLOCKED = "PLANNING_BLOCKED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    AWAITING_CLOSURE = "AWAITING_CLOSURE"
    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class Event(Model):
    id: Identifier
    supplier_id: Identifier
    material_id: Identifier
    plant_id: Identifier
    event_type: str
    source: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    severity: float = Field(ge=0, le=1)
    planning_days: int = Field(ge=1, le=30)
    delay_min_days: float = Field(ge=0)
    delay_mode_days: float = Field(ge=0)
    delay_max_days: float = Field(gt=0)
    synthetic: bool = True
    planning_start: date | None = None

    @model_validator(mode="after")
    def check_distribution(self):
        if not self.delay_min_days <= self.delay_mode_days <= self.delay_max_days:
            raise ValueError("Delay assumptions must satisfy min <= mode <= max")
        if self.delay_min_days == self.delay_max_days:
            raise ValueError("Delay distribution must have nonzero width")
        return self


class Inventory(Model):
    plant_id: Identifier
    material_id: Identifier
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)
    quality_hold: int = Field(ge=0)
    safety_stock: int = Field(ge=0)

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved - self.quality_hold

    @property
    def transferable(self) -> int:
        return max(0, self.available - self.safety_stock)

    @model_validator(mode="after")
    def check_balance(self):
        if self.available < 0:
            raise ValueError("Reserved and quality-held inventory exceed on-hand stock")
        return self


class Option(Model):
    id: Identifier
    action_type: Literal["TRANSFER", "EXPEDITE", "ALTERNATE_SUPPLIER"]
    source_id: Identifier
    material_id: Identifier
    destination: Identifier
    capacity: int = Field(ge=0)
    arrival_day: int = Field(ge=1, le=30)
    unit_cost_paise: int = Field(ge=0)
    fixed_cost_paise: int = Field(ge=0)
    approved: bool
    compatible: bool = True
    route_open: bool = True
    minimum_order_qty: int = Field(default=1, ge=1)
    order_multiple: int = Field(default=1, ge=1)
    capacity_group: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class Document(Model):
    id: Identifier
    title: str
    text: str
    supplier_id: Identifier | None = None
    document_type: Literal["POLICY", "AUDIT", "SOP", "INCIDENT"]
    active: bool = True
    classification: Literal["INTERNAL"] = "INTERNAL"
    version: int = Field(ge=1)


class ShipmentUpdate(Model):
    """An untrusted message; provenance is metadata, never inferred from its prose."""

    id: Identifier
    source_label: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=8000)
    received_at: datetime
    supersedes: list[Identifier] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def timezone_required(self):
        if self.received_at.tzinfo is None:
            raise ValueError("Source timestamps must include a timezone")
        return self


class UpdateSubmission(Model):
    source_label: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=8000)
    supersedes: list[Identifier] = Field(default_factory=list, max_length=8)


class IncidentRequest(Model):
    scenario_id: Identifier = "baseline"


class Dataset(Model):
    event: Event
    inventories: list[Inventory]
    options: list[Option]
    daily_demand: list[int] = Field(min_length=1)
    supplier_history: list[list[float]]
    edges: list[tuple[str, str]]
    unit_shortage_cost_paise: int = Field(ge=0)
    documents: list[Document]
    updates: list[ShipmentUpdate] = Field(default_factory=list, max_length=8)
    scheduled_receipts: list[int] = Field(default_factory=list)
    required_policy_ids: list[Identifier] = Field(
        default_factory=lambda: ["POLICY-TRANSFER-01", "POLICY-SOURCING-01"]
    )
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    max_cost_paise: int | None = Field(default=None, ge=0)
    latest_arrival_day: int | None = Field(default=None, ge=1, le=30)
    excluded_option_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_data(self):
        if len(self.daily_demand) != self.event.planning_days:
            raise ValueError("Demand must cover every planning day")
        if any(x < 0 for x in self.daily_demand):
            raise ValueError("Demand must be nonnegative")
        if self.scheduled_receipts and (
            len(self.scheduled_receipts) != self.event.planning_days
            or any(qty < 0 for qty in self.scheduled_receipts)
        ):
            raise ValueError("Scheduled receipts must be nonnegative and cover the horizon")
        keys = [(i.plant_id, i.material_id) for i in self.inventories]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate inventory keys")
        for values in [self.options, self.documents, self.updates]:
            if len({v.id for v in values}) != len(values):
                raise ValueError("Duplicate option/document IDs")
        seen = set()
        for update in self.updates:
            if not set(update.supersedes).issubset(seen):
                raise ValueError(
                    "A correction may supersede only earlier messages in this incident"
                )
            seen.add(update.id)
        if (self.event.plant_id, self.event.material_id) not in keys:
            raise ValueError("Event destination/material has no inventory")
        if any(len(row) != 4 for row in self.supplier_history):
            raise ValueError("Supplier history requires OTIF, lead days, defect rate, delay days")
        return self

    def receipt_on(self, day: int) -> int:
        return self.scheduled_receipts[day - 1] if self.scheduled_receipts else 0


class Evidence(Model):
    id: Identifier
    kind: Literal["FACT", "CALCULATION", "ESTIMATE", "SIMULATION", "DOCUMENT"]
    source: str
    value: Any
    explanation: str
    synthetic: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Allocation(Model):
    option_id: Identifier
    quantity: int = Field(gt=0)


class Plan(Model):
    id: Identifier
    version: int = Field(ge=1)
    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "NO_ACTION"]
    allocations: list[Allocation]
    total_cost_paise: int = Field(ge=0)
    currency: Literal["INR"] = "INR"
    evidence_ids: list[Identifier]
    snapshot_hash: str
    expires_at: datetime | None = None
    solver: str
    assumptions: list[str]
    approval_policy: str = "DEMO-POLICY-1"


class Decision(Model):
    plan_hash: str = Field(min_length=64, max_length=64)
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    comment: str = Field(default="", max_length=1000)


class ExecuteRequest(Model):
    plan_hash: str = Field(min_length=64, max_length=64)


class Principal(Model):
    id: str
    role: Literal["manager", "senior"]


class DomainError(Exception):
    """A controlled failure that is safe to expose through the API."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code
