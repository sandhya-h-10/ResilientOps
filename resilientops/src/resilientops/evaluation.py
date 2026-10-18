"""Small, labeled synthetic evaluation; never substitutes test doubles for live AI."""

import asyncio
import hashlib
import html
import json
import math
import statistics
import tempfile
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from resilientops.models import Dataset, Plan, utcnow
from resilientops.services.policy import validate_plan
from resilientops.services.scenarios import catalog, scenario_dataset
from resilientops.services.workflow import Workflow
from resilientops.storage import Store, fingerprint


def suite_fingerprint(settings):
    labels = settings.data_dir.parent / "evaluation" / "cases.json"
    source_root = Path(__file__).parent
    code = hashlib.sha256()
    for path in sorted(source_root.rglob("*.py")):
        code.update(str(path.relative_to(source_root)).encode())
        code.update(path.read_bytes())
    return fingerprint(
        {
            "scenarios": catalog(settings.data_dir),
            "labels": json.loads(labels.read_text()),
            "base": json.loads((settings.data_dir / "scenario.json").read_text()),
            "code": code.hexdigest(),
        }
    )


def score_case(incident, gold, truth):
    interpretation = incident["results"].get("Investigator", {}).get("interpretation") or {}
    raw = set()
    cited, count = 0, 0
    sources = {u.id: u.text for u in truth.updates}
    for reading in interpretation.get("readings", []):
        for field in ("arrival_date", "capacity_units"):
            claim = reading.get(field)
            if claim:
                count += 1
                raw.add((reading["source_id"], reading["option_id"], field, claim["value"]))
                text = sources.get(reading["source_id"], "")
                cited += bool(
                    claim["quote"]
                    and claim["quote"] in text
                    and reading["entity_quote"]
                    and reading["entity_quote"] in text
                )
    expected = {tuple(fact) for fact in gold["facts"]}
    plan = Plan.model_validate(incident["plan"]) if incident.get("plan") else None
    outcome = "FAILED"
    if incident["status"] == "ESCALATED":
        outcome = "ESCALATE"
    elif plan and plan.status == "NO_ACTION":
        outcome = "NO_ACTION"
    elif incident["status"] == "AWAITING_APPROVAL":
        outcome = "PLAN"
    validation = validate_plan(truth, plan) if outcome == "PLAN" else []
    feasible = outcome == "PLAN" and not validation and gold["expected_outcome"] == "PLAN"
    correct = outcome == gold["expected_outcome"] and (outcome != "PLAN" or feasible)
    if "expected_cost_paise" in gold and plan and outcome in {"PLAN", "NO_ACTION"}:
        correct = correct and plan.total_cost_paise == gold["expected_cost_paise"]
    return {
        "id": gold["id"],
        "expected_outcome": gold["expected_outcome"],
        "outcome": outcome,
        "decision_correct": bool(correct),
        "returned_feasible_plan": feasible,
        "true_positive_facts": len(raw & expected),
        "predicted_facts": len(raw),
        "expected_facts": len(expected),
        "exact_citation_spans": cited,
        "citation_count": count,
        "plan_cost_paise": plan.total_cost_paise if plan else None,
        "truth_validation_errors": validation,
        "error": incident.get("error"),
        "usage": interpretation.get(
            "usage", {"calls": 0, "estimated_cost_usd": None if outcome == "FAILED" else 0}
        ),
        "business_impact": incident["results"].get("Recovery", {}).get("business_impact"),
    }


def summarize(rows):
    tp = sum(r["true_positive_facts"] for r in rows)
    predicted = sum(r["predicted_facts"] for r in rows)
    expected = sum(r["expected_facts"] for r in rows)
    citations = sum(r["citation_count"] for r in rows)
    latencies = sorted(r["latency_ms"] for r in rows)
    returned = sum(r["outcome"] == "PLAN" for r in rows)
    escalation_cases = [r for r in rows if r["expected_outcome"] == "ESCALATE"]
    costs = [r["usage"].get("estimated_cost_usd") for r in rows]
    return {
        "cases": len(rows),
        "correct_decisions": sum(r["decision_correct"] for r in rows),
        "decision_success_rate": sum(r["decision_correct"] for r in rows) / len(rows),
        "extraction_precision": tp / predicted if predicted else None,
        "extraction_recall": tp / expected if expected else None,
        "citation_span_validity": sum(r["exact_citation_spans"] for r in rows) / citations
        if citations
        else None,
        "feasible_plan_rate": sum(r["returned_feasible_plan"] for r in rows) / returned
        if returned
        else None,
        "escalation_recall": sum(r["outcome"] == "ESCALATE" for r in escalation_cases)
        / len(escalation_cases)
        if escalation_cases
        else None,
        "false_escalations": sum(
            r["outcome"] == "ESCALATE" and r["expected_outcome"] != "ESCALATE" for r in rows
        ),
        "failed_runs": sum(r["outcome"] == "FAILED" for r in rows),
        "median_latency_ms": round(statistics.median(latencies), 2),
        "p95_latency_ms": round(latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)], 2),
        "reported_model_calls": sum(r["usage"].get("calls", 0) for r in rows),
        "estimated_cost_usd": sum(costs)
        if all(c is not None for c in costs) and not any(r["outcome"] == "FAILED" for r in rows)
        else None,
        "human_review_time_seconds": None,
    }


