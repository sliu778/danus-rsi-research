"""Valency is the scholarly database; SQLite stores local experiment state."""
from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import urlparse

from .protocol import ProtocolError, require, text


def unwrap(value):
    if isinstance(value, dict) and value.get("isError"):
        raise ValueError("Valency returned an MCP tool error")
    if isinstance(value, dict) and isinstance(value.get("structuredContent"), dict):
        return value["structuredContent"]
    if isinstance(value, dict) and "content" in value:
        for block in value["content"]:
            if block.get("type") == "text":
                try:
                    result = json.loads(block["text"])
                    if isinstance(result, dict):
                        return result
                except (ValueError, KeyError):
                    continue
    return value


def normalize_snapshot(value):
    value = unwrap(value)
    require(isinstance(value, dict) and isinstance(value.get("papers"), list), "expected a Valency paper search/export object")
    papers, seen = [], set()
    for item in value["papers"]:
        for key in ("id", "source", "title", "url"):
            text(item.get(key), "Valency paper " + key)
        url = urlparse(item["url"])
        require(url.scheme == "https" and bool(url.netloc) and not url.username, "paper permalink must be HTTPS")
        identity = (item["source"], item["id"])
        if identity in seen:
            continue
        seen.add(identity)
        papers.append({k: item[k] for k in ("id", "source", "title", "url", "doi", "authors", "categories", "abstract", "first_submitted") if k in item})
    return {"provider": "valency", "query": value.get("query", "imported export"),
            "retrieved_at": value.get("retrieved_at"), "tool": value.get("tool", value.get("_meta", {}).get("tool")),
            "server_version": value.get("server_version", value.get("_meta", {}).get("server_version")),
            "warnings": value.get("warnings", []), "papers": papers}


MATH_PREFIXES = ("math.",)
PHYSICS_CATEGORIES = {"math-ph", "math.MP", "hep-th", "hep-ph", "gr-qc", "quant-ph", "nucl-th"}
PHYSICS_PREFIXES = ("cond-mat.", "nlin.", "physics.", "astro-ph.")


def paper_domains(paper):
    """Benchmark domains a paper can seed, from its arXiv categories only."""
    domains = set()
    for category in paper.get("categories") or []:
        if category in PHYSICS_CATEGORIES or category.startswith(PHYSICS_PREFIXES):
            domains.add("theoretical-physics")
        elif category.startswith(MATH_PREFIXES):
            domains.add("mathematics")
    return domains


def eligible_papers(papers, since):
    """Papers first submitted on or after `since` (ISO date), with a usable domain.

    Restricting mining to recent papers limits, but does not exclude,
    contamination from model training data. Undated records are excluded."""
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", since or "") is not None, "--since must be an ISO date YYYY-MM-DD")
    return [p for p in papers if isinstance(p.get("first_submitted"), str)
            and p["first_submitted"][:10] >= since and paper_domains(p)]


def import_snapshot(store, value):
    snapshot = normalize_snapshot(value)
    for paper in snapshot["papers"]:
        store.put("paper", paper)
    return store.put("literature_snapshot", snapshot)


async def _call(tool, arguments):
    token = os.environ.get("VALENCY_TOKEN", "").strip()
    require(bool(token), "Set VALENCY_TOKEN from your Valency settings for standalone access, or import a connector export. See docs/valency.md.")
    endpoint = os.environ.get("VALENCY_URL", "https://mcp.valency.io/")
    url = urlparse(endpoint)
    require(url.scheme == "https" and url.hostname == "mcp.valency.io" and url.path in ("", "/")
            and url.port in (None, 443) and not url.username and not url.query and not url.fragment,
            "Valency endpoint must be https://mcp.valency.io/")
    try:
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise ProtocolError("Install the optional dependency: pip install '.[valency]'") from exc
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=60, follow_redirects=False) as client:
        async with streamable_http_client(endpoint, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=60) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return unwrap(result.model_dump(by_alias=True, mode="json"))


def search(query, limit=10):
    text(query, "query", 5000)
    require(type(limit) is int and 1 <= limit <= 100, "limit must be 1..100")
    async def bounded():
        return await asyncio.wait_for(_call("semantic_search_papers", {
            "query": query, "limit": limit, "include_abstract": True, "enrich_citations": False}), timeout=90)
    try:
        result = asyncio.run(bounded())
    except ProtocolError:
        raise
    except Exception as exc:
        # SDK exception strings can contain request details. Never log bearer headers.
        raise RuntimeError("Valency request failed; check connectivity and token permissions. " + type(exc).__name__) from None
    from datetime import datetime, timezone
    result["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    return normalize_snapshot(result)
