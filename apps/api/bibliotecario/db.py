from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    pass


def build_database(settings: Settings):
    url = settings.database_url.get_secret_value()
    connect_args = {} if settings.environment == "test" else {
        "connect_timeout": 5, "options": "-c statement_timeout=5000"
    }
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return engine, sessionmaker(engine, expire_on_commit=False)
