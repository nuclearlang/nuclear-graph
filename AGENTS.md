# AGENTS.md — nuclear-graph

The Nuclear Smart Graph: the private knowledge base (Chroma + EmbeddingGemma) of NuclearLang and Dragonfly, its HTTP
server with access control, and the MCP server of the ecosystem. Read README.md first; the decision is ADR-0102 of
the `nuclear` repository.

This repository is a folder of the NuclearLang working tree (`nuclear/nuclear-graph`); the platform's rules are the
working tree's `../AGENTS.md` and its state is `../STATUS.md`.

- Never weaken a security rule (token on every route, no `Origin`, encryption at rest, only the owner writes
  `knowledge`) to make something easier: build the access the right way (`connect`, a request the user allows).
- The prompts in `src/nuclear_graph/prompts/` are measured (`nuclear-developer/eval`): a change is a new round of the
  evaluation, recorded in its report.
- Checks: `uv sync --extra server --extra test && .venv/bin/python -m pytest -q`.
