"""Configuration is explicit; local runs never require cloud credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    database_url: str = field(default="", repr=False)
    agent_mode: str = "local"
    manager_token: str = ""
    senior_token: str = ""
    chat_model: str = "gemini-2.5-flash"
    chat_api_key: str = ""
    model_backend: str = "auto"
    model: str = ""
    project: str = ""
    location: str = "us-central1"
    knowledge_mode: str = "local"
    erp_mode: str = "local"
    bigquery_dataset: str = ""
    index_endpoint: str = ""
    deployed_index_id: str = ""
    embedding_model: str = ""
    max_llm_calls: int = 80
    analysis_timeout: int = 1800
    llm_requests_per_minute: int = 0
    evidence_mode: str = "auto"
    input_usd_per_million: float | None = None
    output_usd_per_million: float | None = None
    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret: str = ""
    public_url: str = "http://127.0.0.1:8000"

    @classmethod
    def from_env(cls):
        root = Path(__file__).resolve().parents[2]
        data_root = root / "resilientops_data"
        if not data_root.exists():
            data_root = Path(__file__).parent / "resilientops_data"
        return cls(
            data_dir=Path(os.getenv("RESILIENTOPS_DATA_DIR", str(data_root))),
            db_path=Path(os.getenv("RESILIENTOPS_DB", str(root / "var" / "operational.db"))),
            llm_requests_per_minute=int(os.getenv("RESILIENTOPS_LLM_REQUESTS_PER_MINUTE", "4")),
            analysis_timeout=int(os.getenv("RESILIENTOPS_ANALYSIS_TIMEOUT", "1800")),
            max_llm_calls=int(os.getenv("RESILIENTOPS_MAX_LLM_CALLS", "80")),
            database_url=os.getenv("RESILIENTOPS_DATABASE_URL", ""),
            agent_mode=os.getenv("RESILIENTOPS_AGENT_MODE", "local"),
            manager_token=os.getenv("RESILIENTOPS_MANAGER_TOKEN", ""),
            senior_token=os.getenv("RESILIENTOPS_SENIOR_TOKEN", ""),
            google_client_id=os.getenv("RESILIENTOPS_GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.getenv("RESILIENTOPS_GOOGLE_CLIENT_SECRET", ""),
            session_secret=os.getenv("RESILIENTOPS_SESSION_SECRET", ""),
            public_url=os.getenv("RESILIENTOPS_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
            chat_model=os.getenv("RESILIENTOPS_CHAT_MODEL", "gemini-2.5-flash"),
            chat_api_key=os.getenv("GEMINI_API_KEY", ""),
            model_backend=os.getenv("RESILIENTOPS_MODEL_BACKEND", "vertex"),
            model=os.getenv("RESILIENTOPS_MODEL", ""),
            project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            knowledge_mode=os.getenv("RESILIENTOPS_KNOWLEDGE_MODE", "local"),
            erp_mode=os.getenv("RESILIENTOPS_ERP_MODE", "local"),
            bigquery_dataset=os.getenv("RESILIENTOPS_BIGQUERY_DATASET", ""),
            index_endpoint=os.getenv("RESILIENTOPS_INDEX_ENDPOINT", ""),
            deployed_index_id=os.getenv("RESILIENTOPS_DEPLOYED_INDEX_ID", ""),
            embedding_model=os.getenv("RESILIENTOPS_EMBEDDING_MODEL", ""),
            evidence_mode=os.getenv("RESILIENTOPS_EVIDENCE_MODE", "auto"),
            input_usd_per_million=float(os.environ["RESILIENTOPS_INPUT_USD_PER_MILLION"])
            if os.getenv("RESILIENTOPS_INPUT_USD_PER_MILLION")
            else None,
            output_usd_per_million=float(os.environ["RESILIENTOPS_OUTPUT_USD_PER_MILLION"])
            if os.getenv("RESILIENTOPS_OUTPUT_USD_PER_MILLION")
            else None,
        )

    @property
    def database_target(self):
        return self.database_url or self.db_path

    @property
    def uses_vertex(self):
        return self.model_backend == "vertex" or (
            self.model_backend == "auto" and not self.chat_api_key
        )

    def model_client_kwargs(self):
        """Explicit routing prevents an old API key from overriding Vertex ADC."""
        if self.uses_vertex:
            if not self.project:
                raise ValueError("Vertex AI requires GOOGLE_CLOUD_PROJECT")
            return {"vertexai": True, "project": self.project, "location": self.location}
        if not self.chat_api_key:
            raise ValueError("Gemini API backend requires GEMINI_API_KEY")
        return {"vertexai": False, "api_key": self.chat_api_key}

    @property
    def google_login_enabled(self):
        return bool(self.google_client_id and self.google_client_secret and self.session_secret)

    def validate_login(self):
        from urllib.parse import urlsplit

        configured = (self.google_client_id, self.google_client_secret, self.session_secret)
        if any(configured) and not all(configured):
            raise ValueError("Google sign-in requires client ID, client secret and session secret")
        if self.google_login_enabled:
            if len(self.session_secret) < 32:
                raise ValueError("Session secret must contain at least 32 random characters")
            url = urlsplit(self.public_url)
            if (
                not url.netloc
                or url.username
                or url.password
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
                or not (
                    url.scheme == "https"
                    or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"})
                )
            ):
                raise ValueError("Public URL must be an HTTPS origin or local HTTP origin")

    @property
    def effective_evidence_mode(self):
        return (
            ("gemini" if self.agent_mode == "google" else "rules")
            if self.evidence_mode == "auto"
            else self.evidence_mode
        )

    def validate(self):
        import math

        self.validate_login()
        if self.database_url and not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("RESILIENTOPS_DATABASE_URL must be a PostgreSQL connection URL")
        if os.getenv("K_SERVICE") and not self.database_url:
            raise ValueError(
                "Cloud Run requires RESILIENTOPS_DATABASE_URL; ephemeral SQLite is disabled"
            )

        if self.model_backend not in {"auto", "vertex", "gemini"}:
            raise ValueError("Model backend must be vertex, gemini or auto")
        if self.llm_requests_per_minute < 0 or self.analysis_timeout < 1 or self.max_llm_calls < 1:
            raise ValueError("Invalid model request budget or analysis timeout")
        if self.evidence_mode not in {"auto", "rules", "gemini"}:
            raise ValueError("Evidence mode must be auto, rules or gemini")
        for rate in (self.input_usd_per_million, self.output_usd_per_million):
            if rate is not None and (not math.isfinite(rate) or rate < 0):
                raise ValueError("Model price assumptions must be finite and nonnegative")
        if self.erp_mode not in {"local", "bigquery"}:
            raise ValueError("RESILIENTOPS_ERP_MODE must be local or bigquery")
        if self.erp_mode == "bigquery" and not (self.project and self.bigquery_dataset):
            raise ValueError("BigQuery mode requires project and dataset")
        if self.agent_mode not in {"local", "google"}:
            raise ValueError("RESILIENTOPS_AGENT_MODE must be local or google")
        if self.knowledge_mode not in {"local", "vertex"}:
            raise ValueError("RESILIENTOPS_KNOWLEDGE_MODE must be local or vertex")
        if self.agent_mode == "google" and self.effective_evidence_mode != "gemini":
            raise ValueError("Google agents require mandatory Gemini evidence extraction")
        if (self.agent_mode == "google" or self.effective_evidence_mode == "gemini") and not (
            self.model and (self.project if self.uses_vertex else self.chat_api_key)
        ):
            raise ValueError(
                "Model configuration requires RESILIENTOPS_MODEL and credentials for the selected backend (Vertex: GOOGLE_CLOUD_PROJECT and ADC)"
            )
        if self.knowledge_mode == "vertex" and not all(
            [self.project, self.index_endpoint, self.deployed_index_id, self.embedding_model]
        ):
            raise ValueError(
                "Vertex retrieval requires project, endpoint, deployed index and embedding model"
            )
        if self.manager_token and self.manager_token == self.senior_token:
            raise ValueError("Manager and senior tokens must be different")
