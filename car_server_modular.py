#!/usr/bin/env python3
import sys, os, asyncio, json, argparse, threading, time, logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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

MSG_VIDEO = 0x01
MSG_COMMAND = 0x02
MSG_ENV = 0x03


def _clamp_int(value: Any, min_v: int, max_v: int, default: int) -> int:
    try:
        return int(max(min_v, min(max_v, int(value))))
    except Exception:
        return int(default)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return False


@dataclass
class CommandPacket:
    action: str = 'stop'
    servo_angle: int = 90
    servo_angle2: int = 90
    speed: int = 80
    left_speed: int = 80
    right_speed: int = 80
    detecting: bool = False
    play_song: str = ''
    stop_audio: bool = False

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]):
        if not isinstance(payload, dict):
            return cls()
        speed = _clamp_int(payload.get('speed', 80), 0, 255, 80)
        return cls(
            action=str(payload.get('action', 'stop') or 'stop'),
            servo_angle=_clamp_int(payload.get('servo_angle', 90), 0, 180, 90),
            servo_angle2=_clamp_int(payload.get('servo_angle2', 90), 0, 180, 90),
            speed=speed,
            left_speed=_clamp_int(payload.get('left_speed', speed), 0, 255, speed),
            right_speed=_clamp_int(payload.get('right_speed', speed), 0, 255, speed),
            detecting=_as_bool(payload.get('detecting', False)),
            play_song=str(payload.get('play_song', '') or '').strip(),
            stop_audio=_as_bool(payload.get('stop_audio', False)),
        )


@dataclass
class ImuPacket:
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    yaw_rate: float = 0.0    # gyro Z (deg/s)，用于速率闭环
    healthy: bool = False
    calibrated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'roll': self.roll,
            'pitch': self.pitch,
            'yaw': self.yaw,
            'yaw_rate': self.yaw_rate,
            'healthy': self.healthy,
            'calibrated': self.calibrated,
        }


@dataclass
class EnvPacket:
    light: int
    light_lux: int
    temp_c: float
    smoke: int
    volume: int
    crying: bool
    cry_score: int
    dist_cm: float
    track: List[int]
    alarm: str
    imu: Optional[ImuPacket]
    fps: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'light': self.light,
            'light_lux': self.light_lux,
            'temp_c': self.temp_c,
            'smoke': self.smoke,
            'volume': self.volume,
            'crying': self.crying,
            'cry_score': self.cry_score,
            'dist_cm': self.dist_cm,
            'track': self.track,
            'alarm': self.alarm,
            'imu': self.imu.to_dict() if self.imu else None,
            'fps': self.fps,
        }


class CryingDetector:
    def __init__(
        self,
        on_threshold=72,
        off_threshold=58,
        on_frames=3,
        off_frames=4,
        alpha=0.35,
        baseline_alpha=0.06,
        margin_on=18,
        margin_off=10,
        warmup_frames=8,
    ):
        self.on_threshold = int(max(0, min(100, int(on_threshold))))
        self.off_threshold = int(max(0, min(100, int(off_threshold))))
        if self.off_threshold > self.on_threshold:
            self.off_threshold = self.on_threshold
        self.on_frames = int(max(1, int(on_frames)))
        self.off_frames = int(max(1, int(off_frames)))
        self.alpha = float(max(0.01, min(1.0, float(alpha))))
        self.baseline_alpha = float(max(0.001, min(0.5, float(baseline_alpha))))
        self.margin_on = int(max(1, min(60, int(margin_on))))
        self.margin_off = int(max(1, min(60, int(margin_off))))
        self.warmup_frames = int(max(0, int(warmup_frames)))

        self.smooth = None
        self.baseline = None
        self.crying = False
        self.on_count = 0
        self.off_count = 0
        self.frame_count = 0

    def _thresholds(self) -> Tuple[int, int]:
        if self.baseline is None:
            return self.on_threshold, self.off_threshold
        base = int(round(self.baseline))
        dyn_on = max(self.on_threshold, min(100, base + self.margin_on))
        dyn_off = max(self.off_threshold, min(dyn_on, base + self.margin_off))
        return dyn_on, dyn_off

    def update(self, volume: int) -> Tuple[bool, int]:
        v = int(max(0, min(100, int(volume))))
        if self.smooth is None:
            self.smooth = float(v)
        else:
            self.smooth += (v - self.smooth) * self.alpha

        if self.baseline is None:
            self.baseline = float(v)
        else:
            self.baseline += (v - self.baseline) * self.baseline_alpha

        self.frame_count += 1
        on_th, off_th = self._thresholds()
        delta = max(0.0, self.smooth - (self.baseline or self.smooth))

        # Let baseline settle before enabling cry decisions.
        if self.frame_count > self.warmup_frames:
            if not self.crying:
                if self.smooth >= on_th and delta >= self.margin_on:
                    self.on_count += 1
                else:
                    self.on_count = 0
                if self.on_count >= self.on_frames:
                    self.crying = True
                    self.off_count = 0
            else:
                if self.smooth <= off_th or delta <= self.margin_off:
                    self.off_count += 1
                else:
                    self.off_count = 0
                if self.off_count >= self.off_frames:
                    self.crying = False
                    self.on_count = 0
        else:
            self.crying = False
            self.on_count = 0
            self.off_count = 0

        if delta <= self.margin_off:
            score = 0
        else:
            den = max(1.0, float(self.margin_on - self.margin_off))
            score = int(max(0.0, min(100.0, (delta - self.margin_off) * 100.0 / den)))

        return self.crying, score


