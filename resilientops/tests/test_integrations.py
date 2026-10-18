import asyncio
import json
import sys
from dataclasses import replace

import pytest

from resilientops.models import DomainError, Inventory
from resilientops.tools.knowledge import LocalKnowledge


def test_inventory_contract_rejects_invalid_quantities():
    with pytest.raises(ValueError):
        Inventory(
            plant_id="PUNE",
            material_id="PCB-X41",
            on_hand=10,
            reserved=9,
            quality_hold=2,
            safety_stock=0,
        )


def test_global_policies_and_active_filter(make_workflow):
    workflow = make_workflow()
    retrieval = LocalKnowledge(workflow.dataset.documents)
    result = retrieval.search("emergency sourcing policy", "SUP017")
    assert "POLICY-SOURCING-01" in [d.id for d in result]
    assert "POLICY-OLD-01" not in [d.id for d in result]
    assert retrieval.search("unrelated zxqv", "SUP017") == []


def test_adk_roles_have_scoped_tools_and_no_execution(make_workflow, monkeypatch):
    pytest.importorskip("google.adk")
    from resilientops.agents.google_adk import build_agent

    workflow = make_workflow()
    workflow.settings = replace(workflow.settings, project="test-project", model="test-model")
    for name in ["GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"]:
        monkeypatch.setenv(name, "")
    root = build_agent(workflow, workflow.create()["id"], "test-owner")
    agents = [node for node in root.graph.nodes if hasattr(node, "tools")]
    assert [a.name for a in agents] == [
        "Sentinel",
        "Investigator",
        "Impact",
        "Recovery",
        "Commander",
    ]
    for agent in agents:
        assert agent.tools[0].__name__ == f"run_{agent.name.lower()}"
        for tool in agent.tools:
            names = getattr(tool, "tool_filter", []) or []
            assert all("execute" not in name and "approve" not in name for name in names)


def test_adk_graph_executes_with_fake_model_and_real_tools(make_workflow, monkeypatch):
    pytest.importorskip("google.adk")
    from google.adk.models.base_llm import BaseLlm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    from resilientops.agents import google_adk

    class ScriptedModel(BaseLlm):
        tool_name: str

        async def generate_content_async(self, llm_request, stream=False):
            called = {
                part.function_response.name
                for content in llm_request.contents
                for part in (content.parts or [])
                if getattr(part, "function_response", None)
            }
            already_called = "submit_assessment" in called
            if "retrieve_evidence" not in called:
                part = types.Part(
                    function_call=types.FunctionCall(
                        name="retrieve_evidence",
                        args={"query": "supplier emergency sourcing policy"},
                    )
                )
            elif self.tool_name not in called:
                part = types.Part(function_call=types.FunctionCall(name=self.tool_name, args={}))
            elif not already_called:
                refs = {
                    "run_sentinel": "EV-DETECTION",
                    "run_investigator": "EV-CONTEXT-EXTRACTION",
                    "run_impact": "EV-IMPACT",
                    "run_recovery": "EV-RECOVERY",
                    "run_commander": "EV-RECOVERY",
                }
                part = types.Part(
                    function_call=types.FunctionCall(
                        name="submit_assessment",
                        args={
                            "summary": "Independent scripted assessment for integration validation.",
                            "evidence_ids": [refs[self.tool_name]],
                            "uncertainties": [],
                            "next_action": "Review validated results",
                            "verdict": "continue",
                        },
                    )
                )
            else:
                part = types.Part(text="Validated stage completed.")
            parts = (
                [
                    types.Part(text="Private test thought must never be persisted.", thought=True),
                    part,
                ]
                if already_called
                else [part]
            )
            yield LlmResponse(content=types.Content(role="model", parts=parts))

    workflow = make_workflow()
    workflow.settings = replace(
        workflow.settings, agent_mode="google", project="test-project", model="test-model"
    )
    monkeypatch.setattr(
        "resilientops.adapters.gemini.extract_context",
        lambda *args, **kwargs: {
            "family": "market",
            "facts": [],
            "provider": "gemini",
            "scope": "Mock Gemini extraction",
        },
    )
    original = google_adk.build_agent

    def build_with_fake_model(*args):
        root = original(*args)
        for agent in root.graph.nodes:
            if hasattr(agent, "tools"):
                agent.model = ScriptedModel(
                    model="scripted-test", tool_name=f"run_{agent.name.lower()}"
                )
        return root

    monkeypatch.setattr(google_adk, "build_agent", build_with_fake_model)
    incident = asyncio.run(workflow.analyze(workflow.create()["id"]))
    assert incident["status"] == "AWAITING_APPROVAL", incident.get("error")
    assert len(incident["results"]) == 5
    assert incident["plan"]["total_cost_paise"] == 6_340_000
    assert set(incident["commentary"]) == {
        "Sentinel",
        "Investigator",
        "Impact",
        "Recovery",
        "Commander",
    }
    assert incident["commentary"]["Commander"]["text"] == "Validated stage completed."


