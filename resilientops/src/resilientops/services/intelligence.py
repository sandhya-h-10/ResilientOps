"""Cited message interpretation, explicit conflicts, and bounded planning changes.

Span/value validation checks provenance and normalization, not semantic truth or
sender authenticity. Every resulting action still requires human approval.
"""

import re
from collections import defaultdict
from datetime import date
from time import perf_counter

from pydantic import Field

from resilientops.models import Dataset, Model


class CitedValue(Model):
    value: str = Field(max_length=100)
    quote: str = Field(min_length=1, max_length=2000)


class Reading(Model):
    source_id: str
    option_id: str
    entity_quote: str = Field(max_length=2000)
    arrival_date: CitedValue | None = None
    capacity_units: CitedValue | None = None
    concerns: list[str] = Field(default_factory=list, max_length=8)


class Extraction(Model):
    readings: list[Reading] = Field(max_length=8)


def active_updates(dataset):
    replaced = {identifier for update in dataset.updates for identifier in update.supersedes}
    return [update for update in dataset.updates if update.id not in replaced]


def token_present(token, text):
    return bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_-])", text))


class RulesExtractor:
    """Deliberately narrow, disclosed baseline: one booking and explicit ISO fields."""

    def extract(self, dataset):
        readings = []
        for update in active_updates(dataset):
            options = [o for o in dataset.options if token_present(o.id, update.text)]
            arrival = re.findall(r"Confirmed arrival: (\d{4}-\d{2}-\d{2})\.", update.text)
            capacity = re.findall(r"Available: ([0-9]+) units\.", update.text)
            if len(options) == len(arrival) == len(capacity) == 1:
                readings.append(
                    Reading(
                        source_id=update.id,
                        option_id=options[0].id,
                        entity_quote=options[0].id,
                        arrival_date=CitedValue(
                            value=arrival[0], quote=f"Confirmed arrival: {arrival[0]}."
                        ),
                        capacity_units=CitedValue(
                            value=capacity[0], quote=f"Available: {capacity[0]} units."
                        ),
                    )
                )
            else:
                readings.append(
                    Reading(
                        source_id=update.id,
                        option_id="",
                        entity_quote="",
                        concerns=[
                            "The rules baseline requires one booking ID, 'Confirmed arrival: YYYY-MM-DD.' and 'Available: N units.'. Review this message or use Gemini."
                        ],
                    )
                )
        return Extraction(readings=readings), {
            "provider": "rules",
            "model": None,
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thought_tokens": 0,
            "estimated_cost_usd": 0,
        }


def date_in_quote(value: date, quote: str):
    formats = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y")
    normalized = re.sub(r"\s+", " ", quote).casefold()
    for fmt in formats:
        rendered = value.strftime(fmt).casefold()
        for candidate in (rendered, rendered.replace(f"{value.day:02d}", str(value.day))):
            if re.search(r"(?<!\w)" + re.escape(candidate) + r"(?!\w)", normalized):
                return True
    return False


