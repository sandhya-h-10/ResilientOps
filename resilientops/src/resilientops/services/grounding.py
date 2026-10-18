"""Machine-checkable claims reference exact fields in authoritative tool outputs."""

from resilientops.models import DomainError

CLAIMS = {
    "Available inventory": ("EV-IMPACT", "available_units"),
    "Days of cover": ("EV-IMPACT", "days_of_cover"),
    "Uncovered material units": ("EV-IMPACT", "shortage_units"),
    "Recovery cost (INR paise)": ("EV-RECOVERY", "total_cost_paise"),
}


def validate_claims(claims: list[dict], evidence: dict):
    for claim in claims:
        expected = CLAIMS.get(claim.get("label"))
        if expected is None or (claim.get("evidence_id"), claim.get("field")) != expected:
            raise DomainError("Unsupported claim or evidence reference")
        source = evidence.get(expected[0])
        if source is None or source["value"].get(expected[1]) != claim.get("value"):
            raise DomainError("Claim does not match its supporting evidence")
