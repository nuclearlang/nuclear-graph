import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["NUCLEAR_GRAPH_NO_KEYRING"] = "1"

from nuclear_graph.access import Access  # noqa: E402
from nuclear_graph import assets  # noqa: E402
from nuclear_graph.server import create_app  # noqa: E402
from nuclear_graph.store import Store  # noqa: E402
from nuclear_graph.toolchain import diagnostics_of, describe, strip_fences  # noqa: E402


def fake_embed(texts):
    """A bag of words hashed into 64 dimensions: enough for closest-match tests without a model. The model's prompt
    words (`title:`, `text:`, `task:`, `query:`) are left out, so a question and a text with its words are close."""
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().replace("|", " ").split():
            if w not in ("title:", "text:", "task:", "query:", "search", "result", "none"):
                v[int(hashlib.md5(w.strip(".,?`'").encode()).hexdigest(), 16) % 64] += 1.0
        out.append(v)
    return out


def row(rid, **fields):
    """A valid row with the least to write."""
    return {"id": rid, "type": fields.pop("type", "diagnostic"), "title": fields.pop("title", rid), "summary": fields.pop("summary", "A summary."),
            "body": fields.pop("body", "A body."), **fields}


def shelve(store, shelf, *rows):
    for r in rows:
        store.put(shelf, assets.facets(r, shelf, "generated"))


@pytest.fixture
def env(tmp_path: Path):
    os.environ["NUCLEAR_GRAPH_HOME"] = str(tmp_path)
    store = Store(str(tmp_path / "db"), key=b"k" * 32, embed=fake_embed)
    access = Access(tmp_path / "grants.json")
    app = create_app(store, access, owner="owner-token")
    return TestClient(app), store, access, tmp_path


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_nothing_without_a_token_and_no_browsers(env):
    http, *_ = env
    assert http.get("/v1/health").status_code == 200
    assert http.post("/v1/search", json={"query": "x"}).status_code == 401
    assert http.post("/v1/search", json={"query": "x"}, headers=auth("guess")).status_code == 401
    browser = {**auth("owner-token"), "Origin": "https://evil.example"}
    assert http.post("/v1/search", json={"query": "x"}, headers=browser).status_code == 403


def test_a_program_gets_access_only_when_the_user_allows_it(env):
    http, _, access, _ = env
    rid = http.post("/v1/access", json={"client": "tool", "scopes": ["read"]}).json()["request"]
    assert http.get(f"/v1/access/{rid}").json()["status"] == "pending"
    assert http.post("/v1/access", json={"client": "tool", "scopes": ["admin"]}).status_code == 400
    access.decide(rid, True)
    first = http.get(f"/v1/access/{rid}").json()
    assert first["status"] == "allowed" and first["token"].startswith("ng_")
    assert "token" not in http.get(f"/v1/access/{rid}").json()  # handed once
    token = first["token"]
    assert http.post("/v1/search", json={"query": "x"}, headers=auth(token)).status_code == 200
    put = {"collection": "memory", "id": "a", "text": "hi"}
    assert http.post("/v1/documents", json=put, headers=auth(token)).status_code == 403  # read only
    grants = (env[3] / "grants.json").read_text()
    assert '"hash"' in grants and token not in grants  # only its hash is kept
    access.revoke("tool")
    assert http.post("/v1/search", json={"query": "x"}, headers=auth(token)).status_code == 401


def test_documents_are_encrypted_at_rest_and_found_by_meaning(env):
    http, store, _, tmp = env
    store.put("docs", [("1", "a repository builds one query per method", {"source": "s", "type": "spec"}),
                       ("2", "the device panel streams frames", {"source": "t", "type": "doc"})])
    got = http.post("/v1/search", json={"query": "repository query", "collection": "docs", "k": 1}, headers=auth("owner-token")).json()
    assert got["items"][0]["id"] == "1" and got["items"][0]["text"].startswith("a repository")
    raw = b"".join(p.read_bytes() for p in Path(tmp, "db").rglob("*") if p.is_file())
    assert b"repository builds" not in raw


