"""developer_task writes a spec the Loop reads; developer_review keeps the lead's review next to the journal."""

import asyncio
import re
from pathlib import Path

from nuclear_graph import mcp_server as m


def test_every_tool_is_in_the_readme_and_in_the_documentation():
    """A tool added to the server is documented in the same change: the README and docs/ai/mcp.md name it."""
    repo = Path(m.__file__).resolve().parents[2]
    names = re.findall(r"@mcp\.tool\(\)\nasync def (\w+)", Path(m.__file__).read_text())
    assert len(names) > 20
    pages = [repo / "README.md", repo.parent / "docs" / "ai" / "mcp.md"]  # the second exists only in the working tree
    for page in filter(Path.exists, pages):
        text = page.read_text()
        assert [n for n in names if f"`{n}" not in text] == [], page


def test_a_machine_of_remote_agents_only_offers_no_local_tool(monkeypatch):
    """ADR-0106: set up for remote agents only, the server offers no tool that needs the graph or the local developer,
    and its instructions ask for neither."""
    import asyncio
    import importlib

    monkeypatch.setenv("NUCLEAR_AI_MODE", "remote")
    remote = importlib.reload(m)
    try:
        names = [t.name for t in asyncio.run(remote.mcp.list_tools())]
        assert "generate_resource" in names and "nuclear_check" in names
        assert [n for n in names if n.startswith(("graph_", "developer_"))] == []
        told = remote.REMOTE_LEAD + remote.GENERATORS + remote.REMOTE
        assert "graph_strategy" not in told and "developer_task" not in told and "generate_resource" in told
    finally:
        monkeypatch.delenv("NUCLEAR_AI_MODE")
        importlib.reload(m)
    assert "graph_strategy" in [t.name for t in asyncio.run(m.mcp.list_tools())]


def test_the_spec_is_led_by_the_local_agents():
    text = m.spec_markdown("Books by author", "List the books of an author.", ["404 for nobody"], "feature")
    assert "- Lead: local agents only" in text
    assert "## Acceptance criteria\n\n- [ ] 404 for nobody" in text


def test_a_review_is_appended_to_the_run(tmp_path):
    (tmp_path / "config.nuc").write_text("")
    runs = tmp_path / ".nuclear" / "loop" / "runs"
    runs.mkdir(parents=True)
    (runs / "books.json").write_text("{}")
    sub = tmp_path / "components"
    sub.mkdir()
    out = asyncio.run(m.developer_review(str(sub), "books", "Fixed the alias."))
    assert out.startswith("review kept in")
    assert "Fixed the alias." in (runs / "books.review.md").read_text()
    assert asyncio.run(m.developer_review(str(tmp_path), "nope", "x")).startswith("no run")
    assert "not a .nuc file" in asyncio.run(m.developer_review(str(tmp_path), "books", "x", ["../etc/passwd"]))


def test_api_inspect_shows_the_shape_of_an_answer():
    answer = {"info": {"count": 2, "next": None}, "results": [{"id": 1, "name": "Rick", "origin": {"name": "Earth"}, "episode": ["a"]}]}
    text = m.shape(answer)
    assert "info: object\n  count: int\n  next: null (optional)" in text
    assert "results: list of\n  id: int\n  name: string\n  origin: object\n    name: string" in text
    assert asyncio.run(m.api_inspect("http://127.0.0.1:7879/x")).startswith("not read")


def test_generate_resource_passes_every_option_to_the_cli(monkeypatch):
    seen: list[list[str]] = []

    async def fake(root: str, args: list[str], timeout: int = 900) -> str:
        seen.append(args)
        return "exit 0"

    monkeypatch.setattr(m.tools, "dragonfly", fake)
    asyncio.run(m.generate_resource("/p", "characters", "Character", from_json="https://x/api/character", actions=["list", "get"], screen="list", dry_run=True))
    assert seen[0] == ["gen", "resource", "characters", "Character", "--from-json", "https://x/api/character", "--screen", "list", "--actions", "list,get", "--dry-run"]
    asyncio.run(m.generate_usecase("/p", "orders", "CancelOrder", route="POST orders/{id}/cancel"))
    asyncio.run(m.generate_usecase("/p", "orders", "PendingOrders", calls="OrderRepository.pending", dry_run=True))
    assert seen[1:] == [
        ["gen", "usecase", "orders", "CancelOrder", "--route", "POST orders/{id}/cancel"],
        ["gen", "usecase", "orders", "PendingOrders", "--calls", "OrderRepository.pending", "--dry-run"],
    ]
