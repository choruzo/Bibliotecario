import asyncio
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from bibliotecario.auth import COOKIE, token_hash
from bibliotecario.cli import create_user
from bibliotecario.config import Settings
from bibliotecario.db import Base
from bibliotecario.main import create_app
from bibliotecario.models import AuditEvent, Role, Session, User
from bibliotecario.providers import ModelClients, ProviderError


def settings(tmp_path, **changes):
    values = dict(environment="test", database_url="sqlite://", storage_path=tmp_path,
                  llm_api_key="test-secret", embedding_dimensions=3)
    return Settings(_env_file=None, **(values | changes))


def transport_response(request):
    body = json.loads(request.content)
    if request.url.path.endswith("embeddings"):
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1, 0.2, 0.3]}
                                                   for i in range(len(body["input"]))]})
    if request.url.path.endswith("rerank"):
        return httpx.Response(200, json={"results": [{"index": i, "relevance_score": 0.5}
                                                       for i in range(len(body["documents"]))]})
    return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})


@pytest.fixture
def application(tmp_path):
    s = settings(tmp_path)
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth.sqlite').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([Role(name="admin"), Role(name="usuario")])
        db.commit()
        create_user(db, "admin", "test-password-123", "admin", bootstrap=True)
        create_user(db, "lector", "test-password-123", "usuario")
    app = create_app(s, engine, sessions, ModelClients(s, transport=httpx.MockTransport(transport_response)))
    with TestClient(app, base_url=s.public_origin) as client:
        yield app, client, sessions


def login(client, username="admin"):
    return client.post("/auth/login", headers={"Origin": "http://localhost:3000"},
                       json={"username": username, "password": "test-password-123"})


def test_authentication_permissions_and_four_checks(application):
    app, client, sessions = application
    assert client.get("/auth/me").status_code == 401
    assert client.get("/health/dependencies").status_code == 401
    assert login(client, "lector").status_code == 200
    assert client.get("/health/dependencies").status_code == 403
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/auth/me").json()["role"] == "admin"
    health = client.get("/health/dependencies")
    assert health.status_code == 200
    assert set(health.json()["checks"]) == {"database", "llm", "embedding", "reranker"}
    with sessions() as db:
        assert db.get(Session, token_hash(client.cookies[COOKIE])) is not None
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "login"))


def test_origin_csrf_logout_and_revocation(application):
    _, client, _ = application
    payload = {"username": "admin", "password": "test-password-123"}
    assert client.post("/auth/login", json=payload).status_code == 403
    assert client.post("/auth/login", json=payload, headers={"Origin": "https://evil.invalid"}).status_code == 403
    csrf = login(client).json()["csrf_token"]
    token = client.cookies[COOKIE]
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"Origin": "http://localhost:3000"}).status_code == 403
    assert client.post("/auth/logout", headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}).status_code == 204
    client.cookies.set(COOKIE, token)
    assert client.get("/auth/me").status_code == 401


def test_session_persistence_expiration_and_deactivation(application):
    app, client, sessions = application
    login(client)
    token = client.cookies[COOKIE]
    with TestClient(app, base_url="http://localhost:3000") as other:
        other.cookies.set(COOKIE, token)
        assert other.get("/auth/me").status_code == 200
        with sessions() as db:
            session = db.get(Session, token_hash(token))
            session.expires_at = int(time.time()) - 1
            db.commit()
        assert other.get("/auth/me").status_code == 401
    login(client)
    with sessions() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        user.active = False
        db.commit()
    assert client.get("/auth/me").status_code == 401
    assert login(client).status_code == 401


def test_bootstrap_no_overwrite_and_password_hash(application):
    _, _, sessions = application
    with sessions() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin.password_hash.startswith("$argon2id$")
        with pytest.raises(ValueError, match="Ya existe"):
            create_user(db, "new", "test-password-123", "admin", bootstrap=True)
        with pytest.raises(ValueError, match="ya existe"):
            create_user(db, "ADMIN", "test-password-123", "admin")
        with pytest.raises(ValueError, match="12"):
            create_user(db, "new", "short", "usuario")


