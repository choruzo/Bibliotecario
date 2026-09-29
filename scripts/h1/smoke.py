"""Comprueba la instalacion H1 con una cuenta real y los cuatro contratos de salud."""
import argparse
import getpass
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-url", default="http://localhost:3000")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    origin = args.web_url.rstrip("/")
    password = getpass.getpass("Contrasena: ")
    with httpx.Client(base_url=origin, timeout=130) as client:
        response = client.post("/api/auth/login", headers={"Origin": origin},
                               json={"username": args.username, "password": password})
        if response.status_code != 200:
            print(f"Login no disponible: HTTP {response.status_code}")
            return 1
        account = response.json()
        try:
            result = client.get("/api/health/dependencies")
            if result.status_code not in (200, 503):
                print(f"Health no disponible: HTTP {result.status_code}")
                return 1
            checks = result.json().get("checks", {})
            if set(checks) != {"database", "llm", "embedding", "reranker"}:
                print("Respuesta de salud incompleta")
                return 1
            print(json.dumps(checks, ensure_ascii=True, indent=2))
            return 0 if result.status_code == 200 else 1
        finally:
            response = client.post("/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": account["csrf_token"]})
            if response.status_code != 204:
                print(f"Logout no disponible: HTTP {response.status_code}")


if __name__ == "__main__":
    sys.exit(main())
