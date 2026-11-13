"""`nuclear-graph`: run, fill and guard the Nuclear Smart Graph."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from . import paths, secrets_store

TREE = os.environ.get("NUCLEAR_ROOT", str(Path(__file__).resolve().parents[3]))


def _api(method: str, path: str, body: dict | None = None, timeout: float = 3600, missing: bool = True) -> dict:
    try:
        r = httpx.request(method, paths.URL + path, json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {secrets_store.owner_token()}"})
    except httpx.ConnectError:
        if not missing:
            return {}
        sys.exit(f"the graph is not running at {paths.URL}: start it with `nuclear-graph serve`")
    if r.status_code >= 400:
        sys.exit(f"{r.status_code}: {r.text}")
    return r.json()


def _ask(out: Path, only: list[str]) -> int:
    """Asks the running graph every question of `<out>/questions.toml` (or the ones that contain a word of `only`)
    and prints which found its row among the first results. 1 when one did not."""
    import tomllib

    questions = tomllib.loads((out / "questions.toml").read_text())["question"]
    questions = [q for q in questions if not only or any(w.lower() in q["ask"].lower() for w in only)]
    failed = first = 0
    for q in questions:
        top = q.get("top", 3)
        where = {"kind": q["kind"]} if q.get("kind") else None
        body = {"query": q["ask"], "k": max(top, 5), "platform": q.get("platform", ""), "agents": q.get("agents", True),
                "shelves": q["shelves"].split(",") if q.get("shelves") else None, "where": where}
        if q.get("request"):
            # a request, not a question: the strategy the graph gives it must be the expected one
            top = q.get("top", 1)
            got = [i["id"] for i in _api("POST", "/v1/strategy", {"text": q["ask"], "platform": q.get("platform", ""), "existing": q.get("existing"), "new": q.get("new")})["items"]]
        else:
            got = [i["id"] for i in _api("POST", "/v1/search", body)["items"]]
        hit = next((n for n, i in enumerate(got, 1) if any(i == e or (e.endswith("*") and i.startswith(e[:-1])) for e in q["expect"])), 0)
        ok = 0 < hit <= top
        failed += not ok
        first += hit == 1
        if not ok:
            print(f"✗ {q['ask']}\n    wanted {q['expect']} in the first {top}; got {got}")
    print(f"{len(questions) - failed} of {len(questions)} questions found their row ({first} as the first result)")
    return 1 if failed else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nuclear-graph", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the graph on 127.0.0.1 (NUCLEAR_GRAPH_PORT, default 7878)")
    sub.add_parser("mcp", help="the MCP server on stdio (for Claude Code, Codex, Cursor...)")
    k = sub.add_parser("knowledge", help="the knowledge base folder (nuclear-developer/data): build its assets from the working tree, "
                                         "check that they are what the tree gives now, record the review of a hand-written row, or "
                                         "ask the running graph the questions of questions.toml and see that each finds its row")
    k.add_argument("action", choices=["build", "check", "review", "ask"])
    k.add_argument("ids", nargs="*", help="review: the rows that still hold (default: every row whose source changed); "
                                          "ask: only the questions that contain one of these words")
    k.add_argument("--tree", default=TREE, help="the NuclearLang working tree (default: $NUCLEAR_ROOT or this checkout's)")
    k.add_argument("--out", default="", help="the knowledge folder (default: <tree>/nuclear-developer/data)")
    i = sub.add_parser("ingest", help="make the knowledge base folder what the graph knows (only what changed is embedded again)")
    i.add_argument("folder", nargs="?", default="", help="the knowledge folder (default: <tree>/nuclear-developer/data)")
    s = sub.add_parser("search", help="search the graph: by meaning and by exact name (a code, a command, a kind)")
    s.add_argument("query")
    s.add_argument("-c", "--collection", default="", help="one shelf (default: every shelf of the knowledge base)")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("-p", "--platform", default="", help="backend, mobile or web")
    s.add_argument("--agents", action="store_true", help="only what the local agents read")
    s.add_argument("--full", action="store_true", help="print each row whole")
    st = sub.add_parser("strategy", help="which kind of request a text is (a whole system, one screen, a rename, a failing test...) and its plan")
    st.add_argument("request")
    st.add_argument("-p", "--platform", default="", help="backend, mobile or web")
    st.add_argument("--full", action="store_true", help="print the plan of the strategy")
    c0 = sub.add_parser("card", help="one row of the knowledge base by its id (error:N0114, kind:backend.usecase), with what it links to")
    c0.add_argument("id")
    sub.add_parser("stats", help="the rows of each collection and the revision of the knowledge base the graph holds")
    c = sub.add_parser("connect", help="give a client (a program) access and keep its token in the keyring")
    c.add_argument("client")
    c.add_argument("--scopes", default="read", help="read,write (admin only for the owner)")
    c.add_argument("--print", action="store_true", help="print the token instead of keeping it")
    for name, text in (("allow", "allow a pending request"), ("deny", "deny a pending request")):
        a = sub.add_parser(name, help=text)
        a.add_argument("request")
    w = sub.add_parser("web-key", help="keep the key of a search engine for the local agents (read from stdin): brave")
    w.add_argument("engine", choices=["brave"])
    sub.add_parser("requests", help="pending access requests and the allowed clients")
    r = sub.add_parser("revoke", help="take a client's access away")
    r.add_argument("client")
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from .server import create_app

        uvicorn.run(create_app(), host="127.0.0.1", port=paths.PORT, log_level="warning")
    elif args.cmd == "mcp":
        from .mcp_server import main as run

        run()
    elif args.cmd == "ingest":
        folder = Path(args.folder).resolve() if args.folder else Path(TREE).resolve() / "nuclear-developer" / "data"
        out = _api("POST", "/v1/ingest", {"roots": [str(folder)]})
        print("\n".join(out.pop("log")))
        print(json.dumps(out, indent=2))
    elif args.cmd == "search":
        body = {"query": args.query, "collection": args.collection, "k": args.k, "platform": args.platform, "agents": args.agents}
        for item in _api("POST", "/v1/search", body)["items"]:
            print(f"── {item['score']:.3f} ({item['distance']:.3f} {item['via']})  {item['shelf']}  {item['id']}")
            print((item["text"] if args.full else item["text"][:600]) + "\n")
    elif args.cmd == "strategy":
        found = _api("POST", "/v1/strategy", {"text": args.request, "platform": args.platform})["items"]
        for n, item in enumerate(found):
            print(f"{'→' if n == 0 else ' '} {item['score']:5.2f}  {item['id']}  ({item['why'] or 'by meaning'})")
        if found and args.full:
            print("\n" + found[0]["text"])
    elif args.cmd == "card":
        from .assets import as_text

        print(as_text([_api("GET", f"/v1/cards/{args.id}")]))
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
        if args.action == "build":
            r = knowledge.build(tree, out)
            if r["problems"]:
                print("\n".join(r["problems"]))
                raise SystemExit(f"{len(r['problems'])} problem(s): nothing was versioned")
            print(f"revision {r['revision']}: {r['rows']} rows ({r['added']} added, {r['changed']} changed, {r['removed']} removed) → {out}")
            print("  " + ", ".join(f"{s} {n}" for s, n in r["shelves"].items()))
            print("\n".join(r["review"]))
        elif args.action == "ask":
            raise SystemExit(_ask(out, args.ids))
        elif args.action == "review":
            done = knowledge.review(tree, out, args.ids)
            print("\n".join(f"reviewed: {i}" for i in done) or "no row was waiting for a review")
        else:
            problems = knowledge.check(tree, out)
            held = _api("GET", "/v1/stats", timeout=5, missing=False).get("knowledge")
            want = knowledge.read_manifest(out)["revision"]
            if held and held["revision"] != want:
                problems.append(f"the graph holds revision {held['revision']} and the knowledge base is revision {want}: `nuclear-graph ingest`")
            print("\n".join(problems) or f"{out}: revision {want}, every row is what the tree gives now" + (" and the graph holds it" if held else " (the graph is not running)"))
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
