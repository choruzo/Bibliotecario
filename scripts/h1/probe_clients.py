"""Sondea los adaptadores H1 desde el host, sin necesidad de PostgreSQL."""
import argparse
import asyncio
import json
import os
from pathlib import Path

from bibliotecario.config import Settings
from bibliotecario.providers import ModelClients


async def probe(args):
    settings = Settings(_env_file=None, environment="development",
                        database_url="postgresql+psycopg://probe:probe@localhost/probe",
                        storage_path=Path.cwd() / ".artifacts" / "h1",
                        llm_base_url=args.llm_url, llm_model=args.llm_model,
                        llm_api_key=os.environ.get("BIB_LLM_API_KEY", "local-no-key"), embedding_base_url=args.embedding_url,
                        reranker_base_url=args.reranker_url)
    clients = ModelClients(settings)
    try:
        return await clients.checks()
    finally:
        await clients.close()


def main():
    parser = argparse.ArgumentParser(description="Comprueba llama.cpp directo o una pasarela LiteLLM")
    parser.add_argument("--llm-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--llm-model", default="gpt-oss-20b-Q5_K_M.gguf")
    parser.add_argument("--embedding-url", default="http://127.0.0.1:8081")
    parser.add_argument("--reranker-url", default="http://127.0.0.1:8082")
    args = parser.parse_args()
    checks = asyncio.run(probe(args))
    print(json.dumps(checks, indent=2))
    return 0 if all(check["status"] == "available" for check in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
