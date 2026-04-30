#!/usr/bin/env python3
"""Microphone streaming module."""
import asyncio
import os
import subprocess
import re
import threading
import time

import websockets

from modules.base import ModuleBase


class MicStream(ModuleBase):
    join_timeout = 2.0

    def __init__(
        self,
        asr_url='ws://127.0.0.1:6006/audio',
        mic_device=None,
        sample_rate=16000,
        channels=1,
        chunk_ms=40,
        connect_timeout=5,
        max_backoff=8.0,
        health_timeout=2.0,
    ):
        self.asr_url = asr_url
        self.mic_device = mic_device or os.getenv('MIC_DEVICE', 'default')
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.chunk_ms = int(chunk_ms)
        self.chunk_bytes = max(320, int(self.sample_rate * self.channels * 2 * self.chunk_ms / 1000))
        self.connect_timeout = float(connect_timeout)
        self.max_backoff = float(max_backoff)
        self.health_timeout = float(health_timeout)

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.started = False
        self.last_ok_ts = 0.0
        self.connected = False
        self._capture_proc = None

        print(f'[MIC] init asr_url={self.asr_url} device={self.mic_device}')

    def _detect_capture_devices(self):
        usb_cards = []
        all_cards = []
        try:
            out = subprocess.check_output(['arecord', '-l'], stderr=subprocess.STDOUT, text=True)
            for line in out.splitlines():
                m = re.search(r'card\s+(\d+):', line)
                if not m:
                    continue
                dev = f'plughw:{m.group(1)},0'
                all_cards.append(dev)
                if 'USB' in line.upper():
                    usb_cards.append(dev)
        except Exception:
            return []

        devices = []
        for dev in usb_cards + all_cards:
            if dev not in devices:
                devices.append(dev)
        return devices

    def _candidate_devices(self):
        devices = [self.mic_device, 'default']
        devices.extend(self._detect_capture_devices())
        devices.append('plughw:1,0')

        out = []
        for dev in devices:
            if dev and dev not in out:
                out.append(dev)
        return out

    def _open_capture(self):
        errors = []
        for dev in self._candidate_devices():
            cmd = [
                'arecord',
                '-q',
                '-D', dev,
                '-f', 'S16_LE',
                '-r', str(self.sample_rate),
                '-c', str(self.channels),
                '-t', 'raw',
            ]
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except Exception as e:
                errors.append(f'{dev}: spawn fail: {e}')
                continue

            time.sleep(0.2)
            if proc.poll() is None:
                with self.lock:
                    self._capture_proc = proc
                return proc, dev

            err = ''
            try:
                err = (proc.stderr.read() or b'').decode('utf-8', errors='replace').strip()
            except Exception:
                pass
            errors.append(f'{dev}: {err or "open failed"}')

        raise RuntimeError('no available microphone device: ' + ' | '.join(errors))

    def _stop_capture(self):
        with self.lock:
            proc = self._capture_proc
            self._capture_proc = None

        if not proc:
            return

        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    async def _stream_once(self):
        proc, device = self._open_capture()
        print(f'[MIC] capture ready device={device}')

        try:
            async with websockets.connect(
                self.asr_url,
                open_timeout=self.connect_timeout,
                ping_interval=20,
                ping_timeout=10,
                max_size=None,
            ) as ws:
                print(f'[MIC] connected {self.asr_url}')
                with self.lock:
                    self.connected = True

                while not self.stop_event.is_set():
                    chunk = await asyncio.to_thread(proc.stdout.read, self.chunk_bytes)
                    if not chunk:
                        raise RuntimeError('audio stream closed')
                    await ws.send(chunk)
                    with self.lock:
                        self.last_ok_ts = time.time()
        finally:
            with self.lock:
                self.connected = False
            self._stop_capture()

    async def _run_async(self):
        backoff = 0.5
        while not self.stop_event.is_set():
            try:
                await self._stream_once()
                backoff = 0.5
            except Exception as e:
                if self.stop_event.is_set():
                    break
                print(f'[MIC] disconnected: {e}')
                print(f'[MIC] reconnect in {backoff:.1f}s')
                await asyncio.sleep(backoff)
                backoff = min(self.max_backoff, backoff * 2)

        print('[MIC] stream loop stopped')

    def _run(self):
        try:
            asyncio.run(self._run_async())
        except Exception as e:
            print(f'[MIC] fatal loop error: {e}')

    def _before_stop(self):
        self._stop_capture()

    def get_last_ok_ts(self):
        with self.lock:
            return self.last_ok_ts

    def is_healthy(self, timeout_s=None):
        timeout_s = self.health_timeout if timeout_s is None else float(timeout_s)
        with self.lock:
            last_ok = self.last_ok_ts
        if last_ok <= 0:
            return False
        return (time.time() - last_ok) <= timeout_s
