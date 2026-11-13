"""Fills the shelves of the graph from the knowledge base folder (`nuclear-graph knowledge build` wrote it;
ADR-0104) and the `prompts` collection from this package's prompt files. Only what changed is embedded again; a row
the base no longer has is removed, and what an agent wrote at run time (`origin: runtime`) is kept."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import assets
from .knowledge import read_manifest
from .shelves import SHELVES
from .store import Item, Store

PROMPTS = Path(__file__).parent / "prompts"
BATCH = 64


def prompts() -> list[Item]:
    """The validated prompt of each use case (`prompts/<use_case>.md`) and of each agent step (`agents/<step>.md`:
    `agent.<step>`)."""
    out: list[Item] = []
    files = [(p.stem, p) for p in sorted(PROMPTS.glob("*.md"))]
    files += [(f"agent.{p.stem}", p) for p in sorted((PROMPTS / "agents").glob("*.md")) if p.name != "README.md"]
    for name, path in files:
        text = path.read_text()
        out.append({"id": f"prompt-{name}", "document": text,
                    "meta": {"source": f"prompt:{name}", "kind": "prompt", "use_case": name, "title": name, "hash": hashlib.sha1(text.encode()).hexdigest()}})
    return out


def sync(store: Store, collection: str, items: list[Item], keep: set[str], log=print) -> dict[str, int]:
    """Makes a collection hold exactly `items` (and the ids of `keep`), embedding only the ones whose hash changed."""
    old = store.hashes(collection)
    ids = {i["id"] for i in items}
    new = [i for i in items if old.get(i["id"]) != i["meta"]["hash"]]
    gone = [i for i in old if i not in ids and i not in keep]
    for at in range(0, len(new), BATCH):
        store.put(collection, new[at : at + BATCH])
        log(f"  {collection}: {min(at + BATCH, len(new))} of {len(new)}")
    store.delete(collection, gone)
    return {"added": len(new), "kept": len(items) - len(new), "removed": len(gone)}


def ingest(store: Store, root: Path, log=print) -> dict[str, Any]:
    """The knowledge base folder `root` becomes what the graph knows. An invalid base is refused whole: the graph
    never holds half of a revision."""
    root = root.resolve()
    if not (root / "manifest.json").is_file() or not (root / "assets").is_dir():
        raise ValueError(f"{root} is not a knowledge base (no manifest.json and assets/): build it with `nuclear-graph knowledge build`")
    manifest = read_manifest(root)
    loaded = assets.load(root)
    problems = assets.problems({shelf: [row for row, _ in rows] for shelf, rows in loaded.items()})
    if problems:
        raise ValueError("the knowledge base is not valid:\n" + "\n".join(problems[:20]))
    result: dict[str, Any] = {}
    for shelf in SHELVES:
        items = [f for row, origin in loaded.get(shelf, [])
                 for f in assets.facets(row, shelf, origin, (manifest["rows"].get(row["id"]) or [0, 0, 0])[2])]
        runtime = {i["id"] for i in store.where(shelf, {"origin": "runtime"})}
        result[shelf] = sync(store, shelf, items, runtime, log)
    result["prompts"] = sync(store, "prompts", prompts(), set(), log)
    store.set_version(manifest["schema"], manifest["revision"])
    if gone := store.drop_legacy():
        log(f"  removed the collections of before the shelves: {', '.join(gone)}")
    return {**result, "version": store.version()}
