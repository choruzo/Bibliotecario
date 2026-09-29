from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIB_", env_file=".env", extra="ignore", hide_input_in_errors=True)

    environment: str = Field(default="development", pattern="^(development|production|test)$")
    database_url: SecretStr
    storage_path: Path
    public_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    session_hours: int = Field(default=12, ge=1, le=168)
    llm_base_url: str = "http://litellm:4000/v1"
    llm_model: str = "bibliotecario-generation"
    llm_api_key: SecretStr
    embedding_base_url: str = "http://host.docker.internal:8081"
    embedding_model: str = "nomic-embed-text-v1.5.f16.gguf"
    embedding_dimensions: int = Field(default=768, ge=1)
    embedding_api_key: SecretStr = SecretStr("")
    reranker_base_url: str = "http://host.docker.internal:8082"
    reranker_model: str = "bge-reranker-v2-m3-Q8_0.gguf"
    reranker_api_key: SecretStr = SecretStr("")
    model_timeout_seconds: float = Field(default=15, gt=0, le=120)
    worker_interval_seconds: float = Field(default=15, ge=1, le=60)

    @model_validator(mode="after")
    def validate_deployment(self):
        from urllib.parse import urlsplit

        db = make_url(self.database_url.get_secret_value())
        if self.environment != "test" and db.drivername != "postgresql+psycopg":
            raise ValueError("Use PostgreSQL con el controlador psycopg")
        if not self.storage_path.is_absolute():
            raise ValueError("BIB_STORAGE_PATH debe ser absoluto")
        for value in [self.public_origin, self.llm_base_url, self.embedding_base_url, self.reranker_base_url]:
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("URL de servicio no valida")
        origin = urlsplit(self.public_origin)
        if origin.path not in {"", "/"}:
            raise ValueError("BIB_PUBLIC_ORIGIN no admite una ruta")
        self.public_origin = self.public_origin.rstrip("/")
        if not self.llm_api_key.get_secret_value():
            raise ValueError("BIB_LLM_API_KEY es obligatorio")
        if self.environment == "production" and (not self.cookie_secure or origin.scheme != "https"):
            raise ValueError("Produccion requiere HTTPS y BIB_COOKIE_SECURE=true")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
