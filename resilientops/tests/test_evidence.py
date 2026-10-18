import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from resilientops.adapters.gemini import GeminiExtractor
from resilientops.config import Settings
from resilientops.evaluation import evaluate, score_case, write_report
from resilientops.models import Decision, DomainError, Principal, UpdateSubmission
from resilientops.services.execution import ActionService
from resilientops.services.intelligence import Extraction, RulesExtractor, interpret
from resilientops.services.scenarios import catalog, scenario_dataset
from resilientops.services.workflow import Workflow
from resilientops.storage import Store

DATA = Path(__file__).resolve().parents[1] / "data" / "demo"
MANAGER = Principal(id="test-reviewer", role="manager")


@pytest.fixture
def scenario_workflow(tmp_path):
    def make(name, extractor=None):
        settings = Settings(data_dir=DATA, db_path=tmp_path / f"{name}.db")
        workflow = Workflow(settings, Store(settings.db_path), extractor=extractor)
        incident = workflow.create(name)
        return workflow, incident

    return make


def run(workflow, incident):
    return asyncio.run(workflow.analyze(incident["id"]))


@pytest.mark.parametrize("name", ["late-arrival", "limited-capacity"])
def test_evidence_changes_recovery_and_invalidates_structured_baseline(scenario_workflow, name):
    workflow, incident = scenario_workflow(name)
    result = run(workflow, incident)
    assert result["status"] == "AWAITING_APPROVAL"
    assert result["plan"]["allocations"] != [{"option_id": "PUNE-TRANSFER", "quantity": 280}]
    assert (
        result["results"]["Recovery"]["structured_only_baseline"]["feasible_after_updates"] is False
    )
    impact = result["results"]["Recovery"]["business_impact"]
    assert impact["without_action_shortage_units"] == 280
    assert impact["with_plan_shortage_units"] == 0
    assert impact["uncovered_unit_days_without_action"] == 540
    assert impact["modeled_net_benefit_paise"] == 280 * 500_000 - result["plan"]["total_cost_paise"]
    assert result["input_snapshot"]["options"][0]["arrival_day"] == 2
    # Approval and action validation must use the revised snapshot, not the original ERP plan.
    service = ActionService(workflow.store)
    service.decide(
        result["id"], Decision(plan_hash=result["plan_hash"], decision="APPROVE"), MANAGER
    )
    assert service.execute(result["id"], result["plan_hash"], MANAGER)["status"] == "COMMITTED"


def test_conflicting_sources_persist_evidence_and_block_downstream_tools(scenario_workflow):
    workflow, incident = scenario_workflow("conflicting-updates")
    result = run(workflow, incident)
    assert result["status"] == "ESCALATED"
    assert "Conflicting arrival_date" in result["error"]
    assert len(result["evidence"]["EV-SHIPMENT-UPDATES"]["value"]["facts"]) == 4
    assert result["plan"] is None
    assert "Recovery" not in result["results"]
    assert result["snapshot"]["options"] == result["input_snapshot"]["options"]
    # Even an orchestrator retrying a completed-but-blocked stage cannot move past it.
    with workflow.store.transaction() as db:
        result.update(status="ANALYZING", analysis_owner="retry")
        workflow.store.save(db, result)
    for stage in ("Investigator", "Impact"):
        with pytest.raises(DomainError, match="review|Unresolved"):
            workflow.run_stage(result["id"], stage, "retry")


