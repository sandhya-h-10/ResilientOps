from resilientops.agents.context import Context
from resilientops.analytics.impact import calculate_impact


class Impact:
    name = "Impact"
    description = (
        "Trace dependencies and calculate time-phased shortage and uncertainty using exact tools."
    )

    def run(self, context: Context) -> dict:
        result = calculate_impact(context.dataset)
        context.evidence(
            "EV-IMPACT",
            "CALCULATION",
            "SQL-equivalent inventory arithmetic + Python",
            result,
            "On-hand minus reserved minus quality hold; cumulative dated demand. Simulation assumptions are separate.",
        )
        return result
