import argparse
import getpass
import re
import uuid

from sqlalchemy import select, text

from .auth import hasher, lookup_user
from .config import get_settings
from .db import build_database
from .models import AuditEvent, User


def create_user(db, username, password, role, bootstrap=False):
    username = username.lower()
    if not re.fullmatch(r"[a-z0-9_.@-]{1,64}", username):
        raise ValueError("Nombre de usuario no valido")
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("La contrasena debe tener entre 12 y 1024 caracteres")
    if role not in {"admin", "usuario"}:
        raise ValueError("Rol no valido")
    # Serialize concurrent bootstrap commands on PostgreSQL.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(72191401)"))
    if bootstrap and db.scalar(select(User.id).where(User.role == "admin")):
        raise ValueError("Ya existe un administrador; use create-user")
    if lookup_user(db, username):
        raise ValueError("El usuario ya existe")
    user = User(username=username, password_hash=hasher.hash(password), role=role)
    db.add(user)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, action="bootstrap_admin" if bootstrap else "create_user",
                      object_id=user.id, correlation_id=str(uuid.uuid4())))
    db.commit()
    return user


def main():
    parser = argparse.ArgumentParser(description="Gestion local de cuentas Bibliotecario")
    parser.add_argument("command", choices=["bootstrap-admin", "create-user"])
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=["admin", "usuario"], default="usuario")
    args = parser.parse_args()
    password = getpass.getpass("Contrasena (minimo 12 caracteres): ")
    if password != getpass.getpass("Repita la contrasena: "):
        parser.error("Las contrasenas no coinciden")
    engine, sessions = build_database(get_settings())
    try:
        with sessions() as db:
            create_user(db, args.username, password, "admin" if args.command == "bootstrap-admin" else args.role,
                        bootstrap=args.command == "bootstrap-admin")
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        engine.dispose()
    print("Cuenta creada")


if __name__ == "__main__":
    main()
