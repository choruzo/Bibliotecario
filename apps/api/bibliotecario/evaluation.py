"""Locator-aware metrics and conservative calibration on disjoint groups."""
import math
import statistics
import unicodedata


def normalize(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value).casefold()
                            if not unicodedata.combining(c) and (c.isalnum() or c.isspace())).split())


def ranking_metrics(case, candidates, document_map):
    documents = case["expected_documents"]
    sections = case["expected_sections"]
    targets = [(doc, None) for doc in documents] + [(None, normalize(section)) for section in sections]
    seen, gains, first = set(), [], 0
    hits5 = hits10 = 0
    for rank, candidate in enumerate(candidates[:10], 1):
        doc = document_map.get(candidate["document_id"])
        headings = {normalize(s) for p in candidate["provenance"] for s in p["section_path"]}
        found = {i for i, (expected_doc, section) in enumerate(targets)
                 if (expected_doc == doc if expected_doc else doc in documents and section in headings)}
        novel = found - seen
        gain = len(novel)
        gains.append(gain)
        if gain and not first:
            first = rank
        seen |= found
        if rank <= 5:
            hits5 = len(seen)
        hits10 = len(seen)
    # Standard binary nDCG over the reranked candidate pool. Recall separately
    # measures missing corpus locators; nDCG evaluates ordering, not missing candidates.
    relevance = []
    for candidate in candidates:
        doc = document_map.get(candidate["document_id"])
        headings = {normalize(s) for p in candidate["provenance"] for s in p["section_path"]}
        relevance.append(int(doc in documents and (not sections or any(normalize(s) in headings for s in sections))))
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(relevance[:10], 1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(10, sum(relevance)) + 1))
    found_documents = {document_map.get(c["document_id"]) for c in candidates[:10]}
    return {"document_recall10": (sum(doc in found_documents for doc in documents) / len(documents)
                                   if documents else None),
            "recall5": hits5 / len(targets) if targets else None,
            "recall10": hits10 / len(targets) if targets else None,
            "mrr10": 1 / first if first else 0,
            "ndcg10": dcg / ideal if ideal else 0}


def decision_metrics(rows, threshold):
    tp = fp = fn = tn = 0
    for row in rows:
        expected = row["expected_behavior"] == "answer"
        answered = (row.get("answer_eligible", True) and threshold is not None
                    and row.get("score") is not None and row["score"] >= threshold)
        tp += answered and expected
        fp += answered and not expected
        fn += not answered and expected
        tn += not answered and not expected
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "accuracy": (tp + tn) / len(rows) if rows else 0,
            "improper_answer_rate": fp / (fp + tn) if fp + tn else None}


def wrong_source(row):
    """Whether an accepted answer lacks an expected document (None if not applicable)."""
    if row["expected_behavior"] != "answer":
        return None
    recall = row.get("document_recall10", row.get("recall10"))
    return recall is None or recall < 1


def calibrate(rows):
    explicit = any(r.get("split") for r in rows)
    if explicit and any(r.get("split") not in {"calibration", "validation"} for r in rows):
        raise ValueError("incomplete_evaluation_split")
    # Alternating IDs within class; conversation groups stay together.
    groups = {}
    for row in rows:
        key = row.get("conversation_id") or row["id"]
        groups.setdefault(row["kind"], {}).setdefault(key, []).append(row)
    train, holdout = [], []
    for kind_groups in groups.values():
        for index, key in enumerate(sorted(kind_groups)):
            group = kind_groups[key]
            if explicit and len({r["split"] for r in group}) != 1:
                raise ValueError("conversation_split_leakage")
            (train if (group[0]["split"] == "calibration" if explicit else index % 2 == 0) else holdout).extend(group)
    candidates = sorted({row["score"] for row in train if row.get("answer_eligible", True) and row.get("score") is not None})
    # Only improper answers and answers without their expected documents make a
    # threshold unsafe. A correct answer that cites fewer expected sections is a
    # locator-quality metric: letting it move the threshold made one noisy case
    # discard every lower score (e.g. -1.29 -> 0.10 after an unrelated upload).
    safe = [threshold for threshold in candidates if decision_metrics(train, threshold)["fp"] == 0
            and decision_metrics(train, threshold)["tp"] > 0
            and not any(wrong_source(row) for row in train
                    if row.get("answer_eligible", True) and row.get("score") is not None and row["score"] >= threshold)]
    threshold = min(safe) if safe else None
    train_metrics, test_metrics = decision_metrics(train, threshold), decision_metrics(holdout, threshold)
    labels_present = all(any(r["expected_behavior"] == label for r in holdout) for label in ("answer", "abstain"))
    reasons = []
    if any(r.get("error") for r in rows):
        reasons.append("evaluation_errors")
    if threshold is None:
        reasons.append("no_safe_calibration_threshold")
    if not labels_present:
        reasons.append("validation_missing_classes")
    if test_metrics["fp"]:
        reasons.append("validation_improper_answers")
    if not test_metrics["tp"]:
        reasons.append("validation_no_answerable_acceptances")
    if threshold is not None and any(wrong_source(r) for r in holdout
            if r.get("answer_eligible", True) and r.get("score") is not None and r["score"] >= threshold):
        reasons.append("validation_incomplete_locators")
    if any(r["kind"] == "ambiguous" and r.get("assessment_action") != "clarify"
           for r in holdout if "assessment_action" in r):
        reasons.append("validation_missing_clarifications")
    approved = not reasons
    accepted = [r for r in rows if r["expected_behavior"] == "answer" and r.get("answer_eligible", True)
                and threshold is not None and r.get("score") is not None and r["score"] >= threshold]
    locator_recall = statistics.mean(r["recall10"] for r in accepted if r.get("recall10") is not None) if any(
        r.get("recall10") is not None for r in accepted) else None
    return {"threshold": threshold, "approved": approved, "train_ids": [r["id"] for r in train],
            "holdout_ids": [r["id"] for r in holdout], "train": train_metrics, "holdout": test_metrics,
            "reason": "empirical_holdout_pass" if approved else reasons[0], "rejection_reasons": reasons,
            "accepted_locator_recall10": locator_recall,
            "limitations": ["Small bank; no statistical guarantee", "Coverage assessment is model-dependent; exact excerpts do not prove semantics"],
            "clarification_accuracy": (sum(r.get("assessment_action") == "clarify" for r in rows if r["kind"] == "ambiguous")
                                       / sum(r["kind"] == "ambiguous" for r in rows))
                                       if any(r["kind"] == "ambiguous" for r in rows) else None}


def summarize(rows):
    report = {}
    for kind in sorted({r["kind"] for r in rows}):
        group = [r for r in rows if r["kind"] == kind]
        report[kind] = {"count": len(group), "errors": sum(bool(r.get("error")) for r in group)}
        for metric in ("recall5", "recall10", "mrr10", "ndcg10"):
            values = [r[metric] for r in group if r.get(metric) is not None]
            report[kind][metric] = statistics.mean(values) if values else None
    latency = {}
    for stage in ("embedding_ms", "search_ms", "fusion_ms", "reranking_ms", "sufficiency_ms"):
        values = sorted(r["latency"][stage] for r in rows if stage in r.get("latency", {}))
        latency[stage] = {"p50": statistics.median(values), "p95": values[math.ceil(.95 * len(values)) - 1],
                          "max": max(values)} if values else None
    return {"by_kind": report, "latency": latency}
