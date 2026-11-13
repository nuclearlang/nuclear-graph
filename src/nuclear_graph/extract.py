"""The generated rows of the knowledge base (ADR-0104): everything that has a structured source in the working tree
is read from it, never written by hand, so it cannot drift: the compiler's diagnostics, the standard library, the
platforms' contracts and words, the help of the command line tools, the MCP tools, the HTTP routes, the Loop's stages,
the local agents, the editor's commands, each component's version, the example projects, the solved tasks of the
evaluation and every document section. `generate` answers `{"<shelf>/<file>": (about, rows)}`."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .assets import Row, nuclear_only
from .shelves import PLATFORMS

SKIP_DIRS = {"node_modules", "build", ".venv", "target", ".git", "expected", ".dart_tool", "dist", "dist-test",
             "__pycache__", ".nuclear", "aprende", "CodeBuilder", "out", "results"}
PRIVATE = ("docs/aprende", "CodeBuilder")  # the user's teaching material: never published nor ingested
DIALECTS = ("typescript", "dart", "python", "fastapi", "nestjs", "flutter", "react")
PLATFORM_OF = {"fastapi": "backend", "nestjs": "backend", "flutter": "mobile", "react": "web"}
REPO_OF = {"backend": "dragonfly-backend", "mobile": "dragonfly-mobile", "web": "dragonfly-web"}
OTHER = {"id": "99-other", "title": "Documents no section claims yet: give them a section in sections.toml", "agents": False, "shelf": "docs"}
MAX = 1400  # characters of a document section's row
PREFIX = {"docs": "doc", "language": "lang", "platforms": "spec"}


def _run(cmd: list[str]) -> str | None:
    """What a command prints; None when the tool is not installed."""
    if not shutil.which(cmd[0]):
        return None
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip()


def _graph_help() -> str:
    """The help of this package's own command line (never of another copy on the PATH)."""
    import os

    from .cli import parser

    os.environ.setdefault("COLUMNS", "100")
    return parser().format_help()


def _mcp() -> tuple[str, list[tuple[str, str, dict[str, Any]]]]:
    """The instructions and the tools (name, description, parameters) of the MCP server of this package."""
    import asyncio
    import logging

    from . import mcp_server

    logging.getLogger("httpx").setLevel(logging.WARNING)  # the MCP library turns request logs on
    tools = asyncio.run(mcp_server.mcp.list_tools())
    return mcp_server.mcp.instructions or "", [(t.name, t.description or "", t.input_schema) for t in tools]


@dataclass
class Context:
    tree: Path
    website: Path | None = None
    sections: dict[str, Any] = field(default_factory=dict)  # sections.toml
    run: Callable[[list[str]], str | None] = _run
    mcp: Callable[[], tuple[str, list[tuple[str, str, dict[str, Any]]]]] = _mcp
    graph_help: Callable[[], str] = _graph_help
    problems: list[str] = field(default_factory=list)

    def read(self, rel: str) -> str:
        path = self.tree / rel
        return path.read_text(errors="replace") if path.is_file() else ""


# ---- small helpers ----

def walk(root: Path) -> Iterator[Path]:
    """Every file under `root`, in order, without entering generated, vendored or hidden folders."""
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and (not d.startswith(".") or d == ".github"))
        for name in sorted(names):
            yield Path(folder) / name


def slug(text: str, size: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:size].strip("-") or "x"


