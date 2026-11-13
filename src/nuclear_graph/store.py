"""The graph's store: one Chroma collection per shelf (ADR-0104), whose documents are encrypted and whose vectors
come from a local embeddings model (Ollama). Only the server process opens it.

A row's metadata is in clear (ids, names, keys, filters: what Chroma searches by); its text is sealed. The shelves of
the knowledge base are made by `ingest`; `prompts` holds the prompt files of this package and `memory` what an agent
decided to keep about a project while working on it."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

import chromadb
from chromadb.config import Settings

from . import paths, secrets_store
from .crypto import Box
from .shelves import COLLECTIONS, LEGACY, SHELVES

EMBED_MODEL = os.environ.get("NUCLEAR_GRAPH_EMBED", "embeddinggemma")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# The texts to embed, already shaped for the model (see `as_document` and `as_query`).
Embed = Callable[[Sequence[str]], list[list[float]]]
Item = dict[str, Any]  # {id, document, meta}; when what is embedded is not the document, {title, embed}; a question: {query}


def as_document(title: str, text: str) -> str:
    """EmbeddingGemma's prompt of a document: its title, then its text."""
    return f"title: {title or 'none'} | text: {text}"


def as_query(text: str) -> str:
    """EmbeddingGemma's prompt of a search."""
    return f"task: search result | query: {text}"


def ollama_embed(shaped: Sequence[str]) -> list[list[float]]:
    import ollama

    client = ollama.Client(host=OLLAMA_URL)
    out: list[list[float]] = []
    for i in range(0, len(shaped), 32):
        out.extend(client.embed(model=EMBED_MODEL, input=list(shaped[i : i + 32])).embeddings)
    return [list(v) for v in out]


def _storable(meta: dict[str, Any]) -> dict[str, Any]:
    """What Chroma keeps as metadata: texts, numbers, booleans and lists of texts that are not empty."""
    return {k: v for k, v in meta.items()
            if isinstance(v, (str, int, float, bool)) or (isinstance(v, list) and v and all(isinstance(x, str) for x in v))}


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

    # ---- writing ----

    def put(self, collection: str, items: Sequence[Item | tuple[str, str, dict[str, Any]]]) -> int:
        """Adds or replaces items. Each is {id, document, meta} (a tuple `(id, text, meta)` is the same); what is
        embedded is `embed` under `title` when given, else the document; with `query`, `embed` is embedded as a search
        is (a question a row answers). The document is stored encrypted."""
        rows = [i if isinstance(i, dict) else {"id": i[0], "document": i[1], "meta": i[2]} for i in items]
        if not rows:
            return 0
        shaped = [as_query(r["embed"]) if r.get("query") else
                  as_document(str(r.get("title") or r["meta"].get("title") or ""), r.get("embed") or r["document"]) for r in rows]
        self._col(collection).upsert(
            ids=[r["id"] for r in rows], embeddings=self._embed(shaped),
            documents=[self._box.seal(r["document"]) for r in rows], metadatas=[_storable(r["meta"]) for r in rows],
        )
        return len(rows)

    def delete(self, collection: str, ids: Sequence[str]) -> None:
        if ids:
            self._col(collection).delete(ids=list(ids))

    def drop_legacy(self) -> list[str]:
        """Removes the collections of before the shelves (ADR-0104)."""
        gone = []
        for name in LEGACY:
            try:
                self._client.delete_collection(name)
                gone.append(name)
            except Exception:  # noqa: BLE001 - it was not there
                pass
        return gone

    # ---- versions ----

    def version(self) -> dict[str, int]:
        """The schema and the revision of the knowledge base this store holds (0: never ingested)."""
        meta = self._client.get_collection(next(iter(SHELVES))).metadata or {}
        return {"schema": int(meta.get("schema", 0)), "revision": int(meta.get("revision", 0))}

    def set_version(self, schema: int, revision: int) -> None:
        for name in SHELVES:
            self._col(name).modify(metadata={"schema": schema, "revision": revision})

    # ---- reading ----

    def hashes(self, collection: str, where: dict[str, Any] | None = None) -> dict[str, str]:
        """id → content hash of the items of a collection (to embed again only what changed)."""
        got = self._col(collection).get(where=where, include=["metadatas"])
        return {i: str(m.get("hash", "")) for i, m in zip(got["ids"], got["metadatas"] or [])}

    def embed_query(self, query: str) -> list[float]:
        return self._embed([as_query(query)])[0]

    def near(self, collection: str, vector: list[float], k: int, where: dict[str, Any] | None = None,
             ids: list[str] | None = None) -> list[dict[str, Any]]:
        """The `k` items closest to a vector: id, metadata and distance (0 is the same meaning), without their text."""
        col = self._col(collection)
        count = col.count()
        if count == 0 or ids == []:
            return []
        got = col.query(query_embeddings=[vector], n_results=min(k, count), where=where or None, ids=ids, include=["metadatas", "distances"])
        return [{"id": i, "meta": m, "distance": round(float(d), 4)} for i, m, d in zip(got["ids"][0], got["metadatas"][0], got["distances"][0])]

    def where(self, collection: str, where: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
        """The items a filter matches: id and metadata."""
        got = self._col(collection).get(where=where, limit=limit, include=["metadatas"])
        return [{"id": i, "meta": m} for i, m in zip(got["ids"], got["metadatas"] or [])]

    def documents(self, collection: str, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """id → {text, meta} of the items with these ids (the ones that exist)."""
        if not ids:
            return {}
        got = self._col(collection).get(ids=list(dict.fromkeys(ids)), include=["documents", "metadatas"])
        return {i: {"text": self._box.open(d), "meta": m} for i, d, m in zip(got["ids"], got["documents"] or [], got["metadatas"] or [])}

    def get(self, collection: str, where: dict[str, Any]) -> list[dict[str, Any]]:
        got = self._col(collection).get(where=where, include=["documents", "metadatas"])
        return [
            {"id": i, "text": self._box.open(d), "meta": m}
            for i, d, m in zip(got["ids"], got["documents"] or [], got["metadatas"] or [])
        ]

    def stats(self) -> dict[str, int]:
        return {name: col.count() for name, col in self._cols.items()}
