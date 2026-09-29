from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import ROOT, load_json, write_json


def request_json(url: str, payload: dict | None = None) -> tuple[int, object, float]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data, round((time.perf_counter() - started) * 1000, 2)


def probe(service: dict) -> dict:
    base = service["base_url_from_host"].rstrip("/")
    result = {"id": service["id"], "base_url": base, "checks": [], "ok": True}
    checks: list[tuple[str, dict | None]] = [("/health", None), ("/v1/models", None)]
    if service["id"] == "embedding":
        checks.append(("/v1/embeddings", {"input": ["search_query: health check"], "model": service["model"]}))
    elif service["id"] == "reranker":
        checks.append(("/v1/rerank", {"query": "health check", "documents": ["health check"], "model": service["model"]}))
    for path, payload in checks:
        try:
            status, data, elapsed = request_json(base + path, payload)
            summary: dict = {"path": path, "status": status, "elapsed_ms": elapsed}
            if path == "/v1/embeddings":
                vectors = data.get("data", []) if isinstance(data, dict) else []
                summary["dimensions"] = len(vectors[0].get("embedding", [])) if vectors else None
            if "rerank" in path and isinstance(data, dict):
                summary["result_count"] = len(data.get("results", data.get("data", [])))
            result["checks"].append(summary)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result["ok"] = False
            result["checks"].append({"path": path, "error": str(exc)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the three configured local model contracts.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "h0" / "model-services.example.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / "h0" / "model-probe.json")
    args = parser.parse_args()
    config = load_json(args.config)
    report = {"observed_contract_date": config["observed_at"], "services": [probe(item) for item in config["services"]]}
    write_json(args.output, report)
    print(f"model probe written to {args.output}")
    return 0 if all(item["ok"] for item in report["services"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
