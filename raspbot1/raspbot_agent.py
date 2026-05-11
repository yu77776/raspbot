"""One-command launcher for the Raspbot PC/car runtime."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pc_modules.local_env import load_local_env
from agent_modules.launcher import main


if __name__ == "__main__":
    load_local_env()
    main()
