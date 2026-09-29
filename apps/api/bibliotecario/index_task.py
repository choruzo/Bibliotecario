"""Disposable child: external model calls never hold a database/job lock."""
import argparse
import asyncio
import json
from pathlib import Path
from .config import get_settings
from .db import build_database
from .indexing import build_index
from .models import NormalizedRevision
from .providers import ModelClients


async def run(revision_id):
    settings = get_settings()
    engine, sessions = build_database(settings)
    clients = ModelClients(settings)
    try:
        with sessions() as db:
            revision = db.get(NormalizedRevision, revision_id)
            return await build_index(settings, revision, clients)
    finally:
        await clients.close()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.revision))
    except Exception as exc:
        # Do not persist request bodies, URLs or credentials in job diagnostics.
        result = {"error": type(exc).__name__}
    Path(args.output).write_text(json.dumps(result), encoding="utf-8")