def test_source_correction_clears_approval_keeps_history_and_resolves_conflict(scenario_workflow):
    workflow, incident = scenario_workflow("baseline")
    initial = run(workflow, incident)
    service = ActionService(workflow.store)
    service.decide(
        initial["id"], Decision(plan_hash=initial["plan_hash"], decision="APPROVE"), MANAGER
    )
    update = UpdateSubmission(
        source_label="Test carrier",
        text="PUNE-TRANSFER. Confirmed arrival: 2026-10-19. Available: 400 units.",
    )
    changed = workflow.reanalyze(initial["id"], update, MANAGER.id)
    assert changed["approval"] is None
    assert changed["plan"] is None
    revised = run(workflow, changed)
    assert revised["plan"]["version"] == 2
    assert revised["plan_hash"] != initial["plan_hash"]
    with pytest.raises(DomainError, match="hash"):
        service.execute(initial["id"], initial["plan_hash"], MANAGER)
    source_id = revised["input_snapshot"]["updates"][0]["id"]
    correction = UpdateSubmission(
        source_label="Verified correction",
        text="PUNE-TRANSFER. Confirmed arrival: 2026-10-15. Available: 400 units.",
        supersedes=[source_id],
    )
    restored = run(workflow, workflow.reanalyze(initial["id"], correction, MANAGER.id))
    assert restored["plan"]["total_cost_paise"] == 6_340_000
    assert len(restored["input_snapshot"]["updates"]) == 2
    assert len(restored["results"]["Investigator"]["interpretation"]["active_source_ids"]) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "quote",
        "value",
        "unknown_source",
        "entity",
        "missing_reading",
        "missing_quantity",
        "extra_field",
    ],
)
def test_untrusted_extraction_cannot_silently_change_inputs(scenario_workflow, mutation):
    workflow, incident = scenario_workflow("late-arrival")
    dataset = scenario_dataset(
        workflow.dataset, next(s for s in catalog(DATA) if s["id"] == "late-arrival")
    )
    payload = RulesExtractor().extract(dataset)[0].model_dump()
    reading = payload["readings"][0]
    if mutation == "quote":
        reading["arrival_date"]["quote"] = "An invented source passage"
    if mutation == "value":
        reading["arrival_date"]["value"] = "2026-10-15"
    if mutation == "unknown_source":
        reading["source_id"] = "NONEXISTENT"
    if mutation == "entity":
        reading["option_id"] = "SUP044-ALTERNATE"
    if mutation == "missing_reading":
        payload["readings"] = []
    if mutation == "missing_quantity":
        reading["capacity_units"] = None
    if mutation == "extra_field":
        reading["approved"] = True

    class Fake:
        def extract(self, _):
            return payload, {"provider": "test-double"}

    if mutation == "extra_field":
        with pytest.raises(ValueError):
            interpret(dataset, Fake())
    else:
        updated, evidence = interpret(dataset, Fake())
        assert evidence["blocking_issues"]
        assert updated == dataset
        assert evidence["changes"] == []


def test_capacity_increase_is_not_authorized_by_a_message(scenario_workflow):
    workflow, incident = scenario_workflow("limited-capacity")
    data = incident["input_snapshot"]
    data["updates"][0]["text"] = (
        "PUNE-TRANSFER. Confirmed arrival: 2026-10-15. Available: 999 units."
    )
    from resilientops.models import Dataset

    updated, evidence = interpret(Dataset.model_validate(data), RulesExtractor())
    assert "ERP ceiling" in " ".join(evidence["blocking_issues"])
    assert updated.options[0].capacity == 400


def test_gemini_structured_adapter_drives_prose_case_with_citations(scenario_workflow):
    pytest.importorskip("google.genai")
    payload = {
        "readings": [
            {
                "source_id": "PUNE-PROSE",
                "option_id": "PUNE-TRANSFER",
                "entity_quote": "PUNE-TRANSFER",
                "arrival_date": {
                    "value": "2026-10-19",
                    "quote": "The confirmed delivery to CHENNAI is now 19 October 2026",
                },
                "capacity_units": {
                    "value": "400",
                    "quote": "We still have 400 units of PCB-X41 allocated at PUNE.",
                },
                "concerns": [],
            }
        ]
    }
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        assert kwargs["config"].response_json_schema == Extraction.model_json_schema()
        assert "expected_outcome" not in kwargs["contents"]
        assert "truth_changes" not in kwargs["contents"]
        return SimpleNamespace(
            parsed=payload,
            usage_metadata=SimpleNamespace(
                prompt_token_count=100, candidates_token_count=50, thoughts_token_count=10
            ),
        )

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    workflow, incident = scenario_workflow("natural-language")
    settings = replace(
        workflow.settings,
        project="test",
        model="test-model",
        input_usd_per_million=1,
        output_usd_per_million=2,
    )
    workflow.extractor = GeminiExtractor(settings, client)
    result = run(workflow, incident)
    assert len(calls) == 1
    assert result["status"] == "AWAITING_APPROVAL"
    assert result["snapshot"]["options"][0]["arrival_day"] == 6
    extraction = result["results"]["Investigator"]["interpretation"]
    assert extraction["usage"]["estimated_cost_usd"] == pytest.approx(0.00022)
    assert extraction["facts"][0]["source_id"] == "PUNE-PROSE"
    assert not result["results"]["Recovery"]["structured_only_baseline"]["feasible_after_updates"]


