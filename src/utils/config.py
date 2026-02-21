"""Config loader."""

import sys
import os
import logging
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger("workspace.config")

_DEFAULT = Path(__file__).parent.parent.parent / "config" / "default.toml"


def load_config() -> dict[str, Any]:
    try:
        with open(_DEFAULT, "rb") as f:
            cfg = tomllib.load(f)
        logger.info("Config loaded")
        return cfg
    except Exception as e:
        logger.error(f"Config load failed: {e}")
        return {}


def resolve_path(raw: str) -> str:
    """Expand %APPDATA% etc."""
    return os.path.expandvars(raw)