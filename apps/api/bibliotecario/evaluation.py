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
    return {"recall5": hits5 / len(targets) if targets else None,
            "recall10": hits10 / len(targets) if targets else None,
            "mrr10": 1 / first if first else 0,
            "ndcg10": dcg / ideal if ideal else 0}


def decision_metrics(rows, threshold):
    tp = fp = fn = tn = 0
    for row in rows:
        expected = row["expected_behavior"] == "answer"
        answered = threshold is not None and row.get("score") is not None and row["score"] >= threshold
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


def calibrate(rows):
    # Alternating IDs within class; conversation groups stay together.
    groups = {}
    for row in rows:
        key = row.get("conversation_id") or row["id"]
        groups.setdefault(row["kind"], {}).setdefault(key, []).append(row)
    train, holdout = [], []
    for kind_groups in groups.values():
        for index, key in enumerate(sorted(kind_groups)):
            (train if index % 2 == 0 else holdout).extend(kind_groups[key])
    candidates = sorted({row["score"] for row in train if row.get("score") is not None})
    safe = [threshold for threshold in candidates if decision_metrics(train, threshold)["fp"] == 0
            and decision_metrics(train, threshold)["tp"] > 0
            and all(row.get("recall10") == 1 for row in train
                    if row.get("score") is not None and row["score"] >= threshold)]
    threshold = min(safe) if safe else None
    train_metrics, test_metrics = decision_metrics(train, threshold), decision_metrics(holdout, threshold)
    labels_present = all(any(r["expected_behavior"] == label for r in holdout) for label in ("answer", "abstain"))
    approved = bool(threshold is not None and labels_present and test_metrics["fp"] == 0 and test_metrics["tp"] > 0
                    and all(r.get("recall10") == 1 for r in holdout if r.get("score") is not None and r["score"] >= threshold))
    return {"threshold": threshold, "approved": approved, "train_ids": [r["id"] for r in train],
            "holdout_ids": [r["id"] for r in holdout], "train": train_metrics, "holdout": test_metrics,
            "reason": "empirical_holdout_pass" if approved else "insufficient_safe_separation",
            "limitations": ["Small initial bank; no statistical guarantee", "Raw follow-ups; contextual reformulation belongs to H4",
                            "Scalar score does not implement clarification; ambiguous cases remain abstentions"]}


def summarize(rows):
    report = {}
    for kind in sorted({r["kind"] for r in rows}):
        group = [r for r in rows if r["kind"] == kind]
        report[kind] = {"count": len(group), "errors": sum(bool(r.get("error")) for r in group)}
        for metric in ("recall5", "recall10", "mrr10", "ndcg10"):
            values = [r[metric] for r in group if r.get(metric) is not None]
            report[kind][metric] = statistics.mean(values) if values else None
    latency = {}
    for stage in ("embedding_ms", "search_ms", "fusion_ms", "reranking_ms"):
        values = sorted(r["latency"][stage] for r in rows if stage in r.get("latency", {}))
        latency[stage] = {"p50": statistics.median(values), "p95": values[math.ceil(.95 * len(values)) - 1],
                          "max": max(values)} if values else None
    return {"by_kind": report, "latency": latency}
