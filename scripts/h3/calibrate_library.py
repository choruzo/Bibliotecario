"""Evaluate an administrator-reviewed library with the H0 bank, then calibrate.

Uses existing API credentials privately. Does not upload or approve source files.
"""
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    origin = "http://localhost:3000"
    credentials = json.loads((ROOT / ".artifacts/h1/admin-credentials.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "evaluation/h0/corpus_catalog.json").read_text(encoding="utf-8"))["documents"]
    questions = ROOT / "evaluation/h0/questions.jsonl"
    cases = [json.loads(line) for line in questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    with httpx.Client(base_url=origin + "/api", timeout=60, trust_env=False) as client:
        client.post("/auth/login", json=credentials, headers={"Origin": origin}).raise_for_status()
        headers = {"Origin": origin, "X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]}
        documents, offset = [], 0
        while True:
            response = client.get("/admin/documents", params={"offset": offset})
            response.raise_for_status()
            page = response.json()
            documents.extend(page["items"])
            if not page["has_more"]:
                break
            offset += 50
        mapping = {}
        for source in catalog:
            matches = [doc["id"] for doc in documents if any(version["id"] == doc["active_version_id"]
                       and version["status"] == "publicado" and version["original_sha256"] == source["sha256"]
                       for version in doc["versions"])]
            if len(matches) != 1:
                raise ValueError("Se requiere exactamente una fuente publicada para " + source["id"])
            mapping[source["id"]] = matches[0]
        labeled = []
        for case in cases:
            response = client.post("/admin/retrieval/search", json={"query": case["query"]}, headers=headers)
            response.raise_for_status()
            result = response.json()
            labeled.append({"id": case["id"], "run_id": result["run_id"], "kind": case["kind"],
                "language": case["language"], "expected_documents": [mapping[doc] for doc in case["expected_documents"]],
                "expected_sections": case["expected_sections"], "conversation_id": case.get("conversation_id")})
            print("Evaluated " + case["id"], flush=True)
        response = client.post("/admin/retrieval/calibrate", json={"cases": labeled}, headers=headers)
        response.raise_for_status()
        report = response.json() | {"questions_sha256": hashlib.sha256(questions.read_bytes()).hexdigest()}
        output = ROOT / ".artifacts/h3/library-calibration.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Calibration " + ("approved" if report["report"]["approved"] else "rejected; abstention retained"))


if __name__ == "__main__":
    main()
