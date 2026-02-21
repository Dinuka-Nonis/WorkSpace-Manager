"""Logging setup."""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO"):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "workspace.log"

    root = logging.getLogger("workspace")
    root.setLevel(logging.DEBUG)

    fmt_detail = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fmt_simple = logging.Formatter("%(levelname)-8s | %(message)s")

    # Rotating file
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_detail)

    # Console
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(fmt_simple)

    root.addHandler(fh)
    root.addHandler(ch)
    root.info("Logging initialized")