"""Config + env loader.

Env vars (POLYGON_API_KEY, SEC_EDGAR_USER_AGENT, etc.) are loaded from:
  1. theme_detector/.env  (shared across the AI workflows family)
  2. positioning_meter/.env  (optional, overrides shared)
The override order means a project-local .env wins if both exist.
"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SHARED_ENV = PROJECT_ROOT.parent / "theme_detector" / ".env"
LOCAL_ENV = PROJECT_ROOT / ".env"


def _load_env_once():
    if SHARED_ENV.exists():
        load_dotenv(SHARED_ENV, override=False)
    if LOCAL_ENV.exists():
        load_dotenv(LOCAL_ENV, override=True)


_load_env_once()


def load():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    cfg["_project_root"] = str(PROJECT_ROOT)
    return cfg


def project_path(rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    return p if p.is_absolute() else PROJECT_ROOT / p


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"{name} not set. Expected in {SHARED_ENV} or {LOCAL_ENV}."
        )
    return v
