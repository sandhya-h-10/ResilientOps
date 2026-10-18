from dataclasses import dataclass

from resilientops.config import Settings
from resilientops.models import Dataset, Evidence
from resilientops.tools.erp import ERPTools
from resilientops.tools.knowledge import Knowledge


@dataclass
class Context:
    incident: dict
    dataset: Dataset
    erp: ERPTools
    knowledge: Knowledge
    settings: Settings | None = None
    extractor: object | None = None

    def evidence(self, identifier: str, kind: str, source: str, value, explanation: str):
        item = Evidence(
            id=identifier,
            kind=kind,
            source=source,
            value=value,
            explanation=explanation,
            synthetic=self.dataset.event.synthetic,
        )
        self.incident["evidence"][identifier] = item.model_dump(mode="json")
        return identifier
