"""Evaluate an administrator-reviewed library with the H0 bank, then calibrate.

Uses existing API credentials privately. Does not upload or approve source files.
"""
import hashlib
import json
import argparse
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['admin', 'usuario'], default='admin')
    parser.add_argument('--validation-bank', type=Path, default=ROOT / 'evaluation/h3/validation-v2.jsonl')
    args = parser.parse_args()
    origin = "http://localhost:3000"
    credentials = json.loads((ROOT / ".artifacts/h1/admin-credentials.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "evaluation/h0/corpus_catalog.json").read_text(encoding="utf-8"))["documents"]
    questions = ROOT / "evaluation/h0/questions.jsonl"
    validation = args.validation_bank
    cases = [json.loads(line) | {'split': split} for path, split in ((questions, 'calibration'), (validation, 'validation'))
             for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    with httpx.Client(base_url=origin + "/api", timeout=120, trust_env=False) as client:
        client.post("/auth/login", json=credentials, headers={"Origin": origin}).raise_for_status()
        headers = {"Origin": origin, "X-CSRF-Token": client.get("/auth/me").json()["csrf_token"]}
        for attempt in range(6):
            health = client.get('/health/dependencies')
            health.raise_for_status()
            if all(check['status'] == 'available' for check in health.json()['checks'].values()):
                break
            if attempt == 5:
                raise RuntimeError('Evaluation providers are not ready')
            time.sleep(3)
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
        labeled, histories = [], {}
        for case in cases:
            group = case.get('conversation_id')
            response = client.post("/admin/retrieval/search", json={"query": case["query"], 'scope': args.scope,
                                   'previous_questions': histories.get(group, []) if group else []}, headers=headers)
            response.raise_for_status()
            result = response.json()
            labeled.append({"id": case["id"], "run_id": result["run_id"], "kind": case["kind"],
                "language": case["language"], "expected_documents": [mapping[doc] for doc in case["expected_documents"]],
                "expected_sections": case["expected_sections"], "conversation_id": group, 'split': case['split']})
            if group:
                histories.setdefault(group, []).append(case['query'])
            print("Evaluated " + case["id"], flush=True)
        response = client.post("/admin/retrieval/calibrate", json={"cases": labeled, 'scope': args.scope}, headers=headers)
        response.raise_for_status()
        report = response.json() | {"questions_sha256": hashlib.sha256(questions.read_bytes()).hexdigest(),
                  'validation_sha256': hashlib.sha256(validation.read_bytes()).hexdigest(), 'scope': args.scope,
                  'model_signature': result['model_signature'], 'corpus_signature': result['corpus_signature'],
                  'assessment_version': result['assessment']['version'],
                  'query_mode': 'h4_contextual_user_history',
                  'limitations': ['History uses user intent only; final answer quality evaluated separately']}
        output = ROOT / f".artifacts/h3/library-calibration-{args.scope}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        public = {key: value for key, value in report.items() if key not in {'id', 'report'}}
        public['date'] = datetime.now(ZoneInfo('Europe/Madrid')).date().isoformat()
        public['calibration'] = {key: value for key, value in report['report'].items() if key != 'cases'}
        public['cases'] = [{key: row.get(key) for key in ('id', 'kind', 'split', 'score', 'recall5', 'recall10',
                           'mrr10', 'ndcg10', 'answer_eligible', 'assessment_action', 'error')}
                           for row in report['report']['cases']]
        public_output = ROOT / f'evaluation/h3/library-calibration-{args.scope}.json'
        public_output.write_text(json.dumps(public, indent=2) + '\n', encoding='utf-8')
        print("Calibration " + ("approved" if report["report"]["approved"] else "rejected; abstention retained"))


if __name__ == "__main__":
    main()
