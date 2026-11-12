"""Who may use the graph. A program asks for access (`POST /v1/access`); nothing is given until the user allows
it (`nuclear-graph allow <request>` or the editor). Each allowed client has its own token, stored only as a hash,
and scopes: `read` (search, prompts, examples), `write` (remember, add examples), `admin` (ingest, manage)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from . import paths

SCOPES = ("read", "write", "admin")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Access:
    def __init__(self, file: Path | None = None) -> None:
        self.file = file or paths.grants()

    def _load(self) -> dict[str, Any]:
        if not self.file.is_file():
            return {"clients": {}, "requests": {}}
        return json.loads(self.file.read_text())

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.touch(mode=0o600)
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.file)

    # clients

    def grant(self, client: str, scopes: list[str]) -> str:
        """Gives `client` a new token with `scopes` (its old token stops working). The token is shown once."""
        bad = [s for s in scopes if s not in SCOPES]
        if bad or not scopes:
            raise ValueError(f"scopes must be some of {', '.join(SCOPES)}")
        token = "ng_" + secrets.token_urlsafe(32)
        data = self._load()
        data["clients"][client] = {"hash": _hash(token), "scopes": scopes, "created": int(time.time())}
        self._save(data)
        return token

    def revoke(self, client: str) -> bool:
        data = self._load()
        found = data["clients"].pop(client, None) is not None
        self._save(data)
        return found

    def clients(self) -> dict[str, Any]:
        return {name: {"scopes": c["scopes"], "created": c["created"]} for name, c in self._load()["clients"].items()}

    def who(self, token: str, owner: str | None = None) -> tuple[str, list[str]] | None:
        """The client and scopes of a token; the owner's token has every scope."""
        if owner and secrets.compare_digest(token, owner):
            return "owner", list(SCOPES)
        h = _hash(token)
        for name, c in self._load()["clients"].items():
            if secrets.compare_digest(c["hash"], h):
                return name, c["scopes"]
        return None

    # requests

    def ask(self, client: str, scopes: list[str], reason: str = "") -> str:
        if not client or len(client) > 80 or [s for s in scopes if s not in SCOPES or s == "admin"]:
            raise ValueError("a client name and scopes among read, write")
        data = self._load()
        pending = [r for r in data["requests"].values() if r["status"] == "pending"]
        if len(pending) >= 20:
            raise ValueError("too many pending requests")
        rid = secrets.token_hex(4)
        data["requests"][rid] = {"client": client, "scopes": scopes or ["read"], "reason": reason[:200],
                                 "status": "pending", "created": int(time.time())}
        self._save(data)
        return rid

    def requests(self) -> dict[str, Any]:
        return {k: {kk: vv for kk, vv in r.items() if kk != "token"} for k, r in self._load()["requests"].items()}

    def decide(self, rid: str, allow: bool) -> None:
        data = self._load()
        r = data["requests"].get(rid)
        if r is None or r["status"] != "pending":
            raise KeyError(f"no pending request '{rid}'")
        if allow:
            token = self.grant(r["client"], r["scopes"])
            data = self._load()
            data["requests"][rid].update(status="allowed", token=token)
        else:
            data["requests"][rid]["status"] = "denied"
        self._save(data)

    def collect(self, rid: str) -> dict[str, Any]:
        """The state of a request; an allowed one hands its token once, then forgets it."""
        data = self._load()
        r = data["requests"].get(rid)
        if r is None:
            raise KeyError(rid)
        out = {"status": r["status"], "client": r["client"], "scopes": r["scopes"]}
        if r["status"] == "allowed" and "token" in r:
            out["token"] = r.pop("token")
            r["status"] = "collected"
            self._save(data)
        return out
