"""The shelves of the Nuclear Smart Graph (ADR-0104): the schema of the knowledge base. A shelf is a Chroma
collection that answers one kind of question; a row is one card of it. This file is the schema itself:
`nuclear-graph knowledge build` writes it as `schema.json` in the knowledge base, and the store, the ingest and the
search read it from here."""

from __future__ import annotations

from dataclasses import dataclass

# The row format. It changes only when a row written with the old one could no longer be read.
SCHEMA = 1


@dataclass(frozen=True)
class Shelf:
    answers: str  # the question a reader brings to this shelf
    holds: str  # what its rows are
    types: tuple[str, ...]  # `type` of a row
    prefixes: tuple[str, ...]  # an id is `<prefix>:<name>`; a prefix lives in exactly one shelf
    meta: tuple[str, ...] = ()  # the metadata of its own a search may filter by, besides the common ones


SHELVES: dict[str, Shelf] = {
    "concepts": Shelf(
        "What is it, why does it exist, how does it work?",
        "The purpose of NuclearLang and Dragonfly, the ideas behind them, the parts of the ecosystem, the theory a "
        "reader needs and the questions people ask.",
        ("purpose", "concept", "theory", "architecture", "comparison", "faq", "term"),
        ("concept", "faq", "term"),
        ("topic",),
    ),
    "language": Shelf(
        "How is it written in Nuclear?",
        "The base language: its guide and rules section by section, and every member of the standard library.",
        ("guide", "rule", "library", "reference"),
        ("lang", "lib"),
        ("base",),
    ),
    "platforms": Shelf(
        "What does a platform have, and where does each thing go?",
        "The three platforms of Dragonfly: their kinds, decorators, layout, plugins and rules.",
        ("platform", "kind", "decorator", "layout", "plugin", "spec"),
        ("platform", "kind", "decorator", "layout", "plugin", "spec"),
        ("kind", "name"),
    ),
    "tools": Shelf(
        "What can run, and how is it called?",
        "Every tool of the ecosystem: the commands of the four CLIs, the MCP tools, the HTTP routes, the generators, "
        "the stages of the Loop, the local agents, the editors' commands and each component's version.",
        ("cli", "mcp", "http", "generator", "stage", "agent", "editor", "service", "component"),
        ("tool", "mcp", "http", "generator", "stage", "agent", "editor", "service", "component"),
        ("tool", "name", "writes", "version"),
    ),
    "errors": Shelf(
        "What went wrong, and how is it fixed?",
        "Every diagnostic of the compiler, the habits of other languages, the failures of the tools and the services, "
        "and the mistakes small models repeat; each one linked to the ones it comes with.",
        ("diagnostic", "habit", "failure", "pitfall"),
        ("error", "habit", "failure", "pitfall"),
        ("code", "family", "severity", "kinds"),
    ),
    "capabilities": Shelf(
        "Can it be done, by NuclearLang or by this agent?",
        "What the ecosystem can do, what it cannot do yet, its limits, and the limits of the local agents: when a "
        "task is beyond them and who takes it.",
        ("can", "cannot", "limit", "agent-limit"),
        ("can", "cannot", "limit"),
        # `triggers`: the words of a spec that mean the row applies to it (a search by them is exact, not by meaning)
        ("area", "status", "triggers"),
    ),
    "playbooks": Shelf(
        "How is this task done, step by step, and by whom?",
        "The strategy of each kind of request (a whole system, one screen, a rename, a failing test...): how it is "
        "recognised and its plan, with the tool of every step; the procedures of each use case; the roles of the "
        "developer (developer, tester, security, devops...) and their skills.",
        ("strategy", "playbook", "role", "skill"),
        ("strategy", "playbook", "role", "skill"),
        # a strategy's own: `family` (create, change, fix, verify, beyond), `scope` (system, component, resource,
        # layer, declaration, member, project) and `triggers`, the words of a request that point to it
        ("use_case", "role", "family", "scope", "triggers"),
    ),
    "examples": Shelf(
        "What does the code look like?",
        "Validated Nuclear: every file of the example projects by kind and platform, and solved tasks.",
        ("file", "solved"),
        ("example", "solved"),
        ("kind", "name", "project", "validated"),
    ),
    "docs": Shelf(
        "What does the full document say?",
        "The long form, section by section: the dialects underneath, the target languages, the runtimes, every "
        "decision (ADR), the context files, the guides, the changelogs and the state of the project.",
        ("spec", "adr", "context", "guide", "readme", "changelog", "status", "doc"),
        ("doc",),
        ("section", "repo", "dialect"),
    ),
}

# Not made from the knowledge base: the prompt files of this package, and what agents keep about a project.
RUNTIME = ("prompts", "memory")
COLLECTIONS = (*SHELVES, *RUNTIME)
# The collections of before ADR-0104: an ingest removes them.
LEGACY = ("knowledge", "nuclear")

PLATFORMS = ("backend", "mobile", "web")
# The metadata every row has (in clear in Chroma: names and keys, never the text).
COMMON = ("card", "facet", "type", "title", "agents", "platforms", "keys", "tags", "links", "origin", "source", "hash")

SHELF_OF = {prefix: name for name, shelf in SHELVES.items() for prefix in shelf.prefixes}


def shelf_of(row_id: str) -> str:
    """The shelf an id lives in, by its prefix ("" for an id no shelf holds)."""
    return SHELF_OF.get(row_id.split(":", 1)[0], "")


def schema() -> dict:
    """The schema as data (what `schema.json` holds)."""
    return {
        "schema": SCHEMA,
        "row": {
            "id": "`<prefix>:<name>`, unique in the whole base and stable: links and direct lookups use it",
            "type": "one of its shelf's types",
            "title": "what the row is, in a line (the title the embedding model reads)",
            "summary": "the answer in one or two sentences (embedded with the start of the body)",
            "body": "the whole card, markdown, as a text or a list of lines; Nuclear only when `agents` is true",
            "keys": "exact names in lower case (a code, a command, a kind): a query that writes one finds the row",
            "asks": "questions the row answers, as a person writes them: each one is a search vector of its own",
            "tags": "free words to filter by",
            "platforms": "backend, mobile, web; left out = every platform",
            "agents": "false = only frontier models and people read it (target languages, dialect internals)",
            "links": "typed edges to other rows: [{rel, to}]; a link to a row that does not exist fails the build",
            "sources": "the files (or `file#Heading`) the row was written from: when one changes, the row is reviewed",
            "meta": "the shelf's own filter fields",
            "data": "machine-readable fields of the type (a command's usage; a strategy's signals, stages and needs)",
        },
        "common_metadata": list(COMMON),
        "shelves": {
            name: {"answers": s.answers, "holds": s.holds, "types": list(s.types), "prefixes": list(s.prefixes), "meta": list(s.meta)}
            for name, s in SHELVES.items()
        },
        "runtime_collections": list(RUNTIME),
    }
