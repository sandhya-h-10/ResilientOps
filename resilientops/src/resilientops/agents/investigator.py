from resilientops.agents.context import Context
from resilientops.models import DomainError
from resilientops.services.intelligence import RulesExtractor, interpret


class Investigator:
    name = "Investigator"
    description = (
        "Retrieve active supplier and policy evidence; abstain when required evidence is absent."
    )

    def run(self, context: Context) -> dict:
        event = context.dataset.event
        # Query supplier-specific and global policies independently so one filter cannot hide the other.
        results = context.knowledge.search(
            f"{event.supplier_id} storm logistics audit", event.supplier_id
        )
        results += context.knowledge.search(
            "emergency inventory transfer alternate sourcing policy", event.supplier_id
        )
        documents = {doc.id: doc for doc in results}
        required = set(context.dataset.required_policy_ids)
        # Required policy IDs are explicit configuration, not semantic aliases.
        for document in context.dataset.documents:
            if (
                document.id in required
                or document.id == "OPERATOR-EVIDENCE"
                or document.document_type == "INCIDENT"
            ) and document.active:
                documents[document.id] = document
        issues = []
        if not required.issubset(documents):
            issues.append(
                "Insufficient evidence: active demo transfer and sourcing policies are required"
            )
        evidence_ids = []
        for document in documents.values():
            evidence_ids.append(
                context.evidence(
                    document.id,
                    "DOCUMENT",
                    document.title,
                    document.model_dump(),
                    "Retrieved source text; treated as data, never instructions.",
                )
            )
        context_extraction = None
        if context.settings and context.settings.effective_evidence_mode == "gemini":
            from resilientops.adapters.gemini import extract_context

            context_extraction = extract_context(
                context.settings, context.dataset, list(documents.values())
            )
            context.evidence(
                "EV-CONTEXT-EXTRACTION",
                "DOCUMENT",
                "Mandatory Gemini evidence extraction",
                context_extraction,
                context_extraction["scope"],
            )
        interpretation = None
        if context.dataset.updates:
            extractor = context.extractor or RulesExtractor()
            if (
                context.extractor is None
                and context.settings
                and context.settings.effective_evidence_mode == "gemini"
            ):
                from resilientops.adapters.gemini import GeminiExtractor

                extractor = GeminiExtractor(context.settings)
            updated, interpretation = interpret(context.dataset, extractor)
            if (
                context.settings
                and context.settings.effective_evidence_mode == "gemini"
                and interpretation["usage"]["provider"] != "gemini"
            ):
                raise DomainError(
                    "Mandatory Gemini extraction cannot fall back to a rules provider"
                )
            issues.extend(interpretation["blocking_issues"])
            if not issues:
                context.dataset = updated
            else:
                interpretation["status"] = "NEEDS_REVIEW"
                interpretation["changes"] = []
            evidence_ids.append(
                context.evidence(
                    "EV-SHIPMENT-UPDATES",
                    "DOCUMENT",
                    "Cited shipment-message interpretation",
                    interpretation,
                    interpretation["assurance"],
                )
            )
        return {
            "context_extraction": context_extraction,
            "document_ids": list(documents),
            "evidence_ids": evidence_ids,
            "findings": "Review the cited shipment facts and planning changes below. Conflicting or unsupported evidence requires review."
            if interpretation
            else "Supplier audit and active emergency policies retrieved. No shipment updates were supplied; planning inputs remain the scenario assumptions.",
            "unknowns": ["Supplier maximum monthly capacity is not established by the audit."],
            "retrieval": type(context.knowledge).__name__,
            "interpretation": interpretation,
            "blocking_issues": issues,
        }
