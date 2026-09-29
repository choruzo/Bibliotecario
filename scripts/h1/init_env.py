"""Genera secretos locales sin mostrarlos y sin sobrescribir configuracion existente."""
import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "bibliotecario-data")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    values = {"POSTGRES_PASSWORD": secrets.token_hex(32), "LITELLM_MASTER_KEY": "sk-" + secrets.token_hex(32),
              "BIB_DATA_DIR": data.as_posix()}
    lines = [f"{line.split('=', 1)[0]}={values[line.split('=', 1)[0]]}" if line.split('=', 1)[0] in values else line
             for line in template.splitlines()]
    try:
        with (ROOT / ".env").open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
    except FileExistsError:
        parser.exit(1, ".env ya existe; se conserva sin cambios.\n")
    for name in ("documents", "postgres", "backups", "exports"):
        (data / name).mkdir(parents=True, exist_ok=True)
    print("Configuracion creada en .env. Secretos omitidos.")


if __name__ == "__main__":
    main()
