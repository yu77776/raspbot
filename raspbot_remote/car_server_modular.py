#!/usr/bin/env python3
import sys, os, asyncio, json, argparse, threading, time, logging
from typing import Optional, Tuple
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from protocol import (
    MSG_COMMAND,
    MSG_ENV,
    MSG_VIDEO,
    CommandPacket,
    EnvPacket,
    as_bool,
)
from command_executor import CommandExecutor
from env_sampler import EnvSampler
from modules.ultrasonic import Ultrasonic
from modules.pcf8591 import PCF8591
from modules.infrared import Infrared
from modules.camera import Camera
from modules.motor import Motor
from modules.audio import Audio
from modules.oled_face import FaceEngine
from modules.mic_stream import MicStream
from modules.mpu6050 import MPU6050
import websockets

logging.getLogger('websockets.server').setLevel(logging.CRITICAL)
logging.getLogger('websockets.asyncio.server').setLevel(logging.CRITICAL)


class CarServer:
    def __init__(self, asr_url=None, mic_health_timeout=2.0):
        self.ultrasonic = Ultrasonic()
        self.pcf8591 = PCF8591()
        self.infrared = Infrared()
        self.camera = Camera(
            width=int(os.getenv('RASPBOT_WS_WIDTH', '640')),
            height=int(os.getenv('RASPBOT_WS_HEIGHT', '480')),
            quality=int(os.getenv('RASPBOT_WS_JPEG_QUALITY', '80')),
            framerate=int(os.getenv('RASPBOT_CAMERA_FPS', '30')),
        )
        self.motor = Motor()
        self.audio = Audio(songs_dir=os.path.join(os.path.dirname(__file__), 'songs'))
        self.oled = FaceEngine()
        self.imu = MPU6050(addr=0x68, sample_hz=100, beta=0.08, auto_calibrate=True)
        resolved_asr = str(asr_url or '').strip()
        self.mic_auto_mode = resolved_asr.lower() == 'auto'
        mic_init_url = 'ws://127.0.0.1:6006/audio' if self.mic_auto_mode else resolved_asr
        self.mic_stream = MicStream(asr_url=mic_init_url)
        self.mic_health_timeout = float(mic_health_timeout)
        self.mic_enabled = resolved_asr.lower() not in {'', 'off', 'none', 'disabled'}
        self.cry_alarm_score_min = int(max(0, min(100, int(os.getenv('CRY_ALARM_SCORE_MIN', '60')))))
        self.stop_event = threading.Event()
        self.oled_thread = None
        self.mic_watchdog_thread = None
        self.command_watchdog_thread = None
        self.mic_fail_safe_active = False
        self.manual_override_until = 0.0
        self.manual_override_sec = float(os.getenv('RASPBOT_MANUAL_OVERRIDE_SEC', '1.2'))
        self.command_timeout_sec = float(os.getenv('RASPBOT_COMMAND_TIMEOUT_SEC', '0.8'))
        self._command_lock = threading.Lock()
        self._last_command_time = 0.0
        self._last_motion_command_active = False
        self.home_servos_on_startup = as_bool(os.getenv('RASPBOT_HOME_SERVOS_ON_STARTUP', '0'))
        self.env_update_interval = float(os.getenv('RASPBOT_ENV_INTERVAL_SEC', '0.5'))
        self.env_debug_interval = float(os.getenv('RASPBOT_ENV_DEBUG_INTERVAL_SEC', '0'))
        self._last_env_debug_log_ts = 0.0
        self._env_lock = threading.Lock()
        self._remote_cry_lock = threading.Lock()
        self._remote_crying: Optional[bool] = None
        self._remote_cry_score: Optional[int] = None
        self._remote_alarm: Optional[str] = None
        self._latest_env = EnvPacket(
            light=0,
            light_lux=0,
            temp_raw=0,
            temp_c=0.0,
            smoke=0,
            volume=0,
            crying=False,
            cry_score=0,
            dist_cm=999.0,
            track=[1, 1, 1, 1],
            alarm='',
            imu=None,
            fps=0,
        )
        self.env_thread = None
        self.env_sampler = EnvSampler(
            self.pcf8591,
            self.ultrasonic,
            self.infrared,
            self.imu,
            self.camera,
            self.audio,
            cry_alarm_score_min=self.cry_alarm_score_min,
            remote_cry_provider=self._get_remote_cry_state,
            knob_volume_enabled=as_bool(os.getenv('RASPBOT_KNOB_VOLUME_ENABLED', '1')),
            knob_volume_deadband=int(max(0, min(20, int(os.getenv('RASPBOT_KNOB_VOLUME_DEADBAND', '3'))))),
            knob_volume_after_app_grace_sec=float(os.getenv('RASPBOT_KNOB_VOLUME_APP_GRACE_SEC', '1.5')),
        )
        self.command_executor = CommandExecutor(
            motor=self.motor,
            audio=self.audio,
            oled=self.oled,
            env_provider=self._get_latest_env,
            mark_command_seen=self._mark_command_seen,
            set_remote_cry_state=self._set_remote_cry_state,
            note_app_audio_volume=self.env_sampler.note_app_audio_volume,
            sync_oled_alarm=self._sync_oled_alarm,
        )

    def _set_remote_cry_state(self, cmd: CommandPacket):
        if cmd.remote_crying is None and cmd.remote_cry_score is None and cmd.remote_alarm is None:
            return
        with self._remote_cry_lock:
            self._remote_crying = cmd.remote_crying
            self._remote_cry_score = cmd.remote_cry_score
            self._remote_alarm = cmd.remote_alarm

    def _get_remote_cry_state(self) -> Tuple[Optional[bool], Optional[int], Optional[str]]:
        with self._remote_cry_lock:
            return self._remote_crying, self._remote_cry_score, self._remote_alarm

    def _sample_env_packet(self):
        return self.env_sampler.sample()

    def _refresh_env_cache(self):
        env_packet = self._sample_env_packet()
        with self._env_lock:
            self._latest_env = env_packet
        return env_packet

    def _get_latest_env(self):
        with self._env_lock:
            return self._latest_env

    def _oled_alarm_text(self, env_packet: EnvPacket) -> str:
        alarm = str(env_packet.alarm or '').lower()
        if 'smoke' in alarm:
            return f'SMOKE {env_packet.smoke}'
        if 'cry' in alarm:
            return 'BABY CRY'
        return ''

    def _sync_oled_alarm(self, env_packet: EnvPacket) -> None:
        self.oled.set_alarm(self._oled_alarm_text(env_packet))

    def _start_env_cache_loop(self):
        def updater():
            while not self.stop_event.is_set():
                try:
                    self._refresh_env_cache()
                except Exception as e:
                    print(f'[ENV] update error: {e}')
                time.sleep(self.env_update_interval)

        self.env_thread = threading.Thread(target=updater, daemon=True)
        self.env_thread.start()

    def _update_oled_loop(self):
        def update():
            while not self.stop_event.is_set():
                try:
                    env = self._get_latest_env()
                    self.oled.set_env_data({
                        "temp_c": env.temp_c,
                        "light_lux": env.light_lux,
                        "smoke": env.smoke,
                        "volume": env.volume,
                        "dist_cm": env.dist_cm,
                    })
                    self._sync_oled_alarm(env)
                except Exception as e:
                    print(f'[OLED] update error: {e}')
                time.sleep(0.5)

        self.oled_thread = threading.Thread(target=update, daemon=True)
        self.oled_thread.start()

    def _start_mic_watchdog(self):
        def watchdog():
            while not self.stop_event.is_set():
                healthy = self.mic_stream.is_healthy(self.mic_health_timeout)
                if not healthy:
                    age = time.time() - self.mic_stream.get_last_ok_ts()
                    if not self.mic_fail_safe_active:
                        print(f'[SAFE] MIC unhealthy age={age:.2f}s timeout={self.mic_health_timeout:.2f}s -> motor.stop()')
                        self.motor.stop()
                        self.mic_fail_safe_active = True
                else:
                    if self.mic_fail_safe_active:
                        print('[SAFE] MIC recovered')
                    self.mic_fail_safe_active = False
                time.sleep(0.2)

        self.mic_watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        self.mic_watchdog_thread.start()

    def _mark_command_seen(self, action: str, speed: int, left_speed: int, right_speed: int):
        moving_actions = {'forward', 'backward', 'left', 'right', 'spin_left', 'spin_right'}
        motion_active = action in moving_actions and max(int(speed), int(left_speed), int(right_speed)) > 0
        with self._command_lock:
            self._last_command_time = time.monotonic()
            self._last_motion_command_active = motion_active

    def _start_command_watchdog(self):
        def watchdog():
            while not self.stop_event.is_set():
                should_stop = False
                age = 0.0
                with self._command_lock:
                    if self._last_motion_command_active and self.command_timeout_sec > 0:
                        age = time.monotonic() - self._last_command_time
                        if age >= self.command_timeout_sec:
                            self._last_motion_command_active = False
                            should_stop = True

                if should_stop:
                    print(f'[SAFE] command timeout age={age:.2f}s timeout={self.command_timeout_sec:.2f}s -> motor.stop()')
                    self.motor.stop()
                time.sleep(0.1)

        self.command_watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        self.command_watchdog_thread.start()

    def _start_mic_pipeline(self, asr_url=None):
        if not self.mic_enabled:
            return
        if asr_url:
            self.mic_stream.asr_url = asr_url
        if not self.mic_stream.started:
            self.mic_stream.start()
        if not self.mic_watchdog_thread or not self.mic_watchdog_thread.is_alive():
            self._start_mic_watchdog()

    def start_all(self):
        self.stop_event.clear()
        self.motor.stop()
        if self.home_servos_on_startup:
            self.motor.center_servos(90, 90, force=True)
            time.sleep(0.12)
        else:
            print('[MOTOR] startup servo homing disabled')
        self.ultrasonic.start()
        self.pcf8591.start()
        self.infrared.start()
        self.imu.start()
        self.camera.start()
        self.audio.start()
        self.oled.start()
        if self.mic_enabled:
            if self.mic_auto_mode:
                print('[MIC] auto mode: waiting for PC websocket client to resolve ASR url')
            else:
                self._start_mic_pipeline()
        else:
            print('[MIC] disabled')

        self._refresh_env_cache()
        self._start_env_cache_loop()
        self._update_oled_loop()
        self._start_command_watchdog()
        print(f'[SYS] all modules started (asr_url={self.mic_stream.asr_url}, mic_timeout={self.mic_health_timeout}s)')

    def stop_all(self):
        self.stop_event.set()
        if self.command_watchdog_thread and self.command_watchdog_thread.is_alive():
            self.command_watchdog_thread.join(timeout=1.0)
        if self.mic_watchdog_thread and self.mic_watchdog_thread.is_alive():
            self.mic_watchdog_thread.join(timeout=1.0)
        if self.oled_thread and self.oled_thread.is_alive():
            self.oled_thread.join(timeout=1.0)
        if self.env_thread and self.env_thread.is_alive():
            self.env_thread.join(timeout=1.0)

        if self.mic_enabled:
            self.mic_stream.stop()
        self.imu.stop()
        self.ultrasonic.stop()
        self.pcf8591.stop()
        self.infrared.stop()
        self.camera.stop()
        self.audio.stop()
        self.oled.stop()
    
    def execute_command(self, cmd: CommandPacket):
        self.command_executor.execute(cmd)

    async def handle_client(self, ws):
        addr = ws.remote_address
        print(f'[WS] connected: {addr}')
        if self.mic_enabled and self.mic_auto_mode:
            peer_ip = addr[0] if isinstance(addr, tuple) and len(addr) >= 1 else None
            if peer_ip:
                asr_port = os.getenv('RASPBOT_ASR_PORT', '6006')
                asr_path = os.getenv('RASPBOT_ASR_PATH', '/audio')
                if not asr_path.startswith('/'):
                    asr_path = '/' + asr_path
                auto_url = f'ws://{peer_ip}:{asr_port}{asr_path}'
                if self.mic_stream.asr_url != auto_url and self.mic_stream.started:
                    print(f'[MIC] PC changed, restart mic stream: {self.mic_stream.asr_url} -> {auto_url}')
                    self.mic_stream.stop()
                print(f'[MIC] auto ASR url from connected PC: {auto_url}')
                self._start_mic_pipeline(asr_url=auto_url)
            else:
                print('[MIC] auto mode failed: cannot parse client ip from websocket peer')

        async def recv_commands():
            async for msg in ws:
                try:
                    cmd_payload = None
                    if isinstance(msg, bytes) and len(msg) > 1 and msg[0] == MSG_COMMAND:
                        cmd_payload = json.loads(msg[1:].decode('utf-8'))
                    elif isinstance(msg, str):
                        cmd_payload = json.loads(msg)
                    if cmd_payload is not None:
                        source = str(cmd_payload.get('source', '') or '').strip().lower() \
                            if isinstance(cmd_payload, dict) else ''
                        is_app_source = source == 'app'
                        now = time.monotonic()
                        if is_app_source:
                            self.manual_override_until = now + self.manual_override_sec
                        elif now < self.manual_override_until:
                            # During manual override window, ignore non-app commands
                            # to prevent APP servo/manual control from being overwritten.
                            continue
                        self.execute_command(CommandPacket.from_dict(cmd_payload))
                except Exception as e:
                    print(f'[WS] command error: {e}')
        
        async def send_env():
            while True:
                env_packet = self._get_latest_env()
                payload = bytes([MSG_ENV]) + json.dumps(env_packet.to_dict()).encode('utf-8')
                
                try:
                    await ws.send(payload)
                except websockets.ConnectionClosed:
                    return
                now = time.monotonic()
                if self.env_debug_interval > 0 and now - self._last_env_debug_log_ts >= self.env_debug_interval:
                    self._last_env_debug_log_ts = now
                    print(f"[ENV] T={env_packet.temp_c:.1f} L={env_packet.light_lux} S={env_packet.smoke}")
                await asyncio.sleep(self.env_update_interval)

        async def send_video():
            last_seq = -1
            last_change_t = time.monotonic()
            last_stale_log_t = 0.0
            while True:
                seq, jpeg = self.camera.get_frame()
                if not jpeg or seq == last_seq:
                    now = time.monotonic()
                    if now - last_change_t >= 2.0 and now - last_stale_log_t >= 2.0:
                        last_stale_log_t = now
                        print(f'[CAM] stale video stream seq={seq} has_jpeg={bool(jpeg)} fps={self.camera.get_fps()}')
                    await asyncio.sleep(0.01)
                    continue
                last_seq = seq
                last_change_t = time.monotonic()
                try:
                    await ws.send(bytes([MSG_VIDEO]) + jpeg)
                except websockets.ConnectionClosed:
                    return
                await asyncio.sleep(0)
        
        try:
            await asyncio.gather(recv_commands(), send_env(), send_video())
        except websockets.ConnectionClosed:
            pass
        finally:
            self.motor.stop()
            print(f'[WS] disconnected: {addr}')