def test_real_mcp_stdio_roundtrip(make_workflow):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    workflow = make_workflow()
    incident = workflow.create()

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "resilientops.tools.mcp_server", "--incident-id", incident["id"]],
            env={
                "RESILIENTOPS_DB": str(workflow.settings.db_path),
                "RESILIENTOPS_DATA_DIR": str(workflow.settings.data_dir),
            },
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "get_inventory",
                "get_supplier_history",
                "get_dependencies",
                "get_recovery_options",
            }
            result = await session.call_tool(
                "get_inventory", {"plant_id": "CHENNAI", "material_id": "PCB-X41"}
            )
            assert not result.isError
            payload = result.structuredContent or json.loads(result.content[0].text)
            assert payload["available"] == 320
            # A long-lived MCP subprocess must observe Investigator's updated snapshot.
            with workflow.store.transaction() as db:
                updated = workflow.store.get(incident["id"], db)
                updated["snapshot"]["options"][0]["arrival_day"] = 6
                workflow.store.save(db, updated)
            result = await session.call_tool(
                "get_recovery_options", {"material_id": "PCB-X41", "plant_id": "CHENNAI"}
            )
            payload = result.structuredContent or json.loads(result.content[0].text)
            assert payload["options"][0]["arrival_day"] == 6

    asyncio.run(check())


def test_bigquery_input_is_parameterized():
    pytest.importorskip("google.cloud.bigquery")
    from resilientops.adapters.bigquery import BigQueryERP

    class Job:
        def result(self, timeout):
            return [
                {
                    "plant_id": "CHENNAI",
                    "material_id": "PCB-X41",
                    "on_hand": 520,
                    "reserved": 120,
                    "quality_hold": 80,
                    "safety_stock": 0,
                }
            ]

    class Client:
        def query(self, query, job_config):
            assert "DROP" not in query
            assert job_config.query_parameters[0].value == "'; DROP TABLE inventory; --"
            return Job()

    adapter = BigQueryERP("test-project", "erp", client=Client())
    assert adapter.get_inventory("'; DROP TABLE inventory; --", "PCB-X41")["available"] == 320


def test_unknown_erp_entity_fails(make_workflow):
    from resilientops.tools.erp import ERPTools

    with pytest.raises(DomainError, match="Unknown"):
        ERPTools(make_workflow().dataset).get_inventory("MUMBAI", "PCB-X41")


def test_retrieval_limit_returns_existing_evidence_without_search(make_workflow, monkeypatch):
    from resilientops.agents.google_adk import build_agent

    workflow = make_workflow()
    workflow.settings = replace(workflow.settings, project="test-project", model="test-model")
    incident_id = workflow.create()["id"]
    assert workflow._claim(incident_id, "test-owner")
    root = build_agent(workflow, incident_id, "test-owner")
    agent = next(node for node in root.graph.nodes if getattr(node, "name", None) == "Sentinel")
    tools = {tool.__name__: tool for tool in agent.tools if callable(tool)}
    for remaining in (3, 2, 1, 0):
        result = tools["retrieve_evidence"]("emergency sourcing policy")
        assert result["searches_remaining"] == remaining
    previous_ids = {d["id"] for d in result["documents"]}

    def unexpected_search(*args, **kwargs):
        raise AssertionError("Retrieval budget must prevent additional searches")

    monkeypatch.setattr(LocalKnowledge, "search", unexpected_search)
    result = tools["retrieve_evidence"]("one more query")
    assert result["budget_exhausted"]
    assert previous_ids.issubset({d["id"] for d in result["documents"]})
    assert len(workflow.store.get(incident_id)["retrievals"]["Sentinel"]) == 4
    workflow.run_stage(incident_id, "Sentinel", "test-owner")
    assert "EV-DETECTION" in tools["get_incident_context"]()["evidence"]


def test_agent_can_correct_missing_retrieval_without_bypassing_validation(make_workflow):
    from resilientops.agents.google_adk import build_agent

    workflow = make_workflow()
    workflow.settings = replace(workflow.settings, project="test-project", model="test-model")
    incident_id = workflow.create()["id"]
    workflow._claim(incident_id, "test-owner")
    workflow.run_stage(incident_id, "Sentinel", "test-owner")
    root = build_agent(workflow, incident_id, "test-owner")
    agent = next(node for node in root.graph.nodes if getattr(node, "name", None) == "Sentinel")
    tools = {tool.__name__: tool for tool in agent.tools if callable(tool)}
    review = dict(
        summary="A cited triage review for this incident.",
        evidence_ids=["EV-DETECTION"],
        uncertainties=[],
        next_action="Investigate the disruption.",
        verdict="continue",
    )
    rejected = tools["submit_assessment"](**review)
    assert rejected["accepted"] is False
    assert not workflow.store.get(incident_id).get("agent_reviews", {}).get("Sentinel")
    tools["retrieve_evidence"]("emergency sourcing policy")
    assert tools["submit_assessment"](**review)["verdict"] == "continue"
    rejected = tools["submit_assessment"](**(review | {"evidence_ids": ["FAKE-CITATION"]}))
    assert rejected["accepted"] is False
    assert workflow.store.get(incident_id)["agent_reviews"]["Sentinel"]["evidence_ids"] == [
        "EV-DETECTION"
    ]
