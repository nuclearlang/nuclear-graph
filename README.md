# Nuclear Smart Graph

The local, private knowledge base of [NuclearLang](https://github.com/nuclearlang/nuclear) and Dragonfly, and the
**MCP server** (Model Context Protocol: the open protocol through which an AI client calls a program's tools) of
the whole ecosystem. Agents (Claude, Codex, Cursor, the local Nuclear Developer) search it instead
of guessing: every spec, guide, ADR, dialect word, example and the help of the `nuclear` and `dragonfly` CLIs, plus
the solved examples and validated prompts that make a 3B local model write Nuclear as well as a frontier model.

Decision record: [ADR-0102](https://github.com/nuclearlang/nuclear/blob/main/docs/adr/0102-ai-loop.md).

```
 Claude Code / Codex / Cursor ──MCP (stdio)──┐
                                             ▼
 VS Code Loop tool ──HTTP──┐        nuclear-graph mcp ──► nuclear / dragonfly CLIs
                           ▼                 │        └─► Nuclear Developer (local 3B agents)
 Nuclear Developer ──HTTP──► nuclear-graph serve (127.0.0.1:7878, token)
                                     │
                                     ▼
                     Chroma (encrypted documents) + EmbeddingGemma (Ollama)
```

## Install

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) with an embeddings model, and the
NuclearLang CLIs on the `PATH`.

```sh
ollama pull embeddinggemma
uv tool install --editable './nuclear-graph[server]'     # nuclear-graph on the PATH (or: ./install.sh --ai)
nuclear-graph serve &                                     # the graph, on 127.0.0.1:7878
nuclear-graph knowledge build                             # the knowledge base folder: nuclear-developer/data
nuclear-graph ingest ~/path/to/nuclearlang/nuclear-developer/data   # what the graph knows (≈2 min the first time)
nuclear-graph stats
```

**What it knows is one folder: the knowledge base** (`nuclear-developer/data`, its own repository
`nuclear-knowledge`). `nuclear-graph knowledge build` copies every document, example and the help of the tools from the
working tree and the website, byte for byte, into the sections of its `sections.toml`, in reading order (introduction,
language, compiler, Dragonfly, the three platforms, the command line, the editors, AI and MCP, the decisions, the
status); a file no section claims goes to `99-other`, so none is left out. `nuclear-graph knowledge check` (and the
test `test_the_knowledge_base_of_this_tree_is_complete`) fails when a copy differs from its source by one byte.

Two collections are made from it: `knowledge` (everything, for frontier models over MCP) and `nuclear` (what the local
agents read: every section but the ones marked `agents = false` — the target languages, the dialects underneath, the
runtimes, the ADRs — with every target-language code block and every `Underneath` note removed; each chunk knows its
`platform`). The local agents write only Nuclear, but they know the whole ecosystem: the MCP server, the Loop, the CLI,
the editors.

`ingest` of the knowledge folder replaces what the graph knew (what the folder lacks is removed); `ingest` of other
folders adds them. It embeds only what changed; build and ingest again after a change. The teaching material
(`docs/aprende`, CodeBuilder) is never copied.

## Who may read it

Nothing reaches the graph without a token, and no token exists until you allow it.

| Command | What it does |
|---|---|
| `nuclear-graph connect <client> --scopes read,write` | gives a program access now and keeps its token in your keyring |
| `nuclear-graph requests` | the pending access requests and the allowed clients |
| `nuclear-graph allow <request>` / `deny <request>` | answers a request a program made (`POST /v1/access`) |
| `nuclear-graph revoke <client>` | takes a client's access away (its token stops working at once) |

Scopes: `read` (search, prompts, examples), `write` (remember, add examples), `admin` (ingest, manage: only you, with
the owner token). The two clients of this ecosystem:

```sh
nuclear-graph connect mcp --scopes read,write                 # the MCP server
nuclear-graph connect nuclear-developer --scopes read,write   # the local agents
```

How it is protected:

- the server listens on `127.0.0.1` only; a request with an `Origin` header (a web page) is refused;
- every route but `/v1/health` and the access request needs a token; tokens are stored as SHA-256 hashes, compared in
  constant time, and an allowed request hands its token once;
- documents are encrypted at rest (AES-256-GCM); the key and the owner token live in the desktop keyring
  (`secret-tool`, libsecret), or in `0600` files of the data folder when there is no keyring;
- the data folder (`$XDG_DATA_HOME/nuclear-graph`, `0700`) is opened only by the server process;
- only `ingest` writes the `knowledge` collection: a client cannot plant false documentation.

Limits: protection is per OS user. A program running as you could ask the keyring for the key as the graph does; the
graph stops other users, web pages and programs that only speak HTTP or MCP. The vectors are stored in clear (Chroma
searches them): they reveal what a document is about, not its text.

## Use it from an AI agent (MCP)

MCP is the **Model Context Protocol**: an AI client (Claude Code, Codex, Cursor) starts a program and calls the tools it
offers. `nuclear-graph mcp` is that program for NuclearLang: it speaks MCP over stdio and offers the graph, the
compiler, the `dragonfly` commands and the local developer as tools.

```sh
claude mcp add nuclear -- nuclear-graph mcp       # Claude Code
codex mcp add nuclear -- nuclear-graph mcp        # Codex
```

Cursor and others: an MCP server with command `nuclear-graph` and argument `mcp`. The tools:

| Tool | What it gives |
|---|---|
| `graph_search(query, collection, k, dialect, kind)` | the closest pieces of knowledge (kinds: doc, spec, adr, word, example, dialect, cli, context, status) |
| `graph_prompt(use_case)` | the validated prompt of `feature`, `refactor`, `bug`, `docs`, `diagram`, `test`, `security`, `piece`, `plan` |
| `graph_remember(id, text, collection, project)` | keeps a decision, or a solved example (`examples`) the local developer will find |
| `nuclear_check(code \| path, dialect)` | `ok`, or one line per error with its fix |
| `nuclear_build`, `nuclear_fmt`, `nuclear_help`, `nuclear_brief`, `nuclear_defs` | the compiler and its documentation |
| `dragonfly(project, command, args)` | `new`, `build`, `install`, `test`, `check`, `analyze`, `make`, `migrate`, `add`, `explain` in a project |
| `project_inspect(project)` | what the project has: platform, dialect, components with their declarations by kind (`dragonfly gen inspect`) |
| `generate_resource(project, component, name, from_json \| from_spec \| fields, source, path, actions, screen, plural, dry_run)` | the finished, compiling code of a resource (`dragonfly gen resource`, ADR-0103): models, repository, a use case per action, the facade, the controller or the screen, the tests |
| `generate_component(project, component)`, `generate_screen(project, component, screen, route)` | a component with its facade; a screen that is not a resource's list (mobile, web) |
| `api_inspect(url, project, component, name)` | a public API's answer as a shape (keys, types, nested objects, a page); with a project, the files `generate_resource` would write |
| `web_search(query, pages)`, `web_read(url)` | the internet: an API's documentation when neither the spec nor the API's answer gives the fields (SearXNG with `NUCLEAR_SEARXNG_URL`, Brave with `nuclear-graph web-key brave`, else Wikipedia) |
| `developer_task(project, title, description, criteria, use_case)` | **the first step of every task**: the local developer does the whole task in the project (`nuclear-loop run --lead local`: plan, tests first, code, verification, security, artifacts) and answers the run's journal |
| `developer_review(project, run, notes, files)` | **the last step**: the lead's corrections, appended to `.nuclear/loop/runs/<run>.review.md`; each corrected file (once the project's check is `ok`) goes to the graph's `examples` |
| `developer_code`, `developer_test`, `developer_security` | the [Nuclear Developer](https://github.com/nuclearlang/nuclear-developer): one file written, checked and repaired by the local 3B model (`platform`: backend, mobile or web; it writes only Nuclear) |

The way to work, which the server's instructions give every client (Sonnet, Opus, Haiku, Codex...): **the local
developer works first, the frontier model validates and corrects.** For a feature it first inspects the project and
generates every resource the spec names (`generate_resource`, the fields from the spec, the API's answer or its
documentation, or the user when none gives them); then it calls `developer_task` for what is left; reads the
journal the local agents wrote (what each agent did, the files, what is left); validates with `nuclear_check` and
`dragonfly test`; corrects only what failed or is wrong; and records its review with `developer_review`, so the journal
keeps it and the local developer learns the corrected files. It writes the code itself only when the local developer
is not running. `developer_code` stays for one quick file outside a task.

## HTTP API

All routes need `Authorization: Bearer <token>` except `GET /v1/health`, `POST /v1/access` and `GET /v1/access/{id}`.

| Route | Scope | Body / answer |
|---|---|---|
| `POST /v1/search` | read | `{query, collection = "knowledge" \| "nuclear" \| ..., k = 5, where}` (`where`: `platform`, `dialect`, `kind`) → `{items: [{id, text, meta, distance}]}` |
| `GET /v1/prompts/{use_case}` | read | the prompt document |
| `POST /v1/documents` | write | `{collection, id, text, meta}`; `knowledge` only for the owner |
| `DELETE /v1/documents/{collection}/{id}` | write | |
| `GET /v1/stats` | read | the size of each collection |
| `POST /v1/ingest` | admin | `{roots: [...]}` |
| `POST /v1/access` | — | `{client, scopes, reason}` → `{request}` |
| `GET /v1/access/{request}` | — | `{status}`; once allowed, the token, a single time |
| `GET /v1/access`, `POST /v1/access/{request}/allow\|deny` | admin | manage requests |

## For programs: the client package

`pip install nuclear-graph` (without `[server]`) needs only `httpx`:

```python
from nuclear_graph.client import GraphClient
from nuclear_graph.toolchain import Toolchain

graph = GraphClient("my-tool")               # token: NUCLEAR_GRAPH_TOKEN or `nuclear-graph connect my-tool`
text = await graph.search("repository query with where", collection="nuclear", platform="backend")
errors = await Toolchain().check(code, "backend")   # "ok" or one line per error; a platform or a dialect
```

## Settings

| Variable | Default |
|---|---|
| `NUCLEAR_GRAPH_PORT` / `NUCLEAR_GRAPH_URL` | `7878` / `http://127.0.0.1:7878` |
| `NUCLEAR_GRAPH_HOME` | `$XDG_DATA_HOME/nuclear-graph` |
| `NUCLEAR_GRAPH_EMBED` | `embeddinggemma` |
| `OLLAMA_URL` | `http://localhost:11434` |
| `NUCLEAR_DEVELOPER_URL` (MCP) | `http://127.0.0.1:7879` |
| `NUCLEAR_ROOT` (`ingest` without arguments) | the current folder |

## Development

```sh
uv sync --extra server --extra test
.venv/bin/python -m pytest -q        # access, encryption at rest, ingest by hash, check parsing
```

Layout: `src/nuclear_graph/` — `store.py` (Chroma + encryption + embeddings), `ingest.py`, `access.py`, `server.py`,
`mcp_server.py`, `client.py`, `toolchain.py`, `secrets_store.py`, `prompts/` (the use-case prompts, ingested into
`prompts`), `cli.py`.

## License

Apache-2.0.
