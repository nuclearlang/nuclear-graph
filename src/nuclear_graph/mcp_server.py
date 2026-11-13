"""The MCP server of NuclearLang (stdio): the Nuclear Smart Graph, the `nuclear` and `dragonfly` command line tools
and the local developer agents, for any MCP client (Claude Code, Codex, Cursor...). The graph is reached with the
token of the client `mcp` (`nuclear-graph connect mcp`), so the user decides whether MCP clients may read it."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from . import paths
from .client import GraphClient
from .toolchain import Toolchain, _run
from .web import Web, public

DEVELOPER_URL = os.environ.get("NUCLEAR_DEVELOPER_URL", "http://127.0.0.1:7879")
DRAGONFLY_COMMANDS = {"new", "n", "build", "install", "test", "check", "analyze", "make", "g", "gen", "migrate", "add", "explain"}

# What the server tells every client. The generators' part is the same with or without the local agents.
LEAD = (
    "NuclearLang and Dragonfly. The generators write the standard code, the local Nuclear Developer writes what is "
    "left; you lead, validate and correct. "
    "For any request, first call graph_strategy with the user's own words: it answers which kind of request it is "
    "(a whole system, one screen, a rename, a failing test...) and the plan of that kind; follow that plan. "
)
GENERATORS = (
    "For a feature: 0) project_inspect the project; for every resource the spec names (a model and what is done "
    "with it: list, get, search, create, update, delete), call generate_resource. Its fields come from the API's "
    "answer (from_json with the url or a file: api_inspect shows its shape first), from the spec (from_spec: its "
    "example answer or its Key | Type table) or from fields; when neither the spec nor the API gives them, look "
    "up the API's documentation with web_search and web_read, and if it is still unclear ask the user, never "
    "guess. A use case that only calls a repository method is generate_usecase with calls. "
)
LOCAL = (
    "Then give developer_task only what the generators did not write (a use case with its own rules, a view's details), "
    "and wire each use case it wrote with generate_usecase (its alias in the facade, its route). "
    "For any task that writes or changes .nuc (a feature, a bug, a refactor, tests): "
    "1) call developer_task first with the project folder, a title, the description and the acceptance criteria: "
    "the local agents plan, write the tests first, write the code, run the tests and the security review, and "
    "document everything they did in a journal it returns; "
    "2) read the journal, then validate: nuclear_check of the project must say ok and dragonfly test must pass; "
    "3) correct only what failed or is wrong, never rewrite what passed; before writing .nuc read "
    "nuclear_brief(<platform>: backend, mobile or web) and search the graph instead of guessing; "
    "If the run failed, read its 'Why it failed' (the local diagnoser): when the cause was passing or you fixed it, "
    "call developer_retry instead of starting again. "
    "4) call developer_review with the run, what you corrected and why, and the corrected files, so the journal "
    "keeps your review and the local developer learns from it. "
    "Write the code yourself only when developer_task cannot run (the local developer is not running) and say so."
    
)
# A machine set up for remote agents only (ADR-0106) has no Smart Graph and no local developer: the model writes
# what the generators do not, and the tools that need those services are taken away (the end of this file).
REMOTE_LEAD = (
    "NuclearLang and Dragonfly. The generators write the standard code; you write what is left, then validate and "
    "correct. This machine has no local agents and no Smart Graph (its user chose remote agents only; "
    "`nuclear-loop setup` installs them). "
)
REMOTE = (
    "Then write only what the generators did not write (a use case with its own rules, a view's details): before "
    "writing .nuc read nuclear_brief(<platform>: backend, mobile or web) and look up a kind, a decorator or a "
    "command with nuclear_help instead of guessing; wire each use case you wrote with generate_usecase (its alias in "
    "the facade, its route). Then validate: nuclear_check of the project must say ok and dragonfly test must pass; "
    "correct only what failed, never rewrite what passed."
)
REMOTE_ONLY = os.environ.get("NUCLEAR_AI_MODE", paths.machine().get("NUCLEAR_AI_MODE", "local")) == "remote"

mcp = MCPServer("nuclear", instructions=REMOTE_LEAD + GENERATORS + REMOTE if REMOTE_ONLY else LEAD + GENERATORS + LOCAL)
graph = GraphClient("mcp")
tools = Toolchain()


@mcp.tool()
async def graph_search(query: str, shelf: str = "", k: int = 5, platform: str = "", kind: str = "", type: str = "") -> str:
    """Search the Nuclear Smart Graph, by meaning and by exact name (a diagnostic code, a command, a kind). shelf:
    concepts (what it is, why, how it works), language (how it is written in Nuclear), platforms (kinds, decorators,
    layout, plugins), tools (CLI commands, MCP tools, HTTP routes, generators, agents), errors (diagnostics, failures
    and their fixes), capabilities (what can and cannot be done, limits), playbooks (procedures, roles, skills),
    examples (validated Nuclear), docs (the long documents: dialects, ADRs, context, status), memory (what agents kept
    about projects); several separated by commas; "" searches every shelf. platform: backend, mobile, web. kind: a
    kind's rows (usecase, repository...). type: a row type (diagnostic, kind, cli, playbook...). Each card comes with
    the rows it links to."""
    return await graph.search(query, shelf, k, platform, kind, type, expand=True)


@mcp.tool()
async def graph_strategy(request: str, platform: str = "") -> str:
    """Which kind of request this is (a whole system, a component, a resource, one screen, a use case, a rename, a
    failing test, a question...) and the plan of that kind, step by step with the tool of each step. Call it first,
    with the user's request in their own words, and follow the plan it answers. platform: backend, mobile or web."""
    found = await graph.strategy(request, platform)
    if not found:
        return "the graph has no strategy: `nuclear-graph ingest` the knowledge base"
    return f"{found['id']} ({found['why'] or 'by meaning'}; the next closest: {found['second'] or 'none'})\n\n{found['plan']}"