def plain(text: str) -> str:
    """Markdown as plain words: no emphasis marks, a link as its text."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\*\*|__", "", text).strip()


def clip(text: str, size: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1].rsplit(" ", 1)[0] + "…"


def first_sentence(text: str, size: int = 300) -> str:
    """The first sentence of a text (or its first paragraph when it has no full stop)."""
    para = plain(text).strip().split("\n\n")[0]
    m = re.search(r"(?<=[^.\d\s][.!?])\s", para + " ")
    return clip(para[: m.start()] if m else para, size)


def cells(line: str) -> list[str]:
    """The cells of a markdown table row (`\\|` is a pipe inside a cell)."""
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def rust_text(s: str) -> str:
    return s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


# ---- errors: the compiler's diagnostics and the habits it corrects ----

CODE = re.compile(r'pub const (\w+): Code = Code \{\s*id: "(N\d{4})",\s*title: "((?:[^"\\]|\\.)*)",\s*explanation:\s*"((?:[^"\\]|\\.)*)",?\s*\};')
FAMILY = {"lexer": "syntax", "parser": "syntax", "resolver": "resolver", "dialects": "dialect", "projects and architecture": "project"}


def documented(spec: str) -> dict[str, dict[str, str]]:
    """spec/diagnostics.md: code → {stage, what, example, fix}."""
    out: dict[str, dict[str, str]] = {}
    stage = ""
    for line in spec.splitlines():
        if line.startswith("## "):
            stage = line[3:].strip().lower()
        elif re.match(r"\| N\d{4} ", line):
            c = cells(line)
            out[c[0]] = {"stage": stage, "what": c[1] if len(c) > 1 else "", "example": c[2] if len(c) > 2 else "", "fix": c[3] if len(c) > 3 else ""}
    return out


def diagnostics(ctx: Context) -> list[Row]:
    spec = documented(ctx.read("spec/diagnostics.md"))
    rows: list[Row] = []
    for const, code, title, why in CODE.findall(ctx.read("crates/nuclear-diag/src/lib.rs")):
        doc = spec.get(code)
        if doc is None:
            ctx.problems.append(f"{code} ({const}) is not documented in spec/diagnostics.md")
            continue
        title, why = rust_text(title), rust_text(why)
        severity = "warning" if "(warning)" in doc["what"] else "error"
        body = [f"`{code}` · {doc['stage']} · {severity}", "", f"**What it is.** {doc['what']}", "", f"**Why.** {why}"]
        if doc["example"] not in ("", "—"):
            body += ["", f"**Example.** {doc['example']}"]
        if doc["fix"] not in ("", "—"):
            body += ["", f"**Fix.** {doc['fix']}"]
        rows.append({
            "id": f"error:{code}", "type": "diagnostic", "title": f"{code} — {title}", "summary": clip(plain(doc["what"]), 400),
            "body": "\n".join(body), "keys": [code.lower(), title.lower()],
            "sources": ["spec/diagnostics.md", "crates/nuclear-diag/src/lib.rs"],
            "meta": {"code": code, "family": FAMILY.get(doc["stage"], doc["stage"]), "severity": severity},
        })
    return rows


HABIT_WORDS = {"function", "return", "const", "let", "var", "final", "new", "await", "async", "class", "extends", "implements",
               "interface", "enum", "switch", "import", "this", "contains", "includes", "pow", "try"}


def habits(ctx: Context) -> list[Row]:
    """The table "Rules that change" of the base brief: what someone who knows another language writes by reflex."""
    rows: list[Row] = []
    table = False
    for line in ctx.read("spec/brief/nuclear-base.md").splitlines():
        if line.startswith("| You would write"):
            table = True
        elif table and line.startswith("|") and not line.startswith("|---"):
            wrong, right, note = (cells(line) + ["", ""])[:3]
            words = sorted({w.lower() for w in re.findall(r"`([^`]+)`", wrong) for w in re.findall(r"[A-Za-z]{3,}", w)} & HABIT_WORDS)
            body = [f"Someone who knows TypeScript, Dart or Python writes {wrong}.", "", f"In Nuclear: {right}." + (f" {note[0].upper()}{note[1:]}." if note else ""),
                    "", "When the compiler sees the habit it reports `N0022` with the Nuclear form, and `nuclear fix` applies the exact ones."]
            rows.append({
                "id": f"habit:{slug(wrong, 48) if len(slug(wrong, 48)) > 3 else slug(right, 48)}", "type": "habit", "title": clip(f"Not {plain(wrong)} — in Nuclear: {plain(right)}", 140),
                "summary": clip(f"In Nuclear write {plain(right)} instead of {plain(wrong)}." + (f" {note[0].upper()}{plain(note[1:])}." if note else ""), 400),
                "body": "\n".join(body), "keys": words, "links": [{"rel": "reported-as", "to": "error:N0022"}],
                "sources": ["spec/brief/nuclear-base.md#Rules that change"], "meta": {"family": "habit", "code": "N0022"},
            })
        elif table and not line.startswith("|"):
            break
    return rows


# ---- language: the standard library, read from the compiler's own table ----

GIVES = {"Str": "string", "StrOpt": "string?", "Int": "int", "IntOpt": "int?", "Double": "double", "DoubleOpt": "double?",
         "Bool": "boolean", "Void": "void", "Same": "the same type", "Elem": "the element", "ElemOpt": "the element, or null",
         "ListElem": "a list of the elements", "ListStr": "string[]", "ListInt": "int[]", "ListAny": "a list", "Keys": "the keys",
         "Values": "the values", "GroupMap": "a map of lists", "Num": "a number", "MatchOpt": "Match?", "ListMatch": "Match[]",
         "DateTime": "DateTime", "DateTimeOpt": "DateTime?", "Duration": "Duration", "Bytes": "Bytes", "Regex": "Regex",
         "SetAny": "Set", "Error": "Error", "Any": "any"}


def _block(src: str, name: str) -> str:
    m = re.search(rf"pub const {name}: [^=]*= &\[(.*?)\n\];", src, re.S)
    return m.group(1) if m else ""


def library(ctx: Context) -> list[Row]:
    src = ctx.read("crates/nuclear-dialect/src/library.rs")
    members: dict[str, list[tuple[str, bool, str]]] = {}
    for how, base, name, ret in re.findall(r'\b([pm])\("(\w+)", "(\w+)", (\w+)\)', _block(src, "MEMBERS")):
        members.setdefault(base, []).append((name, how == "p", GIVES.get(ret, ret)))
    wrong: dict[str, list[tuple[str, str]]] = {}
    for base, name, fix in re.findall(r'\("([\w*]+)", "(\w+)", "([^"]*)"\)', _block(src, "WRONG")):
        wrong.setdefault("any" if base == "*" else base, []).append((name, fix))
    for obj, name, fix in re.findall(r'\("(\w+)", "(\w+)", "([^"]*)"\)', _block(src, "WRONG_STATIC")):
        wrong.setdefault(obj if obj in members else "functions", []).append((f"{obj}.{name}", fix))
    for name, fix in re.findall(r'\("(\w+)", "([^"]*)"\)', _block(src, "WRONG_FUNCTIONS")):
        wrong.setdefault("functions", []).append((f"{name}(x)", fix))
    rows: list[Row] = []
    own = {n.lower() for ms in members.values() for n, _, _ in ms} | {b.lower() for b in members} | {"int", "double", "number", "string", "boolean"}
    for base in sorted(set(members) | set(wrong)):
        mine, bad = members.get(base, []), wrong.get(base, [])
        props = [f"`{n}` → {g}" for n, p, g in mine if p]
        methods = [f"`{n}()` → {g}" for n, p, g in mine if not p]
        body: list[str] = []
        if props:
            body += ["Properties (written without parentheses): " + ", ".join(props) + ".", ""]
        if methods:
            body += ["Methods: " + ", ".join(methods) + ".", ""]
        if bad:
            body += ["Names of other languages and the Nuclear one (the compiler reports them as `N0114` with this fix):", ""]
            body += [f"- `{n}` → `{f}`" for n, f in bad]
        what = "functions and statics of other languages" if base == "functions" else f"`{base}`"
        summary = (f"The functions and statics of other languages (`len`, `str`, `console.log`...) and what Nuclear writes instead."
                   if base == "functions" else
                   f"The members of {what} in Nuclear's standard library, the same in every dialect: " + clip(", ".join(n for n, _, _ in mine), 260) + ".")
        rows.append({
            "id": f"lib:{base}", "type": "library", "title": f"{what} — Nuclear's standard library", "summary": summary,
            "body": "\n".join(body).strip(), "keys": sorted({f"{base.lower()} members", *(k for n, _ in bad if "." not in n and (k := re.sub(r"\W.*", "", n).lower()) not in own)}),
            "links": [{"rel": "wrong-name-is", "to": "error:N0114"}] if bad else [],
            "sources": ["crates/nuclear-dialect/src/library.rs", "spec/library.md"], "meta": {"base": base},
        })
    return rows


# ---- platforms: the contract of each platform and the words of its default dialect ----

SAMPLE = {"Name": "Book", "name": "book", "Component": "Books", "component": "books", "table": "books"}


def _platform(ctx: Context, p: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    base = f"{REPO_OF[p]}/dialects/{p}"
    contract = tomllib.loads(ctx.read(f"{base}/platform.toml") or "")
    default = contract.get("platform", {}).get("default_dialect", "")
    docs = tomllib.loads(ctx.read(f"{base}/{default}/docs.toml") or "")
    dialect = tomllib.loads(ctx.read(f"{base}/{default}/dialect.toml") or "")
    return contract, docs, dialect, base


def platform(ctx: Context, p: str) -> list[Row]:
    contract, docs, dialect, base = _platform(ctx, p)
    info = contract.get("platform", {})
    if not info:
        return []
    kinds, decorators = info.get("kinds", []), info.get("decorators", [])
    layout, skeletons = contract.get("layout", {}), contract.get("skeletons", {})
    kind_docs, deco_docs = docs.get("kinds", {}), docs.get("decorators", {})
    args = contract.get("decorators", {}).get("args", {})
    sources = [f"{base}/platform.toml", f"{base}/{info.get('default_dialect')}/docs.toml"]
    rows: list[Row] = []
    for kind in kinds:
        doc = nuclear_only(str(kind_docs.get(kind, "")).strip())
        if not doc:
            ctx.problems.append(f"{p}: the kind `{kind}` has no entry in docs.toml")
            continue
        body = [doc]
        if kind in layout:
            body += ["", f"Its file: `{layout[kind]}` (`{{component}}`: the component's folder, `{{file}}`: the name in snake_case)."]
        if kind in skeletons:
            code = re.sub(r"\{\{(\w+)\}\}", lambda m: SAMPLE.get(m.group(1), m.group(1)), skeletons[kind].strip())
            body += ["", f"The smallest file of the kind (what `dragonfly make {kind} books Book` writes):", "", "```nuclear", code, "```"]
        used = sorted({d for d in re.findall(r"@(\w+)", doc) if d in decorators})
        rows.append({
            "id": f"kind:{p}.{kind}", "type": "kind", "title": f"`{kind}` — a kind of the {p} platform",
            "summary": first_sentence(doc), "body": "\n".join(body), "keys": sorted({kind.lower(), *ALIASES.get(kind, [])}),
            "platforms": [p], "links": [{"rel": "uses", "to": f"decorator:{p}.{d}"} for d in used if d in deco_docs] + [{"rel": "placed-by", "to": f"layout:{p}"}],
            "sources": sources, "meta": {"kind": kind, "name": kind},
        })
    for deco in decorators:
        doc = nuclear_only(str(deco_docs.get(deco, "")).strip())
        if not doc:
            continue  # a decorator the platform consumes without a word of its own (documented with its kind)
        extra = f"\n\nIts arguments: {', '.join(f'`{a}`' for a in args[deco]) or 'none'} (`!` = required)." if deco in args else ""
        rows.append({
            "id": f"decorator:{p}.{deco}", "type": "decorator", "title": f"`@{deco}` — a decorator of the {p} platform",
            "summary": first_sentence(doc), "body": doc + extra, "keys": [f"@{deco.lower()}", deco.lower()], "platforms": [p],
            "sources": sources, "meta": {"name": deco},
        })
    if layout:
        table = "\n".join(f"- `{k}` → `{v}`" for k, v in sorted(layout.items()))
        rows.append({
            "id": f"layout:{p}", "type": "layout", "title": f"Where each kind's file goes in a {p} project",
            "summary": f"The folder and file name of every kind of a {p} project: `{{component}}` is the component's folder, `{{screen}}` the screen's, `{{file}}` the declaration's name in snake_case.",
            "body": f"`nuclear help layout --platform {p}` prints it; `dragonfly make` and the generators follow it.\n\n{table}",
            "keys": ["layout", f"{p} layout"], "platforms": [p], "sources": [f"{base}/platform.toml"], "meta": {"name": "layout"},
            "asks": [f"where does the file of each kind go in a {p} project", f"in which folder do I put a repository, a use case or a model of a {p} project"],
        })
    plugins = dialect.get("project", {}).get("plugins", {})
    for name in info.get("plugins", []):
        plug = plugins.get(name, {})
        parts = [str(plug.get("description", "")).strip() or f"An optional part of the {p} platform."]
        if plug.get("kinds"):
            parts.append("Kinds it brings: " + ", ".join(f"`{k}`" for k in plug["kinds"]) + ".")
        if plug.get("requires"):
            parts.append("It enables: " + ", ".join(f"`{r}`" for r in plug["requires"]) + ".")
        parts.append(f"Enable it in `config.nuc`: `plugins({name} = true)`. A kind or a name of a plugin that is not enabled is `N0304`, which says the line to add.")
        rows.append({
            "id": f"plugin:{p}.{name}", "type": "plugin", "title": f"`{name}` — a plugin of the {p} platform",
            "summary": first_sentence(parts[0]), "body": "\n\n".join(parts), "keys": [name.lower(), f"plugin {name.lower()}"], "platforms": [p],
            "links": [{"rel": "missing-is", "to": "error:N0304"}], "sources": [f"{base}/platform.toml", f"{base}/{info.get('default_dialect')}/dialect.toml"],
            "meta": {"name": name},
        })
    dialects = sorted(d.name for d in (ctx.tree / base).iterdir() if (d / "dialect.toml").is_file()) if (ctx.tree / base).is_dir() else []
    listing = "\n".join(f"- `{k}`: {first_sentence(nuclear_only(str(kind_docs.get(k, ''))), 160)}" for k in kinds)
    rows.append({
        "id": f"platform:{p}", "type": "platform", "title": f"The {p} platform of Dragonfly",
        "summary": f"The {p} platform: {info.get('description', '')}. {len(kinds)} kinds, {len(decorators)} decorators, {len(info.get('plugins', []))} plugins; built by the dialects {', '.join(dialects)} (default: {info.get('default_dialect')}).",
        "body": f"A project of the platform is written once in Nuclear and builds with any of its dialects ({', '.join(f'`{d}`' for d in dialects)}; `{info.get('default_dialect')}` when none is named). Create one: `dragonfly new <name> -p {p}`.\n\nIts kinds:\n\n{listing}\n\nIts plugins: {', '.join(f'`{x}`' for x in info.get('plugins', [])) or 'none'}.",
        "keys": [p, f"{p} platform"], "platforms": [p],
        "links": [{"rel": "has", "to": f"kind:{p}.{k}"} for k in kinds if k in kind_docs] + ([{"rel": "has", "to": f"layout:{p}"}] if layout else []),
        "sources": [f"{base}/platform.toml"], "meta": {"name": p},
    })
    return rows


# How people write a kind when it is not its own word: the planner reads them from the kind's keys.
ALIASES = {
    "appcomponent": ["app component", "application component"], "usecase": ["use case"], "statemanager": ["state manager"],
    "statemodel": ["state model"], "formmanager": ["form manager"], "appConfig": ["app config", "application config"],
}


def generators(ctx: Context) -> list[Row]:
    """What `dragonfly gen` writes on each platform, from the platform's own templates."""
    rows: list[Row] = []
    for p in PLATFORMS:
        contract, _, _, base = _platform(ctx, p)
        for what, pieces in contract.get("generators", {}).items():
            lines = []
            for piece in pieces:
                cond = f" (when `{piece['when']}`)" if piece.get("when") else ""
                each = f", one per `{piece['each']}`" if piece.get("each") else ""
                merge = ", added to the file when it exists" if piece.get("merge") else ""
                lines.append(f"- {piece.get('kind', '?')} `{piece.get('name', '')}`{cond}{each}{merge}")
            rows.append({
                "id": f"generator:{p}.{what}", "type": "generator", "title": f"`dragonfly gen {what}` on the {p} platform: what it writes",
                "summary": f"The files `dragonfly gen {what}` writes in a {p} project, finished and compiling: {clip(', '.join(sorted({str(x.get('kind')) for x in pieces})), 200)}.",
                "body": f"Each piece is a file at its kind's place (`nuclear help layout --platform {p}`); nothing is overwritten.\n\n" + "\n".join(lines)
                        + "\n\nThe names: `{{Name}}` the resource, `{{Names}}` its plural, `{{Component}}` the component, `{{UseCase}}` one per action.",
                "keys": [f"gen {what}", f"dragonfly gen {what}"], "platforms": [p], "links": [{"rel": "run-by", "to": f"tool:dragonfly.gen.{what}"}],
                "sources": [f"{base}/platform.toml"], "meta": {"tool": "dragonfly", "name": f"gen {what}"},
            })
    return rows


