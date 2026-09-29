import os
from pathlib import Path


def main():
    root = Path("/data/documents")
    for directory in (root, root / "originals", root / "normalized"):
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, 10001, 10001)
        directory.chmod(0o750)


if __name__ == "__main__":
    main()
