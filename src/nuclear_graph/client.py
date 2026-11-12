"""The client of the graph for other programs (the local agents, the MCP server). Its token comes from
`NUCLEAR_GRAPH_TOKEN` or from the keyring entry `nuclear-graph connect <client>` stored. Answers are plain text,
shaped to be put in a prompt."""

from __future__ import annotations

import os
from typing import Any

import httpx

from . import paths, secrets_store


def token_of(client: str) -> str:
    token = os.environ.get("NUCLEAR_GRAPH_TOKEN") or secrets_store._keyring_get(f"client:{client}")
    if not token:
        f = paths.home() / f".client-{client}"
        token = f.read_text().strip() if f.is_file() else ""
    if not token:
        raise PermissionError(
            f"'{client}' has no access to the Nuclear Smart Graph: run `nuclear-graph connect {client}` and allow it"
        )
    return token


class GraphClient:
    """Reads and writes the Nuclear Smart Graph."""

    def __init__(self, client: str = "nuclear-developer", url: str = "") -> None:
        self.client = client
        self.url = url or paths.URL

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(base_url=self.url, timeout=120) as http:
            r = await http.request(method, path, json=body, headers={"Authorization": f"Bearer {token_of(self.client)}"})
            if r.status_code >= 400:
                raise RuntimeError(f"graph {path}: {r.status_code} {r.text}")
            return r.json()

    async def items(self, query: str, collection: str = "knowledge", k: int = 5, dialect: str = "",
                    kind: str = "", platform: str = "") -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        filters: list[dict[str, Any]] = [{"dialect": {"$in": [dialect, ""]}}] if dialect else []
        if platform:
            filters.append({"platform": {"$in": [platform, ""]}})
        if kind:
            filters.append({"kind": kind})
        if len(filters) == 1:
            where = filters[0]
        elif filters:
            where = {"$and": filters}
        out = await self._call("POST", "/v1/search", {"query": query, "collection": collection, "k": k, "where": where or None})
        return out["items"]

    async def search(self, query: str, collection: str = "knowledge", k: int = 5, dialect: str = "", kind: str = "",
                     platform: str = "") -> str:
        """The closest pieces of knowledge, as one text for a prompt. A local agent reads the `nuclear` collection
        by `platform`: Nuclear and Dragonfly only, nothing of a target language."""
        found = await self.items(query, collection, k, dialect, kind, platform)
        return "\n\n---\n\n".join(i["text"] for i in found)

    async def examples(self, task: str, dialect: str = "", k: int = 2, platform: str = "") -> str:
        """Solved tasks closest to `task` (validated answers of a frontier model)."""
        found = await self.items(task, "examples", k, dialect, platform=platform)
        return "\n\n---\n\n".join(i["text"] for i in found)

    async def prompt(self, use_case: str) -> str:
        """The validated prompt of a use case (feature, refactor, bug, docs, diagram, test, security, piece)."""
        return (await self._call("GET", f"/v1/prompts/{use_case}"))["text"]

    async def remember(self, id: str, text: str, collection: str = "memory", project: str = "", kind: str = "note") -> str:
        """Keeps a piece of knowledge about a project (or a solved example) for later."""
        meta = {"project": project, "kind": kind}
        return (await self._call("POST", "/v1/documents", {"collection": collection, "id": id, "text": text, "meta": meta}))["id"]

    async def stats(self) -> dict[str, Any]:
        return await self._call("GET", "/v1/stats")