# ---- tools: the command line ----

def entries(text: str, indent: int = 2) -> list[tuple[str, list[str]]]:
    """A help text as entries: a line at `indent` starts one, the more indented lines below belong to it. Each is
    (the heading it is under, its lines)."""
    out: list[tuple[str, list[str]]] = []
    heading = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip())
        if depth < indent:
            heading = line.strip()
        elif depth == indent:
            out.append((heading, [line]))
        elif out and out[-1][0] == heading:
            out[-1][1].append(line)
    return out


def _described(lines: list[str]) -> str:
    """The description of a help entry: what follows the command after two spaces (or its `(alias)`), and its
    continuation lines."""
    head = re.split(r"\s{2,}|\s(?=\(\w{1,3}\)\s)", lines[0].strip(), maxsplit=1)
    words = [head[1] if len(head) > 1 else ""] + [re.split(r"\s{2,}", ln.strip())[-1] for ln in lines[1:]]
    text = re.sub(r"^\(\w+\)\s*", "", " ".join(w for w in words if w)).strip()
    return text[:1].upper() + text[1:]


def _tool_row(tool: str, name: str, found: list[list[str]], sources: list[str], extra: str = "") -> Row:
    """One command's row from its help entries (each entry is its lines)."""
    lines = [ln for entry in found for ln in entry]
    block = "\n".join(lines)
    described = "; ".join(d for d in (_described(entry) for entry in found) if d)
    command = f"{tool} {name}".strip()
    return {
        "id": f"tool:{tool}.{'.'.join(slug(w) for w in name.split())}" if name else f"tool:{tool}", "type": "cli",
        "title": clip(f"`{command}` — {first_sentence(described, 100)}", 140), "summary": clip(described, 400) or f"The `{command}` command.",
        "body": f"```text\n{block}\n```" + (f"\n\n{extra}" if extra else ""), "keys": sorted({command.lower(), *([name.lower()] if " " in name else [])}),
        "sources": sources, "meta": {"tool": tool, "name": name},
    }


