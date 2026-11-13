"""The knowledge base as a folder (the `nuclear-knowledge` repository, `nuclear-developer/data`; ADR-0104): the asset
files the Smart Graph ingests, their schema and their version.

- `assets/<shelf>/<name>.json` with `"origin": "generated"`: written here from the working tree (`extract.py`); never
  edited by hand. `<name>.overlay.json` beside one adds hand-written fields to its rows (links, examples, questions).
- `assets/<shelf>/<name>.json` with `"origin": "curated"`: written by hand (the purpose, the concepts, the playbooks,
  the capabilities, the failures). Each row names the `sources` it was written from.
- `manifest.json`: the schema, the revision and every row with its hash and the revision that last changed it; for a
  curated row, the hash of each of its sources when it was last reviewed.

`build` writes what is generated, validates everything and raises the revision when a row changed. `check` fails when
the assets are not what the tree generates now, when a row is invalid, or when a source of a curated row changed since
its review: the base is never left behind the code."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from . import assets, extract
from .assets import Row
from .shelves import SCHEMA, SHELVES, schema

MANIFEST = "manifest.json"
REVISIONS = "revisions.json"
SCHEMA_FILE = "schema.json"
INDEX = "INDEX.md"
MERGED = ("keys", "asks", "tags", "links", "sources", "platforms")  # an overlay adds to these; it replaces the rest


def context(tree: Path, out: Path) -> extract.Context:
    file = out / "sections.toml"
    sections = tomllib.loads(file.read_text()) if file.is_file() else {}
    site = sections.get("website")
    website = Path(site).expanduser() if site and Path(site).expanduser().is_dir() else None
    return extract.Context(tree=tree, website=website, sections=sections)


def overlaid(name: str, rows: list[Row], out: Path, problems: list[str]) -> list[Row]:
    """The generated rows with the hand-written fields of `<name>.overlay.json` merged in by id."""
    file = out / "assets" / f"{name}.overlay.json"
    if not file.is_file():
        return rows
    by_id = {r["id"]: dict(r) for r in rows}
    for extra in assets.read_file(file)["rows"]:
        row = by_id.get(extra.get("id"))
        if row is None:
            problems.append(f"assets/{name}.overlay.json: `{extra.get('id')}` is not a row of {name}.json any more")
            continue
        for key, value in extra.items():
            if key == "add":  # more body, after the generated one
                row["body"] = f"{assets.text_of(row.get('body')).strip()}\n\n{assets.text_of(value).strip()}"
            elif key in MERGED:
                row[key] = [*row.get(key, []), *[v for v in value if v not in row.get(key, [])]]
            elif key == "meta":
                row["meta"] = {**row.get("meta", {}), **value}
            elif key != "id":
                row[key] = value
    return list(by_id.values())


def generated(tree: Path, out: Path, ctx: extract.Context | None = None) -> tuple[dict[str, tuple[str, list[Row]]], list[str]]:
    """Every generated file as the tree gives it now (overlays merged), and what the extraction found wrong."""
    ctx = ctx or context(tree, out)
    files = extract.generate(ctx)
    problems = list(ctx.problems)
    return {name: (about, overlaid(name, rows, out, problems)) for name, (about, rows) in files.items()}, problems


def _files(out: Path, origin: str) -> dict[str, dict[str, Any]]:
    """The asset files of one origin as they are written now: `<shelf>/<name>` → the file."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted((out / "assets").glob("*/*.json")):
        if not path.name.endswith(".overlay.json") and (data := assets.read_file(path)).get("origin", "curated") == origin:
            found[f"{path.parent.name}/{path.stem}"] = data
    return found


def source_hash(ctx: extract.Context, source: str) -> str:
    """The hash of a source of a curated row: a file, or one heading's section of it (`file#Heading`)."""
    rel, _, heading = source.partition("#")
    path = (ctx.website / rel.removeprefix("website/")) if rel.startswith("website/") and ctx.website else ctx.tree / rel
    if not path.is_file():
        return "missing"
    text = path.read_text(errors="replace")
    if heading:
        m = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.M)
        if not m:
            return "missing"
        rest = text[m.end():]
        end = re.search(rf"^#{{1,{len(m.group(1))}}} ", rest, re.M)
        text = rest[: end.start()] if end else rest
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def rows_of(files: dict[str, Any]) -> dict[str, list[Row]]:
    """shelf → rows, from `<shelf>/<name>` → (about, rows) or a file's data."""
    out: dict[str, list[Row]] = {}
    for name, value in files.items():
        out.setdefault(name.split("/", 1)[0], []).extend(value[1] if isinstance(value, tuple) else value["rows"])
    return out


def read_manifest(out: Path) -> dict[str, Any]:
    try:
        return json.loads((out / MANIFEST).read_text())
    except (OSError, ValueError):
        return {"schema": SCHEMA, "revision": 0, "rows": {}, "reviewed": {}}


def write_manifest(out: Path, manifest: dict[str, Any]) -> None:
    """One row per line: a diff of the manifest shows the rows that changed."""
    def block(items: dict[str, Any]) -> list[str]:
        lines = [f"  {json.dumps(k)}: {json.dumps(v, sort_keys=True)}," for k, v in sorted(items.items())]
        return [*lines[:-1], lines[-1].rstrip(",")] if lines else []

    lines = ["{", f' "schema": {manifest["schema"]},', f' "revision": {manifest["revision"]},', ' "rows": {', *block(manifest["rows"]),
             " },", ' "reviewed": {', *block(manifest["reviewed"]), " }", "}"]
    (out / MANIFEST).write_text("\n".join(lines) + "\n")


def index_md(shelves: dict[str, list[Row]], revision: int) -> str:
    lines = ["# The knowledge base of NuclearLang", "", f"Schema {SCHEMA}, revision {revision}. Generated by `nuclear-graph knowledge build`: "
             "the shelves of the Smart Graph, what each one answers and its rows. The row format is in `schema.json`.", ""]
    for name, shelf in SHELVES.items():
        rows = sorted(shelves.get(name, []), key=lambda r: r["id"])
        by_type: dict[str, int] = {}
        for r in rows:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        lines += [f"## {name} — {shelf.answers}", "", shelf.holds, "", f"{len(rows)} rows: " + ", ".join(f"{n} {t}" for t, n in sorted(by_type.items())) + ".", ""]
        if name not in ("docs", "examples") and len(rows) <= 400:
            lines += [f"- `{r['id']}` — {r['title']}" for r in rows] + [""]
    return "\n".join(lines)


def build(tree: Path, out: Path, ctx: extract.Context | None = None, today: str = "") -> dict[str, Any]:
    """Writes the generated assets, validates the whole base and raises the revision when a row changed. With a
    problem nothing is versioned: fix it and build again."""
    ctx = ctx or context(tree, out)
    files, problems = generated(tree, out, ctx)
    for name, (about, rows) in files.items():
        assets.write_file(out / "assets" / f"{name}.json", name.split("/", 1)[0], "generated", about, rows, name.split("/", 1)[1])
    for name in set(_files(out, "generated")) - set(files):  # a generated file the tree no longer gives
        (out / "assets" / f"{name}.json").unlink()
    hand = _files(out, "curated")
    shelves = rows_of({**files, **hand})
    problems += assets.problems(shelves)
    if problems:
        return {"problems": problems, "rows": sum(len(r) for r in shelves.values())}
    old = read_manifest(out)
    hashes = {r["id"]: (shelf, assets.row_hash(r)[:12]) for shelf, rows in shelves.items() for r in rows}
    changed = sorted(i for i, (_, h) in hashes.items() if i in old["rows"] and old["rows"][i][1] != h)
    added = sorted(i for i in hashes if i not in old["rows"])
    removed = sorted(i for i in old["rows"] if i not in hashes)
    revision = old["revision"] + (1 if changed or added or removed or old.get("schema") != SCHEMA else 0)
    touched = {*changed, *added}
    manifest = {"schema": SCHEMA, "revision": revision, "reviewed": {},
                "rows": {i: [shelf, h, revision if i in touched else old["rows"][i][2]] for i, (shelf, h) in hashes.items()}}
    # a curated row is reviewed when it is written or changed; an unchanged one keeps the hashes of its last review
    for data in hand.values():
        for r in data["rows"]:
            if r.get("sources"):
                kept = old["reviewed"].get(r["id"]) if r["id"] not in touched else None
                manifest["reviewed"][r["id"]] = kept or {s: source_hash(ctx, s) for s in r["sources"]}
    if revision != old["revision"]:
        log = json.loads((out / REVISIONS).read_text()) if (out / REVISIONS).is_file() else []
        both = [*added, *changed, *removed]
        log.append({"revision": revision, "date": today or datetime.date.today().isoformat(), "added": len(added), "changed": len(changed),
                    "removed": len(removed), "rows": both[:40] + ([f"… and {len(both) - 40} more"] if len(both) > 40 else [])})
        (out / REVISIONS).write_text(json.dumps(log, indent=1) + "\n")
    if manifest != old:
        write_manifest(out, manifest)
    (out / SCHEMA_FILE).write_text(json.dumps(schema(), indent=1) + "\n")
    (out / INDEX).write_text(index_md(shelves, revision))
    return {"problems": [], "rows": len(hashes), "revision": revision, "added": len(added), "changed": len(changed), "removed": len(removed),
            "shelves": {s: len(r) for s, r in shelves.items()}, "review": stale(ctx, manifest)}


def stale(ctx: extract.Context, manifest: dict[str, Any]) -> list[str]:
    """The curated rows whose source changed since their last review."""
    out = []
    for rid, sources in sorted(manifest.get("reviewed", {}).items()):
        for source, was in sources.items():
            if source_hash(ctx, source) != was:
                out.append(f"review: `{rid}` was written from {source}, which changed: update the row, or confirm it still holds with `nuclear-graph knowledge review {rid}`")
    return out


def check(tree: Path, out: Path, ctx: extract.Context | None = None) -> list[str]:
    """Every way the base is behind the tree: a generated file that is not what the tree gives now, an invalid row, a
    manifest of other rows, a curated row whose source changed."""
    ctx = ctx or context(tree, out)
    files, problems = generated(tree, out, ctx)
    disk = _files(out, "generated")
    for name, (_, rows) in files.items():
        have = {r["id"]: assets.row_hash(r) for r in disk.get(name, {"rows": []})["rows"]}
        want = {r["id"]: assets.row_hash(r) for r in rows}
        if have != want:
            diff = sorted(i for i in {*have, *want} if have.get(i) != want.get(i))
            problems.append(f"stale: assets/{name}.json is not what the tree gives now ({len(diff)} rows: {', '.join(diff[:4])}{'…' if len(diff) > 4 else ''}): `nuclear-graph knowledge build`")
    problems += [f"extra: assets/{name}.json is generated from nothing now: `nuclear-graph knowledge build`" for name in sorted(set(disk) - set(files))]
    shelves = rows_of({**files, **_files(out, "curated")})
    problems += assets.problems(shelves)
    manifest = read_manifest(out)
    hashes = {r["id"]: [shelf, assets.row_hash(r)[:12]] for shelf, rows in shelves.items() for r in rows}
    if {i: v[:2] for i, v in manifest["rows"].items()} != hashes:
        problems.append(f"{MANIFEST} is not the one of these rows (a curated row changed, or it was never built): `nuclear-graph knowledge build`")
    return problems + stale(ctx, manifest)


def review(tree: Path, out: Path, ids: list[str], ctx: extract.Context | None = None) -> list[str]:
    """Records that the curated rows `ids` (every stale one when empty) still hold with their sources as they are."""
    ctx = ctx or context(tree, out)
    manifest = read_manifest(out)
    done = []
    for rid, sources in manifest["reviewed"].items():
        now = {s: source_hash(ctx, s) for s in sources}
        if now != sources and (not ids or rid in ids):
            manifest["reviewed"][rid] = now
            done.append(rid)
    write_manifest(out, manifest)
    return done
