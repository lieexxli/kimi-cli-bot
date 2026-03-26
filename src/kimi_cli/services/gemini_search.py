"""Gemini Search Adapter Service.

A lightweight HTTP server that wraps Gemini's Google Search grounding
and exposes it in the moonshot_search format expected by SearchWeb.

Usage:
    GEMINI_API_KEY=xxx uv run python -m kimi_cli.services.gemini_search
    # or with options:
    uv run python -m kimi_cli.services.gemini_search --port 8765 --model gemini-2.0-flash

Configure in kimi.toml:
    [services.moonshot_search]
    base_url = "http://localhost:8765/search"
    api_key = "any"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_model_name = "gemini-2.5-flash-lite"
_api_key: str = ""


def _do_search(text_query: str, limit: int) -> list[dict[str, str]]:
    """Call Gemini with Google Search grounding and extract results."""
    from google import genai
    from google.genai.types import GenerateContentConfig, GoogleSearch, Tool

    client = genai.Client(api_key=_api_key)

    response = client.models.generate_content(
        model=_model_name,
        contents=f"搜索并简要总结以下内容，尽量列出信息来源：{text_query}",
        config=GenerateContentConfig(
            tools=[Tool(google_search=GoogleSearch())],
            temperature=0,
        ),
    )

    search_results: list[Any] = []

    # Extract grounding chunks from metadata
    candidate = response.candidates[0] if response.candidates else None
    if not candidate:
        return search_results

    meta = getattr(candidate, "grounding_metadata", None)
    if not meta:
        return search_results

    chunks: list[Any] = getattr(meta, "grounding_chunks", []) or []
    supports: list[Any] = getattr(meta, "grounding_supports", []) or []

    # Build snippet map: chunk_index -> text snippets
    snippet_map: dict[int, list[str]] = {}
    for support in supports:
        seg_text = ""
        if hasattr(support, "segment") and support.segment:
            seg_text = getattr(support.segment, "text", "") or ""
        if not seg_text:
            continue
        # grounded_chunk_indices is a list of int in current SDK
        indices: list[Any] = (
            getattr(support, "grounding_chunk_indices", None)
            or getattr(support, "grounded_chunk_indices", None)
            or []
        )
        for idx in indices:
            chunk_idx: int | None = (
                idx if isinstance(idx, int) else getattr(idx, "chunk_index", None)
            )
            if chunk_idx is not None:
                snippet_map.setdefault(chunk_idx, []).append(seg_text)

    # Fallback: use model's synthesized response text as shared snippet
    response_text = ""
    for part in (response.text or "").split("\n"):
        part = part.strip()
        if part:
            response_text = part
            break

    for i, chunk in enumerate(chunks[:limit]):
        web = getattr(chunk, "web", None)
        if not web:
            continue
        snippets = snippet_map.get(i, [])
        snippet = " ".join(snippets[:3]) if snippets else response_text
        entry: dict[str, str] = {
            "site_name": getattr(web, "title", "") or "",
            "title": getattr(web, "title", "") or "",
            "url": getattr(web, "uri", "") or "",
            "snippet": snippet,
            "content": "",
            "date": "",
        }
        search_results.append(entry)

    return search_results


class SearchHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.info("%s - %s", self.address_string(), format % args)

    def do_POST(self):  # noqa: N802
        if self.path != "/search":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        text_query = body.get("text_query", "")
        limit = min(int(body.get("limit", 5)), 20)

        logger.info("Search: %r (limit=%d)", text_query, limit)

        try:
            results = _do_search(text_query, limit)
            payload = json.dumps({"search_results": results}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            logger.exception("Search failed")
            self.send_error(500, str(e))


def main():
    global _model_name, _api_key

    parser = argparse.ArgumentParser(description="Gemini Search Adapter")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default="gemini-2.5-flash-lite")
    args = parser.parse_args()

    _model_name = args.model
    _api_key = os.environ.get("GEMINI_API_KEY", "")
    if not _api_key:
        raise SystemExit("GEMINI_API_KEY environment variable is required")

    server = HTTPServer(("127.0.0.1", args.port), SearchHandler)
    logger.info("Gemini search adapter listening on http://127.0.0.1:%d/search", args.port)
    logger.info("Model: %s", _model_name)
    logger.info('Configure kimi.toml: base_url = "http://localhost:%d/search"', args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
