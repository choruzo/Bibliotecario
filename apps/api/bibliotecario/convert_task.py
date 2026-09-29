import argparse
import json
from pathlib import Path

from .config import get_settings
from .converters import convert
from .storage import InvalidFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--format", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = convert(args.input, args.format, get_settings())
    except Exception as exc:
        result = {"error": str(exc) if isinstance(exc, InvalidFile) else "conversion_failed"}
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=True)


if __name__ == "__main__":
    main()
