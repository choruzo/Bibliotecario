from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "evaluation" / "h0" / "corpus_catalog.json"
SELECTION_PATH = ROOT / "evaluation" / "h0" / "variant_selection.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_metrics(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8-sig")
    return {
        "bytes": path.stat().st_size,
        "lines": len(text.splitlines()),
        "headings": len(re.findall(r"(?m)^#{1,6}\s", text)),
        "list_items": len(re.findall(r"(?m)^\s*[-*+]\s", text))
        + len(re.findall(r"(?m)^\s*\d+[.)]\s", text)),
        "table_rows": len(re.findall(r"(?m)^\s*\|.*\|\s*$", text)),
        "code_blocks": len(re.findall(r"(?m)^```", text)) // 2,
    }


def catalog_by_id() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in load_json(CATALOG_PATH)["documents"]}


def clean_inline(text: str) -> str:
    text = re.sub(r"^\s*>\s?", "", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`*_~]", "", text)
    text = text.replace("—", "-").replace("–", "-")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "So")
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def word_tokens(text: str) -> list[str]:
    return re.findall(r"[\w]+", normalize_text(text), flags=re.UNICODE)
