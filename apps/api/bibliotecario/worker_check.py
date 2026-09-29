import time

from sqlalchemy import text

from .config import get_settings
from .db import build_database


def main():
    settings = get_settings()
    engine, _ = build_database(settings)
    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT heartbeat_at, state FROM worker_status WHERE name='ingestion'")).first()
        healthy = row and row.state == "idle" and time.time() - row.heartbeat_at < settings.worker_interval_seconds * 3
        raise SystemExit(0 if healthy else 1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