@mcp.tool()
async def graph_card(id: str) -> str:
    """One row of the graph by its id, with what it links to: error:N0114 (a diagnostic), kind:backend.usecase,
    decorator:backend.get, tool:dragonfly.gen.resource, mcp:generate_resource, lib:string, platform:mobile,
    layout:web, playbook:<name>, concept:<name>."""
    return await graph.card(id) or f"no row `{id}`: search it with graph_search"


@mcp.tool()
async def graph_prompt(use_case: str) -> str:
    """The validated prompt of a use case: feature, refactor, bug, docs, diagram, test, security, piece, plan."""
    return await graph.prompt(use_case)


@mcp.tool()
async def graph_remember(id: str, text: str, collection: str = "memory", project: str = "") -> str:
    """Keep a decision, a name or a solved example (collection examples: the task, then the validated .nuc) so the
    local developer and later sessions find it."""
    return await graph.remember(id, text, collection, project)


@mcp.tool()
async def nuclear_check(code: str = "", path: str = "", dialect: str = "backend") -> str:
    """Errors of a piece of Nuclear (code) or of a whole project (path of its folder): `ok` or one line per error
    with its fix."""
    return await (tools.check_project(path) if path else tools.check(code, dialect))


@mcp.tool()
async def nuclear_build(code: str, dialect: str = "backend") -> str:
    """What a piece of Nuclear becomes in the dialect's language (Python, TypeScript, Dart)."""
    return await tools.build(code, dialect)


@mcp.tool()
async def nuclear_help(word: str, dialect: str = "") -> str:
    """Documentation of a kind, decorator, header word (with dialect), a topic or a command."""
    return await tools.help(word, dialect)


@mcp.tool()
async def nuclear_brief(dialect: str = "backend") -> str:
    """The short sheet of Nuclear and a platform (backend, mobile, web), or a dialect: read it before writing .nuc."""
    return await tools.brief(dialect)


@mcp.tool()
async def nuclear_fmt(code: str) -> str:
    """The piece of Nuclear in the canonical layout."""
    return await tools.fmt(code)


@mcp.tool()
async def nuclear_defs(name: str, dialect: str) -> str:
    """A declaration of the type definitions (a class or Class.member of a library the dialect uses)."""
    return (await _run(["nuclear", "defs", "show", name, "--dialect", dialect]))[1]


