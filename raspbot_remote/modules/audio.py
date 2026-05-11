#!/usr/bin/env python3
"""Audio playback module."""

import asyncio
import os
import hashlib
import re
import shutil
import random
import tempfile
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
    pygame = None

try:
    import edge_tts  # type: ignore[import-not-found]
    HAS_TTS = True
    _TTS_DRIVER = 'edge-tts'
except ImportError:
    HAS_TTS = False
    _TTS_DRIVER = 'unavailable'

_CJK_RE = re.compile(r'[一-鿿㐀-䶿豈-﫿]')
_ZH_VOICE = 'zh-CN-XiaoxiaoNeural'
_EN_VOICE = 'en-US-JennyNeural'


def _safe_text(value):
    return str(value)


def _decode_escaped(text: str) -> str:
    """Ensure text is proper Unicode — decode \\uXXXX escapes if present."""
    t = str(text)
    if '\\u' in t:
        try:
            decoded = t.encode('ascii').decode('unicode_escape')
            # unicode_escape is greedy; only accept if the result contains plausible CJK/non-ASCII
            if any(ord(c) > 127 for c in decoded):
                return decoded
        except Exception:
            pass
    return t


class Audio(ModuleBase):
    join_timeout = 1.0

    def __init__(self, songs_dir='songs'):
        self.songs_dir = songs_dir
        self.queue = []
        self.volume = 100
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stop_flag = threading.Event()
        self.tts_lock = threading.Lock()
        self.cache_dir = os.path.join('/tmp', 'raspbot_audio_cache')
        self._playlist = []
        self._playlist_index = -1
        self.thread = None
        self.started = False
        logger.info('init done (audio=%s tts=%s driver=%s)', HAS_AUDIO, HAS_TTS, _TTS_DRIVER)

    def set_volume(self, vol):
        try:
            v = int(max(0, min(100, int(vol))))
        except Exception:
            v = 100
        with self.lock:
            self.volume = v
        if HAS_AUDIO:
            pygame.mixer.music.set_volume(v / 100.0)
        logger.info('volume=%s%%', v)

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

        playlist = self._ensure_playlist()
        if not playlist:
            return ''

        with self.lock:
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
                return ''  # reject unknown names — prevent path traversal

            if self._playlist_index < 0 or self._playlist_index >= len(playlist):
                self._playlist_index = 0
            return playlist[self._playlist_index]

    def _ensure_playlist(self):
        """Return cached playlist, rescanning only on first call or explicit refresh.

        Scanning is done outside the lock because os.listdir may block on
        network mounts.
        """
        # Fast path: playlist already populated.
        with self.lock:
            if self._playlist:
                return list(self._playlist)

        new_list = self._scan_songs()
        with self.lock:
            if not self._playlist:
                self._playlist = new_list
                if self._playlist_index >= len(self._playlist):
                    self._playlist_index = -1
            return list(self._playlist)

    def _scan_songs(self):
        """Return a sorted list of playable files in songs_dir. Pure, no side effects."""
        try:
            entries = os.listdir(self.songs_dir)
            return sorted(
                f for f in entries
                if f.lower().endswith(('.mp3', '.ogg', '.wav', '.flac', '.m4a'))
            )
        except Exception as e:
            logger.warning('list songs failed: %s', _safe_text(e))
            return []

    def refresh_playlist(self):
        """Force rescan of songs directory. Call after syncing new files."""
        new_list = self._scan_songs()
        with self.lock:
            self._playlist = new_list
            if self._playlist_index >= len(self._playlist):
                self._playlist_index = -1
            return list(self._playlist)

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
        # Defend against path traversal: ensure resolved path stays within songs_dir.
        real_songs = os.path.realpath(self.songs_dir)
        real_path = os.path.realpath(path)
        if not real_path.startswith(real_songs + os.sep) and real_path != real_songs:
            logger.warning('path traversal blocked: %s', _safe_text(filename))
            return
        if not os.path.exists(path):
            logger.warning('file not found: %s', _safe_text(path))
            return
        play_path = self._ascii_playback_path(path)
        with self.lock:
            vol = self.volume
        try:
            logger.info('play file=%s via=%s volume=%s%%', _safe_text(filename), _safe_text(play_path), vol)
            pygame.mixer.music.load(play_path)
            pygame.mixer.music.set_volume(vol / 100.0)
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
            self._prune_cache()
        return cache_path

    def _prune_cache(self, max_files: int = 50):
        """Remove oldest cache entries when the cache exceeds *max_files*."""
        try:
            entries = []
            for name in os.listdir(self.cache_dir):
                full = os.path.join(self.cache_dir, name)
                if os.path.isfile(full) and name.startswith('song_'):
                    entries.append((os.path.getmtime(full), full))
            if len(entries) <= max_files:
                return
            entries.sort()
            for _, full in entries[:len(entries) - max_files]:
                try:
                    os.unlink(full)
                except OSError:
                    pass
        except Exception as exc:
            logger.warning('cache prune error: %s', exc)

    def _tts(self, text):
        if not HAS_TTS:
            logger.warning('tts skipped (edge-tts unavailable): %s', _safe_text(text[:80]))
            return
        text = _decode_escaped(text)
        voice = _ZH_VOICE if _CJK_RE.search(text) else _EN_VOICE
        tmp_path = os.path.join(tempfile.gettempdir(), f'raspbot_tts_{threading.get_ident()}.mp3')
        try:
            logger.info('tts start voice=%s: %s', voice, _safe_text(text[:80]))
            with self.tts_lock:
                async def _synth():
                    communicate = edge_tts.Communicate(text, voice)
                    await communicate.save(tmp_path)
                asyncio.run(_synth())
                if HAS_AUDIO:
                    pygame.mixer.music.load(tmp_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.05)
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            logger.info('tts done')
        except Exception as e:
            logger.warning('tts error: %s', _safe_text(e))
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

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
        with self.tts_lock:
            if HAS_AUDIO:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass


if __name__ == '__main__':
    print('=== audio test ===')

    audio = Audio()
    audio.start()

    print('test tts...')
    audio.enqueue('tts', 'Hello, this is a test')
    time.sleep(3)

    audio.stop()
    print('test done')