def cli(ctx: Context) -> list[Row]:
    rows: list[Row] = []
    # nuclear: `nuclear help` lists every usage line, then the documentation topics
    text = ctx.run(["nuclear", "help"])
    if text:
        usage, _, rest = text.partition("\ndocumentation:")
        by: dict[str, list[list[str]]] = {}
        for _, lines in entries(usage.partition("usage:")[2]):
            m = re.match(r"\s*nuclear (\w+)", lines[0])
            by.setdefault(m.group(1) if m else "options", []).append(lines)
        for name, found in by.items():
            if name != "options":
                rows.append(_tool_row("nuclear", name, found, ["crates/nuclear-cli/src/main.rs"]))
        topics = "documentation:" + rest.split("\ndialects:")[0]
        rows.append({
            "id": "tool:nuclear", "type": "cli", "title": "`nuclear` — the compiler's command line",
            "summary": clip(text.splitlines()[0], 300) + " Commands: " + ", ".join(sorted(n for n in by if n != "options")) + ".",
            "body": f"```text\n{chr(10).join(ln for e in by.get('options', []) for ln in e)}\n```\n\nEvery command has its own row (`nuclear build`, `nuclear check`...). The documentation it prints:\n\n```text\n{topics.strip()}\n```",
            "keys": ["nuclear cli", "nuclear command"], "sources": ["crates/nuclear-cli/src/main.rs"], "meta": {"tool": "nuclear", "name": ""},
        })
    # dragonfly: sections; the commands of a project each have a row, the tables (make, gen, packages) one per section
    text = ctx.run(["dragonfly", "--help"])
    if text:
        src = ["dragonfly/dragonfly/src/main.rs"]
        by = {}
        sections: dict[str, list[list[str]]] = {}
        for heading, lines in entries(text):
            if heading.startswith(("project", "backend", "setup")):
                by.setdefault(lines[0].split()[0], []).append(lines)
            elif "dragonfly make" in heading:
                sections.setdefault("make", [[heading]]).append(lines)
            elif "dragonfly gen" in heading:
                sections.setdefault("gen", [[heading]]).append(lines)
                # every generator the help lists has its row (a platform's `generator:` rows link to it)
                rows.append(_tool_row("dragonfly", f"gen {lines[0].split()[0]}", [lines], src))
            elif heading.startswith("packages"):
                sections.setdefault("packages", []).append([heading] if [heading] not in sections.get("packages", []) else [])
                sections["packages"].append(lines)
            elif heading.startswith("options"):
                sections.setdefault("options", [[heading]]).append(lines)
        for name, found in by.items():
            rows.append(_tool_row("dragonfly", name, found, src))
        for name, found in sections.items():
            if name != "options":
                rows.append(_tool_row("dragonfly", name, [e for e in found if e], src))
        rows.append({
            "id": "tool:dragonfly", "type": "cli", "title": "`dragonfly` — the command line of Dragonfly projects",
            "summary": "Creates, generates, builds, runs, tests and repairs a Dragonfly project of any platform. Commands: " + clip(", ".join(sorted({*by, *sections} - {"options"})), 280) + ".",
            "body": f"```text\n{text.splitlines()[0]}\n\n{chr(10).join(ln for e in sections.get('options', []) for ln in e)}\n```\n\nEvery command has its own row (`dragonfly new`, `dragonfly gen resource`...).",
            "keys": ["dragonfly cli", "dragonfly command"], "sources": src, "meta": {"tool": "dragonfly", "name": ""},
        })
    # nuclear-loop
    text = ctx.run(["nuclear-loop", "help"])
    if text:
        src = ["nuclear-vscode/src/loopCli.ts"]
        for _, lines in entries(text):
            m = re.match(r"\s*nuclear-loop (\w+)", lines[0])
            if m:
                rows.append(_tool_row("nuclear-loop", m.group(1), [lines], src))
        rows.append({
            "id": "tool:nuclear-loop", "type": "cli", "title": "`nuclear-loop` — the Nuclear Loop without the editor",
            "summary": "Runs a spec through the pipeline (generate, plan, tests first, code, verification, security, artifacts, deploy), retries a failed run and exports the CI file.",
            "body": f"```text\n{text}\n```", "keys": ["nuclear-loop", "loop cli"], "sources": src, "meta": {"tool": "nuclear-loop", "name": ""},
        })
    # nuclear-graph: argparse prints its commands at 4 spaces
    text = ctx.graph_help()
    if text:
        src = ["nuclear-graph/src/nuclear_graph/cli.py"]
        names = []
        for _, lines in entries(text.partition("positional arguments:")[2].partition("options:")[0], indent=4):
            name = lines[0].split()[0]
            names.append(name)
            rows.append(_tool_row("nuclear-graph", name, [[f"nuclear-graph {ln.strip()}" if i == 0 else ln for i, ln in enumerate(lines)]], src))
        rows.append({
            "id": "tool:nuclear-graph", "type": "cli", "title": "`nuclear-graph` — run, fill and guard the Nuclear Smart Graph",
            "summary": "Runs the graph's server and its MCP server, builds and checks the knowledge base, ingests it, searches it and decides which programs may read it. Commands: " + ", ".join(names) + ".",
            "body": f"```text\n{text}\n```", "keys": ["nuclear-graph", "graph cli"], "sources": src, "meta": {"tool": "nuclear-graph", "name": ""},
        })
    return rows


