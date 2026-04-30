"""Raspbot PC WebSocket client entrypoint."""

from pc_modules.local_env import load_local_env
from pc_modules.app import main


if __name__ == '__main__':
    load_local_env()
    main()
