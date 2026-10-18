"""ERP tool contract; the local adapter operates on validated snapshots."""

from resilientops.models import Dataset, DomainError


class ERPTools:
    def __init__(self, dataset: Dataset):
        self.dataset = dataset

    def get_inventory(self, plant_id: str, material_id: str) -> dict:
        """Read one known inventory balance; quantities are individual material units."""
        for item in self.dataset.inventories:
            if item.plant_id == plant_id and item.material_id == material_id:
                return item.model_dump() | {
                    "available": item.available,
                    "transferable": item.transferable,
                }
        raise DomainError("Unknown plant/material inventory", 404)

    def get_supplier_history(self, supplier_id: str) -> dict:
        """Read OTIF, lead time, defect rate and shipment delay observations."""
        if supplier_id != self.dataset.event.supplier_id:
            raise DomainError("Unknown supplier history", 404)
        return {
            "supplier_id": supplier_id,
            "columns": ["otif", "lead_days", "defect_rate", "delay_days"],
            "observations": self.dataset.supplier_history,
            "synthetic": True,
        }

    def get_dependencies(self, supplier_id: str) -> dict:
        """Return directed supply-chain dependency edges for the known supplier."""
        if supplier_id != self.dataset.event.supplier_id:
            raise DomainError("Unknown supplier", 404)
        return {"edges": self.dataset.edges}

    def get_recovery_options(self, material_id: str, plant_id: str) -> dict:
        """Read candidate routes and suppliers, including qualification flags."""
        return {
            "options": [
                o.model_dump()
                for o in self.dataset.options
                if o.material_id == material_id and o.destination == plant_id
            ]
        }
