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


def node_workers() -> int:
    """Size of the pool that executes task-graph nodes (per process)."""
    return max(1, int(os.getenv("HACFEW_NODE_WORKERS", "8")))


# ---------------------------------------------------------------- files and email connectors
def files_dir() -> Path:
    return Path(os.getenv("HACFEW_FILES_DIR") or (Path(os.getenv("HACFEW_STATE_DIR", ".hacfew")) / "files"))


def max_upload_bytes() -> int:
    return int(float(os.getenv("HACFEW_MAX_UPLOAD_MB", "5")) * 1024 * 1024)


def email_mode() -> str:
    """mock (default; nothing leaves the machine) or smtp (a real provider; opt-in)."""
    return os.getenv("HACFEW_EMAIL_MODE", "mock").lower()


def email_from() -> str:
    return os.getenv("HACFEW_EMAIL_FROM", "audit@hacfew.local")


def email_allowed_domains() -> list[str]:
    """Recipient domains that may receive mail. `*` allows any (mock mode only: real SMTP fails closed without a list)."""
    raw = os.getenv("HACFEW_EMAIL_ALLOWED_DOMAINS", "*" if email_mode() == "mock" else "")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def smtp_settings() -> dict:
    """Credentials come from the environment only; they are never stored in workflows, logs or API responses."""
    return {"host": os.getenv("HACFEW_SMTP_HOST", ""), "port": int(os.getenv("HACFEW_SMTP_PORT", "587")),
            "user": os.getenv("HACFEW_SMTP_USER", ""), "password": os.getenv("HACFEW_SMTP_PASSWORD", ""),
            "starttls": os.getenv("HACFEW_SMTP_STARTTLS", "1") == "1", "ssl": os.getenv("HACFEW_SMTP_SSL", "0") == "1",
            "timeout": float(os.getenv("HACFEW_SMTP_TIMEOUT", "20"))}
