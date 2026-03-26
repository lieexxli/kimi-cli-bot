"""Gemini Google Search tool.

Uses Gemini's built-in Google Search grounding to perform web searches.
Requires GEMINI_API_KEY environment variable or a gemini provider configured
with an api_key in the config.
"""

import asyncio
import os
from typing import Any, override

from kosong.tooling import CallableTool2, ToolOk, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.config import Config
from kimi_cli.soul.agent import Runtime
from kimi_cli.tools import SkipThisTool


class Params(BaseModel):
    query: str = Field(description="The query text to search for.")
    limit: int = Field(default=5, ge=1, le=20, description="Number of results to return.")


class GeminiSearch(CallableTool2[Params]):
    name: str = "SearchWeb"
    description: str = (
        "Search the web for up-to-date information using Google Search. "
        "Use this when you need current news, facts, or information that may have changed recently."
    )
    params: type[Params] = Params

    def __init__(self, config: Config, runtime: Runtime):
        super().__init__()
        # Resolve API key: from gemini provider config or environment variable
        api_key = ""
        for provider in config.providers.values():
            if provider.type in ("gemini", "google_genai"):
                api_key = provider.api_key.get_secret_value()
                break
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise SkipThisTool()

        # Resolve model: use the gemini provider's model or a default
        model_name = "gemini-2.5-flash-lite"
        for model_cfg in config.models.values():
            if model_cfg.provider in config.providers:
                p = config.providers[model_cfg.provider]
                if p.type in ("gemini", "google_genai"):
                    model_name = model_cfg.model
                    break

        self._api_key = api_key
        self._model_name = model_name

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        results = await asyncio.get_event_loop().run_in_executor(
            None, self._search, params.query, params.limit
        )
        lines: list[str] = []
        for r in results:
            lines.append(f"Title: {r['title']}")
            lines.append(f"URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"Summary: {r['snippet']}")
            lines.append("")
        return ToolOk(output="\n".join(lines).strip())

    def _search(self, query: str, limit: int) -> list[dict[str, str]]:
        from google import genai
        from google.genai.types import GenerateContentConfig, GoogleSearch, Tool

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self._model_name,
            contents=f"搜索并简要总结以下内容，尽量列出信息来源：{query}",
            config=GenerateContentConfig(
                tools=[Tool(google_search=GoogleSearch())],
                temperature=0,
            ),
        )

        candidate = response.candidates[0] if response.candidates else None
        if not candidate:
            return []

        meta = getattr(candidate, "grounding_metadata", None)
        if not meta:
            return []

        chunks: list[Any] = getattr(meta, "grounding_chunks", []) or []
        supports: list[Any] = getattr(meta, "grounding_supports", []) or []

        # Build snippet map: chunk_index -> text
        snippet_map: dict[int, list[str]] = {}
        for support in supports:
            seg_text: str = getattr(getattr(support, "segment", None), "text", "") or ""
            if not seg_text:
                continue
            for idx in getattr(support, "grounding_chunk_indices", []) or []:
                chunk_idx: int | None = (
                    idx if isinstance(idx, int) else getattr(idx, "chunk_index", None)
                )
                if chunk_idx is not None:
                    snippet_map.setdefault(chunk_idx, []).append(seg_text)

        # Fallback snippet: first sentence of model response
        fallback = ""
        for line in (response.text or "").split("\n"):
            line = line.strip()
            if line:
                fallback = line
                break

        results: list[dict[str, str]] = []
        for i, chunk in enumerate(chunks[:limit]):
            web = getattr(chunk, "web", None)
            if not web:
                continue
            snippets = snippet_map.get(i, [])
            results.append(
                {
                    "title": getattr(web, "title", "") or "",
                    "url": getattr(web, "uri", "") or "",
                    "snippet": " ".join(snippets[:3]) if snippets else fallback,
                }
            )
        return results