def test_an_agent_writes_only_memory_and_examples(env):
    http, _, access, _ = env
    token = access.grant("agent", ["read", "write"])
    body = {"collection": "concepts", "id": "concept:x", "text": "lies"}
    assert http.post("/v1/documents", json=body, headers=auth(token)).status_code == 403
    assert http.delete("/v1/documents/errors/error:N0114", headers=auth(token)).status_code == 403
    body["collection"] = "memory"
    assert http.post("/v1/documents", json=body, headers=auth(token)).status_code == 200
    kept = http.post("/v1/search", json={"query": "lies", "collection": "memory", "agents": True}, headers=auth(token)).json()["items"]
    assert kept[0]["meta"]["origin"] == "runtime" and kept[0]["meta"]["by"] == "agent"


def test_a_row_is_found_by_the_exact_name_it_carries(env):
    http, store, *_ = env
    shelve(store, "errors",
           row("error:N0114", title="not a member of the library", summary="A name of another language.", keys=["n0114"]),
           row("error:N0011", title="invalid escape sequence", summary="A backslash before a letter that is no escape.", keys=["n0011"]))
    got = http.post("/v1/search", json={"query": "what does N0114 mean", "collection": "errors"}, headers=auth("owner-token")).json()["items"]
    assert [i["id"] for i in got][0] == "error:N0114" and got[0]["via"] == "key"
    assert got[0]["card"]["summary"] == "A name of another language." and got[0]["text"].startswith("[errors/diagnostic]")
    one = http.get("/v1/cards/error:N0114", headers=auth("owner-token")).json()
    assert one["id"] == "error:N0114" and http.get("/v1/cards/error:N9999", headers=auth("owner-token")).status_code == 404


def test_a_question_finds_the_card_that_answers_it_once(env):
    http, store, *_ = env
    shelve(store, "concepts",
           row("concept:mcp", type="concept", summary="The protocol an AI client speaks.", asks=["how does the mcp work", "what is the mcp"],
               links=[{"rel": "command", "to": "concept:serve"}]),
           row("concept:serve", type="concept", summary="Runs the server."),
           row("concept:protocol", type="concept", summary="The protocol of the mcp.", links=[{"rel": "command", "to": "concept:serve"}]))
    got = http.post("/v1/search", json={"query": "how does the mcp work", "expand": True}, headers=auth("owner-token")).json()["items"]
    assert got[0]["id"] == "concept:mcp" and got[0]["via"] == "ask" and got[0]["distance"] < 0.01
    assert [i["id"] for i in got].count("concept:mcp") == 1
    assert got[0].get("related") is None  # the row it links to is already an answer
    two = http.post("/v1/search", json={"query": "how does the mcp work", "k": 2, "expand": True}, headers=auth("owner-token")).json()["items"]
    assert {i["id"] for i in two} == {"concept:mcp", "concept:protocol"}  # both link to the same row: it is read once
    assert all(i["related"] == [{"id": "concept:serve", "rel": "command", "title": "concept:serve", "summary": "Runs the server."}] for i in two)


def test_a_local_agent_reads_only_its_rows_and_its_platform(env):
    http, store, *_ = env
    shelve(store, "platforms",
           row("kind:backend.usecase", type="kind", summary="one operation", platforms=["backend"], meta={"kind": "usecase"}),
           row("kind:mobile.usecase", type="kind", summary="one operation", platforms=["mobile"], meta={"kind": "usecase"}),
           row("spec:fastapi", type="spec", summary="one operation underneath", agents=False))
    shelve(store, "errors", row("pitfall:exec", type="pitfall", summary="one operation only", meta={"kinds": ["usecase", "service"]}))

    def ids(**body):
        return {i["id"] for i in http.post("/v1/search", json={"query": "one operation", "k": 9, **body}, headers=auth("owner-token")).json()["items"]}

    assert ids() == {"kind:backend.usecase", "kind:mobile.usecase", "spec:fastapi", "pitfall:exec"}
    assert ids(agents=True, platform="backend") == {"kind:backend.usecase", "pitfall:exec"}  # a row of no platform is of all
    assert ids(where={"kinds": "usecase"}) == {"pitfall:exec"} and ids(where={"kinds": "entity"}) == set()
    assert ids(shelves=["platforms"], where={"kind": "usecase", "type": "kind"}) == {"kind:backend.usecase", "kind:mobile.usecase"}


def test_check_output_is_read():
    out = '[]\n[{"code": "N0114", "line": 4, "col": 14, "message": "bad", "severity": "error", "fix": null}]'
    assert describe(diagnostics_of(out)) == "4:14 N0114 bad"
    assert describe(diagnostics_of("[]\n[]")) == "ok"
    assert strip_fences("here:\n```nuclear\nmodel A\n```\nbye") == "model A\n"


