"""Stdio MCP server exposing ERP reads only; no network listener or write tool."""

import argparse

from resilientops.adapters.operational import load_dataset
from resilientops.config import Settings
from resilientops.models import Dataset
from resilientops.tools.erp import ERPTools


def build_server(settings: Settings | None = None, incident_id: str | None = None):
    from mcp.server.fastmcp import FastMCP

    settings = settings or Settings.from_env()
    server = FastMCP("resilientops-erp-readonly")

    def current_tools():
        if incident_id:
            from resilientops.storage import Store

            dataset = Dataset.model_validate(Store(settings.database_target).get(incident_id)["snapshot"])
        else:
            dataset = load_dataset(settings.data_dir)
        return ERPTools(dataset)

    def get_inventory(plant_id: str, material_id: str) -> dict:
        """Read inventory in the current validated incident snapshot."""
        return current_tools().get_inventory(plant_id, material_id)

    def get_supplier_history(supplier_id: str) -> dict:
        """Read the known supplier's performance history."""
        return current_tools().get_supplier_history(supplier_id)

    def get_dependencies(supplier_id: str) -> dict:
        """Read supply dependencies for the known supplier."""
        return current_tools().get_dependencies(supplier_id)

    def get_recovery_options(material_id: str, plant_id: str) -> dict:
        """Read recovery options including reconciled shipment dates and capacities."""
        return current_tools().get_recovery_options(material_id, plant_id)

    for tool in [
        get_inventory,
        get_supplier_history,
        get_dependencies,
        get_recovery_options,
    ]:
        server.tool()(tool)
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-id")
    args = parser.parse_args()
    build_server(incident_id=args.incident_id).run(transport="stdio")


if __name__ == "__main__":
    main()