class CarServer:
    def __init__(self, asr_url=None, mic_health_timeout=2.0):
        self.ultrasonic = Ultrasonic()
        self.pcf8591 = PCF8591()
        self.infrared = Infrared()
        self.camera = Camera(
            width=int(os.getenv('RASPBOT_WS_WIDTH', '640')),
            height=int(os.getenv('RASPBOT_WS_HEIGHT', '480')),
            quality=int(os.getenv('RASPBOT_WS_JPEG_QUALITY', '80')),
            framerate=int(os.getenv('RASPBOT_CAMERA_FPS', '20')),
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
        self.crying_detector = CryingDetector(
            on_threshold=int(os.getenv('CRY_ON_THRESHOLD', '72')),
            off_threshold=int(os.getenv('CRY_OFF_THRESHOLD', '58')),
            on_frames=int(os.getenv('CRY_ON_FRAMES', '3')),
            off_frames=int(os.getenv('CRY_OFF_FRAMES', '4')),
            alpha=float(os.getenv('CRY_EMA_ALPHA', '0.35')),
            baseline_alpha=float(os.getenv('CRY_BASELINE_ALPHA', '0.06')),
            margin_on=int(os.getenv('CRY_MARGIN_ON', '18')),
            margin_off=int(os.getenv('CRY_MARGIN_OFF', '10')),
            warmup_frames=int(os.getenv('CRY_WARMUP_FRAMES', '8')),
        )
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

        self.env_update_interval = float(os.getenv('RASPBOT_ENV_INTERVAL_SEC', '0.5'))
        self.env_debug_interval = float(os.getenv('RASPBOT_ENV_DEBUG_INTERVAL_SEC', '5.0'))
        self._last_env_debug_log_ts = 0.0
        self._env_lock = threading.Lock()
        self._latest_env = EnvPacket(
            light=0,
            light_lux=0,
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

    def _sample_env_packet(self):
        env = self.pcf8591.get_data()
        dist = self.ultrasonic.get_distance()
        track = self.infrared.get_data().get('track', [1, 1, 1, 1])
        volume = int(env.get('volume', 0))
        crying, cry_score = self.crying_detector.update(volume)
        imu_data = self.imu.get_data() if self.imu.enabled else {}
        imu_payload = None
        if imu_data:
            gyro = imu_data.get('gyro_dps', [0.0, 0.0, 0.0])
            imu_payload = ImuPacket(
                roll=float(imu_data.get('roll', 0.0)),
                pitch=float(imu_data.get('pitch', 0.0)),
                yaw=float(imu_data.get('yaw', 0.0)),
                yaw_rate=float(gyro[2]) if len(gyro) > 2 else 0.0,
                healthy=bool(imu_data.get('healthy', False)),
                calibrated=bool(imu_data.get('calibrated', False)),
            )
        alarms = []
        if env.get('smoke_alarm'):
            alarms.append('smoke')
        if crying and cry_score >= self.cry_alarm_score_min:
            alarms.append('cry')
        alarm = '+'.join(alarms)
        return EnvPacket(
            light=int(env.get('light', 0)),
            light_lux=int(env.get('light_lux', 0)),
            temp_c=float(env.get('temp_c', 0.0)),
            smoke=int(env.get('smoke', 0)),
            volume=volume,
            crying=crying,
            cry_score=cry_score,
            dist_cm=round(float(dist), 1),
            track=track,
            alarm=alarm,
            imu=imu_payload,
            fps=int(self.camera.get_fps()),
        )

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
        # Always home servos on startup so hardware state is deterministic.
        self.motor.stop()
        self.motor.center_servos(90, 90, force=True)
        time.sleep(0.12)
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
        if not isinstance(cmd, CommandPacket):
            cmd = CommandPacket.from_dict(cmd)
        servo1 = cmd.servo_angle
        servo2 = cmd.servo_angle2
        speed = cmd.speed
        env_packet = self._get_latest_env()
        action = cmd.action
        song_cmd = str(cmd.play_song or '').strip()
        is_sensor_event = song_cmd.startswith('__sensor__')
        
        if song_cmd and not is_sensor_event:
            self.audio.enqueue('song', song_cmd)
        if cmd.stop_audio:
            self.audio.clear()
        
        dist = env_packet.dist_cm
        if action == 'forward' and dist < 30:
            print(f'[SAFE] block forward at dist={dist:.1f}cm (<30cm)')
            action = 'stop'
        self._mark_command_seen(action, speed, cmd.left_speed, cmd.right_speed)

        self.motor.set_servo(1, servo1)
        self.motor.set_servo(2, servo2)
        self.oled.set_pan(servo1)
        
        if action == 'forward':
            l = cmd.left_speed
            r = cmd.right_speed
            self.motor.forward(l, r)
        elif action == 'left':
            self.motor.left(speed)
        elif action == 'right':
            self.motor.right(speed)
        elif action == 'spin_left':
            self.motor.spin_left(speed)
        elif action == 'spin_right':
            self.motor.spin_right(speed)
        elif action == 'backward':
            self.motor.backward(speed)
        else:
            self.motor.stop()
        
        # OLED 表情状态映射
        if action in ('spin_left', 'spin_right'):
            self.oled.set_state('turning')
        elif cmd.detecting:
            self.oled.set_state('tracking')
        else:
            self.oled.set_state('idle')
        
        # 播放音乐时推送音乐事件；传感器查询编码走 sensor 事件
        if song_cmd and not is_sensor_event:
            song_name = os.path.splitext(os.path.basename(song_cmd))[0]
            self.oled.push_event('music', song_name, duration=3.0)
        elif is_sensor_event:
            parts = song_cmd.split('__')
            if len(parts) >= 4:
                self.oled.push_event(
                    'sensor',
                    {'label': parts[2], 'text': parts[3]},
                    duration=3.0,
                )
        
        self._sync_oled_alarm(env_packet)

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
        last_seq = -1
        
        async def send_video():
            nonlocal last_seq
            cam_fps = int(getattr(self.camera, 'framerate', 20) or 20)
            poll_interval = max(0.005, 1.0 / max(5, cam_fps))
            while True:
                seq, jpeg = self.camera.get_frame()
                if jpeg and seq != last_seq:
                    last_seq = seq
                    try:
                        await ws.send(bytes([MSG_VIDEO]) + jpeg)
                    except websockets.ConnectionClosed:
                        return
                # Match polling cadence with camera FPS to avoid busy looping.
                await asyncio.sleep(poll_interval)
        
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
        
        try:
            await asyncio.gather(send_video(), recv_commands(), send_env())
        except websockets.ConnectionClosed:
            pass
        finally:
            self.motor.stop()
            self.motor.center_servos(90, 90, force=True)
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