@mcp.tool()
async def dragonfly(project: str, command: str, args: list[str] | None = None) -> str:
    """A dragonfly command in a project folder: new, build, install, test, check, analyze, make (g), migrate, add,
    explain. Example: command="make", args=["component", "orders"]."""
    if command not in DRAGONFLY_COMMANDS:
        return f"'{command}' is not allowed here (allowed: {', '.join(sorted(DRAGONFLY_COMMANDS))})"
    return await tools.dragonfly(project, [command, *(args or [])])


@mcp.tool()
async def project_inspect(project: str) -> str:
    """What a Dragonfly project has: its platform and dialect, its components with their declarations by kind, and
    the generators of its platform. Call it before generating or writing, so nothing is declared twice."""
    return await tools.dragonfly(project, ["gen", "inspect"])


@mcp.tool()
async def generate_component(project: str, component: str) -> str:
    """A new component of the project with its facade (appcomponent)."""
    return await tools.dragonfly(project, ["gen", "component", component])


@mcp.tool()
async def generate_resource(
    project: str,
    component: str,
    name: str,
    from_json: str = "",
    from_spec: str = "",
    fields: str = "",
    source: str = "",
    path: str = "",
    actions: list[str] | None = None,
    screen: str = "",
    plural: str = "",
    dry_run: bool = False,
) -> str:
    """The finished, compiling code of a resource: its models, the repository, one use case per action, the
    facade's aliases, the controller (backend) or, with screen, a screen with its state manager (mobile, web), and
    the tests. The fields: from_json (an example answer of the API: a url, which also gives the API, or a file),
    from_spec (a spec.md: its example answer or its Key | Type table, and its `GET <url>` line), or fields
    ("id:int name:string origin:Origin?"). source: "rest:<base url>", "rest" or "db" (backend only). actions: of
    list, get, search, create, update, delete (default: list and get for an API, the rest for a database).
    dry_run shows the files without writing them. Nothing is overwritten; a name declared elsewhere stops it."""
    args = ["gen", "resource", component, name]
    for flag, value in (("--from-json", from_json), ("--from-spec", from_spec), ("--fields", fields), ("--source", source),
                        ("--path", path), ("--screen", screen), ("--plural", plural)):
        if value:
            args += [flag, value]
    if actions:
        args += ["--actions", ",".join(actions)]
    if dry_run:
        args.append("--dry-run")
    return await tools.dragonfly(project, args)


@mcp.tool()
async def generate_usecase(project: str, component: str, name: str, calls: str = "", route: str = "", dry_run: bool = False) -> str:
    """A use case wired into its component: its alias in the facade and, with route (backend), its route in the
    controller of the route's prefix ("POST orders/{id}/cancel": a {name} is a parameter of the use case; the
    controller is created when missing). With calls ("OrderRepository.pending": a method that repository declares)
    the use case is written too, because it only calls that method. Without calls the use case must already be in
    the project: one with rules of its own is written first (developer_task, or by hand), then this wires it.
    dry_run shows the files without writing them."""
    args = ["gen", "usecase", component, name]
    for flag, value in (("--calls", calls), ("--route", route)):
        if value:
            args += [flag, value]
    if dry_run:
        args.append("--dry-run")
    return await tools.dragonfly(project, args)


@mcp.tool()
async def generate_screen(project: str, component: str, screen: str, route: str = "") -> str:
    """A screen of a mobile or web project with its state manager and state model, for a view that is not a list of
    a resource (generate_resource with screen writes those)."""
    return await tools.dragonfly(project, ["make", "screen", component, screen, *(["--route", route] if route else [])])


def shape(value: Any, depth: int = 0) -> str:
    """The shape of a JSON value, one key per line: `name: string`, a nested object indented, a list by its first item."""
    pad = "  " * depth
    if isinstance(value, dict):
        lines: list[str] = []
        for key, v in value.items():  # pyright: ignore[reportUnknownVariableType]
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}: {'object' if isinstance(v, dict) else 'list of'}")
                lines.append(shape(v, depth + 1))
            else:
                lines.append(f"{pad}{key}: {_kind(v)}")
        return "\n".join(lines)
    if isinstance(value, list) and value:
        return shape(value[0], depth)  # pyright: ignore[reportUnknownArgumentType]
    return f"{pad}{_kind(value)}"


