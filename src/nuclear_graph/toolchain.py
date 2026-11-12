"""The NuclearLang command line tools, for agents: check, build and format a piece of Nuclear, and run the
Dragonfly commands of a project. Answers are short texts a small model can read."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path


async def _run(args: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[int, str]:
    if not shutil.which(args[0]):
        return 127, f"{args[0]} is not installed (run the NuclearLang installer)"
    p = await asyncio.create_subprocess_exec(*args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except TimeoutError:
        p.kill()
        return 124, f"{' '.join(args)}: timed out after {timeout} s"
    return p.returncode or 0, out.decode(errors="replace")


def diagnostics_of(out: str) -> list[dict] | None:
    """Every JSON array `nuclear check --json` printed (one per file group), joined; None if there is none."""
    dec = json.JSONDecoder()
    found: list[dict] = []
    i, seen = out.find("["), False
    while i != -1:
        try:
            value, end = dec.raw_decode(out, i)
        except json.JSONDecodeError:
            i = out.find("[", i + 1)
            continue
        if isinstance(value, list):
            found.extend(v for v in value if isinstance(v, dict))
            seen = True
        i = out.find("[", end)
    return found if seen else None


def describe(diagnostics: list[dict]) -> str:
    """`line:col CODE message (fix: ...)`, one per error; `ok` when there are none."""
    lines = []
    for d in diagnostics:
        if d.get("severity") != "error":
            continue
        fix = f" (fix: {d['fix']})" if d.get("fix") else ""
        where = f"{d.get('file', '')}:" if d.get("file") else ""
        lines.append(f"{where}{d.get('line')}:{d.get('col')} {d.get('code')} {d.get('message')}{fix}")
    return "\n".join(lines) or "ok"


def strip_fences(code: str) -> str:
    """The code inside a model's ```nuclear block (or the text as it is)."""
    if "```" not in code:
        return code.strip() + "\n"
    inside, block, out = False, [], []
    for line in code.splitlines():
        if line.strip().startswith("```"):
            if inside:
                out.append("\n".join(block))
                block = []
            inside = not inside
            continue
        if inside:
            block.append(line)
    return ("\n\n".join(out) if out else code).strip() + "\n"


def snake(name: str) -> str:
    """`BooksOfAuthor` → `books_of_author`, `HTTPClient` → `http_client` (a file name)."""
    out = []
    for i, c in enumerate(name):
        if c.isupper() and i > 0 and (name[i - 1].islower() or name[i - 1].isdigit() or (i + 1 < len(name) and name[i + 1].islower() and name[i - 1].isupper())):
            out.append("_")
        out.append(c.lower())
    return "".join(out)


def layout_path(layout: dict[str, str], kind: str, name: str, component: str, screen: str = "") -> str:
    """The path of a declaration's file by the platform's layout; "" for a kind the layout does not know."""
    template = layout.get(kind, "")
    if not template:
        return ""
    return template.replace("{component}", snake(component) or "app").replace("{screen}", snake(screen) or "widgets").replace("{file}", snake(name))


PLATFORMS = ("backend", "mobile", "web")


def target(name: str) -> list[str]:
    """`--platform backend` for a platform (what an agent that writes only Nuclear names), `--dialect fastapi` else."""
    return ["--platform", name] if name in PLATFORMS else ["--dialect", name]


class Toolchain:
    """`nuclear` and `dragonfly` for agents."""

    async def check(self, code: str, platform: str = "backend") -> str:
        """The errors of a piece of Nuclear (`ok` when it has none)."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "piece.nuc"
            f.write_text(strip_fences(code))
            _, out = await _run(["nuclear", "check", str(f), *target(platform), "--json"])
        found = diagnostics_of(out)
        # the piece is checked in a scratch file: its errors are told by line, never by that file's path
        return out.strip() if found is None else describe([{**d, "file": ""} for d in found])

    async def build(self, code: str, platform: str = "backend") -> str:
        """The code a piece of Nuclear becomes (with a platform, in its default dialect's language)."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "piece.nuc"
            f.write_text(strip_fences(code))
            _, out = await _run(["nuclear", "build", str(f), *target(platform)])
        return out

    async def check_project(self, root: str) -> str:
        """The errors of every file of a project."""
        code, out = await _run(["nuclear", "check", root, "--json"])
        found = diagnostics_of(out)
        if found is None:
            return "ok" if code == 0 else out.strip()
        return describe(found)

    async def fmt(self, code: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "piece.nuc"
            f.write_text(strip_fences(code))
            await _run(["nuclear", "fmt", str(f)])
            return f.read_text()

    async def help(self, word: str, platform: str = "") -> str:
        """`nuclear help <word> [--platform p | --dialect d]`: a kind, decorator, topic or command."""
        args = ["nuclear", "help", word] + (target(platform) if platform else [])
        return (await _run(args))[1]

    async def layout(self, platform: str = "backend") -> dict[str, str]:
        """Where each kind's file goes in a project of the platform (`nuclear help layout`): kind → path."""
        _, out = await _run(["nuclear", "help", "layout", *target(platform)])
        found: dict[str, str] = {}
        for line in out.splitlines():
            cells = line.split()
            if len(cells) == 2 and cells[1].endswith(".nuc"):
                found[cells[0]] = cells[1]
        return found

    async def path_of(self, platform: str, kind: str, name: str, component: str, screen: str = "") -> str:
        """The path of one declaration's file in a project of the platform ("" for an unknown kind)."""
        return layout_path(await self.layout(platform), kind, name, component, screen)

    async def brief(self, platform: str = "backend") -> str:
        """The short sheet: with a platform, Nuclear and the platform only (what a local agent reads); with a dialect,
        also the dialect and its language."""
        return (await _run(["nuclear", "spec", "--brief", *target(platform)]))[1]

    async def dragonfly(self, root: str, args: list[str], timeout: int = 900) -> str:
        """A `dragonfly` command in a project (build, test, check, make, migrate...): its exit code and output."""
        code, out = await _run(["dragonfly", *args], cwd=root, timeout=timeout)
        return f"exit {code}\n{out[-6000:]}"
