"""Settings from the environment, with .env (repo root) as a fallback. No extra dependency.

Real environment variables win over .env. The app refuses to start (ConfigError) when a required
setting is missing, with a message that says which one.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH_KEYS = ("DEMO_DOCTOR_NAME", "DEMO_DOCTOR_USER", "DEMO_DOCTOR_PASSWORD", "AUTH_SECRET")
MIN_SECRET_LENGTH = 32


class ConfigError(RuntimeError):
    pass


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE lines into os.environ, without overriding variables that are already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def setting(key: str, default: str = "") -> str:
    load_dotenv()
    return os.environ.get(key, default).strip()


def check_auth_settings() -> None:
    """Raise ConfigError unless the demo doctor and the token secret are configured."""
    missing = [k for k in AUTH_KEYS if not setting(k)]
    if missing:
        raise ConfigError(f"ChronoTrace cannot start: {', '.join(missing)} missing in .env "
                          "(copy .env.example to .env and fill them in)")
    if len(setting("AUTH_SECRET")) < MIN_SECRET_LENGTH:
        raise ConfigError(f"ChronoTrace cannot start: AUTH_SECRET must be at least {MIN_SECRET_LENGTH} characters "
                          "(e.g. python -c \"import secrets; print(secrets.token_urlsafe(48))\")")


def auth_secret() -> bytes:
    check_auth_settings()
    return setting("AUTH_SECRET").encode("utf-8")
