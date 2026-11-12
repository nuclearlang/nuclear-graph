"""The two secrets of the graph: the key that encrypts its documents and the owner's token. They live in the
desktop keyring (libsecret's `secret-tool`); without one, in files of the data folder readable only by the owner."""

from __future__ import annotations

import base64
import os
import secrets
import shutil
import subprocess

from . import paths

SERVICE = "nuclear-graph"


def _env() -> dict[str, str]:
    """MCP clients start servers with a minimal environment: find the user's session bus (where the keyring is)."""
    env = dict(os.environ)
    if "DBUS_SESSION_BUS_ADDRESS" not in env and hasattr(os, "getuid"):
        bus = f"/run/user/{os.getuid()}/bus"
        if os.path.exists(bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    return env


def _keyring_get(name: str) -> str | None:
    if os.environ.get("NUCLEAR_GRAPH_NO_KEYRING") or not shutil.which("secret-tool"):
        return None
    r = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "secret", name], capture_output=True, text=True, env=_env())
    return r.stdout.strip() or None if r.returncode == 0 else None


def _keyring_set(name: str, value: str) -> bool:
    if os.environ.get("NUCLEAR_GRAPH_NO_KEYRING") or not shutil.which("secret-tool"):
        return False
    r = subprocess.run(
        ["secret-tool", "store", f"--label=Nuclear Smart Graph {name}", "service", SERVICE, "secret", name],
        input=value,
        text=True,
        capture_output=True,
        env=_env(),
    )
    return r.returncode == 0


def _file(name: str):
    return paths.home() / f".{name}"


def get(name: str, make) -> str:
    """The secret `name`, made with `make()` the first time."""
    value = _keyring_get(name)
    if value:
        return value
    f = _file(name)
    if f.is_file():
        return f.read_text().strip()
    value = make()
    if not _keyring_set(name, value):
        f.touch(mode=0o600)
        f.write_text(value)
        os.chmod(f, 0o600)
    return value


def key() -> bytes:
    """The AES-256 key of the documents."""
    return base64.b64decode(get("key", lambda: base64.b64encode(secrets.token_bytes(32)).decode()))


def owner_token() -> str:
    """The token of the graph's owner (the user's CLI and editor): every scope."""
    return get("owner", lambda: secrets.token_urlsafe(32))


def find(name: str) -> str | None:
    """The secret `name` if it was kept, or None (never made here)."""
    value = _keyring_get(name)
    if value:
        return value
    f = _file(name)
    return f.read_text().strip() if f.is_file() else None


def keep(name: str, value: str) -> None:
    """Keeps a secret given by the user (a search key) in the keyring, or in a file only the owner reads."""
    if not _keyring_set(name, value):
        f = _file(name)
        f.touch(mode=0o600)
        f.write_text(value)
        os.chmod(f, 0o600)
