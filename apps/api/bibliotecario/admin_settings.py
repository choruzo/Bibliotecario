"""Only explicitly public provider fields may be persisted or exported."""
from typing import Literal
import hashlib
import json
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from .models import AppSetting


class PublicSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    llm_base_url: str = Field(max_length=300)
    llm_model: str = Field(min_length=1, max_length=200)
    embedding_base_url: str = Field(max_length=300)
    embedding_model: str = Field(min_length=1, max_length=200)
    reranker_base_url: str = Field(max_length=300)
    reranker_model: str = Field(min_length=1, max_length=200)
    model_timeout_seconds: float = Field(gt=0, le=120)
    sufficiency_reasoning_effort: Literal["low", "medium", "high", "disabled"]
    index_timeout_seconds: int = Field(ge=10, le=3600)
    conversion_timeout_seconds: int = Field(ge=10, le=1800)

    @field_validator("llm_base_url", "embedding_base_url", "reranker_base_url")
    @classmethod
    def service_url(cls, value):
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            raise ValueError("URL de servicio sin credenciales, query ni fragmento")
        _ = url.port
        return value.rstrip("/")

    @field_validator("llm_model", "embedding_model", "reranker_model")
    @classmethod
    def model_name(cls, value):
        if not value.strip() or any(c.isspace() for c in value) or "://" in value:
            raise ValueError("Nombre de modelo no valido")
        return value


def public_settings(settings):
    return PublicSettings.model_validate({k: getattr(settings, k) for k in PublicSettings.model_fields}).model_dump()


def settings_signature(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def load_settings(settings, sessions):
    with sessions() as db:
        record = db.get(AppSetting, "providers")
        if not record:
            return settings
        values = PublicSettings.model_validate(record.value).model_dump()
    return type(settings).model_validate(settings.model_dump() | values)
