"""Raspbot PC WebSocket client entrypoint."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from pc_modules.local_env import load_local_env
from pc_modules.app import main


if __name__ == '__main__':
    load_local_env()
    main()
