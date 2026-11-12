"""The graph's store: Chroma collections whose documents are encrypted and whose vectors come from a local
embeddings model (Ollama). Only the server process opens it.

Collections:
- `knowledge`: the ecosystem's documentation, specs, dialect words, examples and CLI help (made by `ingest`);
- `examples`: validated task → solution pairs (the distillation of a frontier model; made by the evaluation);
- `prompts`: the validated prompt of each use case (feature, refactor, bug, docs...);
- `memory`: what an agent decided to keep about a project while working on it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

import chromadb
from chromadb.config import Settings

from . import paths, secrets_store
from .crypto import Box

COLLECTIONS = ("knowledge", "nuclear", "examples", "prompts", "memory")
EMBED_MODEL = os.environ.get("NUCLEAR_GRAPH_EMBED", "embeddinggemma")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

Embed = Callable[[Sequence[str], bool], list[list[float]]]


def ollama_embed(texts: Sequence[str], query: bool) -> list[list[float]]:
    """EmbeddingGemma's prompts: a query and a document are embedded differently."""
    import ollama

    client = ollama.Client(host=OLLAMA_URL)
    shaped = [f"task: search result | query: {t}" if query else f"title: none | text: {t}" for t in texts]
    out: list[list[float]] = []
    for i in range(0, len(shaped), 32):
        out.extend(client.embed(model=EMBED_MODEL, input=shaped[i : i + 32]).embeddings)
    return [list(v) for v in out]


class Store:
    def __init__(self, path: str | None = None, key: bytes | None = None, embed: Embed = ollama_embed) -> None:
        self._client = chromadb.PersistentClient(
            path=path or str(paths.db()), settings=Settings(anonymized_telemetry=False, allow_reset=False)
        )
        self._box = Box(key or secrets_store.key())
        self._embed = embed
        self._cols = {
            name: self._client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"}, embedding_function=None)
            for name in COLLECTIONS
        }

    def _col(self, name: str) -> Any:
        if name not in self._cols:
            raise KeyError(f"unknown collection '{name}' (collections: {', '.join(COLLECTIONS)})")
        return self._cols[name]

    def hashes(self, collection: str, source: str) -> dict[str, str]:
        """id → content hash of the chunks of a source (to skip what did not change)."""
        got = self._col(collection).get(where={"source": source}, include=["metadatas"])
        return {i: str(m.get("hash", "")) for i, m in zip(got["ids"], got["metadatas"] or [])}

    def put(self, collection: str, items: Sequence[tuple[str, str, dict[str, Any]]]) -> int:
        """Adds or replaces (id, text, metadata) items; the text is embedded, then stored encrypted."""
        if not items:
            return 0
        ids = [i for i, _, _ in items]
        texts = [t for _, t, _ in items]
        metas = [{k: v for k, v in m.items() if isinstance(v, (str, int, float, bool))} for _, _, m in items]
        vectors = self._embed(texts, False)
        self._col(collection).upsert(
            ids=ids, embeddings=vectors, documents=[self._box.seal(t) for t in texts], metadatas=metas
        )
        return len(ids)

    def delete(self, collection: str, ids: Sequence[str]) -> None:
        if ids:
            self._col(collection).delete(ids=list(ids))

    def search(
        self, query: str, collection: str = "knowledge", k: int = 5, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """The `k` closest items: id, text, metadata and distance (0 is the same meaning)."""
        col = self._col(collection)
        if col.count() == 0:
            return []
        got = col.query(
            query_embeddings=self._embed([query], True),
            n_results=min(k, col.count()),
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        out = []
        for i, doc, meta, dist in zip(got["ids"][0], got["documents"][0], got["metadatas"][0], got["distances"][0]):
            out.append({"id": i, "text": self._box.open(doc), "meta": meta, "distance": round(float(dist), 4)})
        return out

    def get(self, collection: str, where: dict[str, Any]) -> list[dict[str, Any]]:
        got = self._col(collection).get(where=where, include=["documents", "metadatas"])
        return [
            {"id": i, "text": self._box.open(d), "meta": m}
            for i, d, m in zip(got["ids"], got["documents"] or [], got["metadatas"] or [])
        ]

    def stats(self) -> dict[str, int]:
        return {name: col.count() for name, col in self._cols.items()}