def _kind(v: Any) -> str:
    if v is None:
        return "null (optional)"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "double"
    if isinstance(v, str):
        return "string"
    return "empty list" if isinstance(v, list) else "empty object"


@mcp.tool()
async def api_inspect(url: str, project: str = "", component: str = "", name: str = "") -> str:
    """Fetches a public API's url and answers the shape of its JSON (keys, types, nested objects, a paged answer).
    With project, component and name it also shows the files generate_resource would write from it."""
    if not await asyncio.to_thread(public, url):
        return f"not read: {url} is not a public http(s) address"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
            r = await http.get(url, headers={"Accept": "application/json"})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return f"{url}: no JSON answer ({e})"
    out = f"GET {url} → {r.status_code}\n\n{shape(data)}"
    if project and component and name:
        out += "\n\n" + await generate_resource(project, component, name, from_json=url, dry_run=True)
    return out


web = Web()


@mcp.tool()
async def web_search(query: str, pages: int = 2) -> str:
    """Searches the internet (e.g. an API's documentation: "rick and morty api character schema") and answers the
    first results with the text of their first pages."""
    return await web.research(query, pages=pages)


@mcp.tool()
async def web_read(url: str) -> str:
    """The text of a public page (an API's documentation), without its code blocks."""
    return await web.read(url)


async def _developer(path: str, body: dict[str, Any]) -> str:
    try:
        async with httpx.AsyncClient(base_url=DEVELOPER_URL, timeout=900) as http:
            r = await http.post(path, json=body)
    except httpx.HTTPError as e:
        return f"the local developer is not running at {DEVELOPER_URL} ({e}); start it: nuclear-developer serve"
    if r.status_code >= 400:
        return f"developer {path}: {r.status_code} {r.text}"
    out = r.json()
    return f"check: {out.get('check')}\nattempts: {out.get('attempts')}\n\n```nuclear\n{out.get('code', '')}```"


def _project(folder: str) -> Path | None:
    """The closest folder up with a config.nuc (a Dragonfly project)."""
    for d in [Path(folder).resolve(), *Path(folder).resolve().parents]:
        if (d / "config.nuc").exists():
            return d
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


def spec_markdown(title: str, description: str, criteria: list[str], use_case: str) -> str:
    """The spec file the Loop reads (the shape of `specMarkdown` in the Loop engine), led by the local agents."""
    items = [f"- [ ] {c}" for c in criteria] or ["- (none yet)"]
    return "\n".join([f"# {title}", "", f"- Use case: {use_case}", "- Source: local", "- Lead: local agents only", "",
                      "## Description", "", description.strip(), "", "## Acceptance criteria", "", *items]) + "\n"


@mcp.tool()
async def developer_task(project: str, title: str, description: str, criteria: list[str], use_case: str = "feature") -> str:
    """FIRST STEP of every task that writes .nuc: the local Nuclear Developer does the whole task in the project
    folder (plan, tests first, code, verification, security, artifacts) and documents it. Give the description and
    one acceptance criterion per item; use_case: feature, bug, refactor, test. Answers the run's journal (every
    step, the files written, what is left for you); then validate and correct, and call developer_review."""
    root = _project(project)
    if root is None:
        return f"{project} is not inside a Dragonfly project (no config.nuc): create it with dragonfly(command='new')"
    run_id = _slug(title)
    spec = root / "specs" / run_id / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(spec_markdown(title, description, criteria, use_case))
    code, out = await _run(["nuclear-loop", "run", str(spec), "--lead", "local"], cwd=str(root), timeout=3600)
    journal = root / ".nuclear" / "loop" / "runs" / f"{run_id}.md"
    if not journal.exists():
        return f"nuclear-loop exited {code} without a journal:\n{out[-3000:]}"
    state = "passed" if code == 0 else "did not pass: correct only what is left"
    return (f"run `{run_id}` {state} · journal {journal}\n\n{journal.read_text()}\n\n---\nNext: validate (nuclear_check of the "
            f"project, dragonfly test), correct only what is wrong, then ALWAYS finish with developer_review(project, "
            f"run=\"{run_id}\", notes=<what you corrected and why>, files=<the .nuc paths you corrected>), also when you "
            f"corrected nothing.")


