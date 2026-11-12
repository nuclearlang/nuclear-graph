"""`nuclear-graph`: run, fill and guard the Nuclear Smart Graph."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from . import paths, secrets_store

USAGE_ROOT = os.environ.get("NUCLEAR_ROOT", "")


def _api(method: str, path: str, body: dict | None = None, timeout: float = 3600) -> dict:
    try:
        r = httpx.request(method, paths.URL + path, json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {secrets_store.owner_token()}"})
    except httpx.ConnectError:
        sys.exit(f"the graph is not running at {paths.URL}: start it with `nuclear-graph serve`")
    if r.status_code >= 400:
        sys.exit(f"{r.status_code}: {r.text}")
    return r.json()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nuclear-graph", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the graph on 127.0.0.1 (NUCLEAR_GRAPH_PORT, default 7878)")
    sub.add_parser("mcp", help="the MCP server on stdio (for Claude Code, Codex, Cursor...)")
    i = sub.add_parser("ingest", help="fill the knowledge from the NuclearLang source roots")
    i.add_argument("roots", nargs="*", help="folders (default: $NUCLEAR_ROOT or the current folder)")
    s = sub.add_parser("search", help="search the graph")
    s.add_argument("query")
    s.add_argument("-c", "--collection", default="knowledge")
    s.add_argument("-k", type=int, default=5)
    sub.add_parser("stats", help="the size of each collection")
    c = sub.add_parser("connect", help="give a client (a program) access and keep its token in the keyring")
    c.add_argument("client")
    c.add_argument("--scopes", default="read", help="read,write (admin only for the owner)")
    c.add_argument("--print", action="store_true", help="print the token instead of keeping it")
    for name, text in (("allow", "allow a pending request"), ("deny", "deny a pending request")):
        a = sub.add_parser(name, help=text)
        a.add_argument("request")
    w = sub.add_parser("web-key", help="keep the key of a search engine for the local agents (read from stdin): brave")
    w.add_argument("engine", choices=["brave"])
    k = sub.add_parser("knowledge", help="the knowledge base folder (nuclear-developer/data): build it from the sources, or check it")
    k.add_argument("action", choices=["build", "check"])
    k.add_argument("--tree", default=os.environ.get("NUCLEAR_ROOT", str(Path(__file__).resolve().parents[3])),
                   help="the NuclearLang working tree (default: $NUCLEAR_ROOT or this checkout's)")
    k.add_argument("--out", default="", help="the knowledge folder (default: <tree>/nuclear-developer/data)")
    sub.add_parser("requests", help="pending access requests and the allowed clients")
    r = sub.add_parser("revoke", help="take a client's access away")
    r.add_argument("client")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from .server import create_app

        uvicorn.run(create_app(), host="127.0.0.1", port=paths.PORT, log_level="warning")
    elif args.cmd == "mcp":
        from .mcp_server import main as run

        run()
    elif args.cmd == "ingest":
        roots = [str(Path(r).resolve()) for r in (args.roots or [USAGE_ROOT or "."])]
        out = _api("POST", "/v1/ingest", {"roots": roots})
        print("\n".join(out.pop("log")))
        print(json.dumps(out, indent=2))
    elif args.cmd == "search":
        for item in _api("POST", "/v1/search", {"query": args.query, "collection": args.collection, "k": args.k})["items"]:
            print(f"── {item['distance']}  {item['meta'].get('source', item['id'])}\n{item['text'][:600]}\n")
    elif args.cmd == "stats":
        print(json.dumps(_api("GET", "/v1/stats"), indent=2))
    elif args.cmd == "connect":
        from .access import Access

        token = Access().grant(args.client, args.scopes.split(","))
        if args.print or not secrets_store._keyring_set(f"client:{args.client}", token):
            if not args.print:
                f = paths.home() / f".client-{args.client}"
                f.touch(mode=0o600)
                f.write_text(token)
                os.chmod(f, 0o600)
                print(f"no keyring: the token of '{args.client}' is in {f} (only you can read it)")
            else:
                print(token)
        else:
            print(f"'{args.client}' can use the graph ({args.scopes}); its token is in the keyring")
    elif args.cmd in ("allow", "deny"):
        from .access import Access

        Access().decide(args.request, args.cmd == "allow")
        print(f"request {args.request}: {args.cmd}ed")
    elif args.cmd == "requests":
        from .access import Access

        a = Access()
        print(json.dumps({"requests": a.requests(), "clients": a.clients()}, indent=2))
    elif args.cmd == "knowledge":
        from . import knowledge

        tree = Path(args.tree).resolve()
        out = Path(args.out).resolve() if args.out else tree / "nuclear-developer" / "data"
        website = knowledge.website_of(out)
        if args.action == "build":
            r = knowledge.build(tree, out, website)
            print(f"{r['files']} files in {r['sections']} sections → {out}")
            for u in r["unclaimed"]:
                print(f"  not in a section yet (99-other): {u}")
        else:
            problems = knowledge.check(tree, out, website)
            print("\n".join(problems) or f"{out}: every file is its source, byte for byte")
            raise SystemExit(1 if problems else 0)
    elif args.cmd == "web-key":
        key = sys.stdin.readline().strip()
        if not key:
            raise SystemExit("give the key on stdin: nuclear-graph web-key brave < key.txt")
        secrets_store.keep(f"search:{args.engine}", key)
        print(f"the local agents now search with {args.engine}")
    elif args.cmd == "revoke":
        from .access import Access

        print("revoked" if Access().revoke(args.client) else f"no client '{args.client}'")


if __name__ == "__main__":
    main()