def test_local_agents_read_only_nuclear():
    text = "A table:\n\n```nuclear\nBook()\n  id: int\n```\n\n```python\nclass Book(Entity): ...\n```\nEnd."
    assert assets.nuclear_only(text) == "A table:\n\n```nuclear\nBook()\n  id: int\n```\n\nEnd."
    assert assets.nuclear_only("A table.\n\n**Underneath (fastapi):** SQLAlchemy 2.") == "A table.\n"
    assert assets.foreign_fences(text) == ["python"]


def test_a_planner_reads_how_people_write_each_kind(env):
    http, store, *_ = env
    shelve(store, "platforms",
           row("kind:backend.usecase", type="kind", platforms=["backend"], keys=["use case", "usecase"], meta={"kind": "usecase"}),
           row("kind:mobile.stateless", type="kind", platforms=["mobile"], keys=["stateless"], meta={"kind": "stateless"}),
           row("decorator:backend.get", type="decorator", platforms=["backend"], keys=["@get"], meta={"name": "get"}))
    assert http.get("/v1/kinds/backend", headers=auth("owner-token")).json() == {"use case": "usecase", "usecase": "usecase"}


def test_a_request_gets_the_strategy_of_its_kind(env):
    http, store, *_ = env
    shelve(store, "playbooks",
           row("strategy:bug-compile", type="strategy", summary="The project does not compile.", meta={"triggers": ["does not compile"]},
               data={"signals": [r"\bN0\d{3}\b"], "stages": ["code", "verify"]}),
           row("strategy:usecase", type="strategy", summary="A rule of the business.", asks=["add a use case that cancels an order"], data={"target": "new"}),
           row("strategy:member", type="strategy", summary="One more field in a declaration.", data={"target": "existing"}),
           row("playbook:refactor", type="playbook", summary="does not compile is a phrase of this text, and it is no strategy"))

    def strategy(text, **more):
        return http.post("/v1/strategy", json={"text": text, **more}, headers=auth("owner-token")).json()["items"]

    # an exact sign of the request decides, and the answer says which one
    best = strategy("error[N0116]: 'OrderRepository' has no member 'search'")[0]
    assert best["id"] == "strategy:bug-compile" and 'it writes "N0116"' in best["why"] and best["data"]["stages"] == ["code", "verify"]
    assert strategy("my project does not compile")[0]["id"] == "strategy:bug-compile"
    # without one: the meaning, and whether the project has what the request names
    assert strategy("add a use case that cancels an order", existing=[], new=["CancelOrder"])[0]["id"] == "strategy:usecase"
    assert strategy("one more thing in Order", existing=["Order"], new=[])[0]["id"] == "strategy:member"
    assert all(i["id"].startswith("strategy:") for i in strategy("anything"))
    # a run of the Loop cannot follow a strategy without stages, unless an exact sign chose it
    shelve(store, "playbooks", row("strategy:question", type="strategy", summary="Explain, do not change.", asks=["what is a facade"],
                                   data={"signals": [r"\?\s*$"], "stages": []}))
    assert strategy("what is a facade")[0]["id"] == "strategy:question"
    assert strategy("what is a facade", runnable=True)[0]["id"] != "strategy:question"
    assert strategy("what is a facade?", runnable=True)[0]["id"] == "strategy:question"


def test_a_spec_is_told_what_cannot_be_done_yet_by_its_own_words(env):
    http, store, *_ = env
    shelve(store, "capabilities",
           row("limit:backend-not-yet", type="limit", title="No guards yet", summary="Routes have no access control.", platforms=["backend"],
               meta={"triggers": ["authentication", "background job"]}),
           row("limit:web-first-version", type="limit", platforms=["web"], meta={"triggers": ["form"]}),
           row("can:backend-api", type="can", summary="authentication is a word of this text, not a trigger"))

    def applies(text, platform):
        return http.post("/v1/applies", json={"text": text, "platform": platform}, headers=auth("owner-token")).json()["items"]

    (hit,) = applies("A login form with authentication and two background jobs.", "backend")
    assert hit == {"id": "limit:backend-not-yet", "type": "limit", "title": "No guards yet", "summary": "Routes have no access control.", "trigger": "authentication"}
    assert [i["id"] for i in applies("A login form.", "web")] == ["limit:web-first-version"]
    assert applies("A list of books by author.", "backend") == []
