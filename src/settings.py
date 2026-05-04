from pydantic_settings import BaseSettings
from pydantic import SecretStr
from typing import Any
import os
from dotenv import load_dotenv

BASEDIR = os.path.abspath(os.path.dirname(__file__))

# Connect the path with your '.env' file name
load_dotenv(os.path.join(BASEDIR, "../.env"))


class Settings(BaseSettings):
    """Settings for the application."""

    ROOT_PATH: str = ""
    API_V1_STR: str = "/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8055
    ENVIRONMENT: str = "development"

    # OpenAI API key
    OPENAI_API_KEY: SecretStr
    OPENAI_BASE_URL: str = "http://localhost:4000"
    OPENAI_TEMPERATURE: float = 0.7

    # PostgreSQL configuration for long-term memory
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "postgres"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr  # optional for local dev; set in .env for real DB
    DATABASE_URL: str | None = None

    # Redis configuration for short-term memory
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_DB: int
    REDIS_PASSWORD: SecretStr | None = None

    # Langfuse configuration
    LANGFUSE_PUBLIC_KEY: SecretStr | None = None
    LANGFUSE_SECRET_KEY: SecretStr | None = None
    LANGFUSE_HOST: str | None = None


SETTINGS = Settings()  # type: ignore

APP_CONFIGS: dict[str, Any] = {
    "title": "Course Learning Assistant",
    "root_path": SETTINGS.ROOT_PATH,
}
