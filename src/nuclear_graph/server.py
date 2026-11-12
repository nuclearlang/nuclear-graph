"""The graph's HTTP API, on 127.0.0.1 only. Every route but `/v1/health` and the access request needs a token;
requests from a browser (with an `Origin` header) are refused, so a web page cannot reach it."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import __version__, secrets_store
from .access import Access
from .ingest import ingest
from .store import Store


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    collection: str = "knowledge"
    k: int = Field(5, ge=1, le=30)
    where: dict[str, Any] | None = None


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
        return {"status": "ok", "version": __version__}

    @app.post("/v1/search")
    async def search(body: SearchIn, client: str = Depends(needs("read"))) -> dict[str, Any]:
        try:
            items = await asyncio.to_thread(db().search, body.query, body.collection, body.k, body.where)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"items": items}

    @app.get("/v1/prompts/{use_case}")
    async def prompt(use_case: str, client: str = Depends(needs("read"))) -> dict[str, Any]:
        found = await asyncio.to_thread(db().get, "prompts", {"use_case": use_case})
        if not found:
            raise HTTPException(404, f"no prompt for '{use_case}'")
        return found[0]

    @app.post("/v1/documents")
    async def put(body: PutIn, client: str = Depends(needs("write"))) -> dict[str, Any]:
        if body.collection == "knowledge" and client != "owner":
            raise HTTPException(403, "only ingest writes the knowledge collection")
        meta = {**body.meta, "by": client, "source": body.meta.get("source", f"{client}:{body.id}")}
        try:
            await asyncio.to_thread(db().put, body.collection, [(body.id, body.text, meta)])
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"id": body.id}

    @app.delete("/v1/documents/{collection}/{doc_id}")
    async def delete(collection: str, doc_id: str, client: str = Depends(needs("write"))) -> dict[str, str]:
        await asyncio.to_thread(db().delete, collection, [doc_id])
        return {"deleted": doc_id}

    @app.get("/v1/stats")
    async def stats(client: str = Depends(needs("read"))) -> dict[str, Any]:
        return {"collections": await asyncio.to_thread(db().stats), "client": client}

    @app.post("/v1/ingest")
    async def run_ingest(body: IngestIn, client: str = Depends(needs("admin"))) -> dict[str, Any]:
        async with lock:
            lines: list[str] = []
            out = await asyncio.to_thread(ingest, db(), [Path(r) for r in body.roots], lines.append)
            return {**out, "log": lines[-200:]}

    @app.post("/v1/access")
    async def ask(body: AccessIn) -> dict[str, str]:
        try:
            return {"request": acc.ask(body.client, body.scopes, body.reason),
                    "hint": "the user allows it with: nuclear-graph allow <request>"}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/v1/access/{rid}")
    async def collect(rid: str) -> dict[str, Any]:
        try:
            return acc.collect(rid)
        except KeyError:
            raise HTTPException(404, "no such request")

    @app.get("/v1/access")
    async def requests(client: str = Depends(needs("admin"))) -> dict[str, Any]:
        return {"requests": acc.requests(), "clients": acc.clients()}

    @app.post("/v1/access/{rid}/{decision}")
    async def decide(rid: str, decision: str, client: str = Depends(needs("admin"))) -> dict[str, str]:
        if decision not in ("allow", "deny"):
            raise HTTPException(400, "allow or deny")
        try:
            acc.decide(rid, decision == "allow")
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"request": rid, "status": decision}

    return app