# ---- tools: the MCP server, the HTTP routes, the Loop's stages, the local agents ----

def mcp_tools(ctx: Context) -> list[Row]:
    instructions, tools = ctx.mcp()
    src = ["nuclear-graph/src/nuclear_graph/mcp_server.py"]
    rows: list[Row] = []
    for name, description, schema in tools:
        required = set(schema.get("required", []))
        params = [f"- `{p}`: {spec.get('type', 'any')}" + ("" if p in required else f" = `{json.dumps(spec.get('default'))}`")
                  for p, spec in schema.get("properties", {}).items()]
        doc = " ".join(description.split())
        rows.append({
            "id": f"mcp:{name}", "type": "mcp", "title": f"`{name}` — a tool of the Nuclear MCP server", "summary": first_sentence(doc, 400),
            "body": doc + ("\n\nParameters:\n\n" + "\n".join(params) if params else ""), "keys": [name.lower(), name.lower().replace("_", " ")],
            "links": [{"rel": "part-of", "to": "mcp:server"}], "sources": src, "meta": {"tool": "mcp", "name": name},
        })
    if tools:
        rows.append({
            "id": "mcp:server", "type": "mcp", "title": "The Nuclear MCP server: its tools and how a client must work with them",
            "summary": f"`nuclear-graph mcp` speaks the Model Context Protocol over stdio and gives an AI client {len(tools)} tools: the Smart Graph, the compiler, the dragonfly commands, the generators, the internet and the local developer.",
            "body": "The instructions every client receives:\n\n" + instructions.strip() + "\n\nIts tools: " + ", ".join(f"`{n}`" for n, _, _ in tools) + ".",
            "keys": ["mcp", "mcp server", "nuclear mcp", "model context protocol"], "sources": src, "meta": {"tool": "mcp", "name": "server"},
        })
    return rows


ROUTE = re.compile(r'@app\.(get|post|delete)\("([^"]+)"\)\s+async def \w+\(([^)]*)\)[^:]*:\s+(?:"""(.*?)""")?', re.S)


def http_routes(ctx: Context) -> list[Row]:
    rows: list[Row] = []
    for verb, path, params, doc in ROUTE.findall(ctx.read("nuclear-graph/src/nuclear_graph/server.py")):
        scope = (re.search(r'needs\("(\w+)"', params) or [None, "none"])[1]
        doc = " ".join(doc.split()) or f"{verb.upper()} {path} of the graph."
        rows.append({
            "id": f"http:graph.{verb}.{slug(path)}", "type": "http", "title": f"`{verb.upper()} {path}` — the Smart Graph's HTTP API",
            "summary": first_sentence(doc, 400), "body": f"{doc}\n\nScope: `{scope}`. The graph listens on `127.0.0.1:7878` only; every route but the health and the access request needs `Authorization: Bearer <token>`.",
            "keys": [f"{verb} {path}".lower(), path.lower()], "sources": ["nuclear-graph/src/nuclear_graph/server.py"], "meta": {"tool": "graph", "name": f"{verb.upper()} {path}"},
        })
    controller = ctx.read("nuclear-developer/components/developer/api/developer_controller.nuc")
    prefix = (re.search(r'@controller\("([^"]+)"\)', controller) or [None, "developer"])[1]
    for verb, path, method, body in re.findall(r'@(get|post|put|patch|delete)\("([^"]*)"[^)]*\)\n\s+(\w+\([^)]*\)[^\n]*)\n((?:\s{4}.*\n)+)', controller):
        agent = (re.search(r"~(\w+)\.run", body) or [None, ""])[1]
        route = f"{verb.upper()} /{prefix}/{path}"
        rows.append({
            "id": f"http:developer.{slug(path)}", "type": "http", "title": f"`{route}` — the Nuclear Developer's HTTP API",
            "summary": f"Runs the local {agent or 'agent'} on one request: `{method.strip()}`. The Developer listens on `127.0.0.1:7879`.",
            "body": f"`{route}` → `{method.strip()}`.\n\nEach request runs on a thread of its own, so nothing of one request reaches the next. Start it: `nuclear-developer` (or `dragonfly run` in its folder).",
            "keys": [route.lower(), f"/{prefix}/{path}"], "links": [{"rel": "runs", "to": f"agent:{agent}"}] if agent else [],
            "sources": ["nuclear-developer/components/developer/api/developer_controller.nuc"], "meta": {"tool": "developer", "name": route},
        })
    return rows


STAGE = re.compile(r"\{ id: '(\w+)', title: '([^']*)', about: '((?:[^'\\]|\\.)*)', actors: \[([^\]]*)\] \}")


def stages(ctx: Context) -> list[Row]:
    found = STAGE.findall(ctx.read("nuclear-vscode/src/loopEngine.ts"))
    rows: list[Row] = []
    for n, (sid, title, about, actors) in enumerate(found, 1):
        about = about.replace("\\'", "'")
        who = ", ".join(a.strip(" '") for a in actors.split(","))
        nxt = found[n][0] if n < len(found) else ""
        rows.append({
            "id": f"stage:{sid}", "type": "stage", "title": f"Stage {n} of the Loop: {title}", "summary": first_sentence(about, 400),
            "body": f"{about}\n\nWho takes part: {who}." + (f" The stage after it: `{nxt}`." if nxt else " It is the last stage."),
            "keys": [f"{title.lower()} stage", f"stage {sid}"], "links": [{"rel": "next", "to": f"stage:{nxt}"}] if nxt else [],
            "sources": ["nuclear-vscode/src/loopEngine.ts"], "meta": {"tool": "nuclear-loop", "name": sid},
        })
    return rows