def resolve_asr_url(cli_url):
    def _clean(v):
        return str(v or '').strip()

    cli_url = _clean(cli_url)
    if cli_url:
        if cli_url.lower() == 'auto':
            print('[MIC] use ASR auto mode from CLI')
            return 'auto'
        print(f'[MIC] use ASR from CLI: {cli_url}')
        return cli_url

    env_url = _clean(os.getenv('RASPBOT_ASR_URL') or os.getenv('ASR_WS_URL'))
    if env_url:
        if env_url.lower() == 'auto':
            print('[MIC] use ASR auto mode from env')
            return 'auto'
        print(f'[MIC] use ASR from env: {env_url}')
        return env_url

    pc_ip = _clean(os.getenv('RASPBOT_PC_IP') or os.getenv('ASR_HOST'))
    if pc_ip in {'0.0.0.0', '127.0.0.1', 'localhost'}:
        pc_ip = ''
    asr_port = _clean(os.getenv('RASPBOT_ASR_PORT') or '6006')
    asr_path = _clean(os.getenv('RASPBOT_ASR_PATH') or '/audio')
    if not asr_path.startswith('/'):
        asr_path = '/' + asr_path
    if pc_ip:
        auto_url = f'ws://{pc_ip}:{asr_port}{asr_path}'
        print(f'[MIC] auto ASR url from configured PC IP: {auto_url}')
        return auto_url

    print('[MIC] auto mode: ASR url will follow connected PC websocket client IP')
    return 'auto'


