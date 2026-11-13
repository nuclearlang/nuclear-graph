"""The rows of the knowledge base (ADR-0104): how an asset file is read, what makes a row valid, what of a row is
embedded and what is stored. An asset file is `assets/<shelf>/<name>.json`: `{shelf, origin, about, rows}`; a file
`<name>.overlay.json` holds hand-written fields that the build merges into the generated rows of `<name>.json`."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .shelves import PLATFORMS, SHELVES, shelf_of

Row = dict[str, Any]

LISTS = ("keys", "asks", "tags", "platforms", "links", "sources")
# what a local agent may read inside a fence: Nuclear, a command line, plain text, data
AGENT_FENCES = ("", "nuclear", "sh", "text", "console", "json")
EMBEDDED = 1200  # characters of the body the embedding reads, after the summary


def text_of(value: Any) -> str:
    """A body is a text or a list of lines (lines read and diff better inside JSON)."""
    return "\n".join(value) if isinstance(value, list) else str(value or "")


def normal(row: Row) -> Row:
    """The row with every field present."""
    out = dict(row)
    out["body"] = text_of(row.get("body")).strip()
    out["summary"] = text_of(row.get("summary")).strip()
    for name in LISTS:
        out[name] = list(row.get(name) or [])
    out["agents"] = bool(row.get("agents", True))
    out["meta"] = dict(row.get("meta") or {})
    out["data"] = dict(row.get("data") or {})
    return out


def nuclear_only(text: str) -> str:
    """The text without the code blocks of a target language (```python, ```dart, ```typescript...) and without what
    a dialect writes underneath a word (the `**Underneath (dialect):**` note): what a local agent reads."""
    out, keep, fence = [], True, False
    for line in text.splitlines():
        if line.startswith("**Underneath ("):
            continue
        if line.lstrip().startswith("```"):
            if not fence:
                keep = line.strip()[3:].strip().lower() in AGENT_FENCES
            fence = not fence
            if keep:
                out.append(line)
            continue
        if keep or not fence:
            out.append(line)
    return "\n".join(out)


def foreign_fences(text: str) -> list[str]:
    """The languages of the fences a local agent must not read."""
    found, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if not fence and (lang := line.strip()[3:].strip().lower()) not in AGENT_FENCES:
                found.append(lang)
            fence = not fence
    return found


def row_hash(row: Row) -> str:
    return hashlib.sha1(json.dumps(normal(row), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def problems(shelves: dict[str, list[Row]]) -> list[str]:
    """Everything that makes the base invalid: a row is fixed, never ingested half right."""
    out: list[str] = []
    seen: dict[str, str] = {}
    for shelf, rows in shelves.items():
        spec = SHELVES.get(shelf)
        if spec is None:
            out.append(f"{shelf}: not a shelf (shelves: {', '.join(SHELVES)})")
            continue
        for raw in rows:
            row = normal(raw)
            rid = str(row.get("id", ""))
            where = f"{shelf}/{rid or '?'}"
            if not re.fullmatch(r"[a-z-]+:[A-Za-z0-9_.@/#+-]+", rid):
                out.append(f"{where}: an id is `<prefix>:<name>` (letters, digits, . _ - / # @ +)")
                continue
            if rid in seen:
                out.append(f"{where}: the id is also in {seen[rid]}")
            seen[rid] = shelf
            if shelf_of(rid) != shelf:
                out.append(f"{where}: the prefix `{rid.split(':')[0]}` is not of this shelf ({', '.join(spec.prefixes)})")
            if row.get("type") not in spec.types:
                out.append(f"{where}: type `{row.get('type')}` is not of this shelf ({', '.join(spec.types)})")
            title = str(row.get("title", ""))
            if not 3 <= len(title) <= 140:
                out.append(f"{where}: the title has {len(title)} characters (3 to 140)")
            if not row["summary"] or len(row["summary"]) > 420:
                out.append(f"{where}: the summary has {len(row['summary'])} characters (1 to 420)")
            if not row["body"]:
                out.append(f"{where}: no body")
            for name in ("keys", "asks", "tags", "platforms", "sources"):
                if any(not isinstance(v, str) or not v for v in row[name]):
                    out.append(f"{where}: `{name}` is a list of texts")
            if any(k != k.lower() for k in row["keys"]):
                out.append(f"{where}: keys are written in lower case")
            if bad := [p for p in row["platforms"] if p not in PLATFORMS]:
                out.append(f"{where}: unknown platform {bad} ({', '.join(PLATFORMS)})")
            if bad := [k for k in row["meta"] if k not in spec.meta]:
                out.append(f"{where}: meta {bad} is not of this shelf ({', '.join(spec.meta) or 'none'})")
            if any(not isinstance(v, (str, int, float, bool)) and not _texts(v) for v in row["meta"].values()):
                out.append(f"{where}: a meta value is a text, a number, a boolean or a list of texts")
            if row["agents"] and (langs := foreign_fences(row["body"])):
                out.append(f"{where}: a row the local agents read has code of {sorted(set(langs))}: Nuclear only, or `agents: false`")
            for link in row["links"]:
                if not isinstance(link, dict) or not link.get("rel") or not link.get("to"):
                    out.append(f"{where}: a link is {{rel, to}}")
    for shelf, rows in shelves.items():
        for raw in rows:
            for link in normal(raw)["links"]:
                if isinstance(link, dict) and link.get("to") and link["to"] not in seen:
                    out.append(f"{shelf}/{raw.get('id')}: links to `{link['to']}`, which no row has")
    return out


def _texts(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) for v in value)


def envelope(row: Row, shelf: str) -> str:
    """What is stored (encrypted) for a row: the card a search answers."""
    r = normal(row)
    card = {"v": 1, "id": r["id"], "shelf": shelf, "type": r["type"], "title": r["title"], "summary": r["summary"],
            "body": r["body"], "links": r["links"], "sources": r["sources"], "data": r["data"]}
    return json.dumps(card, ensure_ascii=False)


def card_of(document: str) -> dict[str, Any] | None:
    """The card of a stored document; None for a plain text (what an agent kept at run time)."""
    if not document.startswith('{"v": 1,'):
        return None
    try:
        return json.loads(document)
    except ValueError:
        return None


def render(card: dict[str, Any]) -> str:
    """A card as the text a model reads."""
    body, summary = card["body"], card["summary"]
    lead = "" if body.startswith(summary[:60]) else f"{summary}\n\n"
    return f"[{card['shelf']}/{card['type']}] {card['title']}\n\n{lead}{body}"


def metadata(row: Row, shelf: str, origin: str, rev: int = 0) -> dict[str, Any]:
    """The metadata of a row in Chroma: names, keys and filters, never the text. A list is never stored empty."""
    r = normal(row)
    meta: dict[str, Any] = {
        "card": r["id"], "facet": "card", "type": r["type"], "title": r["title"], "agents": r["agents"],
        "platforms": r["platforms"] or ["all"], "origin": origin, "source": (r["sources"] or [""])[0],
        "hash": row_hash(row), "rev": rev,
    }
    for name, value in (("keys", r["keys"]), ("tags", r["tags"]), ("links", [link["to"] for link in r["links"]])):
        if value:
            meta[name] = sorted(set(value))
    meta.update(r["meta"])
    return meta


def facets(row: Row, shelf: str, origin: str, rev: int = 0) -> list[dict[str, Any]]:
    """What a row becomes in its collection: the card (found by its title, summary and the start of its body) and one
    entry per question it answers. Each is {id, title, embed, document, meta}."""
    r = normal(row)
    meta = metadata(row, shelf, origin, rev)
    out = [{"id": r["id"], "title": r["title"], "embed": f"{r['summary']}\n\n{r['body'][:EMBEDDED]}".strip(),
            "document": envelope(row, shelf), "meta": meta}]
    for n, ask in enumerate(r["asks"], 1):
        ask_meta = {k: v for k, v in meta.items() if k != "keys"}
        # a question is embedded as a search is, so the same question asked again is the closest thing to it
        out.append({"id": f"{r['id']}#ask{n}", "embed": ask, "query": True, "document": ask,
                    "meta": {**ask_meta, "facet": "ask", "hash": f"{meta['hash']}:q"}})
    return out


def read_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError(f"{path}: an asset file is {{shelf, origin, about, rows: [...]}}")
    return data


def load(folder: Path) -> dict[str, list[tuple[Row, str]]]:
    """Every row of `<folder>/assets` by shelf, each with its origin (`generated` or `curated`)."""
    out: dict[str, list[tuple[Row, str]]] = {}
    for path in sorted((folder / "assets").glob("*/*.json")):
        if path.name.endswith(".overlay.json"):
            continue
        data = read_file(path)
        shelf = data.get("shelf") or path.parent.name
        out.setdefault(shelf, []).extend((row, str(data.get("origin", "curated"))) for row in data["rows"])
    return out


def write_file(path: Path, shelf: str, origin: str, about: str, rows: list[Row], generator: str = "") -> bool:
    """Writes an asset file with its rows sorted by id; False when it already says the same."""
    data: dict[str, Any] = {"shelf": shelf, "origin": origin}
    if generator:
        data["generator"] = generator
    data["about"] = about
    data["rows"] = [_lined(r) for r in sorted(rows, key=lambda r: r["id"])]
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def _lined(row: Row) -> Row:
    """The row as it is written: a body of several lines as a list of lines, and no empty field."""
    out = {k: v for k, v in row.items() if v not in ("", [], {}, None) and not (k == "agents" and v is True)}
    body = text_of(row.get("body")).strip()
    out["body"] = body.split("\n") if "\n" in body else body
    return out


def as_text(items: list[dict[str, Any]]) -> str:
    """Search results as one text for a prompt: each card, then the rows it links to in a line each."""
    parts = []
    for item in items:
        related = "".join(f"\n- {r['rel']}: {r['title']} — {r['summary']} (`{r['id']}`)" for r in item.get("related", []))
        parts.append(item["text"] + (f"\n\nRelated:{related}" if related else ""))
    return "\n\n---\n\n".join(parts)
