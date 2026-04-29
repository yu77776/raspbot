#!/usr/bin/env python3
"""Shared lifecycle base for threaded car modules."""

import threading
from typing import Optional


class ModuleBase:
    """模块基类，提供统一的生命周期接口。"""

    _thread: Optional[threading.Thread] = None
    _running = False
    join_timeout = 2.0

    def _can_start(self) -> bool:
        return True

    def _before_start(self) -> bool:
        return True

    def _before_stop(self):
        return None

    def _after_stop(self):
        return None

    def start(self):
        if not self._can_start():
            return
        thread = getattr(self, "thread", None)
        if getattr(self, "started", False) and thread and thread.is_alive():
            return
        if not self._before_start():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.started = True
        self._running = True
        self._thread = self.thread

    def stop(self):
        self.stop_event.set()
        self._before_stop()
        thread = getattr(self, "thread", None)
        if thread and thread.is_alive():
            thread.join(timeout=self.join_timeout)
        self.started = False
        self._running = False
        self._after_stop()

    def get_data(self) -> dict:
        return {}

    def _run(self):
        raise NotImplementedError
