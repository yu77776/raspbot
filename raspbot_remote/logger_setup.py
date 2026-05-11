"""Re-exports setup_logger from the canonical raspbot_common package.

This file exists for backward-compatible bare imports on the car side.
"""

from raspbot_common.logger_setup import setup_logger  # noqa: F401
