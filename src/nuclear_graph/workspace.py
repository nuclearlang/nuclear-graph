"""A project's files for a local agent, confined to the project's folder: the lite toolbox a coding agent needs to
read a project before it writes in it. Read a file, list a folder, find files, search a text, outline a file's
declarations, find the files that declare the names a task writes (its context), and give every file that writes a
name with another name in its place (a rename). Nothing outside the project is
reached; generated, vendored and hidden folders are never read. Answers are short texts a small model can read.

It only reads: an agent's files are written by the Loop, which keeps the ledger that undoes them."""

from __future__ import annotations

import re
from pathlib import Path

SKIP = {"build", "node_modules", ".git", ".venv", ".nuclear", ".dart_tool", "dist", "target", "__pycache__"}
DECLARATION = re.compile(r"^(?:([a-z][A-Za-z]*)\s+)?([A-Z][A-Za-z0-9]*)\b(?!\s*=)", re.M)
MEMBER = re.compile(r"^  (?:@.*\n  )*([a-z][A-Za-z0-9]*\??(?:\([^\n]*\))?[^\n=]*?)\s*(?:=.*)?$", re.M)
NAME = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)*\b")


class Workspace:
    """The files of one project, for an agent."""

    def __init__(self, root: str = ".") -> None:
        self.root = Path(root).resolve()

    def _path(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"{rel} is outside the project")
        if SKIP & set(path.relative_to(self.root).parts):
            raise ValueError(f"{rel} is generated or hidden: an agent reads only the project's own files")
        return path

    def _files(self, pattern: str) -> list[Path]:
        found = [p for p in self.root.glob(pattern) if p.is_file() and not SKIP & set(p.relative_to(self.root).parts)]
        return sorted(found)

    def read(self, path: str, start: int = 1, lines: int = 200) -> str:
        """A file's lines, numbered, from `start`, at most `lines` of them."""
        try:
            text = self._path(path).read_text(errors="replace").splitlines()
        except (OSError, ValueError) as e:
            return f"not read: {e}"
        part = text[start - 1 : start - 1 + lines]
        more = f"\n… {len(text) - (start - 1 + len(part))} more lines (read from line {start + len(part)})" if start - 1 + len(part) < len(text) else ""
        return "\n".join(f"{n:4}  {line}" for n, line in enumerate(part, start)) + more

    def list(self, folder: str = "") -> str:
        """What a folder holds, one name per line (a folder ends with `/`)."""
        try:
            entries = sorted(self._path(folder or ".").iterdir(), key=lambda p: (p.is_file(), p.name))
        except (OSError, ValueError) as e:
            return f"not listed: {e}"
        return "\n".join(p.name + ("/" if p.is_dir() else "") for p in entries if p.name not in SKIP and not p.name.startswith(".")) or "(empty)"

    def find(self, pattern: str = "**/*.nuc") -> str:
        """The project's files that match a glob (`**/*_repository.nuc`), one path per line."""
        return "\n".join(p.relative_to(self.root).as_posix() for p in self._files(pattern)[:200]) or "(none)"

    def grep(self, text: str, pattern: str = "**/*.nuc", limit: int = 40) -> str:
        """The lines that have a text (a regular expression) in the files of a glob: `path:line: text`."""
        try:
            wanted = re.compile(text)
        except re.error:
            wanted = re.compile(re.escape(text))
        out: list[str] = []
        for file in self._files(pattern):
            for n, line in enumerate(file.read_text(errors="replace").splitlines(), 1):
                if wanted.search(line):
                    out.append(f"{file.relative_to(self.root).as_posix()}:{n}: {line.strip()}")
                    if len(out) == limit:
                        return "\n".join(out) + "\n… (more)"
        return "\n".join(out) or "(no line has it)"

    def outline(self, path: str) -> str:
        """The declarations of a `.nuc` file: each with its kind word, its name and its members' signatures."""
        try:
            text = self._path(path).read_text(errors="replace")
        except (OSError, ValueError) as e:
            return f"not read: {e}"
        out: list[str] = []
        starts = [m for m in DECLARATION.finditer(text) if not text[: m.start()].endswith(("// ", "//"))]
        for i, m in enumerate(starts):
            body = text[m.end() : starts[i + 1].start() if i + 1 < len(starts) else len(text)]
            header = text[m.start() : text.find("\n", m.start()) if "\n" in text[m.start():] else len(text)]
            out.append(header.strip())
            out += [f"  {s.strip()}" for s in MEMBER.findall(body)]
        return "\n".join(out) or "(no declaration)"

    def declarations(self) -> dict[str, str]:
        """Every declaration of the project's `.nuc` files: its name → the file that declares it."""
        found: dict[str, str] = {}
        for file in self._files("**/*.nuc"):
            rel = file.relative_to(self.root).as_posix()
            for m in DECLARATION.finditer(file.read_text(errors="replace")):
                found.setdefault(m.group(2), rel)
        return found

    def renames(self, old: str, new: str) -> dict[str, str]:
        """The names a rename changes: `old` itself and every declaration of the project whose name is built from it
        by putting words before or after (`NewBook`, `BookRepository`, `CreateBook` for `Book`), each with `new` in
        its place. A framework binds some of them to it by their name (a repository to its entity), so they follow
        it. A plural (`ListBooks`) is another word and stays."""
        names = {old: new}
        built = re.compile(rf"^(?:[A-Z][a-z0-9]*)*{re.escape(old)}(?:[A-Z][a-z0-9]*)*$")
        if old[:1].isupper():
            for name in self.declarations():
                if name != old and built.match(name):
                    names[name] = name.replace(old, new)
        return names

    def renamed(self, old: str, new: str) -> dict[str, str]:
        """A rename done by a tool, not by a model: every `.nuc` file that writes one of the names the rename changes
        (`renames`) as a word, as its path → its whole text with the new names. Nothing is written: the caller writes
        the files (the Loop, which can undo them) and the compiler and the tests say whether a use was missed."""
        names = self.renames(old, new)
        word = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b")
        out: dict[str, str] = {}
        for file in self._files("**/*.nuc"):
            text = file.read_text(errors="replace")
            if word.search(text):
                out[file.relative_to(self.root).as_posix()] = word.sub(lambda m: names[m.group(1)], text)
        return out

    def context(self, task: str, skip: str = "", most: int = 5, size: int = 1800) -> str:
        """The project's files that declare the names a task writes (`BookRepository`, `Book`), each as a ```nuclear
        block under its path: what a piece depends on. `skip`: the file being written."""
        where = self.declarations()
        files: list[str] = []
        for name in dict.fromkeys(NAME.findall(task)):
            rel = where.get(name)
            if rel and rel != skip and rel not in files:
                files.append(rel)
        blocks = []
        for rel in files[:most]:
            text = (self.root / rel).read_text(errors="replace").strip()
            blocks.append(f"```nuclear\n// {rel}\n{text[:size]}{chr(10) + '// ... (the file goes on)' if len(text) > size else ''}\n```")
        return "\n\n".join(blocks)
