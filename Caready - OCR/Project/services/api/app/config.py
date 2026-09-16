"""Application settings and YAML config loading.

Two distinct kinds of configuration, deliberately kept apart:

  Settings (this module's `Settings`)  - environment/deployment concerns:
      connection strings, secrets, feature toggles. From the environment.

  Business config (config/*.yaml)      - grading rubrics, thresholds,
      deduction tables, field weights. Versioned in git, reviewable by
      non-engineers, changeable without a deploy.

Business rules never live in `Settings`, and secrets never live in YAML.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    """Resolve the monorepo root.

    Walks up looking for the `config/` directory so the same code works when
    run from `services/api`, from a container where the repo is mounted at
    `/app`, or from a test runner's temp cwd.
    """
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "config").is_dir() and (parent / "docs").is_dir():
            return parent
    # Container layout: /app/config exists but /app/docs may not be copied.
    for parent in [here, *here.parents]:
        if (parent / "config").is_dir():
            return parent
    raise RuntimeError("Could not locate repo root (no config/ directory found)")


REPO_ROOT = _repo_root()
CONFIG_DIR = REPO_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- environment ---
    environment: Literal["dev", "ci", "staging", "prod"] = "dev"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- synthetic data banner (§9) ---
    #: When true, the UI shows a persistent banner and every generated report
    #: carries a header stating the data is synthetic and pricing output has no
    #: real-world validity. Defaults to TRUE so a forgotten env var errs toward
    #: over-disclosure rather than passing synthetic output off as real.
    synthetic_data_mode: bool = True

    # --- database ---
    database_url: str = "postgresql+psycopg://caready:caready@localhost:5432/caready"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- redis / queue ---
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_default: str = "caready-default"
    rq_queue_slow: str = "caready-slow"
    rq_job_timeout_seconds: int = 900

    # --- object storage ---
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "caready"
    s3_secret_access_key: str = "caready-dev-secret"
    s3_bucket_photos: str = "caready-photos"
    s3_bucket_exports: str = "caready-exports"
    s3_use_path_style: bool = True
    s3_signed_url_ttl_seconds: int = 300

    # --- auth ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900          # 15 minutes
    refresh_token_ttl_seconds: int = 1209600     # 14 days
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 4

    # --- PII ---
    #: Comma-separated. First key encrypts; all keys are tried on decrypt,
    #: which is what makes rotation possible without downtime.
    pii_encryption_keys: str = "dev-only-insecure-passphrase-change-me"

    # --- MLflow ---
    mlflow_tracking_uri: str = "http://localhost:5500"
    mlflow_experiment: str = "caready-pricing"

    # --- api ---
    api_cors_origins: str = "http://localhost:3000"
    api_rate_limit_per_minute: int = 300

    @field_validator("jwt_secret", "pii_encryption_keys")
    @classmethod
    def _reject_dev_secrets_outside_dev(cls, v: str, info: Any) -> str:
        return v

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    def assert_production_safe(self) -> list[str]:
        """Return a list of production misconfigurations. Empty means safe.

        Called at startup; in `prod` a non-empty result aborts the process
        rather than logging a warning nobody reads.
        """
        problems: list[str] = []
        if self.environment != "prod":
            return problems
        if "change-me" in self.jwt_secret or self.jwt_secret == "dev-only-change-me":
            problems.append("JWT_SECRET is still the development default")
        if "change-me" in self.pii_encryption_keys:
            problems.append("PII_ENCRYPTION_KEYS is still the development default")
        if self.debug:
            problems.append("DEBUG is enabled in production")
        if self.synthetic_data_mode:
            problems.append(
                "SYNTHETIC_DATA_MODE is enabled in production - this would label "
                "real output as synthetic"
            )
        return problems


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------
# YAML business config
# --------------------------------------------------------------------------


class ConfigError(RuntimeError):
    pass


@functools.lru_cache(maxsize=None)
def load_config(name: str) -> dict[str, Any]:
    """Load and cache `config/<name>.yaml`.

    Cached for the process lifetime. A config change is a deploy or an
    explicit `reload_config()` - not a per-request file read, which would make
    two requests in the same batch potentially use different rubrics.
    """
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} did not parse to a mapping")
    if "version" not in data:
        raise ConfigError(f"Config file {path} is missing a `version` key")
    return data


def reload_config() -> None:
    """Drop the config cache. Used by tests and the admin config endpoint."""
    load_config.cache_clear()


def config_version(name: str) -> str:
    return str(load_config(name)["version"])


def grading_is_placeholder() -> bool:
    """Whether the active grading rubric is still the placeholder (§7.4).

    Drives a UI warning banner and a pricing-confidence degradation. Fails
    closed: an unrecognised status is treated as a placeholder.
    """
    return str(load_config("grading").get("rubric_status", "PLACEHOLDER")).upper() != "ACTIVE"
