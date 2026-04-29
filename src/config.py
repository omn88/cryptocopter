"""Single source of truth for application configuration.

Reads ``config/.env`` relative to the repository root. When the file is
absent (CI, tests without credentials) both values fall back to empty
strings so imports never raise.
"""

from pathlib import Path

_env_path = Path(__file__).parent.parent / "config" / ".env"

if _env_path.exists():
    from decouple import Config, RepositoryEnv

    _config = Config(RepositoryEnv(_env_path))
    API_KEY: str = _config("API_KEY", default="")
    API_SECRET: str = _config("API_SECRET", default="")
else:
    API_KEY = ""
    API_SECRET = ""
