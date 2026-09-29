"""Matriz H2 con extractores de produccion; informes sin fragmentos del corpus."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "h0"))
from common import load_json, sha256_file  # noqa: E402
from compare_variants import plain_source, score  # noqa: E402
from generate_variants import blocks_from_markdown  # noqa: E402
from bibliotecario.config import Settings  # noqa: E402
from bibliotecario.converters import convert  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / "h2" / "conversion-matrix.json")
    args = parser.parse_args()
    settings = Settings(_env_file=None, environment="test", database_url="sqlite://",
                        storage_path=ROOT / ".artifacts" / "h2", llm_api_key="not-used")
    selection = load_json(ROOT / "evaluation" / "h0" / "variant_selection.json")
    manifest = load_json(ROOT / ".artifacts" / "h0" / "variants" / "manifest.json")
    catalog = load_json(ROOT / "evaluation" / "h0" / "corpus_catalog.json")
    results = []
    sources = catalog.get("documents", [])
    for entry in sources:
        document_id = entry["id"]
        source = ROOT / entry["path"]
        assert sha256_file(source) == entry["sha256"], "El corpus ha cambiado"
        cases = [("md", source)]
        variant = next((item for item in manifest["variants"] if item["document_id"] == document_id), None)
        if variant:
            assert sha256_file(source) == variant["source_sha256"], "El corpus ha cambiado"
            for fmt in ("pdf", "docx"):
                path = ROOT / variant["outputs"][fmt]["path"]
                assert sha256_file(path) == variant["outputs"][fmt]["sha256"], "La variante ha cambiado"
                cases.append((fmt, path))
        blocks = blocks_from_markdown(source.read_text(encoding="utf-8-sig"))
        for fmt, path in cases:
            result = convert(path, fmt, settings)
            extracted = plain_source(blocks_from_markdown(result["markdown"]))
            metrics = score(blocks, extracted)
            thresholds = selection["thresholds"].get(fmt, {"token_recall": 1.0, "heading_recall": 1.0, "order_ratio": 1.0})
            gates = {name: metrics[name] >= minimum for name, minimum in thresholds.items()}
            lines = len(result["markdown"].splitlines())
            valid_provenance = bool(result["provenance"]) and all(
                1 <= locator["line_start"] <= locator["line_end"] <= lines and
                (fmt != "pdf" or isinstance(locator["page"], int) and locator["page"] > 0)
                for locator in result["provenance"])
            gates["provenance"] = valid_provenance
            row = {"document_id": document_id, "format": fmt, "source_sha256": sha256_file(source),
                   "input_sha256": sha256_file(path), "normalized_sha256": result["sha256"],
                   "metrics": metrics, "gates": gates, "diagnostics": result["diagnostics"],
                   "locators": len(result["provenance"]), "passed": all(gates.values()),
                   "warnings": (["structure_difference"] if metrics["structure_recall"] < 1 else []) +
                               (["additional_tokens"] if metrics["extracted_tokens"] > metrics["source_tokens"] else [])}
            results.append(row)
            print(f"{document_id} {fmt}: {'REFERENCE_PASS' if row['passed'] else 'FAIL'} {metrics} warnings={row['warnings']}")
    report = {"threshold_basis": "H0 fixture reference; not final H2 fidelity acceptance",
              "structural_review_required": any(row["warnings"] for row in results),
              "results": results, "passed": bool(results) and all(row["passed"] for row in results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
