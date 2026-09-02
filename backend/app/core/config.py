import os
from pathlib import Path
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: this file is backend/app/core/config.py, so parents[3] is the root.
# Every filesystem-bound setting is anchored here so that the process's working
# directory can never decide which database or data directory is used.
REPO_ROOT = Path(__file__).resolve().parents[3]

_ENV_PATHS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.env")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.env")),
    ".env"
]


def _is_absolute_path(raw: str) -> bool:
    """True for POSIX and Windows absolute paths, including drive-less roots."""
    return Path(raw).is_absolute() or raw.startswith(("/", "\\"))


def _anchor_to_root(raw: str) -> str:
    """Resolve a relative filesystem path against the repository root."""
    if not raw or _is_absolute_path(raw):
        return raw
    return str((REPO_ROOT / raw).resolve())


def anchor_sqlite_url(url: str) -> str:
    """
    Rewrite a relative SQLite URL into an absolute one anchored at REPO_ROOT.

    ``sqlite:///./finance_controller.db`` resolves relative to the *working
    directory*, so launching from the repo root and from ``backend/`` silently
    produced two divergent databases. Non-SQLite URLs and in-memory databases
    are returned untouched.
    """
    if not url.startswith("sqlite"):
        return url

    scheme, _, remainder = url.partition(":///")
    if not remainder or remainder.startswith(":memory:"):
        return url
    if _is_absolute_path(remainder):
        return url

    absolute = (REPO_ROOT / remainder).resolve()
    # SQLAlchemy's SQLite dialect takes the post-scheme portion as a literal
    # filesystem path; forward slashes are required for Windows drive paths.
    return f"{scheme}:///" + str(absolute).replace("\\", "/")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_PATHS, env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "AI Financial Controller"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Security & Auth
    # NOTE: this default exists only so a fresh clone boots. It is a known-public value.
    # Set SECRET_KEY in the environment for anything other than local development;
    # `settings.secret_key_is_insecure_default` is True while the default is in use.
    SECRET_KEY: str = "dev_secret_key_change_in_production_finance_controller_jwt_9921"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 hours
    ALGORITHM: str = "HS256"

    # Database: Supports SQLite for zero-config local run, or PostgreSQL for production.
    # Relative SQLite paths are anchored to the repository root (see anchor_sqlite_url)
    # so the launch directory cannot select a different database file.
    DATABASE_URL: str = "sqlite:///./finance_controller.db"
    ASYNC_DATABASE_URL: Optional[str] = None

    # Redis Configuration (Optional volatile cache & distributed locks - fail-open if unreachable)
    REDIS_ENABLED: bool = True
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"
    REDIS_CONNECT_TIMEOUT_SEC: float = 2.0

    # AI API Keys — supplied via environment / .env only. Never hardcode a
    # default: a committed default is a published credential.
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    # Storage (Local or MinIO/S3)
    UPLOAD_DIR: str = "./data/uploads"
    DATA_DIR: str = "./data"

    # Tenancy Defaults
    DEFAULT_ORG_ID: str = "00000000-0000-0000-0000-000000000001"
    DEFAULT_ORG_NAME: str = "Acme Global Enterprise"
    BASE_CURRENCY: str = "INR"
    MATERIALITY_THRESHOLD_MINOR: int = 50000 # ₹500.00 (in paise)

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    # ------------------------------------------------------------------
    # Reporting period
    # ------------------------------------------------------------------
    # By default the period is DERIVED from the value_dates present in the
    # uploaded data (see services/period.py). These two settings only act as an
    # explicit override; leave them unset to keep the period honest.
    PERIOD_START_OVERRIDE: Optional[str] = None   # "YYYY-MM-DD"
    PERIOD_END_OVERRIDE: Optional[str] = None     # "YYYY-MM-DD"

    # ------------------------------------------------------------------
    # AI agent runtime bounds & Global Budget
    # ------------------------------------------------------------------
    AGENT_MAX_TOOL_CALLS: int = 6
    AGENT_TIMEOUT_SECONDS: int = 60
    AGENT_MAX_CONTEXT_TOKENS: int = 12000
    AGENT_TRIAGE_MODEL: str = "claude-haiku-4-5-20251001"
    AGENT_INVESTIGATION_MODEL: str = "claude-sonnet-5"
    AGENT_GEMINI_MODEL: str = "gemini-3.6-flash"
    AGENT_PRIMARY_PROVIDER: str = "groq"
    AGENT_MAX_RETRIES: int = 1
    MAX_RETRIES_PER_PROVIDER: int = 1
    MAX_LLM_CALLS_PER_BATCH: int = 3
    MAX_LLM_CALLS_PER_AGENT: int = 1
    AI_CIRCUIT_BREAKER_COOLDOWN_SEC: float = 60.0
    AI_TELEMETRY_STRUCTURED_LOGS: bool = True

    # ------------------------------------------------------------------
    # Autonomy limits — the boundary between "code may apply this" and
    # "a human must sign it". Nothing above materiality is ever auto-applied.
    # ------------------------------------------------------------------
    AUTO_APPLY_CONFIDENCE_THRESHOLD: float = 0.93
    AUTO_APPLY_ENABLED: bool = True
    # Exception types that may ever be auto-applied below materiality.
    AUTO_APPLY_ALLOWED_TYPES: List[str] = [
        "FEE_VARIANCE",
        "MDR_FEE_MISMATCH",
        "ROUNDING_DIFFERENCE",
    ]

    # ------------------------------------------------------------------
    # Metrics honesty guards
    # ------------------------------------------------------------------
    # Below this many scored matches, calibration/ECE is reported as
    # "not measured" rather than as a number that means nothing.
    MIN_SAMPLES_FOR_CALIBRATION: int = 50
    GROUND_TRUTH_PATH: Optional[str] = "./data/ground_truth_links.json"

    ALLOW_DEMO_SEED: bool = False

    # ------------------------------------------------------------------
    # Path normalisation — applied after env/.env loading so that a relative
    # value supplied anywhere is still anchored to the repository root.
    # ------------------------------------------------------------------
    @field_validator("DATABASE_URL")
    @classmethod
    def _normalise_database_url(cls, v: str) -> str:
        return anchor_sqlite_url(v)

    @field_validator("UPLOAD_DIR", "DATA_DIR")
    @classmethod
    def _normalise_dirs(cls, v: str) -> str:
        return _anchor_to_root(v)

    @field_validator("GROUND_TRUTH_PATH")
    @classmethod
    def _normalise_optional_paths(cls, v: Optional[str]) -> Optional[str]:
        return _anchor_to_root(v) if v else v

    @property
    def secret_key_is_insecure_default(self) -> bool:
        return self.SECRET_KEY == "dev_secret_key_change_in_production_finance_controller_jwt_9921"

    def validate_production_environment(self) -> None:
        """Enforces hard validation in production environment."""
        if self.APP_ENV.lower() in ("production", "prod"):
            if self.secret_key_is_insecure_default or len(self.SECRET_KEY) < 32:
                raise ValueError("PRODUCTION_CONFIG_ERROR: SECRET_KEY must be set to a secure secret of at least 32 characters in production.")
            if self.DEBUG:
                raise ValueError("PRODUCTION_CONFIG_ERROR: DEBUG must be set to False in production.")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("PRODUCTION_CONFIG_ERROR: Wildcard CORS_ORIGINS ('*') is forbidden in production. Explicit allowed origins required.")
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("PRODUCTION_CONFIG_ERROR: SQLite is forbidden for production. PostgreSQL connection string required.")

settings = Settings()

if settings.APP_ENV.lower() in ("production", "prod"):
    settings.validate_production_environment()
elif settings.secret_key_is_insecure_default:
    import logging
    logging.getLogger("finance_controller.config").warning(
        "Running in dev mode with default SECRET_KEY. Set SECRET_KEY in .env for production."
    )

# Ensure storage directories exist
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.DATA_DIR, exist_ok=True)
