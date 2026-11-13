# AGENTS.md — nuclear-graph

The Nuclear Smart Graph: the private library of NuclearLang and Dragonfly (one Chroma collection per shelf of typed,
linked rows; EmbeddingGemma; the exact facts in SQLite, in memory), its HTTP server with access control, and the MCP
server of the ecosystem. Read README.md first; the decisions are ADR-0104 (the library), ADR-0107 (the exact facts and
the query planner; the graph written in Nuclear) and ADR-0102 (the AI loop) of the `nuclear` repository.

**It is written in Nuclear** (the `python` dialect; `nuclear.toml`): the `.nuc` files of this folder are the source,
`nuclear build .` writes the Python package into `build/nuclear_graph` (never edited, never committed) and
`pyproject.toml` packages that folder. After a change: `nuclear check .`, `nuclear build .`, the tests. What Nuclear
cannot express is a finding of the compiler for `../STATUS.md`, never a `.py` file written by hand.

This repository is a folder of the NuclearLang working tree (`nuclear/nuclear-graph`); the platform's rules are the
working tree's `../AGENTS.md` and its state is `../STATUS.md`.

- Never weaken a security rule (token on every route, no `Origin`, encryption at rest, only ingest writes the shelves
  of the base) to make something easier: build the access the right way (`connect`, a request the user allows). The
  exact facts are never written to disk: the database is made in memory from the sealed cards (`facts.nuc`).
- The knowledge base is rows, not copied documents. What has a structured source is generated (the `extract_*.nuc`
  modules), never written by hand; what is written by hand names its sources. `shelves.nuc` is the schema: a new
  shelf, type or filter is added there, with a test.
- A question with one right answer (which, how many, what are) is a row of `assets/queries/` over the views of
  `facts.nuc`, never a card someone keeps in step by hand: a new kind of fact is a view, a new question a row with
  its parameters, and an entry of `questions.toml` with `exact = true`.
- After any change here or in the tree: `nuclear-graph knowledge build`, `knowledge check`, `ingest`,
  `knowledge ask` (every question finds its row), and `knowledge examples` (every Nuclear example compiles).
- The prompts in `prompts/` are measured (`nuclear-developer/eval`): a change is a new round of the
  evaluation, recorded in its report.
- Checks: `nuclear check . && nuclear build . && uv sync --extra server --extra test && .venv/bin/python -m pytest -q`
  (the tests are `tests/*.nuc`).
