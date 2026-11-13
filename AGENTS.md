# AGENTS.md — nuclear-graph

The Nuclear Smart Graph: the private library of NuclearLang and Dragonfly (one Chroma collection per shelf of typed,
linked rows; EmbeddingGemma), its HTTP server with access control, and the MCP server of the ecosystem. Read README.md
first; the decisions are ADR-0104 (the library) and ADR-0102 (the AI loop) of the `nuclear` repository.

This repository is a folder of the NuclearLang working tree (`nuclear/nuclear-graph`); the platform's rules are the
working tree's `../AGENTS.md` and its state is `../STATUS.md`.

- Never weaken a security rule (token on every route, no `Origin`, encryption at rest, only ingest writes the shelves
  of the base) to make something easier: build the access the right way (`connect`, a request the user allows).
- The knowledge base is rows, not copied documents. What has a structured source is generated (`extract.py`), never
  written by hand; what is written by hand names its sources. `shelves.py` is the schema: a new shelf, type or filter
  is added there, with a test.
- After any change here or in the tree: `nuclear-graph knowledge build`, `knowledge check`, `ingest`,
  `knowledge ask` (every question finds its row), and `python tests/check_examples.py`.
- The prompts in `src/nuclear_graph/prompts/` are measured (`nuclear-developer/eval`): a change is a new round of the
  evaluation, recorded in its report.
- Checks: `uv sync --extra server --extra test && .venv/bin/python -m pytest -q`.
