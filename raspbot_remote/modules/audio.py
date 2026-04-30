#!/usr/bin/env python3
"""Audio playback module."""

import os
import threading
import time

from modules.base import ModuleBase

try:
    import pygame  # type: ignore[import-not-found]
    pygame.mixer.init()
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False


def _safe_text(value):
    return str(value).encode('utf-8', errors='backslashreplace').decode('utf-8')


class Audio(ModuleBase):
    join_timeout = 1.0

    def __init__(self, songs_dir='songs'):
        self.songs_dir = songs_dir
        self.queue = []
        self.volume = 100
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stop_flag = threading.Event()
        self.tts_engine = None
        self.tts_lock = threading.Lock()
        self.thread = None
        self.started = False
        print(f'[AUDIO] init done (enabled={HAS_AUDIO})')

    def set_volume(self, vol):
        try:
            self.volume = int(max(0, min(100, int(vol))))
        except Exception:
            self.volume = 100
        if HAS_AUDIO:
            pygame.mixer.music.set_volume(self.volume / 100.0)
        print(f'[AUDIO] volume={self.volume}%')

    def enqueue(self, kind, content):
        with self.lock:
            self.queue.append((kind, content))

    def resolve_song(self, filename):
        name = str(filename or '').strip()
        if name.lower() != 'default':
            return name

        try:
            entries = os.listdir(self.songs_dir)
            candidates = sorted(
                f for f in entries
                if f.lower().endswith(('.mp3', '.ogg', '.wav', '.flac', '.m4a'))
            )
        except Exception as e:
            print(f'[AUDIO] list songs failed: {_safe_text(e)}')
            return ''

        clean = [f for f in candidates if not any('\udc80' <= ch <= '\udcff' for ch in f)]
        return (clean or candidates)[0] if candidates else ''

    def _wait_until_finished(self):
        while pygame.mixer.music.get_busy():
            if self.stop_flag.is_set():
                pygame.mixer.music.stop()
                break
            time.sleep(0.1)

    def _play_file(self, filename):
        if not HAS_AUDIO:
            return
        filename = self.resolve_song(filename)
        if not filename:
            print(f'[AUDIO] no song available in: {self.songs_dir}')
            return
        path = os.path.join(self.songs_dir, filename)
        if not os.path.exists(path):
            print(f'[AUDIO] file not found: {_safe_text(path)}')
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self.volume / 100.0)
            pygame.mixer.music.play()
            self._wait_until_finished()
        except Exception as e:
            print(f'[AUDIO] path playback failed: {_safe_text(e)}')
            try:
                namehint = os.path.splitext(filename)[1].lstrip('.').lower()
                with open(path, 'rb') as fh:
                    pygame.mixer.music.load(fh, namehint)
                    pygame.mixer.music.set_volume(self.volume / 100.0)
                    pygame.mixer.music.play()
                    self._wait_until_finished()
            except Exception as fallback_exc:
                print(f'[AUDIO] playback error: {_safe_text(fallback_exc)}')

    def _tts(self, text):
        try:
            import pyttsx3  # type: ignore[import-not-found]
            with self.tts_lock:
                if self.tts_engine is None:
                    self.tts_engine = pyttsx3.init()
                    self.tts_engine.setProperty('rate', 150)
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
        except Exception as e:
            print(f'[AUDIO] tts error: {_safe_text(e)}')

    def _run(self):
        while not self.stop_event.is_set():
            task = None
            with self.lock:
                if self.queue:
                    task = self.queue.pop(0)
            if task:
                self.stop_flag.clear()
                kind, content = task
                if kind == 'song':
                    self._play_file(content)
                elif kind == 'tts':
                    self._tts(content)
            else:
                time.sleep(0.1)

    def clear(self):
        self.stop_flag.set()
        with self.lock:
            self.queue.clear()


if __name__ == '__main__':
    print('=== audio test ===')

    audio = Audio()
    audio.start()

    print('test tts...')
    audio.enqueue('tts', 'Hello, this is a test')
    time.sleep(3)

    audio.stop()
    print('test done')
