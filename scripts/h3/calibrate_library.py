"""Evaluate an administrator-reviewed library with one or more banks, then calibrate.

Several calibration and validation banks can be combined (e.g. the technical H0 bank
and the agnostic one); each catalog maps its source IDs to exactly one published
document by SHA-256. Uses existing API credentials privately. Does not upload or
approve source files.
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
    parser.add_argument('--calibration-bank', type=Path, nargs='+', default=[ROOT / 'evaluation/h0/questions.jsonl'])
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--validation-bank', type=Path, nargs='+', default=[ROOT / 'evaluation/h3/validation-v2.jsonl'])
    parser.add_argument('--catalog', type=Path, nargs='+', default=[ROOT / 'evaluation/h0/corpus_catalog.json'])
    args = parser.parse_args()
    origin = "http://localhost:3000"
    credentials = json.loads((ROOT / ".artifacts/h1/admin-credentials.json").read_text(encoding="utf-8"))
    catalog = [source for path in args.catalog for source in json.loads(path.read_text(encoding="utf-8"))["documents"]]
    if len({source["id"] for source in catalog}) != len(catalog):
        raise ValueError("Los catálogos repiten identificadores de fuente")
    banks = [(path, 'calibration') for path in args.calibration_bank] + [(path, 'validation') for path in args.validation_bank]
    cases = [json.loads(line) | {'split': split} for path, split in banks
             for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError("Los bancos repiten identificadores de caso")
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
        checkpoint = ROOT / f'.artifacts/retrieval-fix/calibration-progress-{args.scope}.json'
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        saved = json.loads(checkpoint.read_text(encoding='utf-8')) if args.resume and checkpoint.exists() else []
        labeled, histories = [], {}
        for case in cases:
            group = case.get('conversation_id')
            previous = next((row for row in saved if row['id'] == case['id']), None)
            if previous:
                detail = client.get('/admin/retrieval/runs/' + previous['run_id'])
                detail.raise_for_status()
                result = detail.json()['result']
                if result.get('question', result.get('query')) != case['query']:
                    raise ValueError('El checkpoint pertenece a otra pregunta: ' + case['id'])
                labeled.append(previous)
                if group:
                    histories.setdefault(group, []).append(case['query'])
                continue
            response = client.post("/admin/retrieval/search", json={"query": case["query"], 'scope': args.scope,
                                   'previous_questions': histories.get(group, []) if group else []}, headers=headers)
            response.raise_for_status()
            result = response.json()
            labeled.append({"id": case["id"], "run_id": result["run_id"], "kind": case["kind"],
                "language": case["language"], "expected_documents": [mapping[doc] for doc in case["expected_documents"]],
                "expected_sections": case["expected_sections"], "conversation_id": group, 'split': case['split']})
            if group:
                histories.setdefault(group, []).append(case['query'])
            checkpoint.write_text(json.dumps(labeled, indent=2), encoding='utf-8')
            print("Evaluated " + case["id"], flush=True)
        response = client.post("/admin/retrieval/calibrate", json={"cases": labeled, 'scope': args.scope}, headers=headers)
        response.raise_for_status()
        digest = lambda paths: hashlib.sha256(b''.join(path.read_bytes() for path in paths)).hexdigest()
        report = response.json() | {"questions_sha256": digest(args.calibration_bank),
                  'validation_sha256': digest(args.validation_bank), 'scope': args.scope,
                  'banks': {path.resolve().relative_to(ROOT).as_posix(): {'split': split,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path, split in banks},
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
