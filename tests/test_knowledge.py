"""The knowledge base (ADR-0104): rows read from their sources, a base that is valid or not built, revisions that
rise only when a row changes, a check that finds what is behind the tree, and an ingest that embeds only what changed."""

import json
from pathlib import Path

import pytest

from nuclear_graph import assets, extract, knowledge
from nuclear_graph.ingest import ingest
from nuclear_graph.store import Store

from test_graph import fake_embed, row

SECTIONS = '''
exclude = ["spec/diagnostics.md"]
[[section]]
id = "01-language"
title = "Language"
shelf = "language"
files = ["spec/nuclear-base.md"]
[[section]]
id = "02-targets"
title = "Targets"
agents = false
files = ["spec/python.md"]
'''
CODES = '''
    pub const LIBRARY_NAME: Code = Code {
        id: "N0114",
        title: "not a member of Nuclear's standard library",
        explanation: "The members are Nuclear's own: a target's name (push) is replaced by the \\"Nuclear\\" one.",
    };
'''


def tree(tmp: Path) -> tuple[Path, Path]:
    root, out = tmp / "tree", tmp / "data"
    for rel, text in {
        "spec/nuclear-base.md": "# Base\n\nBlocks are indented.\n\n## Lists\n\nA list is `[1, 2]`, never this:\n\n```python\nxs.append(1)\n```\n\nUse `add`, a method of every list in Nuclear.\n",
        "spec/python.md": "# Python\n\nWhat Nuclear becomes in Python, with every rule of the dialect.\n",
        "spec/diagnostics.md": "# Diagnostics\n\n## Resolver\n\n| Code | Error | Example | Fix |\n|---|---|---|---|\n| N0114 | Not a member of the library | `xs.push(x)` | `add(x)` |\n",
        "crates/nuclear-diag/src/lib.rs": CODES,
        "docs/aprende/x.md": "private teaching material, never part of the base",
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    (out / "assets" / "concepts").mkdir(parents=True)
    (out / "sections.toml").write_text(SECTIONS)
    return root, out


def context(root: Path, out: Path) -> extract.Context:
    ctx = knowledge.context(root, out)
    ctx.run, ctx.mcp, ctx.graph_help = (lambda cmd: None), (lambda: ("", [])), (lambda: "")
    return ctx


def curated(out: Path, *rows: dict, name: str = "concepts/purpose") -> None:
    assets.write_file(out / "assets" / f"{name}.json", name.split("/")[0], "curated", "by hand", list(rows))


def test_rows_are_read_from_their_sources(tmp_path):
    root, out = tree(tmp_path)
    r = knowledge.build(root, out, context(root, out), today="2026-01-01")
    assert r["problems"] == [] and r["revision"] == 1 and r["shelves"] == {"errors": 1, "language": 1, "docs": 1}
    (error,) = json.loads((out / "assets/errors/diagnostics.json").read_text())["rows"]
    assert error["id"] == "error:N0114" and error["keys"][0] == "n0114" and error["meta"]["family"] == "resolver"
    assert 'the "Nuclear" one' in "\n".join(error["body"]) and "**Fix.** `add(x)`" in error["body"]
    lists = next(x for x in json.loads((out / "assets/language/01-language.json").read_text())["rows"] if x["id"].endswith("#lists"))
    assert "python" not in "\n".join(lists["body"]) and "Use `add`" in "\n".join(lists["body"])  # a local agent reads no target code
    target = json.loads((out / "assets/docs/02-targets.json").read_text())["rows"][0]
    assert target["agents"] is False and target["type"] == "spec"
    assert not any("aprende" in p.as_posix() for p in out.rglob("*")) and "private teaching" not in (out / "manifest.json").read_text()
    assert knowledge.check(root, out, context(root, out)) == []


def test_the_base_is_valid_or_it_is_not_versioned(tmp_path):
    root, out = tree(tmp_path)
    (root / "notes.md").write_text("# Notes\n\nA document that no section of sections.toml names at all.\n")
    curated(out, row("concept:mcp", type="concept", links=[{"rel": "see", "to": "tool:nowhere"}], body="```python\nprint(1)\n```"),
            row("error:N0114", type="concept"))
    src = root / "crates/nuclear-diag/src/lib.rs"
    src.write_text(src.read_text() + CODES.replace("N0114", "N0999").replace("LIBRARY_NAME", "NEW_ONE"))
    problems = "\n".join(knowledge.build(root, out, context(root, out))["problems"])
    for expected in ("N0999 (NEW_ONE) is not documented", "notes.md: no section", "links to `tool:nowhere`", "code of ['python']",
                     "the id is also in", "prefix `error` is not of this shelf"):
        assert expected in problems
    assert not (out / "manifest.json").exists()


def test_a_revision_rises_only_when_a_row_changes(tmp_path):
    root, out = tree(tmp_path)
    curated(out, row("concept:mcp", type="concept", sources=["spec/nuclear-base.md#Lists"]))
    assert knowledge.build(root, out, context(root, out))["revision"] == 1
    assert knowledge.build(root, out, context(root, out))["revision"] == 1
    spec = root / "spec/diagnostics.md"
    spec.write_text(spec.read_text().replace("Not a member of the library", "Not a member of Nuclear's library"))
    assert any(p.startswith("stale: assets/errors/diagnostics.json") for p in knowledge.check(root, out, context(root, out)))
    r = knowledge.build(root, out, context(root, out))
    assert (r["revision"], r["changed"]) == (2, 1)
    rows = knowledge.read_manifest(out)["rows"]
    assert rows["error:N0114"][2] == 2 and rows["concept:mcp"][2] == 1  # each row knows the revision that last changed it
    assert [e["revision"] for e in json.loads((out / "revisions.json").read_text())] == [1, 2]


def test_a_hand_written_row_is_reviewed_when_its_source_changes(tmp_path):
    root, out = tree(tmp_path)
    curated(out, row("concept:mcp", type="concept", sources=["spec/nuclear-base.md#Lists"]))
    knowledge.build(root, out, context(root, out))
    base = root / "spec/nuclear-base.md"
    base.write_text(base.read_text().replace("Blocks are indented.", "Blocks are indented by two spaces."))  # another section
    knowledge.build(root, out, context(root, out))
    assert not [p for p in knowledge.check(root, out, context(root, out)) if p.startswith("review")]
    base.write_text(base.read_text().replace("Use `add`", "Use `add` or `addAll`"))  # the section the row was written from
    knowledge.build(root, out, context(root, out))
    (stale,) = [p for p in knowledge.check(root, out, context(root, out)) if p.startswith("review")]
    assert "`concept:mcp` was written from spec/nuclear-base.md#Lists" in stale
    assert knowledge.review(root, out, [], context(root, out)) == ["concept:mcp"]
    assert knowledge.check(root, out, context(root, out)) == []


def test_an_overlay_adds_hand_written_fields_to_generated_rows(tmp_path):
    root, out = tree(tmp_path)
    (out / "assets/errors").mkdir()
    (out / "assets/errors/diagnostics.overlay.json").write_text(json.dumps({"rows": [
        {"id": "error:N0114", "add": ["**Right.** `xs.add(x)`."], "keys": ["push"], "agents": False, "meta": {"kinds": ["usecase"]}},
        {"id": "error:N0001", "tags": ["gone"]}]}))
    r = knowledge.build(root, out, context(root, out))
    assert r["problems"] == ["assets/errors/diagnostics.overlay.json: `error:N0001` is not a row of errors/diagnostics.json any more"]
    (out / "assets/errors/diagnostics.overlay.json").write_text(json.dumps({"rows": [
        {"id": "error:N0114", "add": ["**Right.** `xs.add(x)`."], "keys": ["push"], "agents": False, "meta": {"kinds": ["usecase"]}}]}))
    assert knowledge.build(root, out, context(root, out))["problems"] == []
    (error,) = json.loads((out / "assets/errors/diagnostics.json").read_text())["rows"]
    assert error["body"][-1] == "**Right.** `xs.add(x)`." and error["keys"][-1] == "push" and error["agents"] is False
    assert error["meta"] == {"code": "N0114", "family": "resolver", "severity": "error", "kinds": ["usecase"]}


def test_an_ingest_embeds_only_what_changed_and_keeps_what_agents_wrote(tmp_path):
    root, out = tree(tmp_path)
    curated(out, row("concept:mcp", type="concept", asks=["how does the mcp work"]))
    knowledge.build(root, out, context(root, out))
    calls: list[int] = []
    store = Store(str(tmp_path / "db"), key=b"k" * 32, embed=lambda t: calls.append(len(t)) or fake_embed(t))
    first = ingest(store, out, log=lambda _: None)
    assert first["concepts"]["added"] == 2 and first["errors"]["added"] == 1 and first["version"] == {"schema": 1, "revision": 1}
    assert store.stats()["prompts"] >= 8
    store.put("examples", [("review-1", "a corrected file", {"origin": "runtime", "hash": "x"})])
    calls.clear()
    again = ingest(store, out, log=lambda _: None)
    assert again["concepts"] == {"added": 0, "kept": 2, "removed": 0} and calls == []
    assert store.stats()["examples"] == 1  # what an agent kept at run time survives
    curated(out, row("concept:graph", type="concept"))
    knowledge.build(root, out, context(root, out))
    third = ingest(store, out, log=lambda _: None)
    assert third["concepts"] == {"added": 1, "kept": 0, "removed": 2} and third["version"]["revision"] == 2
    curated(out, row("concept:graph", type="concept", links=[{"rel": "see", "to": "concept:none"}]))
    with pytest.raises(ValueError, match="not valid"):
        ingest(store, out, log=lambda _: None)
    with pytest.raises(ValueError, match="not a knowledge base"):
        ingest(store, root, log=lambda _: None)


def test_a_help_text_becomes_one_row_per_command(tmp_path):
    help_text = "x: a tool\n\nusage:\n  nuclear build <file.nuc> --dialect <name>   transpile (prints to stdout)\n  nuclear build <folder> [-o <out>]          transpile a project\n" \
                "  nuclear check <folder> [--json]            report the errors of every file\n                                             of a project\n\ndocumentation: nuclear help <topic>\n  guide   the guide\n"
    ctx = extract.Context(tree=tmp_path, run=lambda cmd: help_text if cmd == ["nuclear", "help"] else None, graph_help=lambda: "")
    rows = {r["id"]: r for r in extract.cli(ctx)}
    assert set(rows) == {"tool:nuclear.build", "tool:nuclear.check", "tool:nuclear"}
    assert rows["tool:nuclear.build"]["summary"] == "Transpile (prints to stdout); Transpile a project"
    assert rows["tool:nuclear.check"]["summary"] == "Report the errors of every file of a project" and rows["tool:nuclear.check"]["keys"] == ["nuclear check"]
    assert "guide   the guide" in rows["tool:nuclear"]["body"]


def test_the_knowledge_base_of_this_tree_is_what_the_tree_gives_now():
    """The real nuclear-developer/data (skipped outside the working tree): `nuclear-graph knowledge build` when it fails."""
    root = Path(__file__).resolve().parents[2]
    out = root / "nuclear-developer" / "data"
    if not (out / "sections.toml").is_file():
        pytest.skip("not inside the NuclearLang working tree")
    problems = knowledge.check(root, out)
    assert problems == [], "nuclear-graph knowledge build, review, then ingest:\n" + "\n".join(problems[:20])
