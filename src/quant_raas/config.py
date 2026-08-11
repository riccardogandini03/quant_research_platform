"""Environment-backed application settings.

Benchmark identifiers are configuration rather than constants because a valid
comparison depends on region, listing, and the PM's research mandate.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings shared by command, API, dashboard, and worker adapters."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="QUANT_RAAS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+pysqlite:///./quant_raas.db"
    database_echo: bool = False
    log_level: str = "INFO"

    # Empty defaults force a deployment to choose mappings explicitly. Pydantic
    # settings accepts these dictionaries as JSON in environment variables.
    default_benchmark_identifier: str | None = None
    sector_benchmark_identifiers: dict[str, str] = Field(default_factory=dict)
    benchmark_mapping_file: Path | None = None

    # Connector configuration is deliberately provider-neutral in the core.
    market_data_provider: str = "fixture"
    config_directory: Path = Path("configs")
    data_directory: Path = Path("data")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""

    return Settings()