def test_credentials_and_validation_do_not_leak(application, caplog):
    _, client, _ = application
    secret = "do-not-log-me"
    response = client.post("/auth/login", headers={"Origin": "http://localhost:3000"},
                           json={"username": "admin", "password": secret})
    assert response.status_code == 401
    response = client.post("/auth/login", headers={"Origin": "http://localhost:3000"},
                           json={"username": "admin", "password": secret * 200})
    assert response.status_code == 422
    assert secret not in response.text and secret not in caplog.text
    cid = str(uuid.uuid4())
    response = client.get("/health/live", headers={"X-Request-ID": cid})
    assert response.headers["x-request-id"] == cid
    response = client.get("/health/live", headers={"X-Request-ID": "bad-id"})
    uuid.UUID(response.headers["x-request-id"])


@pytest.mark.parametrize("changes", [
    {"environment": "production"}, {"storage_path": "relative/path"},
    {"llm_api_key": ""}, {"embedding_base_url": "file:///tmp"},
    {"public_origin": "http://localhost:3000/path"}, {"environment": "development"},
    {"model_timeout_seconds": 0},
])
def test_config_rejects_invalid_deployments(tmp_path, changes):
    with pytest.raises(ValidationError):
        settings(tmp_path, **changes)


def test_provider_prefixes_and_sorting(tmp_path):
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [
                {"index": 1, "embedding": [1, 2, 3]}, {"index": 0, "embedding": [4, 5, 6]}]})
        return transport_response(request)

    async def run():
        clients = ModelClients(settings(tmp_path), httpx.MockTransport(handle))
        assert await clients.embed(["uno", "dos"], query=True) == [[4, 5, 6], [1, 2, 3]]
        assert captured[-1]["input"] == ["search_query: uno", "search_query: dos"]
        await clients.embed(["uno", "dos"])
        assert captured[-1]["input"][0] == "search_document: uno"
        await clients.close()
    asyncio.run(run())


@pytest.mark.parametrize("payload", [
    {"data": [{"index": 0, "embedding": [1, 2]}]},
    {"data": [{"index": 1, "embedding": [1, 2, 3]}]},
    {"data": [{"index": 0, "embedding": [True, 2, 3]}]},
    {"error": "secret upstream text"},
])
def test_provider_rejects_invalid_embeddings(tmp_path, payload):
    async def run():
        clients = ModelClients(settings(tmp_path), httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
        with pytest.raises(ProviderError, match="invalid_embedding"):
            await clients.embed(["uno"])
        await clients.close()
    asyncio.run(run())


def test_dependency_errors_are_independent_and_sanitized(tmp_path):
    def handle(request):
        if request.url.path.endswith("embeddings"):
            raise httpx.ReadTimeout("secret endpoint", request=request)
        if request.url.path.endswith("rerank"):
            return httpx.Response(401, json={"error": "secret provider content"})
        return transport_response(request)
    async def run():
        clients = ModelClients(settings(tmp_path), httpx.MockTransport(handle))
        checks = await clients.checks()
        assert checks["llm"]["status"] == "available"
        assert checks["embedding"]["error"] == "timeout"
        assert checks["reranker"]["error"] == "http_401"
        assert "secret" not in json.dumps(checks)
        await clients.close()
    asyncio.run(run())


def test_reasoning_only_health_probe_is_available(tmp_path):
    def handle(request):
        if request.url.path.endswith("chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": None, "reasoning_content": "Analisis"}}]})
        return transport_response(request)
    async def run():
        clients = ModelClients(settings(tmp_path), httpx.MockTransport(handle))
        assert (await clients.checks())["llm"]["status"] == "available"
        await clients.close()
    asyncio.run(run())


def test_database_readiness_failure_keeps_other_checks(application, monkeypatch):
    _, client, _ = application
    login(client)
    monkeypatch.setattr("bibliotecario.main.database_check", lambda _: {"status": "unavailable", "error": "database_error"})
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    response = client.get("/health/dependencies")
    assert response.status_code == 503
    assert response.json()["checks"]["database"]["status"] == "unavailable"
    assert response.json()["checks"]["llm"]["status"] == "available"


@pytest.mark.parametrize("payload", [
    {"results": [{"index": 2, "relevance_score": 0.5}]},
    {"results": [{"index": 0, "relevance_score": True}]},
    {"results": []},
])
def test_provider_rejects_invalid_reranking(tmp_path, payload):
    async def run():
        clients = ModelClients(settings(tmp_path), httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
        with pytest.raises(ProviderError, match="invalid_reranking"):
            await clients.rerank("consulta", ["doc"])
        await clients.close()
    asyncio.run(run())
