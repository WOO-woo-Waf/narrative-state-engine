from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float
    text: str
    metadata: dict[str, Any]


class HTTPEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("NOVEL_AGENT_VECTOR_STORE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("NOVEL_AGENT_VECTOR_STORE_API_KEY") or "local"
        self.model = model or os.getenv("NOVEL_AGENT_EMBEDDING_MODEL") or "Qwen/Qwen3-Embedding-4B"
        if not self.base_url:
            raise ValueError("Embedding service base_url is required.")
        self.client = OpenAI(
            base_url=f"{self.base_url}/v1",
            api_key=self.api_key,
            timeout=timeout,
        )

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [list(item.embedding) for item in response.data]


class HTTPReranker:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("NOVEL_AGENT_VECTOR_STORE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("NOVEL_AGENT_VECTOR_STORE_API_KEY") or ""
        self.model = model or os.getenv("NOVEL_AGENT_RERANK_MODEL") or "Qwen/Qwen3-Reranker-4B"
        self.timeout = timeout
        if not self.base_url:
            raise ValueError("Rerank service base_url is required.")

    def rerank(self, *, query: str, documents: list[str], top_n: int = 30) -> list[RerankResult]:
        if not documents:
            return []
        import urllib.request
        import json

        payload = json.dumps(
            {
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/rerank",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        rows = body.get("results", body if isinstance(body, list) else [])
        results: list[RerankResult] = []
        for row in rows:
            idx = int(row.get("index", 0))
            text = documents[idx] if 0 <= idx < len(documents) else str(row.get("text", ""))
            results.append(
                RerankResult(
                    index=idx,
                    score=float(row.get("score", row.get("relevance_score", 0.0)) or 0.0),
                    text=text,
                    metadata=dict(row),
                )
            )
        return results
