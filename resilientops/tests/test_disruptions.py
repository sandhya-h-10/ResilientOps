import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from resilientops.adapters.disruptions import DisruptionSignal
from resilientops.adapters.gemini import ContextExtraction, SourceFact, extract_context
from resilientops.adapters.operational import OperationalData
from resilientops.analytics.disruptions import assess_disruptions
from resilientops.config import Settings
from resilientops.models import DomainError

ROOT = Path(__file__).resolve().parents[1] / "resilientops_data"


def test_statistical_detection_and_control():
    source = OperationalData(ROOT)
    labels = json.loads((ROOT / "disruptions/evaluation-labels.json").read_text())["labels"]
    families = set()
    for label in labels:
        data = source.snapshot(label["scenario_id"])
        signals = data.source_metadata["disruption_signals"]
        result = assess_disruptions(signals)["signals"][0]
        assert result["anomaly"] == label["expected_anomaly"]
        assert result["baseline_samples"] == 60
        assert result["baseline_end"] < result["observation_date"]
        assert result["probability"] is None
        families.add(result["family"])
    assert families == {"external", "internal", "market"}


def test_history_chronology_and_demand_overlay():
    data = OperationalData(ROOT).snapshot("RISK_011")
    assert data.source_metadata["demand_multiplier"] == 1.4
    signal = data.source_metadata["disruption_signals"][0]
    signal["observations"][1]["day"] = signal["observations"][0]["day"]
    with pytest.raises(ValueError, match="unique increasing"):
        DisruptionSignal.model_validate(signal)


def test_mandatory_extraction_validates_exact_quotes(tmp_path):
    data = OperationalData(ROOT).snapshot("RISK_001")
    doc = next(d for d in data.documents if d.id == "SIGNAL_001")
    fake = Mock()
    value = ContextExtraction(
        family="external",
        subtype="political",
        facts=[
            SourceFact(
                source_id=doc.id,
                quote=doc.text[:80],
                interpretation="Synthetic external monitoring notice",
            )
        ],
        uncertainties=["Not a live event"],
    )
    fake.models.generate_content.return_value = SimpleNamespace(parsed=value, usage_metadata=None)
    settings = Settings(
        data_dir=ROOT, db_path=tmp_path / "test.db", chat_api_key="fake", model="fake"
    )
    result = extract_context(settings, data, [doc], client=fake)
    assert result["provider"] == "gemini"
    value.facts[0].quote = "Fabricated evidence"
    with pytest.raises(DomainError, match="unsupported citation"):
        extract_context(settings, data, [doc], client=fake)
    with pytest.raises(ValueError, match="mandatory Gemini"):
        replace(settings, agent_mode="google", evidence_mode="rules").validate()
    replace(settings, agent_mode="google", evidence_mode="gemini").validate()


def test_agent_assessments_require_retrieval_and_real_references(make_workflow):
    from resilientops.agents.reasoning import save_review

    workflow = make_workflow()
    i = workflow.create()
    owner = "review-test"
    assert workflow._claim(i["id"], owner)
    workflow.run_stage(i["id"], "Sentinel", owner)
    review = {
        "summary": "Investigate the synthetic supplier signal.",
        "evidence_ids": ["EV-DETECTION"],
        "uncertainties": [],
        "next_action": "Review source evidence",
        "verdict": "continue",
    }
    with pytest.raises(DomainError, match="Retrieve evidence"):
        save_review(workflow, i["id"], owner, "Sentinel", review)
    with workflow.store.transaction() as db:
        current = workflow.store.get(i["id"], db)
        current["retrievals"] = {"Sentinel": [{"document_ids": [], "query": "supplier"}]}
        workflow.store.save(db, current)
    with pytest.raises(DomainError, match="not available"):
        save_review(workflow, i["id"], owner, "Sentinel", review | {"evidence_ids": ["INVENTED"]})
    save_review(workflow, i["id"], owner, "Sentinel", review | {"verdict": "needs_review"})
    workflow.settings = replace(workflow.settings, agent_mode="google")
    with pytest.raises(DomainError, match="requires review"):
        workflow.run_stage(i["id"], "Investigator", owner)
