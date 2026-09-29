import asyncio
import math
from time import perf_counter

import httpx

from .config import Settings


class ProviderError(Exception):
    pass


def headers(secret):
    value = secret.get_secret_value()
    return {"Authorization": f"Bearer {value}"} if value else {}


class ModelClients:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=settings.model_timeout_seconds, transport=transport)

    async def close(self):
        await self.http.aclose()

    async def post(self, base, path, body, key):
        response = await self.http.post(base.rstrip("/") + path, json=body, headers=headers(key))
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("invalid_json") from exc

    async def generate(self, messages, max_tokens=128):
        s = self.settings
        data = await self.post(s.llm_base_url, "/chat/completions", {
            "model": s.llm_model, "messages": messages, "max_tokens": max_tokens, "stream": False
        }, s.llm_api_key)
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError()
            return content
        except (KeyError, TypeError, IndexError, ValueError) as exc:
            raise ProviderError("invalid_generation") from exc

    async def probe_generation(self):
        s = self.settings
        data = await self.post(s.llm_base_url, "/chat/completions", {
            "model": s.llm_model, "messages": [{"role": "user", "content": "Responde OK"}],
            "max_tokens": 8, "stream": False
        }, s.llm_api_key)
        try:
            message = data["choices"][0]["message"]
            # Reasoning models can spend the probe's small budget before producing final content.
            if not any(isinstance(message.get(key), str) and message[key].strip()
                       for key in ("content", "reasoning_content", "reasoning")):
                raise ValueError()
        except (KeyError, TypeError, IndexError, ValueError, AttributeError) as exc:
            raise ProviderError("invalid_generation") from exc

    async def embed(self, texts: list[str], query=False):
        if not texts:
            raise ValueError("texts no puede estar vacio")
        s = self.settings
        prefix = "search_query: " if query else "search_document: "
        data = await self.post(s.embedding_base_url, "/v1/embeddings", {
            "model": s.embedding_model, "input": [prefix + text for text in texts]
        }, s.embedding_api_key)
        try:
            rows = data["data"]
            if len(rows) != len(texts) or sorted(row["index"] for row in rows) != list(range(len(texts))):
                raise ValueError()
            vectors = [row["embedding"] for row in sorted(rows, key=lambda row: row["index"])]
            if any(len(v) != s.embedding_dimensions or
                   any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in v)
                   for v in vectors):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("invalid_embedding") from exc

    async def embedding_tokens(self, content):
        data = await self.post(self.settings.embedding_base_url, "/tokenize",
                               {"content": content, "add_special": True}, self.settings.embedding_api_key)
        if not isinstance(data, dict) or not isinstance(data.get("tokens"), list) or not data["tokens"] or any(
                isinstance(token, bool) or not isinstance(token, int) for token in data["tokens"]):
            raise ProviderError("invalid_tokenization")
        return len(data["tokens"])

    async def rerank(self, query: str, documents: list[str]):
        if not documents:
            raise ValueError("documents no puede estar vacio")
        s = self.settings
        data = await self.post(s.reranker_base_url, "/v1/rerank", {
            "model": s.reranker_model, "query": query, "documents": documents, "top_n": len(documents)
        }, s.reranker_api_key)
        try:
            rows = data["results"]
            if len(rows) != len(documents) or sorted(row["index"] for row in rows) != list(range(len(documents))):
                raise ValueError()
            if any(isinstance(row["relevance_score"], bool) or
                   not isinstance(row["relevance_score"], (int, float)) or
                   not math.isfinite(row["relevance_score"]) for row in rows):
                raise ValueError()
            return sorted(rows, key=lambda row: row["relevance_score"], reverse=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("invalid_reranking") from exc

    async def checks(self):
        async def check(name, operation):
            started = perf_counter()
            try:
                await operation
                result = {"status": "available"}
            except httpx.TimeoutException:
                result = {"status": "unavailable", "error": "timeout"}
            except httpx.HTTPStatusError as exc:
                result = {"status": "unavailable", "error": f"http_{exc.response.status_code}"}
            except httpx.RequestError:
                result = {"status": "unavailable", "error": "connection_error"}
            except ProviderError as exc:
                result = {"status": "unavailable", "error": str(exc)}
            result["latency_ms"] = round((perf_counter() - started) * 1000)
            return name, result

        return dict(await asyncio.gather(
            check("llm", self.probe_generation()),
            check("embedding", self.embed(["comprobacion de disponibilidad"], query=True)),
            check("reranker", self.rerank("biblioteca", ["biblioteca documental"]))
        ))
