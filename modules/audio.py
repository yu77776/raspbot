#!/usr/bin/env python3
"""音频播放模块"""
import os
import time
import threading

try:
    import pygame  # type: ignore[import-not-found]
    pygame.mixer.init()
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False

class Audio:
    def __init__(self, songs_dir='songs'):
        self.songs_dir = songs_dir
        self.queue = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stop_flag = threading.Event()
        self.tts_engine = None
        self.tts_lock = threading.Lock()
        self.thread = None
        self.started = False
        print(f'[AUDIO] 初始化完成 (enabled={HAS_AUDIO})')
    
    def set_volume(self, vol):
        if HAS_AUDIO:
            pygame.mixer.music.set_volume(vol / 100.0)

    def enqueue(self, kind, content):
        with self.lock:
            self.queue.append((kind, content))
    
    def _play_file(self, filename):
        if not HAS_AUDIO:
            return
        path = os.path.join(self.songs_dir, filename)
        if not os.path.exists(path):
            print(f'[AUDIO] 文件不存在: {path}')
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self.stop_flag.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.1)
        except Exception as e:
            print(f'[AUDIO] 播放错误: {e}')
    
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
            print(f'[AUDIO] TTS错误: {e}')
    
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
    
    def start(self):
        if self.started and self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.started = True
    
    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.started = False
    
    def clear(self):
        self.stop_flag.set()
        with self.lock:
            self.queue.clear()

if __name__ == '__main__':
    import sys
    print('=== 音频测试 ===')
    
    audio = Audio()
    audio.start()
    
    print('测试 TTS...')
    audio.enqueue('tts', 'Hello, this is a test')
    
    import time
    time.sleep(3)
    
    audio.stop()
    print('测试完成')
