from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict

from catalog_corpus import check_catalog
from common import ROOT, catalog_by_id, load_json


REQUIRED_COUNTS = {"answerable": 10, "unanswerable": 5, "ambiguous": 3, "conversation": 6}
IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
SECRET_VALUE = re.compile(r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*\S+")


def load_questions() -> list[dict]:
    path = ROOT / "evaluation" / "h0" / "questions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate() -> list[str]:
    errors = check_catalog()
    catalog = catalog_by_id()
    questions = load_questions()
    counts = Counter(item.get("kind") for item in questions)
    for kind, minimum in REQUIRED_COUNTS.items():
        if counts[kind] < minimum:
            errors.append(f"question bank needs at least {minimum} {kind}, found {counts[kind]}")
    ids = [item.get("id") for item in questions]
    if len(ids) != len(set(ids)):
        errors.append("question ids are not unique")
    conversations: dict[str, list[int]] = defaultdict(list)
    for item in questions:
        query = item.get("query", "")
        if IPV4.search(query) or SECRET_VALUE.search(query):
            errors.append(f"{item.get('id')} contains a possible sensitive value")
        for document_id in item.get("expected_documents", []):
            if document_id not in catalog:
                errors.append(f"{item.get('id')} references unknown {document_id}")
        if item.get("kind") == "conversation":
            conversations[item.get("conversation_id", "")].append(item.get("turn", 0))
            if "retrieval_required" not in item.get("tags", []):
                errors.append(f"{item.get('id')} does not require retrieval")
    for conversation_id, turns in conversations.items():
        if sorted(turns) != list(range(1, len(turns) + 1)):
            errors.append(f"{conversation_id} has non-contiguous turns: {turns}")
    selection = load_json(ROOT / "evaluation" / "h0" / "variant_selection.json")
    selected = selection.get("documents", [])
    if len(selected) < 3 or len({item["profile"] for item in selected}) < 3:
        errors.append("variant selection must cover three distinct profiles")
    for item in selected:
        if item["document_id"] not in catalog:
            errors.append(f"variant selection references unknown {item['document_id']}")
    models = load_json(ROOT / "config" / "h0" / "model-services.example.json")
    if {item.get("id") for item in models.get("services", [])} != {"generation", "embedding", "reranker"}:
        errors.append("model config must define generation, embedding and reranker")
    serialized = json.dumps(models, ensure_ascii=False)
    if SECRET_VALUE.search(serialized):
        errors.append("model config contains a possible secret")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("H0 validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    counts = Counter(item["kind"] for item in load_questions())
    print(f"H0 contracts ok; question bank: {dict(counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
