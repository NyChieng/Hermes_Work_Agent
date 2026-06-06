"""
Web search + page fetch tools for the Hermes agent.

Default: DuckDuckGo (zero config, no API key).
Upgrade: set TAVILY_API_KEY in .env for better results.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; HermesAgent/1.0)"


# ── Web search ────────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 6) -> list[dict] | str:
    """
    Search the web. Returns [{title, url, snippet}] or an error string.
    Tries Tavily first if TAVILY_API_KEY is set, falls back to DuckDuckGo.
    """
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tavily_key:
        try:
            return _tavily(query, max_results, tavily_key)
        except Exception as exc:
            logger.warning("Tavily failed, falling back to DDG: %s", exc)
    return _ddg(query, max_results)


def _tavily(query: str, n: int, key: str) -> list[dict]:
    try:
        from tavily import TavilyClient
    except ImportError:
        raise ImportError("tavily-python not installed")
    client = TavilyClient(api_key=key)
    resp   = client.search(query=query, max_results=n)
    return [
        {"title": r.get("title",""), "url": r.get("url",""), "snippet": r.get("content","")[:500]}
        for r in resp.get("results", [])
    ]


def _ddg(query: str, n: int) -> list[dict] | str:
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=n):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href",  ""),
                    "snippet": r.get("body",  "")[:500],
                })
        return results or "No results found."
    except ImportError:
        return "Web search unavailable — run: pip install duckduckgo-search"
    except Exception as exc:
        logger.warning("DDG search error: %s", exc)
        return f"Search failed: {exc}"


# ── Page fetch ────────────────────────────────────────────────────────────────

def fetch_page(url: str, max_chars: int = 4000) -> str:
    """
    Fetch a URL and extract readable text content (strips scripts/styles/nav).
    Useful when search snippets aren't enough and you need the full article.
    """
    try:
        from html.parser import HTMLParser

        r = httpx.get(url, timeout=12, follow_redirects=True,
                      headers={"User-Agent": _UA})
        r.raise_for_status()

        class _Extractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.chunks: list[str] = []
                self._skip = 0

            def handle_starttag(self, tag, attrs):
                if tag in ("script","style","nav","footer","head","aside","noscript"):
                    self._skip += 1

            def handle_endtag(self, tag):
                if tag in ("script","style","nav","footer","head","aside","noscript"):
                    self._skip = max(0, self._skip - 1)

            def handle_data(self, data):
                if not self._skip:
                    text = data.strip()
                    if len(text) > 20:
                        self.chunks.append(text)

        p = _Extractor()
        p.feed(r.text)
        content = "\n".join(p.chunks)
        if len(content) > max_chars:
            content = content[:max_chars] + "\n[truncated]"
        return content or "(no readable text found)"

    except Exception as exc:
        logger.warning("fetch_page failed for %s: %s", url, exc)
        return f"Could not fetch {url}: {exc}"
