"""Crea la primera cuenta con un secreto aleatorio local; nunca lo pasa en argumentos."""
import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="administrador")
    args = parser.parse_args()
    output = ROOT / ".artifacts" / "h1" / "admin-credentials.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    account = {"username": args.username, "password": secrets.token_urlsafe(32)}
    try:
        with output.open("x", encoding="utf-8") as handle:
            json.dump(account, handle)
            handle.write("\n")
        os.chmod(output, 0o600)
    except FileExistsError:
        parser.exit(1, "El archivo local de credenciales ya existe; se conserva sin cambios.\n")
    code = """import json,sys
from bibliotecario.config import get_settings
from bibliotecario.db import build_database
from bibliotecario.cli import create_user
account=json.load(sys.stdin)
engine,sessions=build_database(get_settings())
try:
    with sessions() as db:
        create_user(db, account['username'], account['password'], 'admin', bootstrap=True)
finally:
    engine.dispose()
"""
    result = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code],
                            cwd=ROOT, input=json.dumps(account), text=True, capture_output=True)
    if result.returncode:
        parser.exit(1, "Bootstrap fallo; credenciales conservadas localmente para diagnostico.\n")
    print(f"Cuenta {args.username} creada. Contrasena guardada en {output}; omitida del log.")


if __name__ == "__main__":
    main()
