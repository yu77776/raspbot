"""Logging setup for PC-side Raspbot modules."""

import logging
import os
import sys


def setup_logger(
    name: str = None,
    level: int = None,
    log_file: str = None,
    console: bool = True,
):
    """Configure and return a logger."""
    if name is None:
        name = "raspbot"

    if level is None:
        level_name = os.getenv("RASPBOT_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    for noisy in ("websockets", "asyncio", "aiortc", "aioice", "PIL", "av"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logger
