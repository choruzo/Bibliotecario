from alembic import context

from bibliotecario.config import get_settings
from bibliotecario.db import Base, build_database
from bibliotecario import models  # noqa: F401

config = context.config
url = get_settings().database_url.get_secret_value()


def include_object(obj, name, type_, reflected, compare_to):
    # H3 owns the PostgreSQL generated text-search column and its GIN index.
    # Neither exists in the portable ORM used by SQLite tests. Autogeneration
    # must not propose deleting them; changes to their DDL require a migration.
    if reflected and compare_to is None:
        if type_ == "column" and obj.table.name == "chunks" and name == "search_vector":
            return False
        if type_ == "index" and obj.table.name == "chunks" and name == "ix_chunks_text":
            return False
    return True


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine, _ = build_database(get_settings())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
