"""Backward-compatibility shim — re-exports canonical definitions from raspbot_shared.

Car code and tests import from this file as `from protocol import ...`.
No consumer changes needed — the shim ensures raspbot_shared is on sys.path
and re-exports every public name the old protocol.py used to define.
"""

import os as _os
import sys as _sys

_repo = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _repo not in _sys.path:
    _sys.path.insert(0, _repo)

from raspbot_shared.protocol import *  # noqa: F401,F403
