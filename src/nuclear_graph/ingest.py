"""Fills the `knowledge` collection from the NuclearLang source roots (the `nuclear` repository and the
repositories inside it) and the `prompts` collection from this package's prompts. Only what changed is embedded
again; the chunks of a deleted or shortened file are removed."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .store import Store

SKIP_DIRS = {"node_modules", "build", ".venv", "target", ".git", "expected", ".dart_tool", "dist", "dist-test",
             "__pycache__", ".nuclear", "aprende", "CodeBuilder", "out", "results"}
DIALECTS = ("typescript", "dart", "python", "fastapi", "nestjs", "flutter", "react")
# the platform of each platform dialect (ADR-0093): the local agents write for a platform, never for a dialect
PLATFORM_OF = {"fastapi": "backend", "nestjs": "backend", "flutter": "mobile", "react": "web"}
PLATFORMS = ("backend", "mobile", "web")
# what a local agent reads (the `nuclear` collection): Nuclear and Dragonfly only, never how a dialect writes its target
AGENT_SPECS = re.compile(r"(^|/)spec/(nuclear-base|library|projects|diagnostics|backend|mobile|web|brief/(nuclear-base|backend|mobile|web))\.md$")
AGENT_DOCS = re.compile(r"(^|/)docs/language/")
KEPT_FENCES = ("", "nuclear", "sh", "text", "console")
# copies of the dialects bundled inside the editor extensions: the originals are ingested once
SKIP_PATHS = ("nuclear-vscode/server/",)
MAX = 1400
PROMPTS = Path(__file__).parent / "prompts"

Chunk = tuple[str, str, dict[str, Any]]  # id, text, metadata


def kind_of(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if rel.endswith(".nuc"):
        return "example"
    if name == "docs.toml":
        return "word"
    if name.endswith(".toml"):
        return "dialect"
    if "/adr/" in f"/{rel}":
        return "adr"
    if name == "STATUS.md":
        return "status"
    if "/spec/" in f"/{rel}" or rel.startswith("specs/"):
        return "spec"
    if "/context/" in rel:
        return "context"
    return "doc"


def dialect_of(rel: str) -> str:
    parts = re.split(r"[/_.\-]", rel)
    for d in DIALECTS:
        if d in parts:
            return d
    return ""


def split(text: str, title: str) -> Iterator[tuple[str, str]]:
    """Pieces of at most MAX characters, cut at blank lines; each one knows its section title."""
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        if size + len(para) > MAX and buf:
            yield title, "\n\n".join(buf)
            buf, size = [], 0
        while len(para) > MAX:  # a long code block or table: hard cut
            yield title, para[:MAX]
            para = para[MAX:]
        buf.append(para)
        size += len(para) + 2
    if buf and "".join(buf).strip():
        yield title, "\n\n".join(buf)


def markdown(text: str) -> Iterator[tuple[str, str]]:
    """Sections of a markdown file (by `#`/`##`/`###` headings), each split to MAX."""
    heading = ""
    lines: list[str] = []
    fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and re.match(r"#{1,3} ", line):
            if lines:
                yield from split("\n".join(lines), heading)
            heading, lines = line.lstrip("# ").strip(), [line]
        else:
            lines.append(line)
    if lines:
        yield from split("\n".join(lines), heading)


def words(text: str) -> Iterator[tuple[str, str]]:
    """One chunk per kind, decorator or word of a dialect's docs.toml, in Nuclear; what the dialect writes underneath
    a word (`[underneath.<section>]`, its framework) is a chunk of its own, titled `underneath <word>`, that the local
    agents never read."""
    data = tomllib.loads(text)
    for section, entries in data.items():
        if isinstance(entries, dict) and section != "underneath":
            for word, doc in entries.items():
                if isinstance(doc, str):
                    yield from split(f"{section[:-1] if section.endswith('s') else section} `{word}`\n\n{doc.strip()}", word)
    for section, entries in data.get("underneath", {}).items():
        for word, doc in entries.items():
            if isinstance(doc, str):
                yield f"underneath {word}", f"{section[:-1]} `{word}`, underneath: {doc.strip()}"


def toml_sections(text: str) -> Iterator[tuple[str, str]]:
    title, lines = "", []
    for line in text.splitlines():
        if line.startswith("[") and lines:
            yield from split("\n".join(lines), title)
            lines = []
        if line.startswith("["):
            title = line.strip("[] ")
        lines.append(line)
    if lines:
        yield from split("\n".join(lines), title)


def files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).parts
        if any(p in SKIP_DIRS or (p.startswith(".") and p not in (".github",)) for p in rel[:-1]):
            continue
        if rel[0:1] and any("/".join(rel).startswith(p) for p in SKIP_PATHS):
            continue
        if path.is_file() and (path.suffix in (".md", ".nuc") or path.name in ("docs.toml", "dialect.toml", "platform.toml")):
            yield path


def platform_of(rel: str, dialect: str) -> str:
    if dialect in PLATFORM_OF:
        return PLATFORM_OF[dialect]
    parts = re.split(r"[/_.\-]", rel)
    return next((p for p in PLATFORMS if p in parts), "")


def for_agents(rel: str, kind: str) -> bool:
    """Whether a local agent reads this file: examples in Nuclear, the words of the kinds, the platform and base specs
    and the language guide. Never the dialects' templates, the runtimes, the target languages' specs or the ADRs."""
    if "packages/" in rel or rel.startswith("tools/"):
        return False
    if kind in ("example", "word"):
        return True
    return bool(AGENT_SPECS.search(rel) or AGENT_DOCS.search(rel))


def nuclear_only(text: str) -> str:
    """The text without code blocks of a target language (```python, ```dart, ```typescript...) and without what a
    dialect writes underneath a word (its framework: the `**Underneath (dialect):**` note of `nuclear help`)."""
    out, keep, fence = [], True, False
    for line in text.splitlines():
        if line.startswith("**Underneath ("):
            continue
        if line.startswith("```"):
            if not fence:
                keep = line[3:].strip().lower() in KEPT_FENCES
            fence = not fence
            if keep:
                out.append(line)
            continue
        if keep or not fence:
            out.append(line)
    return "\n".join(out)


def chunks_of(path: Path, rel: str, repo: str, agents: bool | None = None) -> list[Chunk]:
    text = path.read_text(errors="replace")
    if path.suffix == ".nuc":
        pieces = list(split(text, path.stem))
    elif path.name == "docs.toml":
        pieces = list(words(text))
    elif path.suffix == ".toml":
        pieces = list(toml_sections(text))
    else:
        pieces = list(markdown(text))
    dialect = dialect_of(rel)
    meta = {"source": f"{repo}:{rel}", "kind": kind_of(rel), "dialect": dialect, "platform": platform_of(rel, dialect),
            "repo": repo, "agents": for_agents(rel, kind_of(rel)) if agents is None else agents}
    out = []
    for n, (title, body) in enumerate(pieces):
        head = f"[{meta['kind']}] {rel}" + (f" — {title}" if title else "")
        doc = f"{head}\n\n{body.strip()}"
        h = hashlib.sha1(doc.encode()).hexdigest()
        agents = meta["agents"] and not title.startswith("underneath ")
        out.append((hashlib.sha1(f"{meta['source']}#{n}".encode()).hexdigest(), doc, {**meta, "title": title, "hash": h, "agents": agents}))
    return out


def cli_help() -> list[Chunk]:
    """The help of the installed `nuclear` and `dragonfly` CLIs and the words of every dialect."""
    runs = [["nuclear", "--help"], ["nuclear", "help"], ["dragonfly", "--help"]]
    runs += [["nuclear", "help", "words", "--dialect", d] for d in DIALECTS]
    runs += [["nuclear", "help", w, "--platform", p] for p in PLATFORMS for w in ("words", "layout")]
    out: list[Chunk] = []
    for cmd in runs:
        if not shutil.which(cmd[0]):
            continue
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        text = (r.stdout + r.stderr).strip()
        if not text:
            continue
        source = "cli:" + " ".join(cmd)
        for n, (_, body) in enumerate(split(text, " ".join(cmd))):
            doc = f"[cli] `{' '.join(cmd)}`\n\n{body}"
            dialect = cmd[-1] if "--dialect" in cmd else ""
            platform = cmd[-1] if "--platform" in cmd else PLATFORM_OF.get(dialect, "")
            meta = {"source": source, "kind": "cli", "dialect": dialect, "platform": platform, "repo": "cli",
                    "agents": "--dialect" not in cmd, "title": " ".join(cmd), "hash": hashlib.sha1(doc.encode()).hexdigest()}
            out.append((hashlib.sha1(f"{source}#{n}".encode()).hexdigest(), doc, meta))
    return out


def prompts() -> list[Chunk]:
    """The validated prompt of each use case (`prompts/<use_case>.md`)."""
    out = []
    for p in sorted(PROMPTS.glob("*.md")):
        text = p.read_text()
        meta = {"source": f"prompt:{p.stem}", "kind": "prompt", "use_case": p.stem, "title": p.stem,
                "hash": hashlib.sha1(text.encode()).hexdigest()}
        out.append((f"prompt-{p.stem}", text, meta))
    for p in sorted((PROMPTS / "agents").glob("*.md")):  # the local agents' prompts: `agent.<step>`
        if p.name == "README.md":
            continue
        text = p.read_text()
        meta = {"source": f"prompt:agent.{p.stem}", "kind": "prompt", "use_case": f"agent.{p.stem}", "title": f"agent.{p.stem}",
                "hash": hashlib.sha1(text.encode()).hexdigest()}
        out.append((f"prompt-agent.{p.stem}", text, meta))
    return out


def sync(store: Store, collection: str, by_source: dict[str, list[Chunk]], log=print) -> dict[str, int]:
    added = kept = removed = 0
    for source, chunks in by_source.items():
        old = store.hashes(collection, source)
        new = [c for c in chunks if old.get(c[0]) != c[2]["hash"]]
        gone = [i for i in old if i not in {c[0] for c in chunks}]
        store.put(collection, new)
        store.delete(collection, gone)
        added, kept, removed = added + len(new), kept + len(chunks) - len(new), removed + len(gone)
        if new:
            log(f"  {source}: {len(new)} chunk(s)")
    return {"added": added, "kept": kept, "removed": removed}


def ingest(store: Store, roots: list[Path], log=print, cli: bool = True) -> dict[str, Any]:
    """Every source root: its own files, and each repository folder inside it gets its own name."""
    by_source: dict[str, list[Chunk]] = {}
    repos: set[str] = set()  # the repositories these roots hold: only their gone sources are removed
    whole = False  # a knowledge base folder is the whole knowledge: what it does not hold is removed
    for root in roots:
        root = root.resolve()
        if (root / "manifest.json").is_file():
            # the knowledge base (nuclear-graph knowledge build): each file classified by its source's path, read by
            # the local agents when its section says so; the help of the tools is in it
            whole, cli = True, False
            manifest = json.loads((root / "manifest.json").read_text())
            for f in manifest["files"]:
                for c in chunks_of(root / f["path"], f["source"], f["repo"], agents=f["agents"]):
                    by_source.setdefault(c[2]["source"], []).append(c)
            continue
        repos.add(root.name)
        repos.update(d.name for d in root.iterdir() if (d / ".git").exists())
        for path in files(root):
            rel = path.relative_to(root).as_posix()
            first = rel.split("/", 1)[0]
            repo = first if (root / first / ".git").exists() else root.name
            for c in chunks_of(path, rel, repo):
                by_source.setdefault(c[2]["source"], []).append(c)
    for c in cli_help() if cli else []:
        by_source.setdefault(c[2]["source"], []).append(c)
    # sources of these roots that no longer exist
    known = {s for s in by_source}
    stale = store.get("knowledge", {"repo": {"$ne": "__none__"}})
    for item in stale:
        src = str(item["meta"].get("source", ""))
        if src not in known and (whole or (not src.startswith("cli:") and item["meta"].get("repo") in repos)):
            by_source.setdefault(src, [])
    result = {"knowledge": sync(store, "knowledge", by_source, log)}
    # the local agents' collection: the same sources, only what they read, without target-language code
    by_agent: dict[str, list[Chunk]] = {}
    for source, chunks in by_source.items():
        kept = [(i, nuclear_only(t), {**m, "hash": hashlib.sha1(nuclear_only(t).encode()).hexdigest()}) for i, t, m in chunks if m.get("agents")]
        by_agent[source] = kept
    result["nuclear"] = sync(store, "nuclear", by_agent, log)
    by_prompt: dict[str, list[Chunk]] = {}
    for c in prompts():
        by_prompt.setdefault(c[2]["source"], []).append(c)
    result["prompts"] = sync(store, "prompts", by_prompt, log)
    return result
