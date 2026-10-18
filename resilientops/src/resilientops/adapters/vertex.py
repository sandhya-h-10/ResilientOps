"""Embedding and vector retrieval adapter; chunk content stays in a versioned manifest."""

from resilientops.config import Settings
from resilientops.models import Document, DomainError


class VertexKnowledge:
    def __init__(self, settings: Settings, documents: list[Document]):
        from google import genai
        from google.cloud import aiplatform

        self.settings = settings
        self.documents = {f"{doc.id}-v{doc.version}": doc for doc in documents}
        self.client = genai.Client(
            vertexai=True, project=settings.project, location=settings.location
        )
        self.endpoint = aiplatform.MatchingEngineIndexEndpoint(
            index_endpoint_name=settings.index_endpoint,
            project=settings.project,
            location=settings.location,
        )

    def embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        response = self.client.models.embed_content(
            model=self.settings.embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(task_type=task_type),
        )
        return [item.values for item in response.embeddings]

    def search(self, query: str, supplier_id: str, top_k: int = 5) -> list[Document]:
        from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import Namespace

        vector = self.embed([query], "RETRIEVAL_QUERY")[0]
        neighbors = self.endpoint.find_neighbors(
            deployed_index_id=self.settings.deployed_index_id,
            queries=[vector],
            num_neighbors=max(1, min(top_k, 20)),
            filter=[Namespace("active", ["true"]), Namespace("supplier", [supplier_id, "GLOBAL"])],
        )[0]
        results = []
        for match in neighbors:
            doc = self.documents.get(match.id)
            if doc is None:
                raise DomainError("Vector index references a missing manifest chunk")
            if doc.active and doc.supplier_id in {None, supplier_id}:
                # Similarity alone does not establish truth; the same policy and evidence gates still run.
                results.append(doc)
        return results


def index_documents(settings: Settings, documents: list[Document], index_name: str):
    """Explicit administrator operation for an existing streaming-update index."""
    from google import genai
    from google.cloud import aiplatform
    from google.cloud.aiplatform_v1.types import IndexDatapoint
    from google.genai import types

    client = genai.Client(vertexai=True, project=settings.project, location=settings.location)
    index = aiplatform.MatchingEngineIndex(
        index_name=index_name, project=settings.project, location=settings.location
    )
    points = []
    for doc in documents:
        response = client.models.embed_content(
            model=settings.embedding_model,
            contents=f"{doc.title}\n{doc.text}",
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        points.append(
            IndexDatapoint(
                datapoint_id=f"{doc.id}-v{doc.version}",
                feature_vector=response.embeddings[0].values,
                restricts=[
                    IndexDatapoint.Restriction(
                        namespace="active", allow_list=[str(doc.active).lower()]
                    ),
                    IndexDatapoint.Restriction(
                        namespace="supplier", allow_list=[doc.supplier_id or "GLOBAL"]
                    ),
                ],
            )
        )
    index.upsert_datapoints(datapoints=points)