def interpret(dataset: Dataset, extractor):
    """All-or-nothing reconciliation; costs, qualification and inventory are immutable."""
    started = perf_counter()
    extraction, usage = extractor.extract(dataset)
    extraction = Extraction.model_validate(extraction)
    sources = {u.id: u for u in active_updates(dataset)}
    options = {o.id: o for o in dataset.options}
    issues, facts, groups = [], [], defaultdict(list)
    readings = extraction.readings
    if sorted(r.source_id for r in readings) != sorted(sources):
        issues.append(
            "Every active source must be interpreted exactly once; missing, duplicate or invented source IDs were returned."
        )
    for reading in readings:
        source = sources.get(reading.source_id)
        if not source:
            continue
        issues.extend(f"{source.id}: {concern}" for concern in reading.concerns)
        option = options.get(reading.option_id)
        if not option:
            issues.append(f"{source.id}: no known recovery option could be established.")
            continue
        quote = reading.entity_quote
        entity_supported = (
            quote
            and quote in source.text
            and (
                token_present(option.id, quote)
                or all(
                    token_present(v, quote)
                    for v in (option.source_id, option.material_id, option.destination)
                )
            )
        )
        if not entity_supported:
            issues.append(f"{source.id}: the cited passage does not identify {option.id}.")
            continue
        for field in ("arrival_date", "capacity_units"):
            claim = getattr(reading, field)
            if claim is None:
                issues.append(
                    f"{source.id}: {field} is unknown; confirm both arrival and available quantity."
                )
                continue
            try:
                if claim.quote not in source.text:
                    raise ValueError("citation is not an exact source passage")
                if field == "arrival_date":
                    arrival = date.fromisoformat(claim.value)
                    if not date_in_quote(arrival, claim.quote):
                        raise ValueError("date is not supported by its cited passage")
                    if dataset.event.planning_start is None:
                        raise ValueError("planning start date is missing")
                    value = (arrival - dataset.event.planning_start).days + 1
                    if not 1 <= value <= 30:
                        raise ValueError("arrival is outside the supported 30-day planning range")
                else:
                    if not re.fullmatch(r"[0-9]+", claim.value):
                        raise ValueError("quantity must be an integer")
                    value = int(claim.value)
                    quantities = re.findall(
                        r"(?<![\w.,+\-])([0-9]+(?:,[0-9]{3})*)\s+(?:units|pieces)\b",
                        claim.quote,
                        re.I,
                    )
                    if value not in [int(q.replace(",", "")) for q in quantities]:
                        raise ValueError("quantity is not supported by its cited passage")
                    if value > option.capacity:
                        raise ValueError(
                            "reported capacity exceeds the ERP ceiling; independent verification is required"
                        )
                fact = {
                    "source_id": source.id,
                    "source_label": source.source_label,
                    "option_id": option.id,
                    "origin_id": option.source_id,
                    "material_id": option.material_id,
                    "destination": option.destination,
                    "field": field,
                    "value": claim.value,
                    "normalized_value": value,
                    "quote": claim.quote,
                    "entity_quote": quote,
                }
                facts.append(fact)
                groups[(option.id, field)].append(fact)
            except ValueError as exc:
                issues.append(f"{source.id}: {field}: {exc}")
    changes = []
    for (option_id, field), items in groups.items():
        if len({f["normalized_value"] for f in items}) > 1:
            issues.append(
                f"Conflicting {field} for {option_id}: "
                + "; ".join(f"{f['source_id']} reports {f['value']}" for f in items)
            )
            continue
        attr = "arrival_day" if field == "arrival_date" else "capacity"
        before, after = getattr(options[option_id], attr), items[0]["normalized_value"]
        if before != after:
            changes.append(
                {
                    "option_id": option_id,
                    "field": attr,
                    "before": before,
                    "after": after,
                    "source_ids": [f["source_id"] for f in items],
                }
            )
    updated = dataset.model_copy(deep=True)
    if not issues:
        for change in changes:
            option = next(o for o in updated.options if o.id == change["option_id"])
            setattr(option, change["field"], change["after"])
        updated = Dataset.model_validate(updated.model_dump())
    return updated, {
        "status": "NEEDS_REVIEW" if issues else "RECONCILED",
        "facts": facts,
        "blocking_issues": list(dict.fromkeys(issues)),
        "readings": extraction.model_dump(mode="json")["readings"],
        "changes": changes if not issues else [],
        "proposed_changes": changes,
        "usage": usage | {"latency_ms": round((perf_counter() - started) * 1000, 2)},
        "sources": [u.model_dump(mode="json") for u in dataset.updates],
        "active_source_ids": list(sources),
        "assurance": "Exact citation spans, explicit dates/quantities and known entities validated. This does not prove semantic entailment or sender authenticity. Synthetic planning assumptions require human review.",
    }
