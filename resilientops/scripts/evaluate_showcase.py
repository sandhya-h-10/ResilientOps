"""Run every showcase in an isolated ledger; no model calls or production mutations."""

import asyncio
import json
import tempfile
from pathlib import Path

from resilientops.adapters.operational import OperationalData
from resilientops.config import Settings
from resilientops.services.diagram import DiagramWorkflow, DraftRequest, RevisionRequest
from resilientops.services.workflow import Workflow
from resilientops.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    data = OperationalData(ROOT / "resilientops_data")
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for case in data.showcase:
            settings = Settings(data_dir=data.root, db_path=Path(directory) / f"{case.id}.db")
            workflow = Workflow(settings, Store(settings.db_path))
            diagram = DiagramWorkflow(workflow)
            incident = diagram.create(
                DraftRequest(title=case.title, description=case.description, scenario_id=case.id),
                "showcase-validator",
            )
            diagram.assess(incident["id"], RevisionRequest(revision=1), "showcase-validator")
            result = asyncio.run(workflow.analyze(incident["id"]))
            impact = result["results"].get("Impact", {})
            results.append(
                {
                    "scenario_id": case.id,
                    "title": case.title,
                    "plant": case.plant,
                    "material": case.material,
                    "status": result["status"],
                    "peak_shortage": impact.get("shortage_units"),
                    "first_shortage_day": impact.get("first_shortage_day"),
                    "candidate_count": len(result.get("candidates", [])),
                    "plan_status": (result.get("plan") or {}).get("status"),
                    "estimated_cost_paise": (result.get("plan") or {}).get("total_cost_paise"),
                    "error": result.get("error"),
                }
            )
            print(case.id, result["status"], impact.get("shortage_units"))
    target = ROOT / "docs/evaluation/showcase-results.json"
    target.write_text(
        json.dumps(
            {
                "synthetic": True,
                "agent_mode": "local",
                "evidence_mode": "rules",
                "live_genai_tested": False,
                "isolated_ledgers": True,
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )
    return results


if __name__ == "__main__":
    evaluate()
