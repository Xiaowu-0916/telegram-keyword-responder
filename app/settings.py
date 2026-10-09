from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env_bool(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    session_path: Path
    admin_user: str
    initial_password: str
    session_secret: str
    https_only: bool
    host: str
    port: int
    session_max_age: int = 14 * 24 * 3600


def load_settings(env: dict[str, str] | None = None) -> Settings:
    if env is None:
        env = dict(os.environ)
    base_dir = Path(env.get("TGKR_BASE_DIR", Path(__file__).resolve().parent.parent)).resolve()
    data_dir = Path(env.get("TGKR_DATA_DIR", base_dir / "data")).resolve()
    db_path = Path(env.get("TGKR_DB_PATH", data_dir / "state.db")).resolve()
    session_path = Path(env.get("TGKR_SESSION_PATH", data_dir / "account")).resolve()
    return Settings(
        base_dir=base_dir,
        data_dir=data_dir,
        db_path=db_path,
        session_path=session_path,
        admin_user=env.get("TGKR_ADMIN_USER", "admin").strip() or "admin",
        initial_password=env.get("TGKR_INITIAL_PASSWORD", ""),
        session_secret=env.get("TGKR_SESSION_SECRET") or secrets.token_hex(32),
        https_only=_env_bool(env, "TGKR_HTTPS_ONLY", False),
        host=env.get("TGKR_HOST", "127.0.0.1"),
        port=int(env.get("TGKR_PORT", "8100")),
    )
