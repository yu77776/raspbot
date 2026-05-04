#!/usr/bin/env python3
"""Audio playback module."""

import os
import hashlib
import shutil
import random
import threading
import time

from logger_setup import setup_logger
from protocol import PLAY_SONG_NEXT, PLAY_SONG_PREV, PLAY_SONG_RANDOM
from modules.base import ModuleBase

logger = setup_logger('raspbot.audio')

try:
    import pygame  # type: ignore[import-not-found]
    pygame.mixer.init()
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False


def _safe_text(value):
    return str(value).encode('ascii', errors='backslashreplace').decode('ascii')


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
        self.cache_dir = os.path.join('/tmp', 'raspbot_audio_cache')
        self._playlist = []
        self._playlist_index = -1
        self.thread = None
        self.started = False
        logger.info('init done (enabled=%s)', HAS_AUDIO)

    def set_volume(self, vol):
        try:
            self.volume = int(max(0, min(100, int(vol))))
        except Exception:
            self.volume = 100
        if HAS_AUDIO:
            pygame.mixer.music.set_volume(self.volume / 100.0)
        logger.info('volume=%s%%', self.volume)

    def enqueue(self, kind, content):
        with self.lock:
            self.queue.append((kind, content))

    def enqueue_song(self, song_cmd):
        filename = self.resolve_song(song_cmd)
        if not filename:
            return ''
        self.clear()
        self.enqueue('song', filename)
        return filename

    def resolve_song(self, filename):
        name = str(filename or '').strip()
        lower = name.lower()

        with self.lock:
            playlist = self._ensure_playlist()
            if not playlist:
                return ''

            if lower in {PLAY_SONG_NEXT, 'next'}:
                self._playlist_index = (self._playlist_index + 1) % len(playlist)
                return playlist[self._playlist_index]
            if lower in {PLAY_SONG_PREV, '__previous__', 'prev', 'previous'}:
                self._playlist_index = (self._playlist_index - 1) % len(playlist)
                return playlist[self._playlist_index]
            if lower in {PLAY_SONG_RANDOM, 'random'}:
                self._playlist_index = random.randrange(len(playlist))
                return playlist[self._playlist_index]
            if lower != 'default':
                if name in playlist:
                    self._playlist_index = playlist.index(name)
                return name

            if self._playlist_index < 0 or self._playlist_index >= len(playlist):
                self._playlist_index = 0
            return playlist[self._playlist_index]

    def _ensure_playlist(self):
        """Return cached playlist, rescanning only on first call or explicit refresh."""
        if self._playlist:
            return self._playlist
        return self._scan_songs()

    def _scan_songs(self):
        try:
            entries = os.listdir(self.songs_dir)
            candidates = sorted(
                f for f in entries
                if f.lower().endswith(('.mp3', '.ogg', '.wav', '.flac', '.m4a'))
            )
        except Exception as e:
            logger.warning('list songs failed: %s', _safe_text(e))
            return []

        self._playlist = candidates
        if self._playlist_index >= len(self._playlist):
            self._playlist_index = -1
        return self._playlist

    def refresh_playlist(self):
        """Force rescan of songs directory. Call after syncing new files."""
        with self.lock:
            self._playlist = []
            return self._scan_songs()

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
            logger.warning('no song available in: %s', self.songs_dir)
            return
        path = os.path.join(self.songs_dir, filename)
        if not os.path.exists(path):
            logger.warning('file not found: %s', _safe_text(path))
            return
        play_path = self._ascii_playback_path(path)
        try:
            logger.info('play file=%s via=%s volume=%s%%', _safe_text(filename), _safe_text(play_path), self.volume)
            pygame.mixer.music.load(play_path)
            pygame.mixer.music.set_volume(self.volume / 100.0)
            pygame.mixer.music.play()
            self._wait_until_finished()
        except Exception as e:
            logger.warning('path playback failed: %s', _safe_text(e))
            try:
                namehint = os.path.splitext(filename)[1].lstrip('.').lower()
                with open(play_path, 'rb') as fh:
                    pygame.mixer.music.load(fh, namehint)
                    pygame.mixer.music.set_volume(self.volume / 100.0)
                    pygame.mixer.music.play()
                    self._wait_until_finished()
            except Exception as fallback_exc:
                logger.error('playback error: %s', _safe_text(fallback_exc))

    def _ascii_playback_path(self, path):
        try:
            path.encode('ascii')
            return path
        except UnicodeEncodeError:
            pass

        os.makedirs(self.cache_dir, exist_ok=True)
        ext = os.path.splitext(path)[1].lower() or '.audio'
        stat = os.stat(path)
        digest = hashlib.sha1(
            os.fsencode(path) + str((stat.st_size, int(stat.st_mtime))).encode('ascii')
        ).hexdigest()[:16]
        cache_name = f'song_{digest}{ext}'
        cache_path = os.path.join(self.cache_dir, cache_name)
        if not os.path.exists(cache_path) or os.path.getsize(cache_path) != stat.st_size:
            shutil.copyfile(path, cache_path)
        return cache_path

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
            logger.warning('tts error: %s', _safe_text(e))

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
