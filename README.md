# Nuclear Smart Graph

The local, private library of everything [NuclearLang](https://github.com/nuclearlang/nuclear) and Dragonfly are, and
the **MCP server** (Model Context Protocol: the open protocol through which an AI client calls a program's tools) of
the whole ecosystem. Agents (Claude, Codex, Cursor, the local Nuclear Developer) ask it instead of guessing: what
Nuclear is for, how each thing is written, every kind and decorator, every tool, every error and its fix, what can and
cannot be done, how a task is done step by step, and validated code.

Decision records: [ADR-0104](https://github.com/nuclearlang/nuclear/blob/main/docs/adr/0104-smart-graph-shelves.md)
(the library: shelves, rows, search, versions) and
[ADR-0102](https://github.com/nuclearlang/nuclear/blob/main/docs/adr/0102-ai-loop.md) (the AI loop).

```
 Claude Code / Codex / Cursor ──MCP (stdio)──┐
                                             ▼
 VS Code Loop tool ──HTTP──┐        nuclear-graph mcp ──► nuclear / dragonfly CLIs
                           ▼                 │        └─► Nuclear Developer (local 3B agents)
 Nuclear Developer ──HTTP──► nuclear-graph serve (127.0.0.1:7878, token)
                                     │
                                     ▼
              Chroma: one collection per shelf (encrypted documents) + EmbeddingGemma (Ollama)
```

## Install

The set-up of the AI services installs it, loads the knowledge base and starts it at every login
(`nuclear-loop setup`, the installer's last step, or the wizard of VS Code:
[Set up the AI services](https://github.com/nuclearlang/nuclear/blob/main/docs/ai/setup.md)).

By hand: it needs Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) with an embeddings
model, and the NuclearLang CLIs on the `PATH`.

```sh
ollama pull embeddinggemma
nuclear build nuclear-graph                               # the graph is written in Nuclear: its Python package
uv tool install --editable './nuclear-graph[server]'     # nuclear-graph on the PATH
nuclear-graph serve &                                     # the graph, on 127.0.0.1:7878
nuclear-graph knowledge build                             # the knowledge base: nuclear-developer/data/assets
nuclear-graph ingest                                      # the graph learns it (≈2 min the first time)
nuclear-graph stats                                       # the rows of each shelf and the revision it holds
nuclear-graph knowledge ask                               # the questions people ask: each finds its row
```

## The library: shelves, cards, links

A **shelf** is a Chroma collection that answers one kind of question. A **row** is one card of it.

| Shelf | The question it answers | What its rows are |
|---|---|---|
| `concepts` | What is it, why does it exist, how does it work? | the purpose, the advantages, the ideas, the parts of the ecosystem, the theory, the questions people ask |
| `language` | How is it written in Nuclear? | the guide and the rules section by section; each base type's members |
| `platforms` | What does a platform have, and where does each thing go? | every kind, decorator and plugin of `backend`, `mobile` and `web`; their layout and rules |
| `tools` | What can run, and how is it called? | each command of the four CLIs, each MCP tool, each HTTP route, the generators, the Loop's stages, the local agents, the editor's commands, each component's version |
| `errors` | What went wrong, and how is it fixed? | each diagnostic of the compiler (linked to the ones it comes with), the habits of other languages, the failures of the tools and services, the mistakes small models repeat |
| `capabilities` | Can it be done, by NuclearLang or by this agent? | what can be done, what cannot yet, the limits, the limits of the local agents |
| `playbooks` | How is this task done, step by step, and by whom? | the strategy of each kind of request (how it is recognised, its plan, what it asks of a run); the procedure of each use case with the tool of each step; the roles and their skills |
| `examples` | What does the code look like? | every `.nuc` of the example projects by kind and platform; solved tasks |
| `docs` | What does the full document say? | the long form: the dialects underneath, the target languages, the runtimes, the decisions, the context files, the guides |
| `queries` | Which, how many, what are: a question with one right answer | the catalogue of exact questions: each row is a question, its parameters and the query that answers it over the exact facts |

A card has a stable id (`error:N0114`, `kind:backend.usecase`, `tool:dragonfly.gen.resource`, `concept:mcp`), a title,
a summary, a body, the exact names it is known by (`keys`), the questions it answers (`asks`), typed links to other
cards, the platforms it belongs to, whether the local agents read it, and the sources it was written from. The whole
format is `shelves.nuc`, written into the base as `schema.json`.

### Exact facts and the query planner

A search by meaning gives the closest cards, never *all* of something: asked for every tool of the MCP server, it
gives four cards and a model fills in the rest. So the graph also holds **the exact facts** of the base in a relational
database (SQLite): every row's names, summary, links and structured fields (`meta`, `data`), with a view per thing a
question can list (`commands`, `mcp_tools`, `mcp_params`, `routes`, `kinds`, `decorators`, `plugins`, `generator_pieces`,
`diagnostics`, `library`, `stages`, `agents`, `components`, `strategies`...). The database lives in the memory of the
graph's process only: it is made from the cards the store keeps sealed when the graph starts, and again at every
ingest; nothing of it is written to disk, and it holds no row's body and nothing an agent kept at run time.

The `queries` shelf is the catalogue: one row per question with one right answer (`query:mcp.tools`, `query:mcp.group`,
`query:kind.create`, `query:cli.commands`, `query:diagnostic`...), with the ways people ask it, its parameters (each
with the query that lists the words people write and the value each means: `generadores` → `generate`, `caso de uso` →
`usecase`) and its SQL, checked at build time against the views. **The planner** (`POST /v1/answer`, `nuclear-graph
answer "<question>"`, MCP `graph_answer`) asks no model: it matches the question to the catalogue (by meaning and by
the names it writes), fills the parameters from the question's own words (or, for a follow-up, from the user's earlier
messages), runs the queries, and searches the shelves for what is left. The shelves also decide whether a question is
exact at all: a query runs only when its exact question is closer to what was asked than the closest card, so "what is
nuclear" gets the card of the language and not the commands of the tool of that name. It answers `facts` (the rows,
whole), `knowledge` (the cards) and `needs` (an exact question it is close to that lacks a name). The local assistant
explains them, and the rows end its answer as they are, put there by code: a list never depends on a model.

**Search** is by meaning and by exact name at once: the query is embedded once and each shelf answers its closest
cards; the names the query writes (`N0114`, `gen resource`, `usecase`, `mcp`) are looked up in the cards' keys, so a
code or a command reaches its card whatever the rest of the sentence says, in any language; a card is also found by
the questions its author wrote for it. The search is exact: the stored vector of every item a filter matches is
compared with the query's (the store's own index is approximate and is not asked). A card is read directly by its id, with a line for each card it links to.

```sh
nuclear-graph search "como funciona el MCP"                # every shelf
nuclear-graph search "how do I declare an entity" -c platforms -p backend --agents
nuclear-graph card error:N0114                             # one card and what it links to
```

**A strategy** is the row of one kind of request a user makes (`strategy:resource-db`, `strategy:refactor-rename`,
`strategy:bug-failing-test`...: 31 of them, ADR-0105). `nuclear-graph strategy` says which one a request is, and why.
It asks no model: an exact sign of the request (a diagnostic code, a test's output, `rename A to B`, a `GET <url>`
line) outweighs any closeness of meaning, and meaning decides when there is none.

```sh
nuclear-graph strategy "renombra Book a Title"             # → strategy:refactor-rename (it writes "renombra"; ...)
nuclear-graph strategy "un CRUD de pedidos" -p backend --full   # with the plan of the strategy
```

Two more collections are not part of the base: `prompts` (the prompt files of this package: `prompts/<use case>.md`
and `prompts/agents/<step>.md`) and `memory` (what an agent keeps about a project while it works).

## The knowledge base: assets, versions, and how it stays current

What the graph knows is one folder: `nuclear-developer/data` (its own repository, `nuclear-knowledge`). Its
`assets/<shelf>/<name>.json` files are the rows.

- **Generated rows** (`"origin": "generated"`, never edited by hand) are read from a structured source by
  `nuclear-graph knowledge build`: the compiler's diagnostics, the standard library, each platform's `platform.toml`
  and words, the help of `nuclear`, `dragonfly`, `nuclear-loop` and `nuclear-graph`, the MCP tools, the HTTP routes,
  the Loop's stages, the local agents' sources, the editor's `package.json`, each component's version, the example
  projects, the evaluation's validated answers, and every markdown file of the tree (one row per heading section, on
  the shelf its section of `sections.toml` names).
- **Curated rows** (`"origin": "curated"`) are written by hand: what no file says in one place (the purpose, the
  concepts, what can and cannot be done, the playbooks, the failures). Each names its `sources`.
- **Overlays** (`<name>.overlay.json`) add hand-written fields to generated rows: which errors come together, a right
  example.

| Command | What it does |
|---|---|
| `nuclear-graph knowledge build` | writes the generated assets, validates the whole base and raises the revision when a row changed |
| `nuclear-graph knowledge check` | fails when an asset is not what the tree gives now, a row is invalid, a curated row's source changed since its review, or the running graph holds another revision |
| `nuclear-graph knowledge review [id...]` | records that curated rows still hold after their sources changed |
| `nuclear-graph knowledge ask [word...]` | asks the running graph the questions of `questions.toml` and fails when one does not find its row (`exact = true`: its exact query) |
| `nuclear-graph knowledge examples` | compiles every ```` ```nuclear ```` block of the hand-written rows |
| `nuclear-graph ingest` | makes the folder what the graph knows: only what changed is embedded again; what an agent wrote at run time is kept |

A base is valid or it is not built: a link to a row that does not exist, a duplicated id, a diagnostic without
documentation, a document no section claims, or code of a target language in a row the local agents read stops the
build. `manifest.json` holds the schema, the revision and each row's hash; `revisions.json` is the log; the graph
remembers the revision it ingested (`nuclear-graph stats`).

**After every change of the ecosystem**: build, review what it names, check, ingest. The end-of-turn hook of the
working tree runs the check. A new tool, error, kind or version reaches the base by building it; a new capability,
limit, failure or procedure gets its row written by hand. The teaching material (`docs/aprende`, CodeBuilder) and
`STATUS.md` are never part of the base.

## Who may read it

Nothing reaches the graph without a token, and no token exists until you allow it.

| Command | What it does |
|---|---|
| `nuclear-graph connect <client> --scopes read,write` | gives a program access now and keeps its token in your keyring |
| `nuclear-graph requests` | the pending access requests and the allowed clients |
| `nuclear-graph allow <request>` / `deny <request>` | answers a request a program made (`POST /v1/access`) |
| `nuclear-graph revoke <client>` | takes a client's access away (its token stops working at once) |

Scopes: `read` (search, cards, prompts), `write` (remember, add examples), `admin` (ingest, manage: only you, with
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
  (`secret-tool`, libsecret), or in `0600` files of the data folder when there is no keyring; a graph that starts
  while its keyring is closed (a service at login) waits for it and never makes a second key or token;
- the data folder (`$XDG_DATA_HOME/nuclear-graph`, `0700`) is opened only by the server process;
- only `ingest` writes the shelves of the base: a client writes `memory` and `examples` and cannot plant false
  documentation.

Limits: protection is per OS user. A program running as you could ask the keyring for the key as the graph does; the
graph stops other users, web pages and programs that only speak HTTP or MCP. The vectors and the metadata (ids,
titles, keys) are stored in clear (Chroma searches them): they reveal what a row is about, not its text.

## Use it from an AI agent (MCP)

MCP is the **Model Context Protocol**: an AI client (Claude Code, Codex, Cursor) starts a program and calls the tools it
offers. `nuclear-graph mcp` is that program for NuclearLang: it speaks MCP over stdio and offers the graph, the
compiler, the `dragonfly` commands and the local developer as tools.

```sh
claude mcp add nuclear -- nuclear-graph mcp       # Claude Code
codex mcp add nuclear -- nuclear-graph mcp        # Codex
```

Cursor and others: an MCP server with command `nuclear-graph` and argument `mcp`. The same reference, with the set-up
of each client and what to do when a tool fails, is a page of the documentation:
[the MCP server of NuclearLang](https://github.com/nuclearlang/nuclear/blob/main/docs/ai/mcp.md). The tools:

| Tool | What it gives |
|---|---|
| `graph_strategy(request, platform)` | **the first call for any request**: which kind of request it is (a whole system, one screen, a rename, a failing test...), the signs that say so, and the plan of that kind (ADR-0105) |
| `graph_answer(question, platform)` | the exact answer of a question that has one (every command of a tool, the tools of this server and their parameters, the commands that write a kind, a diagnostic by its code...): the rows of the exact facts (SQLite), whole, then the cards the shelves answer by meaning |
| `graph_search(query, shelf, k, platform, kind, type)` | the cards that answer a query, each with the rows it links to; `shelf`: one or several of the shelves above, or `memory` |
| `graph_card(id)` | one card by its id (`error:N0114`, `kind:backend.usecase`, `playbook:feature-from-a-spec`) |
| `graph_prompt(use_case)` | the validated prompt of `feature`, `refactor`, `bug`, `docs`, `diagram`, `test`, `security`, `piece`, `plan` |
| `graph_remember(id, text, collection, project)` | keeps a decision (`memory`), or a solved example (`examples`) the local developer will find |
| `nuclear_check(code \| path, dialect)` | `ok`, or one line per error with its fix |
| `nuclear_build`, `nuclear_fmt`, `nuclear_help`, `nuclear_brief`, `nuclear_defs` | the compiler and its documentation |
| `dragonfly(project, command, args)` | `new`, `build`, `install`, `test`, `check`, `analyze`, `make`, `migrate`, `add`, `explain` in a project |
| `project_inspect(project)` | what the project has: platform, dialect, components with their declarations by kind (`dragonfly gen inspect`) |
| `generate_resource(project, component, name, from_json \| from_spec \| fields, source, path, actions, screen, plural, dry_run)` | the finished, compiling code of a resource (`dragonfly gen resource`, ADR-0103): models, repository, a use case per action, the facade, the controller or the screen, the tests |
| `generate_usecase(project, component, name, calls, route, dry_run)` | a use case wired into its component (`dragonfly gen usecase`): its alias in the facade and, with `route` (backend, `"POST orders/{id}/cancel"`), its route in the controller; with `calls` (`"OrderRepository.pending"`) the use case is written too, because it only calls that method |
| `generate_component(project, component)`, `generate_screen(project, component, screen, route)` | a component with its facade; a screen that is not a resource's list (mobile, web) |
| `api_inspect(url, project, component, name)` | a public API's answer as a shape (keys, types, nested objects, a page); with a project, the files `generate_resource` would write |
| `web_search(query, pages)`, `web_read(url)` | the internet: an API's documentation when neither the spec nor the API's answer gives the fields (SearXNG with `NUCLEAR_SEARXNG_URL`, Brave with `nuclear-graph web-key brave`, else Wikipedia) |
| `developer_task(project, title, description, criteria, use_case)` | **the first step of every task**: the local developer does the whole task in the project (`nuclear-loop run --lead local`: plan, tests first, code, verification, security, artifacts) and answers the run's journal |
| `developer_retry(project, run, from_stage, from_step, scratch)` | a run again: from the step that failed (every step that passed is kept), the whole of `from_stage`, from one step and every step after it (`from_step`, passed or failed), or from scratch (`scratch`); what the steps left out wrote is undone first |
| `developer_review(project, run, notes, files)` | **the last step**: the lead's corrections, appended to `.nuclear/loop/runs/<run>.review.md`; each corrected file (once the project's check is `ok`) goes to the graph's `examples` |
| `developer_code`, `developer_test`, `developer_security` | the [Nuclear Developer](https://github.com/nuclearlang/nuclear-developer): one file written, checked and repaired by the local 3B model (`platform`: backend, mobile or web; it writes only Nuclear) |

The way to work, which the server's instructions give every client (Sonnet, Opus, Haiku, Codex...): **the local
developer works first, the frontier model validates and corrects.** For a feature it first inspects the project and
generates every resource the spec names (`generate_resource`, the fields from the spec, the API's answer or its
documentation, or the user when none gives them); then it calls `developer_task` for what is left and wires each
use case it wrote with `generate_usecase`; reads the
journal the local agents wrote (what each agent did, the files, what is left); validates with `nuclear_check` and
`dragonfly test`; corrects only what failed or is wrong; and records its review with `developer_review`, so the journal
keeps it and the local developer learns the corrected files. It writes the code itself only when the local developer
is not running. `developer_code` stays for one quick file outside a task.

## HTTP API

All routes need `Authorization: Bearer <token>` except `GET /v1/health`, `POST /v1/access` and `GET /v1/access/{id}`.

| Route | Scope | Body / answer |
|---|---|---|
| `POST /v1/search` | read | `{query, collection \| shelves, k = 5, platform, agents, where, expand}` → `{items: [{id, shelf, text, meta, distance, score, via, card, related}]}`; without a collection, every shelf of the base; `where` filters by metadata (`{"type": "kind"}`, `{"kinds": "usecase"}`) |
| `GET /v1/cards/{id}` | read | one card by its id, with the title and summary of the rows it links to |
| `POST /v1/answer` | read | `{question, platform, history, agents, k}` → `{exact, needs, cards, facts, knowledge}`: what a question needs before a model answers it. `exact`: the exact queries it is, each with its parameters and its rows; `needs`: the ones it is close to that lack a name; `cards`: the shelves' answer by meaning; `facts` and `knowledge`: both as the text a prompt gets. No model is asked |
| `POST /v1/strategy` | read | `{text, platform, existing, new, runnable, only}` → the strategies that fit a request, best first (at most three): `{id, title, summary, score, why, data, text}`. `existing` and `new`: the declarations the request names that a project has, and the ones it has not; `runnable`: for a run of the Loop; `only`: the strategy the request itself names |
| `POST /v1/applies` | read | `{text, platform}` → the capabilities rows whose trigger words a spec writes: what the platform cannot do yet, limits, parts never run for real (exact, never by meaning) |
| `GET /v1/kinds/{platform}` | read | every way a kind of the platform is written (`use case`, `application component`) and the kind it means |
| `GET /v1/prompts/{use_case}` | read | the prompt document |
| `POST /v1/documents` | write | `{collection: "memory" \| "examples", id, text, meta}`: what an agent keeps at run time |
| `DELETE /v1/documents/{collection}/{id}` | write | |
| `GET /v1/stats` | read | the rows of each collection; the schema and revision of the base the graph holds |
| `POST /v1/ingest` | admin | `{roots: [<knowledge folder>]}` |
| `POST /v1/access` | — | `{client, scopes, reason}` → `{request}` |
| `GET /v1/access/{request}` | — | `{status}`; once allowed, the token, a single time |
| `GET /v1/access`, `POST /v1/access/{request}/allow\|deny` | admin | manage requests |

## For programs: the client package

`pip install nuclear-graph` (without `[server]`) needs only `httpx`:

```python
from nuclear_graph.client import GraphClient
from nuclear_graph.toolchain import Toolchain

graph = GraphClient("my-tool")               # token: NUCLEAR_GRAPH_TOKEN or `nuclear-graph connect my-tool`
text = await graph.search("repository query with where", shelves="platforms,errors", platform="backend", agents=True)
card = await graph.card("kind:backend.repository")
errors = await Toolchain().check(code, "backend")   # "ok" or one line per error; a platform or a dialect
limits = await graph.applies(spec, "backend")       # what of a spec the platform cannot do yet
chosen = await graph.strategy(request, "backend")   # which kind of request it is: id, why, plan, stages, needs...

from nuclear_graph.workspace import Workspace       # a project's files for an agent: read-only, inside the project
files = Workspace("/path/to/project")
context = files.context("A use case BooksOfAuthor(books: BookRepository)")   # the files that declare those names
files.read("config.nuc"); files.list("components"); files.find("**/*_repository.nuc"); files.grep("byAuthor")
files.renamed("Book", "Title")                      # a rename by a tool: every file that writes the name, rewritten
```

## Settings

| Variable | Default |
|---|---|
| `NUCLEAR_GRAPH_PORT` / `NUCLEAR_GRAPH_URL` | `7878` / `http://127.0.0.1:7878` |
| `NUCLEAR_GRAPH_HOME` | `$XDG_DATA_HOME/nuclear-graph` |
| `NUCLEAR_GRAPH_EMBED` | `embeddinggemma` |
| `OLLAMA_URL` | `http://localhost:11434` |
| `NUCLEAR_DEVELOPER_URL` (MCP) | `http://127.0.0.1:7879` |
| `NUCLEAR_AI_MODE` (MCP) | the mode of `~/.config/nuclearlang/ai.env`, else `local`; `remote`: no `graph_*` nor `developer_*` tools |
| `NUCLEAR_ROOT` (`knowledge`, `ingest`) | this checkout's working tree |

## Development

The graph is written in Nuclear (the `python` dialect): the `.nuc` files of this folder are the source, and
`nuclear build .` writes the Python package `build/nuclear_graph` that `pyproject.toml` packages (`[project] package`
of `nuclear.toml` names it). `build/` is never edited and never committed.

```sh
nuclear check . && nuclear build .          # the .nuc files → build/nuclear_graph
uv sync --extra server --extra test
.venv/bin/python -m pytest -q               # tests/*.nuc: access, encryption at rest, the search, the exact facts, the planner, the knowledge base's build and check
nuclear-graph knowledge examples            # every ```nuclear block of the hand-written rows compiles
```

Layout: `shelves.nuc` (the schema), `assets.nuc` (a row: validation, what is embedded, what is stored),
`extract*.nuc` (the generated rows), `knowledge.nuc` (build, check, review), `store.nuc` (Chroma + encryption +
embeddings), `retrieve.nuc` (the search), `facts.nuc` (the exact facts: the tables and their views), `planner.nuc`
(the query planner), `ingest.nuc`, `access.nuc`, `server.nuc`, `mcp_server.nuc`, `client.nuc`, `toolchain.nuc`,
`workspace.nuc` (a project's files for an agent), `web.nuc`, `secrets_store.nuc`, `crypto.nuc`, `paths.nuc`,
`cli.nuc`, `prompts/` (the prompt files, ingested into `prompts`), `tests/`.

## License

Apache-2.0.
