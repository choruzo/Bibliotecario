"""Live H3 API/worker smoke test, using only temporary synthetic documents."""
import json
import time
import uuid
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    origin = "http://localhost:3000"
    credentials = json.loads((ROOT / ".artifacts/h1/admin-credentials.json").read_text(encoding="utf-8"))
    created = []
    report = {}
    with httpx.Client(base_url=origin + "/api", trust_env=False, timeout=60) as client:
        client.post("/auth/login", json=credentials, headers={"Origin": origin}).raise_for_status()
        headers = {"Origin": origin, "X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]}

        def request(method, path, **kwargs):
            r = client.request(method, path, headers=headers, **kwargs)
            r.raise_for_status()
            return r.json() if r.content else None

        def wait(jid):
            for _ in range(150):
                items = request("GET", "/admin/jobs")["items"]
                job = next(j for j in items if j["id"] == jid)
                if job["status"] in {"completado", "fallido", "cancelado"}:
                    assert job["status"] == "completado", job["error_code"]
                    return
                time.sleep(.4)
            raise TimeoutError("job_timeout")

        def upload(content, did=None):
            path = f"/admin/documents/{did}/versions" if did else "/admin/documents"
            response = client.post(path, headers=headers | {"Idempotency-Key": str(uuid.uuid4())},
                                   files={"file": ("h3-acceptance.md", content.encode(), "text/markdown")})
            response.raise_for_status()
            data = response.json()
            did = data["document"]["id"]
            if did not in created:
                created.append(did)
            wait(data["job"]["id"])
            version = request("GET", f"/admin/documents/{did}")["versions"][0]
            body = {"expected_revision_id": version["revision_id"]}
            request("POST", f"/admin/versions/{version['id']}/review", json=body)
            job = request("POST", f"/admin/versions/{version['id']}/publish", json=body)
            wait(job["id"])
            return did, version

        try:
            marker = "h3" + uuid.uuid4().hex[:10]
            did, first = upload(f"# Procedimiento {marker}\n\nLa prueba {marker} verifica la recuperacion hibrida de fuentes publicadas.\n")
            first_search = request("POST", "/admin/retrieval/search", json={"query": marker})
            found = [r for r in first_search["results"] if r["document_id"] == did]
            assert found and all(r["version_id"] == first["id"] for r in found)
            assert any(set(r["channels"]) == {"vector", "text"} for r in found)
            assert first_search["decision"]["action"] == "abstain"
            assert first_search["run_id"]
            report["published_hybrid_trace"] = True
            did, second = upload(f"# Procedimiento {marker}\n\nLa segunda version {marker} sustituye atomicamente a la primera.\n", did)
            replacement = request("POST", "/admin/retrieval/search", json={"query": marker})
            assert not any(r["version_id"] == first["id"] for r in replacement["candidates"])
            assert any(r["version_id"] == second["id"] for r in replacement["results"])
            report["atomic_replacement"] = True
            # Reindex the same revision while retaining the active index until commit.
            job = request("POST", f"/admin/versions/{second['id']}/publish", json={"expected_revision_id": second["revision_id"]})
            wait(job["id"])
            report["reindex"] = True
            request("POST", f"/admin/documents/{did}/withdraw")
            withdrawn = request("POST", "/admin/retrieval/search", json={"query": marker})
            assert not any(r["document_id"] == did for r in withdrawn["candidates"])
            report["withdraw_excluded"] = True
            assert client.get("/admin/retrieval/runs").status_code == 200
            assert client.get("/admin/retrieval/runs/" + first_search["run_id"]).status_code == 200
            assert httpx.get(origin + "/admin/retrieval", timeout=15, trust_env=False).status_code == 200
            report["inspection_page"] = True
        finally:
            # Retired published versions respect the normal retention period.
            # Keep synthetic fixtures withdrawn rather than bypassing deletion policy.
            for did in created:
                doc = request("GET", f"/admin/documents/{did}")
                if doc["active_version_id"]:
                    request("POST", f"/admin/documents/{did}/withdraw")
            report["synthetic_document_ids"] = created
            output = ROOT / ".artifacts/h3/acceptance.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
