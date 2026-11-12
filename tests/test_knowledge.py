"""The knowledge folder is every source file byte for byte, ordered by its sections; a changed comma is found."""

from pathlib import Path

from nuclear_graph import knowledge
from nuclear_graph.ingest import ingest
from nuclear_graph.store import Store

from test_graph import fake_embed


def tree(tmp: Path) -> tuple[Path, Path]:
    root = tmp / "tree"
    (root / "spec").mkdir(parents=True)
    (root / "spec" / "nuclear-base.md").write_text("# Base\n\nRules, with commas.\n")
    (root / "spec" / "python.md").write_text("# Python\n\nWhat Nuclear becomes in Python.\n")
    (root / "docs" / "aprende").mkdir(parents=True)
    (root / "docs" / "aprende" / "x.md").write_text("private")
    (root / "notes.md").write_text("no section names me")
    out = tmp / "data"
    out.mkdir()
    (out / "README.md").write_text("the repository's own file")
    (out / "sections.toml").write_text(
        '[[section]]\nid = "01-language"\ntitle = "Language"\nfiles = ["spec/nuclear-base.md"]\n\n'
        '[[section]]\nid = "02-targets"\ntitle = "Targets"\nagents = false\nfiles = ["spec/python.md"]\n'
    )
    return root, out


def test_a_build_copies_every_file_and_the_check_finds_a_comma(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "HELP", [])
    root, out = tree(tmp_path)
    r = knowledge.build(root, out, None)
    assert r["files"] == 3 and r["unclaimed"] == ["notes.md"]
    assert (out / "01-language/spec/nuclear-base.md").read_text() == "# Base\n\nRules, with commas.\n"
    assert (out / "99-other/notes.md").exists() and (out / "README.md").exists()
    assert not any("aprende" in p.as_posix() for p in out.rglob("*"))
    assert knowledge.check(root, out, None) == []
    (root / "spec" / "nuclear-base.md").write_text("# Base\n\nRules with commas.\n")
    assert any(p.startswith("changed: 01-language/spec/nuclear-base.md") for p in knowledge.check(root, out, None))


def test_the_agents_read_only_the_sections_for_them(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "HELP", [])
    root, out = tree(tmp_path)
    knowledge.build(root, out, None)
    store = Store(str(tmp_path / "db"), key=b"k" * 32, embed=fake_embed)
    ingest(store, [out], log=lambda _: None)
    agents = {i["meta"]["source"] for i in store.get("nuclear", {"repo": {"$ne": "__none__"}})}
    assert "tree:spec/nuclear-base.md" in agents
    assert "tree:spec/python.md" not in agents


def test_the_knowledge_base_of_this_tree_is_complete():
    """The real nuclear-developer/data: every source copied byte for byte (skipped outside the working tree)."""
    import pytest

    root = Path(__file__).resolve().parents[2]
    out = root / "nuclear-developer" / "data"
    if not (out / "sections.toml").is_file():
        pytest.skip("not inside the NuclearLang working tree")
    problems = knowledge.check(root, out, knowledge.website_of(out))
    assert problems == [], "nuclear-graph knowledge build, then ingest it:\n" + "\n".join(problems[:20])
