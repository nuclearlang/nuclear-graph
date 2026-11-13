"""How the graph is searched (ADR-0104): by meaning and by exact name at once, over several shelves.

1. The query is embedded once and each shelf answers its closest rows (a row is found by its own text or by one of
   the questions it answers).
2. The exact names the query writes (`N0114`, `dragonfly gen`, `usecase`, `mcp`) are looked up in the rows' `keys`:
   a row that carries one is brought in and moves up, more for a longer name.
3. The rows are ranked together, each card once; a search may follow the links of the best ones."""

from __future__ import annotations

import re
from typing import Any

from .assets import card_of, render
from .shelves import SHELVES, shelf_of
from .store import Store

# words that name nothing (English and Spanish: people ask in both)
STOP = set(
    "the and for with that this from what when where which how why who does can are was has have not you your its into "
    "use using used about all any each more most some than then them they there here make made get got set let via "
    "que como cual donde cuando por para con una uno unos unas los las del este esta esto ese esa eso hay son ser "
    "puede puedo hace hacer tiene tengo sirve funciona funcionan sobre entre desde hasta pero porque mas muy".split()
)
# how much closer a row gets by carrying a name the query writes: a plain word, a longer name, a name nothing else is
# written like (a code `n0114`, a decorator `@get`, a phrase of three words or more)
KEY_WORD, KEY_NAME, KEY_CODE = 0.12, 0.22, 0.32
DOCS_PENALTY = 0.04  # a card answers before the long document it was written from
PER_SOURCE = 2  # sections of one document in a result
LISTS = ("kinds", "tags", "keys", "links", "platforms")


def candidates(query: str) -> list[str]:
    """The exact names a query may be writing: every run of 1 to 5 of its words, in lower case."""
    words = [w.strip(".-:") for w in re.findall(r"[a-z0-9_@.:/-]+", query.lower())]
    words = [w for w in words if w]
    out: list[str] = []
    for n in (5, 4, 3, 2, 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i : i + n])
            if n > 1 or (gram not in STOP and len(gram) >= 3):
                out.append(gram)
    return list(dict.fromkeys(out))[:40]


