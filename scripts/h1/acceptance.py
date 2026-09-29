"""Ensayo real de Compose. Lee credenciales de un archivo local sin imprimir secretos."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def compose(*args):
    result = subprocess.run(["docker", "compose", *args], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Docker Compose fallo: {args[0]} (exit {result.returncode})")
    return result.stdout.strip()


def execute(code):
    return compose("exec", "-T", "api", "python", "-c", code)


def snapshot():
    return json.loads(execute("""import json
from sqlalchemy import text
from bibliotecario.config import get_settings
from bibliotecario.db import build_database
engine,_=build_database(get_settings())
with engine.connect() as c:
    print(json.dumps({'revision': c.scalar(text('SELECT version_num FROM alembic_version')),
        'pgvector': c.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")),
        'users': c.scalar(text('SELECT count(*) FROM users')),
        'audit_events': c.scalar(text('SELECT count(*) FROM audit_events'))}))
engine.dispose()
"""))


def wait_for_session(client):
    for _ in range(45):
        try:
            response = client.get("/api/auth/me", timeout=7)
            if response.status_code == 200:
                return response.json()
        except httpx.RequestError:
            pass
        time.sleep(1)
    raise RuntimeError("La sesion no se recupero despues del reinicio")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--web-url", default="http://localhost:3000")
    parser.add_argument("--restart", action="store_true", help="Reinicia solo PostgreSQL, API y worker de este proyecto")
    args = parser.parse_args()
    account = json.loads(args.credentials.read_text(encoding="utf-8"))
    origin = args.web_url.rstrip("/")
    report = {"schema": snapshot(), "restarted": args.restart}
    if report["schema"]["revision"] not in {"0001_h1", "0002_h2", "0003_h2_events"} or not report["schema"]["pgvector"]:
        raise RuntimeError("Esquema o pgvector no disponible")
    compose("exec", "-T", "api", "alembic", "upgrade", "head")
    assert snapshot() == report["schema"], "Reaplicar migraciones modifico registros"

    marker = uuid.uuid4().hex
    filename = f".h1-storage-probe-{marker}"
    data_dir = Path(dotenv_values(ROOT / ".env")["BIB_DATA_DIR"])
    host_file = data_dir / "documents" / filename
    execute(f"from pathlib import Path; Path('/data/documents/{filename}').write_text('{marker}', encoding='ascii')")
    try:
        assert host_file.read_text(encoding="ascii") == marker, "El bind mount no es visible desde el host"
        with httpx.Client(base_url=origin, timeout=130) as client:
            response = client.post("/api/auth/login", headers={"Origin": origin}, json=account)
            assert response.status_code == 200, f"Login: HTTP {response.status_code}"
            identity = response.json()
            try:
                response = client.get("/api/health/dependencies")
                report["dependencies"] = response.json()
                assert response.status_code == 200, "Una dependencia no esta disponible"
                before = snapshot()
                if args.restart:
                    compose("restart", "postgres", "api", "worker")
                    after_identity = wait_for_session(client)
                    assert identity == after_identity, "La identidad o sesion cambio tras el reinicio"
                    assert snapshot() == before, "No se conservaron usuarios o auditoria"
                    assert host_file.read_text(encoding="ascii") == marker, "No se conservo el archivo"
                    execute(f"from pathlib import Path; assert Path('/data/documents/{filename}').read_text() == '{marker}'")
                    report["persistence"] = "passed"
                report["storage"] = "passed"
            finally:
                result = client.post("/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": identity["csrf_token"]})
                assert result.status_code == 204, "Logout fallo"
            assert client.get("/api/auth/me").status_code == 401, "Logout no revoco la sesion"
        report["logout"] = "passed"
        output = ROOT / ".artifacts" / "h1" / "compose-acceptance.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        if host_file.exists():
            host_file.unlink()


if __name__ == "__main__":
    main()
