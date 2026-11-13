"""The client of the graph for other programs (the local agents, the MCP server). Its token comes from
`NUCLEAR_GRAPH_TOKEN` or from the keyring entry `nuclear-graph connect <client>` stored. Answers are plain text,
shaped to be put in a prompt."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from . import paths, secrets_store
from .assets import as_text


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

    async def items(self, query: str, shelves: str = "", k: int = 5, platform: str = "", kind: str = "", type: str = "",
                    agents: bool = False, expand: bool = False, kinds: str = "") -> list[dict[str, Any]]:
        """The cards that answer a query. `shelves`: one shelf or several separated by commas ("" = every shelf of
        the knowledge base). `kind` and `type` filter by those fields of a row; `kinds` keeps the rows that apply to
        a kind (the pitfalls of `usecase`)."""
        where = {key: value for key, value in (("kind", kind), ("type", type), ("kinds", kinds)) if value}
        body = {"query": query, "shelves": [s.strip() for s in shelves.split(",") if s.strip()] or None, "k": k, "platform": platform,
                "agents": agents, "where": where or None, "expand": expand}
        return (await self._call("POST", "/v1/search", body))["items"]

    async def search(self, query: str, shelves: str = "", k: int = 5, platform: str = "", kind: str = "", type: str = "",
                     agents: bool = False, expand: bool = False, kinds: str = "") -> str:
        """The closest pieces of knowledge, as one text for a prompt. A local agent searches with `agents = true` and
        its `platform`: Nuclear and Dragonfly only, nothing of a target language."""
        return as_text(await self.items(query, shelves, k, platform, kind, type, agents, expand, kinds))

    async def examples(self, task: str, platform: str = "", k: int = 2, kind: str = "", type: str = "") -> str:
        """Validated Nuclear closest to `task`: files of the example projects (`type = "file"`), solved tasks
        (`type = "solved"`) or both; `kind` keeps one kind (usecase, repository...)."""
        return as_text(await self.items(task, "examples", k, platform, kind, type, True))

    async def pitfalls(self, task: str, kind: str, platform: str = "", full: int = 2) -> str:
        """The mistakes small models repeat with a kind, all of them: the `full` closest to the task as whole cards
        (the right shape to copy), the others in one line each (the rule)."""
        found = await self.items(task, "errors", 12, platform, type="pitfall", agents=True, kinds=kind)
        rules = [f"- {i['card']['summary']}" for i in found[full:] if i.get("card")]
        return as_text(found[:full]) + ("\n\n---\n\nAlso with this kind:\n\n" + "\n".join(rules) if rules else "")

    async def card(self, id: str, related: bool = True) -> str:
        """One row of the knowledge base by its id (`error:N0114`, `kind:backend.usecase`), with a line for each row
        it links to (`related`); "" when there is no such row."""
        try:
            found = await self._call("GET", f"/v1/cards/{quote(id, safe=':')}")
        except RuntimeError:
            return ""
        return as_text([found if related else {k: v for k, v in found.items() if k != "related"}])

    async def brief(self, id: str) -> str:
        """A row in one line: `title — summary (`id`)`; "" when there is no such row."""
        try:
            card = (await self._call("GET", f"/v1/cards/{quote(id, safe=':')}")).get("card") or {}
        except RuntimeError:
            return ""
        return f"{card.get('title', id)} — {card.get('summary', '')} (`{id}`)"

    async def applies(self, text: str, platform: str = "") -> list[str]:
        """What of a spec or a task the platform cannot do yet, limits, or was never run for real (the capabilities
        rows whose trigger words the text writes), one line each: `title — summary (`id`, because it says "word")`."""
        found = (await self._call("POST", "/v1/applies", {"text": text[:40000], "platform": platform}))["items"]
        return [f"{i['title']} — {i['summary']} (`{i['id']}`, because it says \"{i['trigger']}\")" for i in found]

    async def strategy(self, text: str, platform: str = "", existing: list[str] | None = None, new: list[str] | None = None,
                       runnable: bool = False, only: str = "") -> dict[str, str]:
        """The strategy of a request (which kind of request it is, and the plan of that kind), each field a text:
        `id`, `title`, `summary`, `why` (the signs that chose it), `plan` (the card), `mode` (write, repair, verify,
        review, answer, commands, lead), `stages` (the Loop's stages it runs) and `generators`, separated by commas,
        `pieces` (where its pieces come from: plan, declaring, naming, none), `lead` (local or frontier), `needs`
        (the facts it cannot start without, one `name=question` per line) and `second` (the next closest).
        `existing` and `new`: the declarations the request names that the project has, and the ones it has not.
        `runnable`: for a run of the Loop. `only`: the strategy the request itself names. {} when the graph has no
        strategy."""
        body = {"text": text[:40000], "platform": platform, "existing": existing, "new": new, "runnable": runnable, "only": only}
        found = (await self._call("POST", "/v1/strategy", body))["items"]
        if not found:
            return {}
        best, data = found[0], found[0]["data"]
        return {"id": best["id"], "title": best["title"], "summary": best["summary"], "why": best["why"], "plan": best["text"],
                "mode": str(data.get("mode", "write")), "stages": ",".join(data.get("stages", [])),
                "generators": ",".join(data.get("generators", [])), "pieces": str(data.get("pieces", "plan")),
                "lead": str(data.get("lead", "local")), "needs": "\n".join(f"{k}={v}" for k, v in (data.get("needs") or {}).items()),
                "second": found[1]["id"] if len(found) > 1 else ""}

    async def kinds(self, platform: str) -> dict[str, str]:
        """Every way a kind of the platform is written, in lower case, and the kind it means: `use case` → `usecase`,
        `application component` → `appcomponent`, `usecase` → `usecase`."""
        return await self._call("GET", f"/v1/kinds/{platform}")

    async def prompt(self, use_case: str) -> str:
        """The validated prompt of a use case (feature, refactor, bug, docs, diagram, test, security, piece)."""
        return (await self._call("GET", f"/v1/prompts/{use_case}"))["text"]

    async def remember(self, id: str, text: str, collection: str = "memory", project: str = "", kind: str = "note",
                       platform: str = "") -> str:
        """Keeps a piece of knowledge about a project (`memory`) or a solved example (`examples`) for later."""
        meta = {"project": project, "kind": kind, "platform": platform}
        return (await self._call("POST", "/v1/documents", {"collection": collection, "id": id, "text": text, "meta": meta}))["id"]

    async def stats(self) -> dict[str, Any]:
        return await self._call("GET", "/v1/stats")
