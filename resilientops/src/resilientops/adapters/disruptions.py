"""Validated synthetic signal histories for three disruption families."""

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from resilientops.models import Model


class Observation(Model):
    day: date
    value: float = Field(ge=0)


class DisruptionSignal(Model):
    id: str
    scenario_id: str
    family: Literal["external", "internal", "market"]
    subtype: str
    plant: str
    material: str
    metric: str
    unit: str
    direction: Literal["high", "low"] = "high"
    source_text: str
    synthetic: Literal[True] = True
    observations: list[Observation] = Field(min_length=31)

    @model_validator(mode="after")
    def chronological(self):
        days = [o.day for o in self.observations]
        if days != sorted(set(days)):
            raise ValueError("Signal observations must have unique increasing dates")
        return self


def signals_for(root: Path, scenario_id: str, planning_start: date):
    path = root / "disruptions/signals.json"
    if not path.exists():
        return []
    pack = json.loads(path.read_text())
    manifest = json.loads((root / "manifest.json").read_text())
    if (
        pack.get("synthetic") is not True
        or pack["base_dataset_version"] != manifest["dataset_version"]
    ):
        raise ValueError("Signal pack must be synthetic and match the operational dataset")
    found = [
        DisruptionSignal.model_validate(row)
        for row in pack["signals"]
        if row["scenario_id"] == scenario_id
    ]
    if len({s.id for s in found}) != len(found):
        raise ValueError("Duplicate signal IDs")
    if any(s.observations[-1].day >= planning_start for s in found):
        raise ValueError("Signal history must end before the planning date")
    return [s.model_dump(mode="json") for s in found]
