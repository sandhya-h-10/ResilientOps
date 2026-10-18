"""Validated, additive synthetic scenarios; the operational export stays immutable."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from resilientops.models import ShipmentUpdate


class ShowcaseCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^(SHOW|RISK)_[0-9]{3}$")
    title: str
    description: str
    plant: str
    material: str
    category: str
    shipment_id: str
    delay_days: int = Field(ge=0, le=30)
    max_cost_paise: int | None = Field(default=None, ge=0)
    latest_arrival_day: int | None = Field(default=None, ge=1, le=30)
    updates: list[ShipmentUpdate] = Field(default_factory=list, max_length=8)
    demand_multiplier: float = Field(default=1, ge=1, le=3)
    questions: list[str]
    demonstrates: list[str]


def load_showcase(root: Path):
    path = root / "showcase/scenarios.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    if raw.get("synthetic") is not True:
        raise ValueError("Showcase pack must be explicitly synthetic")
    manifest = json.loads((root / "manifest.json").read_text())
    if raw.get("base_dataset_version") != manifest["dataset_version"]:
        raise ValueError("Showcase pack targets a different dataset version")
    rows = list(raw["scenarios"])
    risk_path = root / "disruptions/scenarios.json"
    if risk_path.exists():
        risk = json.loads(risk_path.read_text())
        if (
            risk.get("synthetic") is not True
            or risk.get("base_dataset_version") != manifest["dataset_version"]
        ):
            raise ValueError("Disruption scenarios must be synthetic and match the dataset")
        rows.extend(risk["scenarios"])
    cases = [ShowcaseCase.model_validate(row) for row in rows]
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("Duplicate showcase scenario ID")
    return cases
