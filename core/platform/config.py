"""Runtime configuration for the platform layer. Read from the environment at call time."""
import os
import secrets
from pathlib import Path


def env() -> str:
    return os.getenv("HACFEW_ENV", "development").lower()


def is_production() -> bool:
    return env() == "production"


def platform_database_url() -> str:
    return os.getenv("PLATFORM_DATABASE_URL", "sqlite:///./hacfew_platform.db")


def sync_execution() -> bool:
    """Run workflows inline instead of on a worker thread (used by tests)."""
    return os.getenv("HACFEW_SYNC_EXECUTION", "0") == "1"


def token_ttl_seconds() -> int:
    return int(os.getenv("HACFEW_TOKEN_TTL_SECONDS", str(8 * 3600)))


def cors_origins() -> list[str]:
    raw = os.getenv("HACFEW_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def legacy_api_enabled() -> bool:
    return os.getenv("HACFEW_ENABLE_LEGACY_API", "0") == "1"


def dev_password() -> str:
    return os.getenv("HACFEW_DEV_PASSWORD", "hacfew-dev")


def jwt_secret() -> str:
    """HACFEW_JWT_SECRET is mandatory in production. In development a random secret is
    generated once and persisted under .hacfew/ (git-ignored) so tokens survive restarts."""
    configured = os.getenv("HACFEW_JWT_SECRET")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("HACFEW_JWT_SECRET must be at least 32 characters")
        return configured
    if is_production():
        raise RuntimeError("HACFEW_JWT_SECRET must be set when HACFEW_ENV=production")
    path = Path(os.getenv("HACFEW_STATE_DIR", ".hacfew")) / "jwt_secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    return value
