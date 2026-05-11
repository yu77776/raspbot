"""Re-exports setup_logger from the canonical raspbot_common package.

This file exists for backward-compatible relative imports within pc_modules.
"""

from raspbot_common.logger_setup import setup_logger  # noqa: F401
