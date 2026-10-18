import argparse
import asyncio
import json
import os
import secrets
import tempfile
from dataclasses import replace
from pathlib import Path

from resilientops.config import Settings
from resilientops.models import Decision, Principal
from resilientops.services.execution import ActionService
from resilientops.services.workflow import Workflow
from resilientops.storage import Store


def local_credentials(settings: Settings) -> Settings:
    if settings.manager_token and settings.senior_token:
        return settings
    path = settings.db_path.parent / "dev_credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(
                {"manager": secrets.token_urlsafe(32), "senior": secrets.token_urlsafe(32)}, handle
            )
    tokens = json.loads(path.read_text())
    return replace(
        settings,
        manager_token=settings.manager_token or tokens["manager"],
        senior_token=settings.senior_token or tokens["senior"],
    )


def main():
    parser = argparse.ArgumentParser(prog="resilientops")
    parser.add_argument("--env-file", type=Path, help="Load explicit local configuration")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local control tower")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    demo = commands.add_parser("demo", help="Run an isolated, reproducible synthetic scenario")
    demo.add_argument(
        "--approve",
        action="store_true",
        help="Approve and execute simulated actions, then simulate delivery",
    )
    demo.add_argument("--scenario", default="baseline", help="Named synthetic scenario")
    evaluation = commands.add_parser(
        "evaluate", help="Compare labeled scenarios without executing inventory actions"
    )
    evaluation.add_argument(
        "--mode",
        choices=["offline", "structured-only", "rules", "gemini", "all"],
        default="offline",
    )
    evaluation.add_argument(
        "--output", type=Path, help="JSON report path; an HTML report is written alongside it"
    )
    commands.add_parser("init", help="Initialize local state and random approver credentials")
    index = commands.add_parser(
        "index-documents", help="Upsert demo chunks into an existing Vertex index"
    )
    index.add_argument(
        "--index", required=True, help="Fully qualified streaming-update index resource"
    )
    signals = commands.add_parser(
        "signals", help="Fetch public event/weather signals without creating actions"
    )
    signals.add_argument("--latitude", type=float, default=22.54)
    signals.add_argument("--longitude", type=float, default=114.06)
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    settings = Settings.from_env()
    settings.validate()
    if args.command in {"init", "serve"}:
        settings = local_credentials(settings)
        if args.command == "init":
            Workflow(settings, Store(settings.database_target))
            print(
                f"Initialized {settings.db_path}. Approver credentials: {settings.db_path.parent / 'dev_credentials.json'}"
            )
        else:
            import uvicorn

            from resilientops.api import create_app

            print(f"Local approver credentials: {settings.db_path.parent / 'dev_credentials.json'}")
            uvicorn.run(create_app(settings), host=args.host, port=args.port)
    elif args.command == "demo":
        with tempfile.TemporaryDirectory(prefix="resilientops-demo-") as directory:
            demo_settings = replace(settings, db_path=Path(directory) / "demo.db", database_url="")
            store = Store(demo_settings.database_target)
            workflow = Workflow(demo_settings, store)
            incident = asyncio.run(workflow.analyze(workflow.create(args.scenario)["id"]))
            if args.approve and incident["status"] == "AWAITING_APPROVAL":
                service = ActionService(store)
                principal = Principal(id="explicit-demo-script", role="senior")
                service.decide(
                    incident["id"],
                    Decision(plan_hash=incident["plan_hash"], decision="APPROVE"),
                    principal,
                )
                service.execute(incident["id"], incident["plan_hash"], principal)
                incident = service.receive_simulated_delivery(incident["id"], principal)
            output = settings.db_path.parent / "demo-report.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(incident, indent=2))
            print(
                json.dumps(
                    {
                        "status": incident["status"],
                        "error": incident.get("error"),
                        "plan": incident["plan"],
                        "report": str(output),
                    },
                    indent=2,
                )
            )
            if incident["status"] in {"FAILED", "ESCALATED"}:
                raise SystemExit(1)
    elif args.command == "evaluate":
        from resilientops.adapters.operational import is_operational
        from resilientops.evaluation import main_evaluation

        if is_operational(settings.data_dir):
            parser.error(
                "resilientops_data has no golden evaluation labels. Legacy evaluations require an explicit RESILIENTOPS_DATA_DIR=data/demo override."
            )

        modes = (
            ["structured-only", "rules"]
            if args.mode == "offline"
            else ["structured-only", "rules", "gemini"]
            if args.mode == "all"
            else [args.mode]
        )
        output = args.output or settings.db_path.parent / "evaluation.json"
        report = main_evaluation(settings, modes, output)
        print(
            json.dumps(
                {
                    "reports": [str(output), str(output.with_suffix(".html"))],
                    "gemini_live": report["gemini_live"],
                    "results": {k: v["summary"] for k, v in report["modes"].items()},
                },
                indent=2,
            )
        )
        if any(v["summary"]["failed_runs"] for v in report["modes"].values()):
            raise SystemExit(1)
    elif args.command == "signals":
        from resilientops.tools.signals import fetch_signals

        print(json.dumps(asyncio.run(fetch_signals(args.latitude, args.longitude)), indent=2))
    elif args.command == "index-documents":
        from resilientops.adapters.operational import load_dataset
        from resilientops.adapters.vertex import index_documents

        if not settings.project or not settings.embedding_model:
            parser.error("Indexing requires GOOGLE_CLOUD_PROJECT and RESILIENTOPS_EMBEDDING_MODEL")
        dataset = load_dataset(settings.data_dir)
        index_documents(settings, dataset.documents, args.index)
        print(f"Indexed {len(dataset.documents)} versioned demo chunks")


if __name__ == "__main__":
    main()
