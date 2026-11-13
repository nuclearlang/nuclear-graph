# Changelog

All notable changes to nuclear-graph are written here; versions follow [Semantic Versioning](https://semver.org).

## Unreleased

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
