import asyncio
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from sqlalchemy import delete, text

from .auth import (COOKIE, administrator, current_identity, database, dummy_hash, hasher,
                   lookup_user, require_csrf, require_origin, token_hash, verify_password)
from .config import Settings, get_settings
from .db import build_database
from .logging import configure_logging
from .models import AuditEvent, Session
from .providers import ModelClients
from .documents import router as documents_router
from .body_limit import UploadBodyLimit
from .retrieval import router as retrieval_router
from .chat import router as chat_router
from .administration import router as administration_router
from .admin_settings import load_settings

logger = logging.getLogger("bibliotecario")


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=1024)


def database_check(engine):
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            if engine.dialect.name == "postgresql":
                version = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                if not version or revision != "0006_h5":
                    return {"status": "unavailable", "error": "schema_or_pgvector_missing"}
        return {"status": "available"}
    except Exception:
        return {"status": "unavailable", "error": "database_error"}


def create_app(settings: Settings | None = None, engine=None, sessions=None, clients=None):
    settings = settings or get_settings()
    if engine is None:
        engine, sessions = build_database(settings)
    settings = load_settings(settings, sessions)
    clients = clients or ModelClients(settings)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        settings.storage_path.mkdir(parents=True, exist_ok=True)
        for name in ("originals", "normalized"):
            (settings.storage_path / name).mkdir(exist_ok=True)
        try:
            yield
        finally:
            await clients.close()
            engine.dispose()

    app = FastAPI(title="Bibliotecario", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.engine, app.state.sessions = settings, engine, sessions
    app.state.clients = clients
    app.include_router(documents_router)
    app.include_router(retrieval_router)
    app.include_router(chat_router)
    app.include_router(administration_router)
    app.add_middleware(UploadBodyLimit, max_bytes=settings.upload_max_bytes + 1024 * 1024)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()]},
                            status_code=422)

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        try:
            cid = str(uuid.UUID(request.headers.get("x-request-id", "")))
        except ValueError:
            cid = str(uuid.uuid4())
        request.state.correlation_id = cid
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("request_failed", extra={"correlation_id": cid, "error_type": type(exc).__name__})
            response = JSONResponse({"detail": "Error interno", "correlation_id": cid}, status_code=500)
        response.headers["X-Request-ID"] = cid
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        route = request.scope.get("route")
        logger.info("request_completed", extra={"correlation_id": cid, "method": request.method,
                    "route": route.path if route else "unmatched", "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000)})
        return response

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        result = database_check(engine)
        return JSONResponse(result, status_code=200 if result["status"] == "available" else 503)

    @app.get("/health/dependencies", dependencies=[Depends(administrator)])
    async def dependencies():
        db_result, model_result = await asyncio.gather(asyncio.to_thread(database_check, engine), clients.checks())
        checks = {"database": db_result, **model_result}
        ok = all(value["status"] == "available" for value in checks.values())
        return JSONResponse({"status": "available" if ok else "degraded", "checks": checks},
                            status_code=200 if ok else 503)

    @app.post("/auth/login", dependencies=[Depends(require_origin)])
    def login(body: Login, request: Request, response: Response, db=Depends(database)):
        username = body.username.lower()
        user = lookup_user(db, username)
        verified = verify_password(user.password_hash if user else dummy_hash, body.password)
        if not verified or not user or not user.active:
            db.add(AuditEvent(action="login", result="denied", correlation_id=request.state.correlation_id))
            db.commit()
            raise HTTPException(401, "Credenciales incorrectas")
        if hasher.check_needs_rehash(user.password_hash):
            user.password_hash = hasher.hash(body.password)
        now = int(time.time())
        db.execute(delete(Session).where(Session.expires_at <= now))
        previous = request.cookies.get(COOKIE)
        if previous:
            db.execute(delete(Session).where(Session.token_hash == token_hash(previous)))
        token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
        db.add(Session(token_hash=token_hash(token), user_id=user.id, csrf_token=csrf,
                       expires_at=now + settings.session_hours * 3600))
        db.add(AuditEvent(actor_id=user.id, action="login", object_id=user.id,
                          correlation_id=request.state.correlation_id))
        db.commit()
        response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600, httponly=True,
                            secure=settings.cookie_secure, samesite="strict", path="/")
        return {"id": user.id, "username": user.username, "role": user.role, "csrf_token": csrf}

    @app.get("/auth/me")
    def me(identity=Depends(current_identity)):
        return {"id": identity.user.id, "username": identity.user.username,
                "role": identity.user.role, "csrf_token": identity.session.csrf_token}

    @app.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response, identity=Depends(require_csrf), db=Depends(database)):
        db.delete(identity.session)
        db.add(AuditEvent(actor_id=identity.user.id, action="logout", object_id=identity.user.id,
                          correlation_id=request.state.correlation_id))
        db.commit()
        response.delete_cookie(COOKIE, secure=settings.cookie_secure, httponly=True, samesite="strict", path="/")

    return app
