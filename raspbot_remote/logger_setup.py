"""Shared logging setup for car and PC sides.

Usage in each module:
    from logger_setup import setup_logger
    logger = setup_logger(__name__)

    logger.info('message %s', value)
    logger.warning('warning %s', value)
    logger.error('error %s', value)
"""

import logging
import os
import sys


def setup_logger(
    name: str = None,
    level: int = None,
    log_file: str = None,
    console: bool = True,
):
    """Configure and return a logger.

    Args:
        name: Logger name. If not set, uses the calling module's __name__.
        level: Logging level. Defaults to INFO, or RASPBOT_LOG_LEVEL env var.
        log_file: Optional file path for log output.
        console: Whether to output to stderr (default True).
    """
    if name is None:
        name = 'raspbot'

    if level is None:
        level_name = os.getenv('RASPBOT_LOG_LEVEL', 'INFO').upper()
        level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(name)

    # Prevent duplicate handlers on re-import by checking existing handlers
    if logger.handlers:
        return logger

    logger.setLevel(level)

    fmt = '%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s %(message)s'
    datefmt = '%H:%M:%S'
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if log_file:
        os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ('websockets', 'asyncio', 'aiortc', 'aioice', 'PIL', 'av'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logger