def agents(ctx: Context) -> list[Row]:
    """The local agents of the Nuclear Developer, from their own sources: the comment above each one says what it does."""
    rows: list[Row] = []
    folder = ctx.tree / "nuclear-developer/components/developer/ai"
    config = ctx.read("nuclear-developer/config/project_config.nuc")
    models = {name or "default": model for model, name in re.findall(r'Ollama\(model = env\("\w+", "([^"]+)"\)(?:, name = "(\w+)")?', config)}
    for path in sorted(folder.glob("*.nuc")) if folder.is_dir() else []:
        text = path.read_text()
        m = re.search(r"((?:^//.*\n)+)(?:@.*\n)*^(graph|tools|agent) (\w+)\(", text, re.M)
        if not m:
            continue
        doc = " ".join(line.lstrip("/ ").strip() for line in m.group(1).splitlines())
        name = m.group(3)
        nodes = re.findall(r"@next\(\"(\w+)\"\)\n\s+(\w+)\(", text)
        asked = sorted(set(re.findall(r'\.ask\("(\w+)"', text))) or (["coder"] if "bench.write" in text else [])
        used = ", ".join(f"`{models.get(a, a)}`" for a in asked)
        body = doc + (f"\n\nIts steps, always in this order: {' → '.join(n for _, n in nodes)}." if nodes else "") + (f"\n\nIts model: {used} (on Ollama, at most 3B parameters)." if used else "")
        rows.append({
            "id": f"agent:{name.lower()}", "type": "agent", "title": f"{name} — a local agent of the Nuclear Developer",
            "summary": first_sentence(doc, 400), "body": body, "keys": [name.lower(), f"{name.lower()} agent"],
            "sources": [f"nuclear-developer/components/developer/ai/{path.name}"], "meta": {"tool": "developer", "name": name},
        })
    return rows


def editor(ctx: Context) -> list[Row]:
    raw = ctx.read("nuclear-vscode/package.json")
    if not raw:
        return []
    c = json.loads(raw).get("contributes", {})
    keys: dict[str, list[str]] = {}
    for k in c.get("keybindings", []):
        keys.setdefault(k["command"], []).append(k["key"] + (f" (arg {k['args']})" if "args" in k else ""))
    lines = [f"- {cmd['title']}" + (f" — `{', '.join(keys[cmd['command']])}`" if cmd["command"] in keys else "") + f" (`{cmd['command']}`)" for cmd in c.get("commands", [])]
    src = ["nuclear-vscode/package.json"]
    rows: list[Row] = [{
        "id": "editor:vscode.commands", "type": "editor", "title": "VS Code: the commands of the Nuclear extension and their shortcuts",
        "summary": f"The {len(lines)} commands the Nuclear extension adds to VS Code, each with its keyboard shortcut: the workspace, run and debug, devices, the HTTP tool, the Loop, the agent's chat and the settings.",
        "body": "\n".join(lines), "keys": ["vscode commands", "keyboard shortcuts", "shortcuts"], "sources": src, "meta": {"tool": "vscode", "name": "commands"},
    }]
    conf = c.get("configuration", [])
    props: dict[str, Any] = {}
    for part in conf if isinstance(conf, list) else [conf]:
        props.update(part.get("properties", {}))
    groups: dict[str, list[str]] = {}
    for name, spec in props.items():
        text = " ".join(str(spec.get("markdownDescription") or spec.get("description") or "").split())
        groups.setdefault("ai" if name.startswith("nuclear.ai.") else "editor", []).append(f"- `{name}` (default `{json.dumps(spec.get('default'))}`): {text}")
    for group, items in groups.items():
        what = "the AI loop, the local agents and their integrations" if group == "ai" else "the language, the dialect, the build and the devices"
        rows.append({
            "id": f"editor:vscode.settings.{group}", "type": "editor", "title": f"VS Code: the settings of the Nuclear extension for {what}",
            "summary": f"The {len(items)} settings of the Nuclear extension for {what}, with their defaults.",
            "body": "\n".join(items), "keys": [f"vscode {group} settings"], "sources": src, "meta": {"tool": "vscode", "name": f"settings {group}"},
        })
    return rows