async def main(host, port, asr_url, mic_health_timeout):
    server = CarServer(
        asr_url=asr_url,
        mic_health_timeout=mic_health_timeout,
    )
    server.start_all()

    try:
        for _ in range(60):
            _, jpeg = server.camera.get_frame()
            if jpeg:
                break
            await asyncio.sleep(0.1)

        print(f'[WS] start ws://{host}:{port}')
        async with websockets.serve(
            server.handle_client, host, port,
            max_size=10*1024*1024, ping_interval=20, ping_timeout=10
        ):
            await asyncio.Future()
    finally:
        print('[SYS] stopping all modules')
        server.stop_all()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--host', default=os.getenv('RASPBOT_CAR_BIND', '0.0.0.0'))
    p.add_argument('--port', type=int, default=int(os.getenv('RASPBOT_CAR_PORT', '5001')))
    p.add_argument('--asr-url', default=os.getenv('RASPBOT_ASR_URL', None))
    p.add_argument('--mic-health-timeout', type=float, default=float(os.getenv('MIC_HEALTH_TIMEOUT', '2')))
    p.add_argument('--disable-mic-stream', action='store_true')
    args = p.parse_args()
    asr_url = '' if args.disable_mic_stream else resolve_asr_url(args.asr_url)
    asyncio.run(main(args.host, args.port, asr_url, args.mic_health_timeout))
