# Changelog

All notable changes to nuclear-graph are written here; versions follow [Semantic Versioning](https://semver.org).

## Unreleased

- First public version (ADR-0102): the private knowledge base (Chroma + EmbeddingGemma, documents AES-GCM encrypted,
  key and owner token in the keyring, a server on 127.0.0.1 with per-client tokens the user allows), ingest by hash,
  the knowledge base build (`nuclear-graph knowledge build|check`, the `nuclear-knowledge` repository), the agents'
  prompts as files, the web tools (`web.py`).
- MCP server: the graph, the Nuclear Developer's agents (`developer_*`, local first, `developer_review`), and the
  generators (ADR-0103): `project_inspect`, `generate_component|resource|screen`, `api_inspect`, `web_search`,
  `web_read`.
