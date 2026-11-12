import hashlib
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["NUCLEAR_GRAPH_NO_KEYRING"] = "1"

from nuclear_graph.access import Access  # noqa: E402
from nuclear_graph.ingest import chunks_of, ingest  # noqa: E402
from nuclear_graph.server import create_app  # noqa: E402
from nuclear_graph.store import Store  # noqa: E402
from nuclear_graph.toolchain import diagnostics_of, describe, strip_fences  # noqa: E402


def fake_embed(texts, query):
    """A bag of words hashed into 64 dimensions: enough for closest-match tests without a model."""
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        out.append(v)
    return out


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
    store.put("knowledge", [("1", "a repository builds one query per method", {"source": "s", "kind": "spec"}),
                            ("2", "the device panel streams frames", {"source": "t", "kind": "doc"})])
    got = http.post("/v1/search", json={"query": "repository query", "k": 1}, headers=auth("owner-token")).json()
    assert got["items"][0]["id"] == "1"
    raw = b"".join(p.read_bytes() for p in Path(tmp, "db").rglob("*") if p.is_file())
    assert b"repository builds" not in raw


def test_only_ingest_writes_knowledge(env):
    http, _, access, _ = env
    token = access.grant("agent", ["read", "write"])
    body = {"collection": "knowledge", "id": "x", "text": "lies"}
    assert http.post("/v1/documents", json=body, headers=auth(token)).status_code == 403
    body["collection"] = "memory"
    assert http.post("/v1/documents", json=body, headers=auth(token)).status_code == 200


def test_ingest_embeds_only_what_changed(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "spec").mkdir(parents=True)
    (root / "spec" / "a.md").write_text("# A\n\nfirst\n\n## B\n\nsecond")
    (root / "build").mkdir()
    (root / "build" / "x.md").write_text("generated")
    calls = []
    store = Store(str(tmp_path / "db"), key=b"k" * 32, embed=lambda t, q: calls.append(len(t)) or fake_embed(t, q))
    first = ingest(store, [root], log=lambda _: None, cli=False)["knowledge"]
    assert first["added"] == 2 and store.stats()["prompts"] >= 8
    again = ingest(store, [root], log=lambda _: None, cli=False)["knowledge"]
    assert again == {"added": 0, "kept": 2, "removed": 0}
    (root / "spec" / "a.md").write_text("# A\n\nfirst")
    assert ingest(store, [root], log=lambda _: None, cli=False)["knowledge"]["removed"] == 1
    # another root (a folder inside the tree, the wrong current folder) never removes what the first one gave
    other = tmp_path / "other"
    (other / "docs").mkdir(parents=True)
    (other / "docs" / "c.md").write_text("# C\n\nthird")
    assert ingest(store, [other], log=lambda _: None, cli=False)["knowledge"]["removed"] == 0
    assert ingest(store, [root], log=lambda _: None, cli=False)["knowledge"] == {"added": 0, "kept": 1, "removed": 0}


def test_chunks_know_their_kind_and_dialect(tmp_path: Path):
    f = tmp_path / "docs.toml"
    f.write_text("[kinds]\nentity = '''\nA table.\n'''\n")
    (c,) = chunks_of(f, "dragonfly-backend/dialects/backend/fastapi/docs.toml", "dragonfly-backend")
    assert c[2]["kind"] == "word" and c[2]["dialect"] == "fastapi" and "kind `entity`" in c[1]


def test_check_output_is_read():
    out = '[]\n[{"code": "N0114", "line": 4, "col": 14, "message": "bad", "severity": "error", "fix": null}]'
    assert describe(diagnostics_of(out)) == "4:14 N0114 bad"
    assert describe(diagnostics_of("[]\n[]")) == "ok"
    assert strip_fences("here:\n```nuclear\nmodel A\n```\nbye") == "model A\n"


def test_local_agents_read_only_nuclear():
    from nuclear_graph.ingest import for_agents, nuclear_only, platform_of
    assert for_agents("dragonfly-backend/spec/backend.md", "spec")
    assert for_agents("dragonfly-backend/spec/brief/backend.md", "spec")
    assert not for_agents("dragonfly-backend/spec/fastapi.md", "spec")
    assert not for_agents("spec/python.md", "spec")
    assert not for_agents("dragonfly-backend/dialects/backend/fastapi/dialect.toml", "dialect")
    assert not for_agents("dragonfly-backend/packages/dragonfly-py/README.md", "doc")
    assert for_agents("dragonfly-backend/examples/examples-backend/tasks_api/components/tasks/api/tasks_controller.nuc", "example")
    text = "A table:\n\n```nuclear\nBook()\n  id: int\n```\n\n```python\nclass Book(Entity): ...\n```\nEnd."
    assert nuclear_only(text) == "A table:\n\n```nuclear\nBook()\n  id: int\n```\n\nEnd."
    assert platform_of("dragonfly-backend/dialects/backend/fastapi/docs.toml", "fastapi") == "backend"
    assert platform_of("dragonfly-web/spec/web.md", "") == "web"


def test_the_agents_never_read_what_a_dialect_writes_underneath():
    from nuclear_graph.ingest import nuclear_only, words

    text = "[kinds]\nentity = '''\nA table of the database.\n'''\n\n[underneath.kinds]\nentity = 'SQLAlchemy 2, like a TypeORM entity.'\n"
    chunks = dict(words(text))
    assert "SQLAlchemy" not in chunks["entity"]
    assert "SQLAlchemy" in chunks["underneath entity"]
    assert nuclear_only("A table.\n\n**Underneath (fastapi):** SQLAlchemy 2.") == "A table.\n"
