# Google Cloud integrations

The default local assessment does not create cloud resources or make model calls. Res chat makes an explicit Gemini call when a signed-in user sends a question and model credentials are configured. Explicit Gemini evidence mode makes model calls even with local stage orchestration. Cloud adapters require a project, Application Default Credentials, enabled APIs and appropriate IAM permissions. Choose supported model IDs and matching regions for your project; the application deliberately has no hard-coded paid model fallback.

## Vertex AI authentication

The configured application uses Vertex AI for all five agents, mandatory Investigator extraction, and Res chat. Set `RESILIENTOPS_MODEL_BACKEND=vertex`; this explicitly ignores any stale Gemini API key. Gemini remains the model family, served through Vertex AI. The local evidence retrieval store remains unchanged.

Install the Google Cloud CLI if it is missing, then run these commands interactively on the server:

```sh
gcloud auth application-default login
gcloud auth application-default set-quota-project project-bceae5b1-7549-4f14-922
```

The project needs billing, the Vertex AI API (`aiplatform.googleapis.com`), and the authenticated principal needs Vertex AI access (typically `roles/aiplatform.user`) plus permission to use the quota project. Do not commit ADC files. Browser sign-in to ResilientOps is separate and cannot supply server credentials.

See [Google ADC setup](https://docs.cloud.google.com/docs/authentication/provide-credentials-adc) and [Gemini 3.5 Flash on Google Cloud](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash). Restart the server after configuration. Missing credentials are surfaced as unavailable AI; the app does not fall back to API-key requests.

## Gemini through Google ADK

Install all extras, copy `.env.example` to `.env`, and set:

```dotenv
RESILIENTOPS_AGENT_MODE=google
RESILIENTOPS_MODEL_BACKEND=vertex
GOOGLE_CLOUD_PROJECT=project-bceae5b1-7549-4f14-922
GOOGLE_CLOUD_LOCATION=global
RESILIENTOPS_MODEL=gemini-3.5-flash
RESILIENTOPS_CHAT_MODEL=gemini-3.5-flash
RESILIENTOPS_EVIDENCE_MODE=auto
```

Configure Application Default Credentials with your normal Google Cloud workflow. Start with `.venv/bin/resilientops --env-file .env serve`.

`agents/google_adk.py` constructs five `LlmAgent` nodes in the ADK 2.x graph workflow. Each role has one required domain-stage tool plus scoped read tools. ERP reads use MCP over local stdio, loading the incident's current validated snapshot on every read so that reconciled arrival/capacity changes are visible to later agents. There is a maximum of 40 orchestration model calls and a configurable overall 900-second analysis timeout. Model errors stop analysis; there is no silent deterministic fallback.

The Investigator's domain tool makes one additional structured Gemini request when active shipment messages exist. It returns cited entity/date/quantity fields, not executable action instructions. Source identity, exact quote spans, normalized dates/quantities, ERP capacity ceilings and cross-source conflicts are validated before any planning input changes. The extraction request has a 60-second HTTP timeout, one attempt, and a bounded output. The outer analysis timeout can leave a synchronous SDK thread finishing its request; ownership checks prevent it from saving superseded results.

The rest of the system calculates/optimizes those revised inputs. Final public ADK explanations are persisted separately for the dashboard. Thought parts and raw prompts are not persisted. Narrative explanations remain unverified prose; they never authorize actions.

## Live extraction evaluation

For a lower-overhead evaluation that isolates extraction rather than orchestration, keep `RESILIENTOPS_AGENT_MODE=local` and set `RESILIENTOPS_EVIDENCE_MODE=gemini`. Project, location, model and ADC are still required. Then run:

```sh
.venv/bin/resilientops --env-file .env evaluate --mode all
.venv/bin/resilientops --env-file .env demo --scenario natural-language
```

For the second command to validate the full five-node ADK integration, use `RESILIENTOPS_AGENT_MODE=google` in that environment. Record both results rather than assuming extraction success proves orchestration success.

If you want cost estimates, set `RESILIENTOPS_INPUT_USD_PER_MILLION` and `RESILIENTOPS_OUTPUT_USD_PER_MILLION` to verified prices for the selected model and pricing tier. No prices are guessed. The extraction record includes input, output and reported thought tokens. The estimate excludes ADK orchestration and infrastructure. Missing prices or failed-call usage are shown as unknown, not zero.

The SDK adapter uses structured output through [`google-genai`](https://googleapis.github.io/python-genai/) with a Pydantic response schema. Schema conformity and valid quote spans do not establish semantic correctness; the [evaluation](evaluation.md) and human evidence review remain necessary.

Business stages, approvals and actions are stored in Cloud SQL PostgreSQL when configured, with SQLite retained for local development. See [Cloud SQL setup and migration](cloud-sql.md). The ADK conversational session is scoped to one invocation and reconstructed on retry; it is not the durable business ledger. See [ADK workflows](https://adk.dev/workflows/) and [MCP tools](https://adk.dev/tools-custom/mcp-tools/).

## BigQuery synthetic ERP

Generate the source tables locally:

```sh
.venv/bin/python scripts/export_bigquery.py
```

The command writes five JSONL files under `var/bigquery/`. Provision tables using `scripts/bigquery_schema.sql`, replacing `PROJECT.DATASET`, and load the exports using your existing Google Cloud administrative workflow. This project does not automatically create datasets or overwrite remote tables.

Configure:

```dotenv
RESILIENTOPS_ERP_MODE=bigquery
RESILIENTOPS_BIGQUERY_DATASET=resilientops_demo
RESILIENTOPS_DB=/absolute/path/to/var/bigquery-simulation.db
```

Fixed queries import the scenario's inventory, recovery options, demand, supplier history and dependencies. Table identifiers are validated, scenario values use parameters, and queries have a maximum scan budget. Imported balances seed an isolated local simulated ledger once; subsequent simulated mutations do not write back to BigQuery. Use a new database path when starting a fresh imported simulation.

## Vertex embeddings and Vector Search

The demo documents are already small chunks. Use a streaming-update vector index with an embedding dimension matching your chosen model. Deploy it to an endpoint reachable by the application and configure:

```dotenv
RESILIENTOPS_KNOWLEDGE_MODE=vertex
RESILIENTOPS_EMBEDDING_MODEL=your-supported-text-embedding-model-id
RESILIENTOPS_INDEX_ENDPOINT=projects/PROJECT/locations/REGION/indexEndpoints/ENDPOINT
RESILIENTOPS_DEPLOYED_INDEX_ID=your-deployed-index-id
```

Explicitly ingest the fixture documents into an existing index:

```sh
.venv/bin/resilientops --env-file .env index-documents --index projects/PROJECT/locations/REGION/indexes/INDEX
```

This command makes embedding calls and writes index datapoints; it is an administrative operation, not part of normal agent execution. Datapoints carry active and supplier/global filters. Query and document embeddings must use the same model and dimensionality. The local manifest resolves retrieved chunk IDs and carries the original text and version. Missing chunks fail closed. Metadata filtering is not a replacement for a production tenant/document authorization service.

This implementation uses your existing Vector Search deployment directly; it does not add a second managed RAG product. Similarity scores depend on the configured metric, so production relevance thresholds must be validated against a representative retrieval evaluation set before deployment. Mandatory demo policy checks are applied after retrieval.

References: [text embeddings](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings), [Vector Search](https://cloud.google.com/vertex-ai/docs/vector-search/overview), [BigQuery](https://cloud.google.com/bigquery/docs/introduction).

## External event collectors

`.venv/bin/resilientops signals --latitude 22.54 --longitude 114.06` reads [NASA EONET](https://eonet.gsfc.nasa.gov/docs/v3) and [Open-Meteo](https://open-meteo.com/en/docs). It returns raw timestamped evidence and per-source availability. These sources are not treated as shipment-confirmation systems. USGS, news, a live Google Maps UI, and continuous geographic event correlation are outside the first runnable scenario.

## Res AI chat

The floating Res panel calls `POST /api/res/chat`. It uses the existing Google
session (same-origin writes), current incident data read from SQLite, and up to
three relevant local source documents. No execution tools are exposed to the
model. The last eight conversation messages are sent with each question and held
in browser memory; history resets for AI context when the selected incident changes.
Res displays connection/provider errors rather than substituting scripted replies.

Install the Google extras if absent: `.venv/bin/pip install -e '.[google]'`.
Set `RESILIENTOPS_CHAT_MODEL=gemini-2.5-flash` in `.env` (override for another model
available in your project). Choose one server-side credential method:

- Vertex AI: keep `GOOGLE_CLOUD_PROJECT=project-bceae5b1-7549-4f14-922`, enable
  Vertex AI for that project, and authenticate with Application Default Credentials
  using `gcloud auth application-default login`. The account needs Vertex AI access
  and the project needs billing. `GOOGLE_CLOUD_LOCATION` defaults to `us-central1`.
- Gemini API: store `GEMINI_API_KEY=your-key` in the local `.env`. This takes
  precedence over Vertex AI. Never put this key in JavaScript or commit it.

Restart `.venv/bin/resilientops --env-file .env serve --port 8000`. Open Res while
signed in and ask about a selected incident. `GET /api/res/status` checks whether
credentials are configured; only a successful chat verifies live model access.
Google browser OAuth client JSON is for login, not AI authentication.

Each question makes at most one generation request, with a 45-second provider
HTTP timeout, 2,048 output tokens, bounded context/history, and at most two
concurrent requests per process. No chat transcript is persisted by this app.
Provider retention/billing follow your Google account configuration. The supplied
incident context is synthetic, but user questions may contain user-entered text.

Implementation uses the [Google Gen AI SDK](https://googleapis.github.io/python-genai/).