async def evaluate(settings, modes=("structured-only", "rules")):
    base = Dataset.model_validate_json((settings.data_dir / "scenario.json").read_text())
    specs = {spec["id"]: spec for spec in catalog(settings.data_dir)}
    labels = json.loads((settings.data_dir.parent / "evaluation" / "cases.json").read_text())
    report = {
        "generated_at": utcnow().isoformat(),
        "suite_fingerprint": suite_fingerprint(settings),
        "dataset": "11 authored synthetic scenarios; not a held-out industry dataset",
        "limits": [
            "Small developer-authored regression benchmark; no statistical claim of generalization or judge score improvement.",
            "Structured-only ignores shipment messages. Rules uses a disclosed strict ISO template; it is not the strongest possible non-LLM baseline.",
            "Gemini is measured only when explicitly selected and actually called. No recorded or scripted model outputs are counted as live results.",
            "Citation metrics check exact spans, not semantic entailment or sender authenticity.",
            "Model tokens/cost cover extraction only. Google-mode ADK orchestration requires a separate live demo run.",
            "Human review time and real business outcomes have not been measured.",
        ],
        "gemini_live": "measured" if "gemini" in modes else "not_run",
        "modes": {},
    }
    for mode in modes:
        if mode not in {"structured-only", "rules", "gemini"}:
            raise ValueError("Unknown evaluation mode")
        config = replace(
            settings,
            agent_mode="local",
            evidence_mode="gemini" if mode == "gemini" else "rules",
            erp_mode="local",
            knowledge_mode="local",
        )
        config.validate()
        rows = []
        for gold in labels:
            dataset = scenario_dataset(base, specs[gold["id"]])
            truth = dataset.model_copy(deep=True)
            for change in gold["truth_changes"]:
                option = next(o for o in truth.options if o.id == change["option_id"])
                for key, value in change.items():
                    if key != "option_id":
                        setattr(option, key, value)
            with tempfile.TemporaryDirectory(prefix="resilientops-eval-") as directory:
                runtime = replace(config, db_path=Path(directory) / "state.db", database_url="")
                workflow = Workflow(runtime, Store(runtime.database_target))
                workflow.dataset = (
                    dataset.model_copy(update={"updates": []})
                    if mode == "structured-only"
                    else dataset
                )
                started = perf_counter()
                incident = await workflow.analyze(workflow.create()["id"])
                row = score_case(incident, gold, truth)
                row["latency_ms"] = round((perf_counter() - started) * 1000, 2)
                rows.append(row)
        report["modes"][mode] = {"summary": summarize(rows), "cases": rows}
    if "gemini" in report["modes"] and report["modes"]["gemini"]["summary"]["failed_runs"]:
        report["gemini_live"] = "attempted_with_failures"
    return report


def write_report(report, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))

    def esc(value):
        return html.escape(str(value))

    def percent(value):
        return f"{value:.1%}" if value is not None else "Not measured"

    sections = []
    for name, mode in report["modes"].items():
        s = mode["summary"]
        metrics = [
            ("Correct decisions", f"{s['correct_decisions']}/{s['cases']}"),
            (
                "Fact precision / recall",
                f"{percent(s['extraction_precision'])} / {percent(s['extraction_recall'])}",
            ),
            ("Citation span validity", percent(s["citation_span_validity"])),
            ("Feasible returned plans", percent(s["feasible_plan_rate"])),
            ("Escalation recall", percent(s["escalation_recall"])),
            ("Median / p95 latency", f"{s['median_latency_ms']} / {s['p95_latency_ms']} ms"),
            (
                "Estimated model cost (USD)",
                s["estimated_cost_usd"]
                if s["estimated_cost_usd"] is not None
                else "Unknown; configure model rates",
            ),
            ("Human review time", "Not measured"),
        ]
        cards = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in metrics)
        rows = "".join(
            f"<tr><td>{esc(r['id'])}</td><td>{esc(r['expected_outcome'])}</td><td>{esc(r['outcome'])}</td><td>{'PASS' if r['decision_correct'] else 'FAIL'}</td><td>{esc('; '.join(r['truth_validation_errors']) or r['error'] or '—')}</td></tr>"
            for r in mode["cases"]
        )
        sections.append(
            f"<section><h2>{esc(name)}</h2><dl>{cards}</dl><div class='scroll'><table><thead><tr><th>Case</th><th>Expected</th><th>Observed</th><th>Decision check</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table></div></section>"
        )
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ResilientOps evaluation</title><style>body{font:16px/1.6 system-ui;margin:0;background:#f3f6f5;color:#18352c}main{max-width:1100px;margin:auto;padding:32px 20px}section{background:white;border:1px solid #d9e3df;border-radius:12px;padding:24px;margin:24px 0}dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}dt{font-size:13px;color:#52665d}dd{margin:0;font-weight:700}.scroll{overflow:auto}table{border-collapse:collapse;font-size:13px;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #d9e3df;vertical-align:top}h1{line-height:1.2}code{overflow-wrap:anywhere}</style><main><h1>ResilientOps · Evidence evaluation</h1>"""
    page += f"<p>Generated {esc(report['generated_at'])}. Live Gemini: <strong>{esc(report['gemini_live'])}</strong>.</p><p>{esc(report['dataset'])}</p>"
    page += (
        "".join(sections)
        + "<h2>Interpretation limits</h2><ul>"
        + "".join(f"<li>{esc(item)}</li>" for item in report["limits"])
        + f"</ul><p>Suite fingerprint: <code>{esc(report['suite_fingerprint'])}</code></p></main></html>"
    )
    output.with_suffix(".html").write_text(page)


def main_evaluation(settings, modes, output):
    report = asyncio.run(evaluate(settings, modes))
    write_report(report, output)
    return report
