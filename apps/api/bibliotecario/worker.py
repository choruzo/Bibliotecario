import logging
import signal
import threading
import time
import uuid

from sqlalchemy import text

from .config import get_settings
from .db import build_database
from .logging import configure_logging
from .jobs import claim, process
from .admin_settings import load_settings, public_settings, settings_signature


def main():
    configure_logging()
    settings = get_settings()
    engine, sessions = build_database(settings)
    settings = load_settings(settings, sessions)
    signature = settings_signature(public_settings(settings))
    stop = threading.Event()
    owner = str(uuid.uuid4())
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger = logging.getLogger("bibliotecario.worker")
    statement = text("""INSERT INTO worker_status (name, heartbeat_at, state, settings_signature)
        VALUES ('ingestion', :now, :state, :signature)
        ON CONFLICT (name) DO UPDATE SET heartbeat_at = EXCLUDED.heartbeat_at, state = EXCLUDED.state,
        settings_signature = EXCLUDED.settings_signature""")
    def heartbeats():
        while not stop.is_set():
            correlation_id = str(uuid.uuid4())
            try:
                with engine.begin() as connection:
                    connection.execute(statement, {"now": int(time.time()), "state": "idle", "signature": signature})
                logger.info("worker_heartbeat", extra={"correlation_id": correlation_id})
            except Exception as exc:
                logger.error("worker_database_unavailable", extra={"error_type": type(exc).__name__,
                                                                  "correlation_id": correlation_id})
            stop.wait(settings.worker_interval_seconds)

    heartbeat = threading.Thread(target=heartbeats, daemon=True)
    heartbeat.start()
    try:
        while not stop.is_set():
            try:
                lease = claim(sessions, settings, owner)
                if lease:
                    process(sessions, settings, lease, stop)
                else:
                    stop.wait(settings.worker_poll_seconds)
            except Exception as exc:
                logger.error("worker_poll_failed", extra={"error_type": type(exc).__name__, "correlation_id": owner})
                stop.wait(settings.worker_poll_seconds)
        heartbeat.join(timeout=settings.worker_interval_seconds + 1)
        with engine.begin() as connection:
            connection.execute(statement, {"now": int(time.time()), "state": "stopped", "signature": signature})
    finally:
        stop.set()
        engine.dispose()


if __name__ == "__main__":
    main()
