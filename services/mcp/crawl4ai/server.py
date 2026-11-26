"""Crawl4AI MCP Server — streamable-HTTP bridge to the Crawl4AI REST API.

Enables LIA to read and scrape any public webpage: product pages, articles, docs.
This is a thin wrapper — all heavy lifting (Playwright, browser rendering) is
handled by the separate crawl4ai container.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

CRAWL4AI_BASE = os.getenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")
CRAWL4AI_TOKEN = os.getenv("CRAWL4AI_API_TOKEN", "").strip()
CRAWL4AI_HEADERS = (
    {"Authorization": f"Bearer {CRAWL4AI_TOKEN}"} if CRAWL4AI_TOKEN else {}
)

mcp = FastMCP(
    "Crawl4AI",
    host=os.getenv("HOST", "0.0.0.0"),
    instructions=(
        "Use scrape_url to read any single webpage as clean markdown. "
        "Use crawl_urls to scrape multiple pages at once (max 5). "
        "Best for: reading product pages, comparing prices, reading articles, "
        "extracting structured information, or researching any topic on the web."
    ),
)


@mcp.tool()
async def scrape_url(url: str) -> str:
    """Scrape a URL and return clean, readable markdown content.

    Use for reading product pages, articles, price comparisons, reviews,
    documentation, recipe pages, or any public webpage.

    Args:
        url: The full URL to scrape (must start with http:// or https://)
    """
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{CRAWL4AI_BASE}/md",
            headers=CRAWL4AI_HEADERS,
            json={"url": url, "f": "fit"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            return f"Failed to scrape {url}"
        content = data.get("markdown", "")
        if len(content) > 50_000:
            content = content[:50_000] + "\n\n[Content truncated to 50,000 chars]"
        return content


@mcp.tool()
async def crawl_urls(urls: list[str]) -> str:
    """Scrape multiple URLs and return all content as markdown.

    Use for comparing products or prices across multiple sites, gathering
    information from several sources at once, or multi-source research.

    Args:
        urls: List of full URLs to scrape — maximum 5 URLs per call
    """
    urls = urls[:5]
    parts = []
    async with httpx.AsyncClient(timeout=120) as client:
        for url in urls:
            try:
                resp = await client.post(
                    f"{CRAWL4AI_BASE}/md",
                    headers=CRAWL4AI_HEADERS,
                    json={"url": url, "f": "fit"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("success"):
                    content = data.get("markdown", "")
                    if len(content) > 20_000:
                        content = content[:20_000] + "\n\n[Truncated]"
                    parts.append(f"## {url}\n\n{content}")
                else:
                    parts.append(f"## {url}\n\nError: failed to scrape")
            except Exception as exc:
                parts.append(f"## {url}\n\nError: {exc}")
    return "\n\n---\n\n".join(parts) if parts else "No results returned"


if __name__ == "__main__":
    mcp.run(transport=os.getenv("MCP_TRANSPORT", "streamable-http"))