COMPONENTS = [  # id, what it is, the file that says its version, how the version is written there
    ("nuclear", "the compiler, its CLI and the language server", "Cargo.toml", r'^version\s*=\s*"([^"]+)"'),
    ("dragonfly", "the CLI of Dragonfly projects", "dragonfly/Cargo.toml", r'^version\s*=\s*"([^"]+)"'),
    ("nuclear-graph", "the Smart Graph: the knowledge base and the MCP server", "nuclear-graph/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    ("nuclear-developer", "the local agents", "nuclear-developer/config.nuc", r'version = "([^"]+)"'),
    ("nuclear-vscode", "the VS Code extension, with the Loop and `nuclear-loop`", "nuclear-vscode/package.json", r'"version":\s*"([^"]+)"'),
    ("nuclear-jetbrains", "the JetBrains plugin (Android Studio, IntelliJ)", "nuclear-jetbrains/resources/META-INF/plugin.xml", r"<version>([^<]+)</version>"),
    ("nuclear-zed", "the Zed extension", "nuclear-zed/extension.toml", r'^version\s*=\s*"([^"]+)"'),
    ("dragonfly-py", "the runtime of the fastapi dialect (Python)", "dragonfly-backend/packages/dragonfly-py/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    ("dragonfly-nest", "the runtime of the nestjs dialect (TypeScript)", "dragonfly-backend/packages/dragonfly-nest/package.json", r'"version":\s*"([^"]+)"'),
    ("dragonfly-dart", "the runtime of the flutter dialect (the `dragonfly` Dart package)", "dragonfly-mobile/packages/dragonfly/pubspec.yaml", r"^version:\s*(\S+)"),
    ("dragonfly-web", "the runtime of the react dialect (TypeScript)", "dragonfly-web/packages/dragonfly-web/package.json", r'"version":\s*"([^"]+)"'),
]


def components(ctx: Context) -> list[Row]:
    rows: list[Row] = []
    for name, what, rel, pattern in COMPONENTS:
        m = re.search(pattern, ctx.read(rel), re.M)
        if not m:
            if (ctx.tree / rel).is_file():  # a manifest that moved is found by the questions (`what version is ...`)
                ctx.problems.append(f"the version of `{name}` is not in {rel} any more: correct COMPONENTS in extract.py")
            continue
        rows.append({
            "id": f"component:{name}", "type": "component", "title": f"`{name}` {m.group(1)} — {what}",
            "summary": f"`{name}` is {what}; its version is {m.group(1)}.",
            "body": f"Version {m.group(1)}, read from `{rel}`. Repository: `nuclearlang/{name.split('-py')[0].split('-nest')[0].split('-dart')[0]}`.",
            "keys": [f"{name} version"], "asks": [f"what version is {name}", f"which version of {name} is this"],
            "sources": [rel], "meta": {"tool": name, "name": "version", "version": m.group(1)},
        })
    return rows


# ---- examples: the example projects and the solved tasks ----

DECLARATION = re.compile(r"^(?:([a-z][A-Za-z]*)\s+)?([A-Z][A-Za-z0-9]*)", re.M)


def _layout_kind(layouts: dict[str, dict[str, str]], platform_: str, rel: str) -> list[str]:
    found = []
    for kind, template in layouts.get(platform_, {}).items():
        pattern = re.escape(template).replace(r"\{component\}", "[^/]+").replace(r"\{screen\}", "[^/]+").replace(r"\{file\}", "[^/]+")
        if re.fullmatch(pattern, rel):
            found.append(kind)
    return found


def _doc_comment(text: str, at: int) -> str:
    """The `//` lines right above the declaration at `at` (its decorators are skipped)."""
    lines = text[:at].splitlines()
    while lines and lines[-1].startswith("@"):
        lines.pop()
    doc: list[str] = []
    while lines and lines[-1].startswith("//"):
        doc.insert(0, lines.pop().lstrip("/ ").lstrip("* ").strip())
    return " ".join(doc)


def projects(ctx: Context) -> list[Row]:
    layouts = {p: _platform(ctx, p)[0].get("layout", {}) for p in PLATFORMS}
    kinds = {p: set(_platform(ctx, p)[0].get("platform", {}).get("kinds", [])) for p in PLATFORMS}
    rows: list[Row] = []
    roots = sorted(p.parent for p in walk(ctx.tree) if p.name == "config.nuc" and "data" not in p.relative_to(ctx.tree).parts)
    roots += [ctx.tree / "examples/projects/greetings"]
    for root in roots:
        if not root.is_dir():
            continue
        config = (root / "config.nuc").read_text() if (root / "config.nuc").is_file() else ""
        plat = (re.search(r'platform\s*=\s*"(\w+)"', config) or [None, ""])[1]
        project = root.name
        for path in walk(root):
            rel = path.relative_to(root).as_posix()
            if path.suffix != ".nuc" or "data" in rel.split("/")[:-1]:
                continue
            code = path.read_text(errors="replace").strip()
            m = next((m for m in DECLARATION.finditer(code)), None)
            word, name = (m.group(1) or "", m.group(2)) if m else ("", path.stem)
            by_path = _layout_kind(layouts, plat, rel)
            kind = word if word in kinds.get(plat, set()) else by_path[0] if by_path else word or ("config" if path.name == "config.nuc" else "file")
            doc = _doc_comment(code, m.start()) if m else ""
            shown = code if len(code) <= 5000 else code[:5000].rsplit("\n", 1)[0] + "\n// ... (the file goes on)"
            rows.append({
                "id": f"example:{project}/{rel[:-4]}", "type": "file",
                "title": clip(f"`{kind}` {name} — the example project {project}" + (f" ({plat})" if plat else ""), 140),
                "summary": clip(doc, 400) or f"A `{kind}` of the example project `{project}`" + (f", a {plat} project." if plat else "."),
                "body": f"`{rel}` of `{project}`:\n\n```nuclear\n{shown}\n```", "platforms": [plat] if plat in PLATFORMS else [],
                "sources": [path.relative_to(ctx.tree).as_posix()], "meta": {"kind": kind, "name": name, "project": project},
            })
    for path in sorted((ctx.tree / "examples/stdlib").glob("*.nuc")):
        code = path.read_text().strip()
        doc = " ".join(line.lstrip("/ ").strip() for line in code.splitlines()[:6] if line.startswith("//"))
        rows.append({
            "id": f"example:stdlib/{path.stem}", "type": "file", "title": f"The standard library at work: {path.stem} (a program that runs in every dialect)",
            "summary": clip(doc, 400) or f"A runnable example of the standard library: {path.stem}.",
            "body": f"`examples/stdlib/{path.name}`:\n\n```nuclear\n{code[:5000]}\n```", "keys": [f"{path.stem} example"],
            "sources": [f"examples/stdlib/{path.name}"], "meta": {"kind": "program", "name": path.stem, "project": "stdlib"},
        })
    return rows


def solved(ctx: Context) -> list[Row]:
    """The answers of a frontier model to the evaluation's `train` tasks that pass the compiler and their acceptance
    texts (the distillation). The `test` tasks are held out: their answers never reach the graph."""
    raw = ctx.read("nuclear-developer/eval/tasks.toml")
    answers = ctx.read("nuclear-developer/eval/results/reference.json")
    if not raw or not answers:
        return []
    bank, refs = tomllib.loads(raw), json.loads(answers)
    src = ["nuclear-developer/eval/tasks.toml", "nuclear-developer/eval/results/reference.json"]
    rows: list[Row] = []

    def row(rid: str, task: str, path: str, kind: str, code: str, plat: str) -> Row:
        return {
            "id": f"solved:{rid}", "type": "solved", "title": clip(f"Solved — a {kind}: {task}", 140), "summary": clip(task, 400),
            "body": f"Task: {task}\n\nFile `{path}`:\n\n```nuclear\n{code.strip()}\n```", "platforms": [plat] if plat in PLATFORMS else [],
            "sources": src, "meta": {"kind": kind, "validated": "sonnet + nuclear check"},
        }

    for t in bank.get("task", []):
        r = refs.get(t["id"])
        if t.get("split") == "train" and r and r.get("pass"):
            rows.append(row(t["id"], t["task"], t["path"], t["kind"], r["code"], PLATFORM_OF.get(t.get("dialect", ""), t.get("platform", ""))))
    for f in bank.get("feature", []):
        r = refs.get(f["id"])
        if f.get("split") != "train" or not r or not r.get("pass"):
            continue
        for path, code in r.get("files", {}).items():  # one example per file, as the coder writes them
            first = next((ln.split()[0] for ln in code.splitlines() if ln.strip() and not ln.startswith(("//", "@", " "))), "file")
            names = [n for _, n in DECLARATION.findall(code)]
            said = ". ".join(x for x in f["spec"].split(". ") if any(re.search(rf"\b{n}\b", x) for n in names))
            rows.append(row(f"{f['id']}/{slug(path)}", said or f["spec"], path, first, code, f.get("platform", "")))
    return rows


# ---- documents: every markdown file of the tree, section by section, on the shelf its section names ----

def split(text: str) -> Iterator[str]:
    """Pieces of at most MAX characters, cut at blank lines."""
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        if size + len(para) > MAX and buf:
            yield "\n\n".join(buf)
            buf, size = [], 0
        while len(para) > MAX:  # a long code block or table: cut at a line
            cut = para.rfind("\n", 0, MAX)
            cut = cut if cut > MAX // 2 else MAX
            yield para[:cut]
            para = para[cut:].lstrip("\n")
        buf.append(para)
        size += len(para) + 2
    if buf and "".join(buf).strip():
        yield "\n\n".join(buf)


def markdown(text: str) -> Iterator[tuple[str, str]]:
    """The sections of a markdown file (by `#`/`##`/`###` headings) as (heading path, text), each cut to MAX."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # the front matter of a context file
    path: list[str] = []
    lines: list[str] = []
    fence = False

    def flush() -> Iterator[tuple[str, str]]:
        body = "\n".join(lines).strip()
        if body:
            for piece in split(body):
                yield " › ".join(path), piece

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"(#{1,3}) (.*)", line)
        if m:
            yield from flush()
            level = len(m.group(1))
            path[level - 1:] = [plain(m.group(2)).strip()]
            lines = []
        else:
            lines.append(line)
    yield from flush()


def kind_of(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if "/adr/" in f"/{rel}":
        return "adr"
    if name == "STATUS.md":
        return "status"
    if name == "CHANGELOG.md":
        return "changelog"
    if name in ("README.md", "AGENTS.md", "CONTRIBUTING.md"):
        return "readme"
    if "/context/" in rel:
        return "context"
    if "/spec/" in f"/{rel}" or rel.startswith("specs/"):
        return "spec"
    if "docs/language/" in rel or "docs/dragonfly/" in rel or "docs/ai/" in rel:
        return "guide"
    return "doc"


def dialect_of(rel: str) -> str:
    parts = re.split(r"[/_.\-]", rel)
    return next((d for d in DIALECTS if d in parts), "")


def platform_of(rel: str, dialect: str) -> str:
    if dialect in PLATFORM_OF:
        return PLATFORM_OF[dialect]
    parts = re.split(r"[/_.\-]", rel)
    return next((p for p in PLATFORMS if p in parts), "")


def documents(tree: Path, website: Path | None) -> list[tuple[str, str, Path]]:
    """Every markdown (and grammar) file of the tree and the website: (the path the sections name, repository, file)."""
    out: list[tuple[str, str, Path]] = []
    for root, prefix in [(tree, ""), *([(website, "website/")] if website and website.is_dir() else [])]:
        for path in walk(root):
            rel = path.relative_to(root).as_posix()
            parts = rel.split("/")
            if any(rel.startswith(p) for p in PRIVATE) or path.suffix not in (".md", ".ebnf"):
                continue
            repo = "website" if prefix else parts[0] if len(parts) > 1 and (root / parts[0] / ".git").exists() else root.name
            out.append((prefix + rel, repo, path))
    return out


def matches(rel: str, globs: list[str]) -> bool:
    p = PurePosixPath(rel)
    return any(p.full_match(g) for g in globs)


def docs(ctx: Context) -> dict[str, tuple[str, list[Row]]]:
    """`<shelf>/<section>` → the rows of every document of that section, one per heading section."""
    sections = [{**s, "shelf": s.get("shelf", "docs"), "agents": s.get("agents", True)} for s in ctx.sections.get("section", [])]
    out: dict[str, tuple[str, list[Row]]] = {}
    for rel, repo, path in documents(ctx.tree, ctx.website):
        if matches(rel, ctx.sections.get("exclude", [])):
            continue
        section = next((s for s in sections if matches(rel, s["files"])), OTHER)
        shelf, agents_read = section["shelf"], bool(section["agents"])
        if section is OTHER:
            ctx.problems.append(f"{rel}: no section of sections.toml claims it")
        text = path.read_text(errors="replace")
        if path.suffix == ".ebnf":
            text = f"# The grammar of NuclearLang (EBNF)\n\n```text\n{text}\n```"
        title = plain((re.search(r"^# (.+)$", text, re.M) or [None, path.stem])[1])
        dialect = dialect_of(rel)
        plat = platform_of(rel, dialect)
        kind = kind_of(rel)
        rows = out.setdefault(f"{shelf}/{section['id']}", (section["title"], []))[1]
        pieces = []
        for heading, body in markdown(text):
            if agents_read:
                body = nuclear_only(body).strip()
            if len(body) >= 40:  # not a heading alone, nor only code a local agent does not read
                # the id of a piece: its heading without the document's own title
                pieces.append((heading, body, slug(" ".join(heading.split(" › ")[1:]) or heading or "top", 80)))
        shared = {name for _, _, name in pieces if sum(1 for p in pieces if p[2] == name) > 1}
        used: set[str] = set()
        for heading, body, name in pieces:
            prose = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith(("|", "```", "#", "-", "*", ">", "<"))]
            last = heading.split(" › ")[-1] if heading else ""
            # a heading cut in several pieces names each by its text, so a piece added above does not rename the rest
            part = f"{name}.{hashlib.sha1(body.encode()).hexdigest()[:6]}" if name in shared else name
            while part in used:
                part += "+"
            used.add(part)
            meta: dict[str, Any] = {"section": section["id"], "repo": repo, "dialect": dialect} if shelf == "docs" else {}
            rows.append({
                "id": f"{PREFIX[shelf]}:{re.sub(r'[^A-Za-z0-9_.@/+-]', '-', rel)}#{part}",
                "type": {"docs": kind, "language": "guide" if "docs/language/" in rel else "reference" if "/brief/" in rel else "rule", "platforms": "spec"}[shelf],
                "title": clip(title if last in ("", title) else f"{title} — {last}", 140),
                "summary": first_sentence(" ".join(prose) or last or title, 300), "body": body,
                "platforms": [plat] if plat else [], "agents": agents_read, "sources": [rel], "meta": meta,
            })
    return out


# ---- everything ----

def generate(ctx: Context) -> dict[str, tuple[str, list[Row]]]:
    """Every generated asset file: `<shelf>/<name>` → (what it holds, its rows)."""
    out: dict[str, tuple[str, list[Row]]] = {
        "errors/diagnostics": ("Every diagnostic of the compiler: the codes of crates/nuclear-diag and their documentation in spec/diagnostics.md.", diagnostics(ctx)),
        "errors/habits": ("What someone who knows another language writes by reflex, and the Nuclear form (the base brief's table).", habits(ctx)),
        "language/library": ("The members of the standard library and the names of other languages they replace (crates/nuclear-dialect/src/library.rs).", library(ctx)),
        "tools/cli": ("The commands of nuclear, dragonfly, nuclear-loop and nuclear-graph, as their help prints them.", cli(ctx)),
        "tools/mcp": ("The tools and the instructions of the Nuclear MCP server.", mcp_tools(ctx)),
        "tools/http": ("The HTTP routes of the Smart Graph and of the Nuclear Developer.", http_routes(ctx)),
        "tools/generators": ("What `dragonfly gen` writes on each platform (the [[generators]] of each platform.toml).", generators(ctx)),
        "tools/stages": ("The stages of the Nuclear Loop (nuclear-vscode/src/loopEngine.ts).", stages(ctx)),
        "tools/agents": ("The local agents of the Nuclear Developer, from their sources.", agents(ctx)),
        "tools/editor": ("The commands, shortcuts and settings of the VS Code extension (its package.json).", editor(ctx)),
        "tools/components": ("Each component of the ecosystem and its version.", components(ctx)),
        "examples/projects": ("Every .nuc file of the example projects, by kind and platform, and the standard library's programs.", projects(ctx)),
        "examples/solved": ("The validated answers of a frontier model to the evaluation's train tasks.", solved(ctx)),
    }
    for p in PLATFORMS:
        out[f"platforms/{p}"] = (f"The {p} platform: its kinds, decorators, layout and plugins (platform.toml and the default dialect's docs.toml).", platform(ctx, p))
    out.update(docs(ctx))
    return {name: value for name, value in out.items() if value[1]}
