"""pgvector storage without a second client dependency; JSON only in unit tests."""
import json
from sqlalchemy.types import UserDefinedType


class Vector768(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return "vector(768)"

    def bind_processor(self, dialect):
        return lambda value: json.dumps(value) if value is not None else None

    def result_processor(self, dialect, coltype):
        return lambda value: json.loads(value) if isinstance(value, str) else value
