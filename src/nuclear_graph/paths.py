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


def machine() -> dict[str, str]:
    """What the AI set-up chose on this machine (ADR-0106): the `KEY=value` lines of nuclearlang/ai.env, written by
    `nuclear-loop setup` and the editor (the mode, the profile and its models)."""
    base = Path(os.environ.get("APPDATA") or Path.home()) if os.name == "nt" else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    try:
        lines = (base / "nuclearlang" / "ai.env").read_text().splitlines()
    except OSError:
        return {}
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def db() -> Path:
    return home() / "db"


def grants() -> Path:
    return home() / "grants.json"
