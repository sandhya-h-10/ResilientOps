from resilientops.agents.context import Context
from resilientops.analytics.detection import assess_signals
from resilientops.analytics.disruptions import assess_disruptions


class Sentinel:
    name = "Sentinel"
    description = "Triage external, internal and market disruptions using evidence and historical anomaly tools."

    def run(self, context: Context) -> dict:
        event = context.dataset.event
        history = context.erp.get_supplier_history(event.supplier_id)
        result = assess_signals(history["observations"], event.severity)
        result["disruption_monitoring"] = assess_disruptions(
            context.dataset.source_metadata.get("disruption_signals", [])
        )
        if result["disruption_monitoring"]["signals"]:
            result.update(
                risk_score=None,
                method="Multi-domain historical anomaly screening",
                history_sufficient=True,
                triage="investigate" if result["disruption_monitoring"]["anomalies"] else "normal",
            )
        for signal in context.dataset.source_metadata.get("disruption_signals", []):
            context.evidence(
                signal["id"],
                "DOCUMENT",
                signal["subtype"] + " signal",
                signal,
                "Synthetic signal observations; not verified causal evidence.",
            )
        result["event"] = event.model_dump(mode="json")
        result["evidence_id"] = context.evidence(
            "EV-DETECTION",
            "ESTIMATE",
            "event + historical monitoring evidence",
            result.copy(),
            "Synthetic statistical screening; no calibrated probability or confirmed causal attribution. No aggregate risk score is inferred from multi-domain anomalies.",
        )
        return result
