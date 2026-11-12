"""The internet for the local agents: search, and read a page as plain text. What comes back is facts for the
business logic (a rule, a format, an external API's routes), never code: code blocks are removed, so the agents keep
writing only Nuclear. Pages are untrusted text, and a page on this machine or the local network is never read (the
graph and the Developer listen on 127.0.0.1).

The search engine, the first one available: SearXNG of your own (`NUCLEAR_SEARXNG_URL`), Brave Search with the key
kept by `nuclear-graph web-key brave`, else Wikipedia (no key)."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

import httpx

from . import secrets_store

AGENT = "nuclear-developer/0.1 (local agent; +https://github.com/nuclearlang/nuclear-developer)"
SKIP = {"script", "style", "pre", "code", "noscript", "svg", "nav", "header", "footer", "form", "button", "template"}
BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "table", "dd", "dt"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def text_of(html: str) -> str:
    """The readable text of a page: no scripts, styles, menus or code blocks."""
    p = _Text()
    p.feed(html)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in "".join(p.out).split("\n"))
    return "\n".join(line for line in lines if line)


def without_code(text: str) -> str:
    """Markdown or plain text without its fenced code blocks."""
    return re.sub(r"```.*?(```|$)", "", text, flags=re.S).strip()


def public(url: str) -> bool:
    """An http(s) url whose host resolves only to public addresses (never this machine or the local network)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except OSError:
        return False
    return all(ipaddress.ip_address(str(i[4][0]).split("%")[0]).is_global for i in infos)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


class Web:
    """Search the internet and read pages, for the local agents."""

    def __init__(self, timeout: float = 20) -> None:
        self.timeout = timeout

    def engine(self) -> str:
        """searxng, brave or wikipedia: the search engine in use."""
        if os.environ.get("NUCLEAR_SEARXNG_URL"):
            return "searxng"
        return "brave" if secrets_store.find("search:brave") else "wikipedia"

    async def _hits(self, query: str, k: int) -> list[tuple[str, str, str]]:
        engine = self.engine()
        async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": AGENT}) as http:
            if engine == "searxng":
                r = await http.get(os.environ["NUCLEAR_SEARXNG_URL"].rstrip("/") + "/search", params={"q": query, "format": "json"})
                r.raise_for_status()
                return [(h.get("title", ""), h.get("url", ""), h.get("content", "")) for h in r.json().get("results", [])[:k]]
            if engine == "brave":
                r = await http.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": k},
                                   headers={"X-Subscription-Token": secrets_store.find("search:brave") or "", "Accept": "application/json"})
                r.raise_for_status()
                return [(h.get("title", ""), h.get("url", ""), h.get("description", "")) for h in r.json().get("web", {}).get("results", [])[:k]]
            r = await http.get("https://en.wikipedia.org/w/api.php",
                               params={"action": "query", "list": "search", "srsearch": query, "srlimit": k, "format": "json"})
            r.raise_for_status()
            return [(h["title"], f"https://en.wikipedia.org/wiki/{quote(h['title'].replace(' ', '_'))}", h.get("snippet", ""))
                    for h in r.json().get("query", {}).get("search", [])]

    async def search(self, query: str, k: int = 5) -> str:
        """The first results of a search: `title — url` and a line of text each, or why there are none."""
        try:
            hits = await self._hits(query, k)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            return f"the search ({self.engine()}) failed: {e}"
        if not hits:
            return f"no results ({self.engine()}) for: {query}"
        clean = lambda s: unescape(re.sub(r"<[^>]+>", "", s)).strip()  # noqa: E731
        return "\n".join(f"{i}. {clean(t)} — {u}\n   {clean(s)}" for i, (t, u, s) in enumerate(hits, 1))

    async def read(self, url: str, limit: int = 6000) -> str:
        """The text of a public page, without code blocks, at most `limit` characters."""
        async with httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": AGENT}, follow_redirects=False) as http:
            for _ in range(4):  # each redirect is checked like the first url
                if not await asyncio.to_thread(public, url):
                    return f"not read: {url} is not a public http(s) address"
                try:
                    r = await http.get(url)
                except httpx.HTTPError as e:
                    return f"not read: {url} ({e})"
                if r.is_redirect and "location" in r.headers:
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    return f"not read: {url} answered {r.status_code}"
                kind = r.headers.get("content-type", "")
                body = text_of(r.text) if "html" in kind else without_code(r.text) if kind.startswith("text/") else ""
                return _clip(body, limit) if body else f"not read: {url} is not text ({kind})"
        return f"not read: {url} redirects too many times"

    async def research(self, query: str, pages: int = 2, limit: int = 2500) -> str:
        """A search and the text of its first pages, ready for a prompt: the sources first, then each page."""
        found = await self.search(query, k=5)
        urls = re.findall(r" — (https?://\S+)", found)[:pages]
        texts = await asyncio.gather(*(self.read(u, limit) for u in urls))
        parts = [f"Search ({self.engine()}): {query}\n\n{found}"]
        parts += [f"## {u}\n\n{t}" for u, t in zip(urls, texts) if not t.startswith("not read")]
        return "\n\n".join(parts)
