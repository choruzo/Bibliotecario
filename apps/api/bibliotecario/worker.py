import logging
import signal
import threading
import time
import uuid

from sqlalchemy import text

from .config import get_settings
from .db import build_database
from .logging import configure_logging


def main():
    configure_logging()
    settings = get_settings()
    engine, _ = build_database(settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger = logging.getLogger("bibliotecario.worker")
    statement = text("""INSERT INTO worker_status (name, heartbeat_at, state)
        VALUES ('ingestion', :now, :state)
        ON CONFLICT (name) DO UPDATE SET heartbeat_at = EXCLUDED.heartbeat_at, state = EXCLUDED.state""")
    try:
        while not stop.is_set():
            correlation_id = str(uuid.uuid4())
            try:
                with engine.begin() as connection:
                    connection.execute(statement, {"now": int(time.time()), "state": "idle"})
                logger.info("worker_heartbeat", extra={"correlation_id": correlation_id})
            except Exception as exc:
                logger.error("worker_database_unavailable", extra={"error_type": type(exc).__name__,
                                                                  "correlation_id": correlation_id})
            stop.wait(settings.worker_interval_seconds)
        with engine.begin() as connection:
            connection.execute(statement, {"now": int(time.time()), "state": "stopped"})
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