@mcp.tool()
async def developer_retry(project: str, run: str, from_stage: str = "") -> str:
    """A developer_task run that failed, again from the step that failed (every step that passed is kept), or the
    whole of from_stage (plan, test, code, verify, security, artifacts, deploy), the stages before it kept. Read the journal's "Why it failed" first: retry when the
    failure was passing (a service down) or after you fixed its cause. Answers the journal again."""
    root = _project(project)
    if root is None:
        return f"{project} is not inside a Dragonfly project (no config.nuc)"
    args = ["nuclear-loop", "retry", run] + (["--from", from_stage] if from_stage else [])
    code, out = await _run(args, cwd=str(root), timeout=3600)
    journal = root / ".nuclear" / "loop" / "runs" / f"{run}.md"
    if not journal.exists():
        return f"nuclear-loop exited {code}:\n{out[-3000:]}"
    return f"run `{run}` {'passed' if code == 0 else 'did not pass'} · journal {journal}\n\n{journal.read_text()}"


@mcp.tool()
async def developer_review(project: str, run: str, notes: str, files: list[str] | None = None) -> str:
    """LAST STEP: record your review of a developer_task run: what you corrected and why (notes), and the project
    paths of the files you corrected. Appends it to the run's journal and keeps each corrected file, with its task,
    in the graph's examples so the local developer writes it right next time."""
    root = _project(project)
    if root is None:
        return f"{project} is not inside a Dragonfly project (no config.nuc)"
    runs = root / ".nuclear" / "loop" / "runs"
    if not (runs / f"{run}.json").exists():
        return f"no run `{run}` in {runs}"
    task = (root / "specs" / run / "spec.md").read_text() if (root / "specs" / run / "spec.md").exists() else run
    paths = [(f, (root / f).resolve()) for f in files or []]
    for f, path in paths:
        if root not in path.parents or not path.is_file() or path.suffix != ".nuc":
            return f"{f} is not a .nuc file of the project"
    if paths and (await tools.check_project(str(root))) != "ok":
        return "nuclear check of the project is not ok yet: correct it before the review"
    for f, path in paths:
        await graph.remember(f"review-{run}-{_slug(f)}", f"{task}\nFile `{f}`:\n\n```nuclear\n{path.read_text()}```", "examples", root.name)
    kept = [f for f, _ in paths]
    review = runs / f"{run}.review.md"
    with review.open("a") as out:
        out.write(f"## Review by the lead\n\n{notes.strip()}\n\n" + "".join(f"- corrected `{f}`\n" for f in kept) + "\n")
    return f"review kept in {review}" + (f"; {len(kept)} corrected file(s) added to the graph's examples" if kept else "")


@mcp.tool()
async def developer_code(task: str, platform: str = "backend", path: str = "", kind: str = "", context: str = "", project: str = "") -> str:
    """Ask the local developer (a 3B model with the graph) for ONE .nuc file, outside a developer_task run (a quick
    piece, a rewrite of one file). A short, complete order: the path, the kind, every name and signature it must use
    and the platform (backend, mobile, web; it writes only Nuclear). With project (the project's folder) it reads by
    itself the files that declare the names the task writes; otherwise paste them in context. It checks its answer
    with the compiler, repairs it, holds it to the task's own words and returns it; it does not write the file."""
    root = _project(project) if project else None
    return await _developer("/developer/code", {"task": task, "platform": platform, "path": path, "kind": kind, "context": context, "root": str(root or "")})


@mcp.tool()
async def developer_test(task: str, code: str, platform: str = "backend") -> str:
    """Ask the local tester for the Nuclear tests (`tests` kind) of a piece of code."""
    return await _developer("/developer/test", {"task": task, "platform": platform, "context": code})


@mcp.tool()
async def developer_security(code: str, platform: str = "backend") -> str:
    """Ask the local security reviewer for the findings of a piece of code."""
    return await _developer("/developer/security", {"task": "review", "platform": platform, "context": code})


if REMOTE_ONLY:
    for _name in [n for n in dict(globals()) if n.startswith(("graph_", "developer_"))]:
        mcp.remove_tool(_name)


def main() -> None:
    mcp.run()
