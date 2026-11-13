# Changelog

All notable changes to nuclear-graph are written here; versions follow [Semantic Versioning](https://semver.org).

## Unreleased

- The planner runs a query of the exact facts only when its exact question is closer to what was asked than the
  closest card of the shelves (ADR-0107 §4): "que es nuclear lang?" was answered with every command of `nuclear`,
  because the question writes the tool's name; so were "what is the smart graph" (47 rows) and "how does the mcp
  work" (27). `knowledge ask` holds the open questions marked `exact = false` in `questions.toml` to no query.
- **The search is exact** (ADR-0104 §3): `Store.near` and `Store.measure` compare the vector the store keeps of every
  item a filter matches; Chroma's approximate index is not asked. Once rows were replaced that index did not reach
  every item it held, and which ones changed at every start of the graph (after an ingest: three cards of 2 617, and
  "ModuleNotFoundError: No module named ..." no longer found its failure). `numpy` is a dependency of the server.
- A search result's `distance` is the closest the card came by meaning, by its text or by any question it answers;
  it was the distance of whichever of them ranked it, so a card brought in by a name hid a question of its own that
  was the same as the one asked.
- **A closed keyring is waited for** (ADR-0106 §9): a graph started at login ran before the keyring opened, found no
  owner's token and made another one in a file (every `nuclear-graph` command was answered 401; the same on the
  documents' key would open no card). The names the keyring keeps are written down (`.keyring`); a secret of a closed
  keyring is waited for, then refused, and never made again.
- Every MCP tool's card answers "what does <tool> do" (a generated question of its row): the planner gave that
  question the 15 rows of `query:mcp.commands`. `query:examples` answers "an example of a <kind>"; "que hace el mcp"
  is a question of `concept:mcp`, no longer of `query:mcp.tools`.
- The package is typed (`py.typed`): a project that uses it is checked against it.
- The graph is a library (ADR-0104): nine shelves (`concepts`, `language`, `platforms`, `tools`, `errors`,
  `capabilities`, `playbooks`, `examples`, `docs`) of rows with a stable id, keys, questions, typed links and sources,
  instead of two collections of document pieces (`knowledge` and `nuclear` are removed by the first ingest). Search by
  meaning and by exact name over several shelves; `GET /v1/cards/{id}`; `nuclear-graph card`, `search -p --agents`;
  MCP `graph_search` by shelf and `graph_card`.
- The knowledge base is asset files: `knowledge build` generates the rows from the working tree (`extract.py`:
  diagnostics, library, platforms, the CLIs' help, MCP tools, routes, stages, agents, editor, versions, examples,
  documents), merges the overlays, validates everything and raises the revision; `knowledge check` fails when the
  base is behind the tree; `knowledge review` confirms a hand-written row whose source changed; `knowledge ask` runs
  the questions of `questions.toml`. `ingest` takes the knowledge folder only, embeds what changed and keeps what
  agents wrote at run time. A client writes only `memory` and `examples`.
- For the agents: `POST /v1/applies` (what of a spec the platform cannot do yet, by the capabilities' trigger words),
  `GET /v1/kinds/{platform}` (how people write each kind), `GraphClient.applies | kinds | brief | card`, and
  `workspace.py`: a project's files, read-only and confined to the project (`read`, `list`, `find`, `grep`, `outline`,
  `declarations`, `context`). MCP `developer_code` takes `project` and the local coder reads the project by itself.

- First public version (ADR-0102): the private knowledge base (Chroma + EmbeddingGemma, documents AES-GCM encrypted,
  key and owner token in the keyring, a server on 127.0.0.1 with per-client tokens the user allows), ingest by hash,
  the knowledge base build (`nuclear-graph knowledge build|check`, the `nuclear-knowledge` repository), the agents'
  prompts as files, the web tools (`web.py`).
- MCP server: the graph, the Nuclear Developer's agents (`developer_*`, local first, `developer_review`), and the
  generators (ADR-0103): `project_inspect`, `generate_component|resource|screen`, `api_inspect`, `web_search`,
  `web_read`.
- MCP `generate_usecase(project, component, name, calls, route, dry_run)`: `dragonfly gen usecase` for a client; the instructions tell it to wire each use case the local developer wrote (ADR-0103).
- The README's tool table has `developer_retry`; a test holds every MCP tool to the README and to the documentation's
  page (`docs/ai/mcp.md` of `nuclear`), so a new tool is documented in the same change.
- Strategies (ADR-0105): the row type `strategy` on the playbooks shelf (`meta`: `family`, `scope`, `triggers`; `data`: `signals`,
  `target`, `mode`, `stages`, `pieces`, `generators`, `needs`, `lead`); the selection `retrieve.strategy` (exact signs, then
  meaning; no model), `POST /v1/strategy`, `GraphClient.strategy`, `nuclear-graph strategy "<request>"`, MCP `graph_strategy`
  (the first call the server's instructions ask for); `knowledge ask` gives a `request = true` entry of `questions.toml` to
  the selection; `Workspace.renamed(old, new)`: a rename as a tool; the prompt `agents/analyze.md`.
- A machine set up for remote agents only (ADR-0106; `NUCLEAR_AI_MODE=remote` in `~/.config/nuclearlang/ai.env`, or in the
  environment): the MCP server offers no `graph_*` nor `developer_*` tool and tells the model to write what the
  generators do not. The extra `mcp` installs the MCP server alone (`nuclear-graph[mcp]`); `paths.machine()` reads the
  set-up's file.
- 0.2.0: **written in Nuclear** (ADR-0107; the `python` dialect, `nuclear.toml`). The `.nuc` files of the repository
  are the source, `nuclear build .` writes the package `build/nuclear_graph` that `pyproject.toml` packages; `src/`
  and the Python tests are gone (`tests/*.nuc`); the prompts are `prompts/`. `nuclear-graph knowledge examples`
  replaces `tests/check_examples.py`.
- **Exact facts and the query planner** (ADR-0107): the names, summaries, links and structured fields of every row in
  a SQLite database kept in the memory of the graph's process only (made from the sealed cards at the start and at
  every ingest; nothing is written to disk), with a view per thing a question can list (`facts.nuc`); the shelf
  `queries`, the catalogue of questions with one right answer, checked at build time; the planner (`planner.nuc`):
  `POST /v1/answer`, `nuclear-graph answer "<question>" [-p platform]`, `GraphClient.answer`, MCP `graph_answer`. The
  generated rows carry what the views read as structured `data`; `knowledge ask` gives an `exact = true` entry of
  `questions.toml` to the planner.
- MCP `developer_retry(project, run, from_stage, from_step, scratch)`: a run again from any step, or from scratch.
- The prompts `chat.md` and `agents/chat.md` have an "Exact facts" section the assistant copies from;
  `agents/accept.md` holds the acceptance criteria against a run.