def scope(platform: str = "", agents: bool = False, where: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The filter of a search: what a local agent may read, the rows of a platform (and of every platform), and the
    caller's own filter."""
    parts: list[dict[str, Any]] = []
    if agents:
        parts.append({"agents": True})
    if platform:
        parts.append({"$or": [{"platforms": {"$contains": platform}}, {"platforms": {"$contains": "all"}}]})
    for key, value in (where or {}).items():
        # a list field (`kinds`, `tags`, `keys`, `links`) given one text: the rows whose list has it
        parts.append({key: {"$contains": value}} if key in LISTS and isinstance(value, str) else {key: value})
    return None if not parts else parts[0] if len(parts) == 1 else {"$and": parts}


def _weight(key: str) -> float:
    if re.search(r"\d|[@_/]", key) or key.count(" ") >= 2:
        return KEY_CODE
    return KEY_NAME if " " in key or "-" in key or "." in key else KEY_WORD


def _both(a: dict[str, Any] | None, b: dict[str, Any]) -> dict[str, Any]:
    return b if a is None else {"$and": [a, b]}


def search(store: Store, query: str, shelves: list[str], k: int = 5, platform: str = "", agents: bool = False,
           where: dict[str, Any] | None = None, expand: bool = False) -> list[dict[str, Any]]:
    """The `k` cards that answer a query best: {id, shelf, text, meta, distance, score, via} and, for a card of the
    knowledge base, `card` (its fields) and with `expand` the rows it links to (`related`)."""
    vector = store.embed_query(query)
    grams = candidates(query)
    base = scope(platform, agents, where)
    best: dict[str, dict[str, Any]] = {}

    def consider(shelf: str, hit: dict[str, Any], bonus: float = 0.0) -> None:
        meta = hit["meta"] or {}
        card = str(meta.get("card") or hit["id"])
        score = hit["distance"] - bonus + (DOCS_PENALTY if shelf == "docs" else 0.0)
        if card not in best or score < best[card]["score"]:
            via = "key" if bonus else str(meta.get("facet") or "card")
            best[card] = {"id": card, "shelf": shelf, "distance": hit["distance"], "score": round(score, 4), "via": via, "source": meta.get("source", "")}

    for shelf in shelves:
        for hit in store.near(shelf, vector, max(k * 3, 12), base):
            consider(shelf, hit)
        if grams and shelf in SHELVES:
            named = [{"keys": {"$contains": g}} for g in grams]
            keyed = store.where(shelf, _both(base, named[0] if len(named) == 1 else {"$or": named}), limit=40)
            bonus = {h["id"]: max(_weight(key) for key in h["meta"].get("keys", []) if key in grams) for h in keyed}
            for hit in store.near(shelf, vector, len(keyed), ids=list(bonus)):
                consider(shelf, hit, bonus[hit["id"]])

    picked: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    for item in sorted(best.values(), key=lambda i: i["score"]):
        if item["shelf"] == "docs" and item["source"]:
            per_source[item["source"]] = per_source.get(item["source"], 0) + 1
            if per_source[item["source"]] > PER_SOURCE:
                continue
        picked.append(item)
        if len(picked) == k:
            break

    for shelf in {i["shelf"] for i in picked}:
        found = store.documents(shelf, [i["id"] for i in picked if i["shelf"] == shelf])
        for item in picked:
            if item["shelf"] == shelf and item["id"] in found:
                _fill(item, found[item["id"]])
    picked = [i for i in picked if "text" in i]
    if expand:
        _expand(store, picked)
    for item in picked:
        item.pop("source", None)
    return picked


def applies(store: Store, text: str, platform: str = "") -> list[dict[str, Any]]:
    """The capabilities rows that apply to a text (a spec, a task) because it writes one of their `triggers`: what the
    platform cannot do yet, a limit, a part never run for real. Exact, never by meaning: {id, type, title, summary,
    trigger}."""
    low = text.lower()
    out = []
    for row in store.where("capabilities", scope(platform, True, {"facet": "card"}) or {}):
        hit = next((t for t in row["meta"].get("triggers", []) if re.search(rf"\b{re.escape(t)}s?\b", low)), None)
        if hit:
            card = card_of(store.documents("capabilities", [row["id"]])[row["id"]]["text"]) or {}
            out.append({"id": row["id"], "type": row["meta"].get("type", ""), "title": card.get("title", row["id"]), "summary": card.get("summary", ""), "trigger": hit})
    return out


# What each sign that a request is of a strategy's kind is worth. An exact sign (the request writes a diagnostic code,
# a test's output, `rename A to B`) outweighs any closeness of meaning; meaning decides between strategies that
# have no exact sign, or the same ones.
SIGNAL, TRIGGER, TARGET, MEANING = 3.0, 1.0, 1.5, (2.5, 2.0, 1.5, 1.0, 0.5)


def strategy(store: Store, text: str, platform: str = "", existing: list[str] | None = None,
             new: list[str] | None = None, runnable: bool = False, only: str = "") -> list[dict[str, Any]]:
    """The strategies that fit a request (a spec, a task, an order of the chat), best first: {id, title, summary,
    score, why, data, text}. A strategy row says how its kind of request is recognised: `data.signals` (regular
    expressions over the request), `meta.triggers` (its words), `data.target` (`existing`: the request names a
    declaration the project has; `new`: one it has not; the caller gives both lists) and, by meaning, its text and
    the questions it answers. `runnable`: the caller is a run of the Loop, which a strategy without stages (a
    question, a command, a limit) would stop: such a strategy comes first only when an exact sign chose it. `only`: the
    strategy the request itself names (`usecase` or `strategy:usecase`), which then comes first. Nothing here asks a
    model."""
    low = text.lower()
    rows = store.where("playbooks", scope(platform, True, {"facet": "card", "type": "strategy"}) or {})
    cards = {rid: card_of(d["text"]) or {} for rid, d in store.documents("playbooks", [r["id"] for r in rows]).items()}
    scores: dict[str, float] = {r["id"]: 0.0 for r in rows}
    why: dict[str, list[str]] = {r["id"]: [] for r in rows}
    for row in rows:
        rid, data = row["id"], cards[row["id"]].get("data") or {}
        for pattern in data.get("signals", []):
            if m := re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                scores[rid] += SIGNAL
                why[rid].append(f'it writes "{" ".join(m.group(0).split())[:48]}"')
        hits = [t for t in row["meta"].get("triggers", []) if re.search(rf"\b{re.escape(t)}\b", low)]
        if hits:
            scores[rid] += TRIGGER * min(len(hits), 3)
            why[rid].append("it says " + ", ".join(f'"{t}"' for t in hits[:3]))
        target = data.get("target")
        if target and (existing is not None or new is not None):
            fits = bool(existing) if target == "existing" else bool(new)
            scores[rid] += TARGET if fits else -2 * TARGET
            if fits:
                names = (existing if target == "existing" else new) or []
                why[rid].append(f"{', '.join(names[:3])}: {'the project has it' if target == 'existing' else 'new to the project'}")
    if new is not None and len(new) >= 2:
        # a request that introduces two declarations or more is a design to build, whatever else its words say (a use
        # case names its repository; a feature says what should happen)
        for row in rows:
            scores[row["id"]] += TARGET if row["meta"].get("family") == "create" else -2 * TARGET
    near = search(store, text[:500], ["playbooks"], k=len(MEANING), platform=platform, agents=True, where={"type": "strategy"})
    for rank, hit in enumerate(near):
        if hit["id"] in scores:
            scores[hit["id"]] += MEANING[rank]
            if rank == 0:
                why[hit["id"]].append("the closest in meaning")
    exact: set[str] = {rid for rid in scores if any(w.startswith("it writes") for w in why[rid])}
    ranked = sorted(scores, key=lambda i: -scores[i])
    if runnable:
        ranked.sort(key=lambda i: not ((cards[i].get("data") or {}).get("stages") or i in exact))
    asked = only if only.startswith("strategy:") else f"strategy:{only}"
    if asked in scores:
        ranked.sort(key=lambda i: i != asked)
        why[asked] = ["the request asks for it"]
    out = []
    for rid in ranked[:3]:
        card = cards[rid]
        out.append({"id": rid, "title": card.get("title", rid), "summary": card.get("summary", ""), "score": round(scores[rid], 2),
                    "why": "; ".join(why[rid]), "data": card.get("data") or {}, "text": render(card) if card else ""})
    return out


def _fill(item: dict[str, Any], stored: dict[str, Any]) -> None:
    card = card_of(stored["text"])
    item["meta"] = stored["meta"]
    item["text"] = render(card) if card else stored["text"]
    if card:
        item["card"] = card


def card(store: Store, card_id: str, expand: bool = True) -> dict[str, Any] | None:
    """One card by its id, with the rows it links to."""
    shelf = shelf_of(card_id)
    found = store.documents(shelf, [card_id]) if shelf else {}
    if card_id not in found:
        return None
    item: dict[str, Any] = {"id": card_id, "shelf": shelf, "distance": 0.0, "score": 0.0, "via": "id"}
    _fill(item, found[card_id])
    if expand:
        _expand(store, [item], limit=12)
    return item


def _expand(store: Store, items: list[dict[str, Any]], limit: int = 6) -> None:
    """Adds to each card the title and summary of the rows it links to (`limit` per search, the closest cards first)."""
    have = {i["id"] for i in items}
    wanted: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in items:
        for link in (item.get("card") or {}).get("links", []):
            if link["to"] not in have and len(wanted) < limit:
                wanted.append((item, link))
    by_shelf: dict[str, list[str]] = {}
    for _, link in wanted:
        by_shelf.setdefault(shelf_of(link["to"]), []).append(link["to"])
    docs = {i: d for shelf, ids in by_shelf.items() if shelf for i, d in store.documents(shelf, ids).items()}
    for item, link in wanted:
        linked = card_of(docs[link["to"]]["text"]) if link["to"] in docs else None
        if linked:
            item.setdefault("related", []).append({"id": link["to"], "rel": link["rel"], "title": linked["title"], "summary": linked["summary"]})
