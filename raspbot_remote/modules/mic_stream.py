#!/usr/bin/env python3
"""Microphone streaming module."""
import asyncio
import os
import subprocess
import re
import threading
import time

import websockets

from logger_setup import setup_logger
from modules.base import ModuleBase

logger = setup_logger('raspbot.mic')


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
        read_timeout=None,
        send_timeout=None,
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
        self.read_timeout = float(
            read_timeout
            if read_timeout is not None
            else os.getenv('MIC_READ_TIMEOUT_SEC', '1.5')
        )
        self.send_timeout = float(
            send_timeout
            if send_timeout is not None
            else os.getenv('MIC_SEND_TIMEOUT_SEC', '2.0')
        )

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.started = False
        self.last_ok_ts = 0.0
        self.last_capture_ok_ts = 0.0
        self.connected = False
        self._capture_proc = None

        logger.info(
            'init asr_url=%s device=%s chunk_bytes=%s read_timeout=%.1fs send_timeout=%.1fs',
            self.asr_url,
            self.mic_device,
            self.chunk_bytes,
            self.read_timeout,
            self.send_timeout,
        )

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
        candidates = self._candidate_devices()
        logger.info('candidate devices: %s', ', '.join(candidates))
        for dev in candidates:
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

    async def _read_chunk(self, proc, device):
        if proc.poll() is not None:
            raise RuntimeError(f'capture process exited rc={proc.returncode} device={device}')
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(proc.stdout.read, self.chunk_bytes),
                timeout=self.read_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                'audio read timeout device=%s timeout=%.1fs -> restart capture',
                device,
                self.read_timeout,
            )
            self._stop_capture()
            raise RuntimeError(f'audio read timeout device={device}')

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
        logger.info('capture ready device=%s', device)
        with self.lock:
            self.last_capture_ok_ts = time.time()

        try:
            async with websockets.connect(
                self.asr_url,
                open_timeout=self.connect_timeout,
                ping_interval=20,
                ping_timeout=10,
                max_size=2 * 1024 * 1024,
            ) as ws:
                logger.info('connected %s', self.asr_url)
                with self.lock:
                    self.connected = True

                last_progress_log = 0.0
                while not self.stop_event.is_set():
                    chunk = await self._read_chunk(proc, device)
                    if not chunk:
                        raise RuntimeError('audio stream closed')
                    now = time.time()
                    with self.lock:
                        self.last_capture_ok_ts = now
                    try:
                        await asyncio.wait_for(ws.send(chunk), timeout=self.send_timeout)
                    except asyncio.TimeoutError:
                        logger.warning(
                            'audio send timeout device=%s timeout=%.1fs -> reconnect',
                            device,
                            self.send_timeout,
                        )
                        raise RuntimeError(f'audio send timeout device={device}')
                    with self.lock:
                        self.last_ok_ts = now
                    if now - last_progress_log >= 10.0:
                        last_progress_log = now
                        logger.info('streaming audio device=%s bytes=%s', device, len(chunk))
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
                with self.lock:
                    had_recent_stream = self.last_ok_ts > 0
                reconnect_delay = 0.5 if had_recent_stream else backoff
                logger.warning('disconnected: %s', e)
                logger.info('reconnect in %.1fs', reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                if had_recent_stream:
                    backoff = 0.5
                else:
                    backoff = min(self.max_backoff, backoff * 2)

        logger.info('stream loop stopped')

    def _run(self):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_async())
        except Exception as e:
            logger.error('fatal loop error: %s', e)
        finally:
            loop.close()

    def _before_stop(self):
        self._stop_capture()

    def get_last_ok_ts(self):
        with self.lock:
            return self.last_ok_ts

    def get_last_capture_ok_ts(self):
        with self.lock:
            return self.last_capture_ok_ts

    def capture_is_healthy(self, timeout_s=None):
        timeout_s = self.health_timeout if timeout_s is None else float(timeout_s)
        with self.lock:
            last_capture_ok = self.last_capture_ok_ts
        if last_capture_ok <= 0:
            return False
        return (time.time() - last_capture_ok) <= timeout_s

    def is_healthy(self, timeout_s=None):
        timeout_s = self.health_timeout if timeout_s is None else float(timeout_s)
        with self.lock:
            last_ok = self.last_ok_ts
        if last_ok <= 0:
            return False
        return (time.time() - last_ok) <= timeout_s
