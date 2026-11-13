"""Every ```nuclear block of a hand-written row compiles: `python tests/check_examples.py [knowledge folder]`. A block
is checked alone, for the row's first platform (backend when it names none). Exit 1 when one has an error."""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from nuclear_graph.toolchain import diagnostics_of

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "nuclear-developer" / "data"
FENCE = re.compile(r"```nuclear\n(.*?)```", re.S)


def blocks():
    for path in sorted((ROOT / "assets").glob("*/*.json")):
        data = json.loads(path.read_text())
        if data.get("origin") == "generated":
            continue
        for row in data["rows"]:
            text = "\n".join(str(row.get(k) if isinstance(row.get(k), str) else "\n".join(row.get(k) or [])) for k in ("body", "add"))
            for n, code in enumerate(FENCE.findall(text), 1):
                if re.search(r"^dragonfly\(", code, re.M):
                    continue  # a project's manifest (config.nuc): not a file to check alone
                yield f"{path.name} {row['id']} #{n}", (row.get("platforms") or ["backend"])[0], code


def main() -> int:
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for n, (where, platform, code) in enumerate(blocks()):
            file = Path(tmp) / "piece.nuc"
            file.write_text(code)
            out = subprocess.run(["nuclear", "check", str(file), "--platform", platform, "--json"], capture_output=True, text=True).stdout
            errors = [e for e in diagnostics_of(out) or [] if e.get("severity") == "error"]
            for e in errors:
                bad += 1
                print(f"{where} ({platform}): {e['line']}:{e['col']} {e['code']} {e['message']}")
    print(f"{n + 1} blocks, {bad} errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
