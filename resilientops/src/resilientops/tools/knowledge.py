"""Offline lexical retrieval, explicitly distinguished from cloud vector retrieval."""

import re
from typing import Protocol

from resilientops.models import Document


class Knowledge(Protocol):
    def search(self, query: str, supplier_id: str, top_k: int = 5) -> list[Document]: ...


class LocalKnowledge:
    def __init__(self, documents: list[Document]):
        self.documents = documents

    def search(self, query: str, supplier_id: str, top_k: int = 5) -> list[Document]:
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        if not terms:
            return []
        ranked = []
        for doc in self.documents:
            if not doc.active or doc.supplier_id not in {None, supplier_id}:
                continue
            tokens = set(re.findall(r"[a-z0-9]+", (doc.title + " " + doc.text).lower()))
            relevance = len(terms & tokens) / len(terms)
            if relevance >= 0.15:
                ranked.append((relevance, doc.id, doc))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [row[2] for row in ranked[: max(0, min(top_k, 20))]]
