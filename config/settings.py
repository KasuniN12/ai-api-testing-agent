"""Application configuration settings using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the AI API Testing Agent."""

    # Project Base Directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent

    # OpenAI & LLM Settings
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TEMPERATURE: float = 0.2

    # Target API Defaults
    TARGET_API_BASE_URL: str = "http://localhost:8000"
    OPENAPI_SPEC_PATH: str = "examples/sample_openapi.json"

    # Execution & Sandbox
    EXECUTION_TIMEOUT: int = 30
    ENABLE_DOCKER_SANDBOX: bool = False
    DOCKER_IMAGE_NAME: str = "python:3.11-slim"

    # Iterative Reflection Loop Settings
    MAX_REFLECTION_ITERATIONS: int = 3
    TARGET_COVERAGE_PERCENT: float = 90.0
    TARGET_QUALITY_SCORE: float = 0.85

    # Artifact Storage Paths
    ARTIFACTS_DIR: Path = BASE_DIR / "artifacts"
    GENERATED_TESTS_DIR: Path = BASE_DIR / "artifacts" / "generated_tests"
    REPORTS_DIR: Path = BASE_DIR / "artifacts" / "reports"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