def test_gemini_failure_has_no_silent_local_fallback(scenario_workflow):
    class Failing:
        def extract(self, _):
            raise RuntimeError("Simulated provider failure containing private payload")

    workflow, incident = scenario_workflow("late-arrival", Failing())
    result = run(workflow, incident)
    assert result["status"] == "FAILED"
    assert result["error"] == "Analysis failed: RuntimeError"
    assert result["plan"] is None


def test_business_metrics_do_not_credit_an_infeasible_plan(scenario_workflow):
    workflow, incident = scenario_workflow("infeasible-arrivals")
    result = run(workflow, incident)
    assert result["status"] == "ESCALATED"
    metrics = result["results"]["Recovery"]["business_impact"]
    assert metrics["shortage_units_covered"] == 0
    assert metrics["modeled_net_benefit_paise"] == 0
    assert metrics["with_plan_shortage_units"] == 280


def test_offline_evaluation_reports_baselines_without_claiming_live_ai(tmp_path):
    settings = Settings(data_dir=DATA, db_path=tmp_path / "state.db")
    report = asyncio.run(evaluate(settings))
    assert report["gemini_live"] == "not_run"
    assert report["modes"]["structured-only"]["summary"]["correct_decisions"] == 5
    rules = report["modes"]["rules"]["summary"]
    assert rules["correct_decisions"] == 10
    assert rules["failed_runs"] == 0
    assert rules["human_review_time_seconds"] is None
    assert rules["reported_model_calls"] == 0
    output = tmp_path / "evaluation.json"
    write_report(report, output)
    assert json.loads(output.read_text())["suite_fingerprint"] == report["suite_fingerprint"]
    assert "not_run" in output.with_suffix(".html").read_text()


def test_citation_metric_penalizes_correct_value_with_fabricated_quote(scenario_workflow):
    workflow, incident = scenario_workflow("late-arrival")
    result = run(workflow, incident)
    result["results"]["Investigator"]["interpretation"]["readings"][0]["arrival_date"]["quote"] = (
        "Fabricated"
    )
    from resilientops.models import Dataset

    gold = next(
        g
        for g in json.loads((DATA.parent / "evaluation/cases.json").read_text())
        if g["id"] == "late-arrival"
    )
    scored = score_case(result, gold, Dataset.model_validate(result["snapshot"]))
    assert scored["true_positive_facts"] == 2
    assert scored["exact_citation_spans"] == 1
    assert scored["citation_count"] == 2


def test_live_evaluation_requires_explicit_project_and_model(tmp_path):
    settings = Settings(data_dir=DATA, db_path=tmp_path / "state.db")
    with pytest.raises(ValueError, match="Model configuration requires"):
        asyncio.run(evaluate(settings, ["gemini"]))


def test_negative_source_quantity_cannot_be_normalized_to_positive(scenario_workflow):
    from resilientops.models import Dataset

    _, incident = scenario_workflow("late-arrival")
    data = incident["input_snapshot"]
    data["updates"][0]["text"] = data["updates"][0]["text"].replace("400 units", "-400 units")
    dataset = Dataset.model_validate(data)
    payload = {
        "readings": [
            {
                "source_id": "PUNE-LATE",
                "option_id": "PUNE-TRANSFER",
                "entity_quote": "PUNE-TRANSFER",
                "arrival_date": {"value": "2026-10-19", "quote": "Confirmed arrival: 2026-10-19."},
                "capacity_units": {"value": "400", "quote": "Available: -400 units."},
            }
        ]
    }

    class Fake:
        def extract(self, _):
            return payload, {"provider": "test-double"}

    updated, result = interpret(dataset, Fake())
    assert updated == dataset
    assert any("quantity is not supported" in issue for issue in result["blocking_issues"])
