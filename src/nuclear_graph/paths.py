"""Where the graph keeps its data: one folder only its owner can open (0700)."""

from __future__ import annotations

import os
from pathlib import Path

PORT = int(os.environ.get("NUCLEAR_GRAPH_PORT", "7878"))
URL = os.environ.get("NUCLEAR_GRAPH_URL", f"http://127.0.0.1:{PORT}")


def home() -> Path:
    base = os.environ.get("NUCLEAR_GRAPH_HOME")
    if base:
        root = Path(base)
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "nuclear-graph"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def db() -> Path:
    return home() / "db"


def grants() -> Path:
    return home() / "grants.json"
