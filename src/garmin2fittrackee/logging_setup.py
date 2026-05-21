import logging
import os
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

DEFAULT_FILE_LOG_LEVEL = "DEBUG"
DEFAULT_CONSOLE_LOG_LEVEL = "CRITICAL"

_root_configured = False


def _resolve_level(value: str | None, env_var: str, default: str) -> int:
    raw: str = value if value is not None else os.getenv(env_var, default)
    level = getattr(logging, raw.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level: {raw}")
    return level


def setup_logging(
    log_file: Path | None = None,
    file_log_level: str | None = None,
    console_log_level: str | None = None,
) -> None:
    global _root_configured
    if _root_configured:
        return
    _root_configured = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for name in ("httpcore", "httpcore.http11", "httpcore.connection", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        _resolve_level(
            console_log_level, "CONSOLE_LOG_LEVEL",
            DEFAULT_CONSOLE_LOG_LEVEL,
        )
    )
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(
            _resolve_level(
                file_log_level, "LOG_LEVEL", DEFAULT_FILE_LOG_LEVEL,
            )
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(file_handler)
