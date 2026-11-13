"""The graph's HTTP API, on 127.0.0.1 only. Every route but `/v1/health` and the access request needs a token;
requests from a browser (with an `Origin` header) are refused, so a web page cannot reach it."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import __version__, retrieve, secrets_store
from .access import Access
from .ingest import ingest
from .shelves import COLLECTIONS, SHELVES
from .store import Store


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    # one collection, or "" for every shelf of the knowledge base
    collection: str = ""
    # several shelves (instead of `collection`)
    shelves: list[str] | None = None
    k: int = Field(5, ge=1, le=30)
    # backend, mobile or web: the rows of that platform and the ones of every platform
    platform: str = ""
    # true: only what a local agent may read (Nuclear only)
    agents: bool = False
    # more filters by metadata: {"type": "kind"}, {"kind": "usecase"}, {"code": "N0114"}
    where: dict[str, Any] | None = None
    # true: each card comes with the title and summary of the rows it links to
    expand: bool = False


class AppliesIn(BaseModel):
    text: str = Field(min_length=1, max_length=40000)
    platform: str = ""


class StrategyIn(BaseModel):
    text: str = Field(min_length=1, max_length=40000)
    platform: str = ""
    # the declarations the request names that the project has, and the ones it has not (None: no project was read)
    existing: list[str] | None = None
    new: list[str] | None = None
    # the caller is a run of the Loop: a strategy without stages comes first only when an exact sign chose it
    runnable: bool = False
    # the strategy the request itself names, when it names one
    only: str = ""


class PutIn(BaseModel):
    collection: str = "memory"
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=40000)
    meta: dict[str, Any] = {}


class AccessIn(BaseModel):
    client: str
    scopes: list[str] = ["read"]
    reason: str = ""


class IngestIn(BaseModel):
    roots: list[str]


def create_app(store: Store | None = None, access: Access | None = None, owner: str | None = None) -> FastAPI:
    app = FastAPI(title="Nuclear Smart Graph", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    state: dict[str, Any] = {"store": store}
    acc = access or Access()
    owner_token = owner if owner is not None else secrets_store.owner_token()
    lock = asyncio.Lock()

    def db() -> Store:
        if state["store"] is None:
            state["store"] = Store()
        return state["store"]

    @app.middleware("http")
    async def no_browsers(request: Request, call_next):
        if request.headers.get("origin"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "browsers cannot use the graph"}, status_code=403)
        return await call_next(request)

    def needs(scope: str):
        def check(request: Request) -> str:
            auth = request.headers.get("authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            who = acc.who(token, owner_token) if token else None
            if who is None:
                raise HTTPException(401, "a token is needed: ask for access (POST /v1/access) and let the user allow it")
            if scope not in who[1]:
                raise HTTPException(403, f"client '{who[0]}' has no '{scope}' scope")
            return who[0]

        return check

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        """Whether the graph is running, and its version. Needs no token."""
        return {"status": "ok", "version": __version__}

    @app.post("/v1/search")
    async def search(body: SearchIn, client: str = Depends(needs("read"))) -> dict[str, Any]:
        """Searches the graph by meaning and by exact name: `{query, collection | shelves, k, platform, agents, where,
        expand}` answers `{items: [{id, shelf, text, meta, distance, score, via, card, related}]}`. Without a
        collection it searches every shelf of the knowledge base."""
        shelves = body.shelves or ([body.collection] if body.collection else list(SHELVES))
        if bad := [s for s in shelves if s not in COLLECTIONS]:
            raise HTTPException(404, f"unknown collection {bad} (collections: {', '.join(COLLECTIONS)})")
        items = await asyncio.to_thread(retrieve.search, db(), body.query, shelves, body.k, body.platform, body.agents, body.where, body.expand)
        return {"items": items}

    @app.get("/v1/cards/{card_id:path}")
    async def card(card_id: str, client: str = Depends(needs("read"))) -> dict[str, Any]:
        """One row of the knowledge base by its id (`error:N0114`, `kind:backend.usecase`, `tool:dragonfly.gen.resource`),
        with the title and summary of the rows it links to."""
        found = await asyncio.to_thread(retrieve.card, db(), card_id)
        if found is None:
            raise HTTPException(404, f"no row `{card_id}`")
        return found

    @app.post("/v1/applies")
    async def applies(body: AppliesIn, client: str = Depends(needs("read"))) -> dict[str, Any]:
        """What of a spec or a task is not possible yet or was never run for real: the capabilities rows whose
        `triggers` the text writes, for its platform: `{text, platform}` answers `{items: [{id, type, title, summary,
        trigger}]}`. Exact, never by meaning."""
        return {"items": await asyncio.to_thread(retrieve.applies, db(), body.text, body.platform)}

    @app.post("/v1/strategy")
    async def strategy(body: StrategyIn, client: str = Depends(needs("read"))) -> dict[str, Any]:
        """The strategy of a request: which kind of request it is (a whole system, one screen, a rename, a failing
        test...) and the plan of that kind. `{text, platform, existing, new}` answers `{items: [{id, title, summary,
        score, why, data, text}]}`, best first, at most three. By the request's exact signs first, then by meaning."""
        return {"items": await asyncio.to_thread(retrieve.strategy, db(), body.text, body.platform, body.existing, body.new, body.runnable, body.only)}

    @app.get("/v1/kinds/{platform}")
    async def kinds(platform: str, client: str = Depends(needs("read"))) -> dict[str, str]:
        """Every way a kind of a platform is written (its own word and how people say it: `use case`, `application
        component`) with the kind it means: what a planner needs to read a spec."""
        rows = await asyncio.to_thread(db().where, "platforms", retrieve.scope(platform, False, {"type": "kind"}))
        return {key: str(r["meta"].get("kind", "")) for r in rows if r["meta"].get("facet") == "card" for key in r["meta"].get("keys", [])}

    @app.get("/v1/prompts/{use_case}")
    async def prompt(use_case: str, client: str = Depends(needs("read"))) -> dict[str, Any]:
        """The prompt file of a use case (`feature`, `piece`, `test`...) or of an agent's step (`agent.repair`)."""
        found = await asyncio.to_thread(db().get, "prompts", {"use_case": use_case})
        if not found:
            raise HTTPException(404, f"no prompt for '{use_case}'")
        return found[0]

    @app.post("/v1/documents")
    async def put(body: PutIn, client: str = Depends(needs("write"))) -> dict[str, Any]:
        """Keeps what an agent learned at run time: a note about a project (`memory`) or a solved example
        (`examples`). The rows of the knowledge base are written only by ingest; these survive it."""
        if body.collection not in ("memory", "examples") and client != "owner":
            raise HTTPException(403, "an agent writes only `memory` and `examples`; the knowledge base is made by ingest")
        platform = str(body.meta.get("platform") or "")
        meta = {"card": body.id, "facet": "card", "type": str(body.meta.get("kind") or "note"), "title": body.id, "agents": True,
                "platforms": [platform or "all"], **body.meta, "by": client, "origin": "runtime",
                "source": body.meta.get("source", f"{client}:{body.id}")}
        try:
            await asyncio.to_thread(db().put, body.collection, [(body.id, body.text, meta)])
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"id": body.id}

    @app.delete("/v1/documents/{collection}/{doc_id}")
    async def delete(collection: str, doc_id: str, client: str = Depends(needs("write"))) -> dict[str, str]:
        """Removes what an agent kept at run time (`memory`, `examples`)."""
        if collection not in ("memory", "examples") and client != "owner":
            raise HTTPException(403, "an agent removes only what agents wrote: `memory` and `examples`")
        await asyncio.to_thread(db().delete, collection, [doc_id])
        return {"deleted": doc_id}

    @app.get("/v1/stats")
    async def stats(client: str = Depends(needs("read"))) -> dict[str, Any]:
        """The rows of each collection, and the schema and revision of the knowledge base the graph holds."""
        return {"collections": await asyncio.to_thread(db().stats), "knowledge": await asyncio.to_thread(db().version), "client": client}

    @app.post("/v1/ingest")
    async def run_ingest(body: IngestIn, client: str = Depends(needs("admin"))) -> dict[str, Any]:
        """Makes the knowledge base folder `roots[0]` what the graph knows; only what changed is embedded again."""
        async with lock:
            lines: list[str] = []
            try:
                out = await asyncio.to_thread(ingest, db(), Path(body.roots[0]), lines.append)
            except (ValueError, IndexError) as e:
                raise HTTPException(400, str(e))
            return {**out, "log": lines[-200:]}

    @app.post("/v1/access")
    async def ask(body: AccessIn) -> dict[str, str]:
        """A program asks for access with the scopes it needs; nothing is given until the user allows the request."""
        try:
            return {"request": acc.ask(body.client, body.scopes, body.reason),
                    "hint": "the user allows it with: nuclear-graph allow <request>"}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/v1/access/{rid}")
    async def collect(rid: str) -> dict[str, Any]:
        """The state of an access request; once allowed, its token, a single time."""
        try:
            return acc.collect(rid)
        except KeyError:
            raise HTTPException(404, "no such request")

    @app.get("/v1/access")
    async def requests(client: str = Depends(needs("admin"))) -> dict[str, Any]:
        """The pending access requests and the allowed clients."""
        return {"requests": acc.requests(), "clients": acc.clients()}

    @app.post("/v1/access/{rid}/{decision}")
    async def decide(rid: str, decision: str, client: str = Depends(needs("admin"))) -> dict[str, str]:
        """Allows or denies an access request (`allow` or `deny`)."""
        if decision not in ("allow", "deny"):
            raise HTTPException(400, "allow or deny")
        try:
            acc.decide(rid, decision == "allow")
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"request": rid, "status": decision}

    return app
