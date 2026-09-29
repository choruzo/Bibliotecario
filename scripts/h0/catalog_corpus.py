from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import CATALOG_PATH, ROOT, load_json, sha256_file, source_metrics, write_json


def actual_entry(expected: dict) -> dict:
    path = ROOT / expected["path"]
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "id": expected["id"],
        "path": expected["path"],
        "sha256": sha256_file(path),
        **source_metrics(path),
    }


def check_catalog() -> list[str]:
    catalog = load_json(CATALOG_PATH)
    errors: list[str] = []
    documents = catalog.get("documents", [])
    if len(documents) != 13:
        errors.append(f"expected 13 documents, found {len(documents)}")
    for expected in documents:
        try:
            actual = actual_entry(expected)
        except FileNotFoundError as exc:
            errors.append(f"missing source: {exc}")
            continue
        for key, value in actual.items():
            if expected.get(key) != value:
                errors.append(
                    f"{expected.get('id', '?')} {key}: catalog={expected.get(key)!r} actual={value!r}"
                )
    return errors


def refresh_catalog(output: Path) -> None:
    catalog = load_json(CATALOG_PATH)
    catalog["documents"] = [actual_entry(item) for item in catalog["documents"]]
    write_json(output, catalog)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the private corpus against its safe catalog.")
    parser.add_argument("--check", action="store_true", help="Fail if files differ from the catalog.")
    parser.add_argument("--output", type=Path, help="Write a refreshed catalog to this path.")
    args = parser.parse_args()
    if args.output:
        refresh_catalog(args.output)
        print(f"catalog written to {args.output}")
        return 0
    errors = check_catalog()
    if errors:
        print("catalog validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("catalog ok: 13 documents and hashes match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
