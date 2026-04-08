#!/usr/bin/env python3
import sys, os, asyncio, json, argparse, threading, time
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
from modules.video_srs_stream import VideoSrsStream
import websockets
from websockets.server import WebSocketServerProtocol

MSG_VIDEO = 0x01
MSG_COMMAND = 0x02
MSG_ENV = 0x03

class CarServer:
    def __init__(self, asr_url=None, mic_health_timeout=2.0, srs_url='', srs_bitrate=4_000_000):
        self.ultrasonic = Ultrasonic()
        self.pcf8591 = PCF8591()
        self.infrared = Infrared()
        self.camera = Camera(
            width=int(os.getenv('RASPBOT_WS_WIDTH', '640')),
            height=int(os.getenv('RASPBOT_WS_HEIGHT', '480')),
            quality=int(os.getenv('RASPBOT_WS_JPEG_QUALITY', '80')),
            stream_width=int(os.getenv('RASPBOT_SRS_WIDTH', '1280')),
            stream_height=int(os.getenv('RASPBOT_SRS_HEIGHT', '720')),
            framerate=int(os.getenv('RASPBOT_CAMERA_FPS', '20')),
        )
        self.motor = Motor()
        self.audio = Audio(songs_dir=os.path.join(os.path.dirname(__file__), 'songs'))
        self.oled = FaceEngine()
        self.imu = MPU6050(addr=0x68, sample_hz=100, beta=0.08, auto_calibrate=True)
        self.video_srs = VideoSrsStream(self.camera, rtmp_url=srs_url, bitrate=srs_bitrate)
        resolved_asr = str(asr_url or '').strip()
        self.mic_auto_mode = resolved_asr.lower() == 'auto'
        mic_init_url = 'ws://127.0.0.1:6006/audio' if self.mic_auto_mode else resolved_asr
        self.mic_stream = MicStream(asr_url=mic_init_url)
        self.mic_health_timeout = float(mic_health_timeout)
        self.mic_enabled = resolved_asr.lower() not in {'', 'off', 'none', 'disabled'}
        self.stop_event = threading.Event()
        self.oled_thread = None
        self.mic_watchdog_thread = None
        self.mic_fail_safe_active = False
    
    def _update_oled_loop(self):
        def update():
            while not self.stop_event.is_set():
                try:
                    env = self.pcf8591.get_data()
                    dist = self.ultrasonic.get_distance()
                    self.oled.set_env_data({"temp_c": env["temp_c"], "light_lux": env["light_lux"], "smoke": env["smoke"], "volume": env["volume"], "dist_cm": round(dist, 1)})
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
        self.ultrasonic.start()
        self.pcf8591.start()
        self.infrared.start()
        self.imu.start()
        self.camera.start()
        self.video_srs.start()
        self.audio.start()
        self.oled.start()
        if self.mic_enabled:
            if self.mic_auto_mode:
                print('[MIC] auto mode: waiting for PC websocket client to resolve ASR url')
            else:
                self._start_mic_pipeline()
        else:
            print('[MIC] disabled')
        self._update_oled_loop()
        print(f'[SYS] all modules started (asr_url={self.mic_stream.asr_url}, mic_timeout={self.mic_health_timeout}s)')

    def stop_all(self):
        self.stop_event.set()
        if self.mic_watchdog_thread and self.mic_watchdog_thread.is_alive():
            self.mic_watchdog_thread.join(timeout=1.0)
        if self.oled_thread and self.oled_thread.is_alive():
            self.oled_thread.join(timeout=1.0)

        if self.mic_enabled:
            self.mic_stream.stop()
        self.video_srs.stop()
        self.imu.stop()
        self.ultrasonic.stop()
        self.pcf8591.stop()
        self.infrared.stop()
        self.camera.stop()
        self.audio.stop()
        self.oled.stop()
    
    def execute_command(self, cmd):
        servo1 = int(max(0, min(180, cmd.get('servo_angle', 90))))
        servo2 = int(max(0, min(180, cmd.get('servo_angle2', 90))))
        speed = int(max(0, min(255, cmd.get('speed', 80))))
        env = self.pcf8591.get_data()
        volume = env.get("volume", 50)
        self.audio.set_volume(volume)
        action = cmd.get('action', 'stop')
        
        if cmd.get('play_song'):
            self.audio.enqueue('song', cmd['play_song'])
        if cmd.get('stop_audio'):
            self.audio.clear()
        
        dist = self.ultrasonic.get_distance()
        if action == 'forward' and dist < 15:
            print(f'[SAFE] block forward by ultrasonic dist={dist:.1f}cm')
            action = 'stop'
        
        self.motor.set_servo(1, servo1)
        self.motor.set_servo(2, servo2)
        self.oled.set_pan(servo1)
        
        if action == 'forward':
            l = int(max(0, min(255, cmd.get('left_speed', speed))))
            r = int(max(0, min(255, cmd.get('right_speed', speed))))
            self.motor.forward(l, r)
        elif action == 'spin_left':
            self.motor.spin_left(speed)
        elif action == 'spin_right':
            self.motor.spin_right(speed)
        elif action == 'backward':
            self.motor.backward(speed)
        else:
            self.motor.stop()
        
        if cmd.get('detecting'):
            self.oled.set_state('env')
        else:
            self.oled.set_state('idle')
        
        env = self.pcf8591.get_data()
        if env['smoke_alarm']:
            self.oled.set_alarm(f"SMOKE {env['smoke']}")
        else:
            self.oled.set_alarm('')

    async def handle_client(self, ws: WebSocketServerProtocol):
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
            while True:
                seq, jpeg = self.camera.get_frame()
                if jpeg and seq != last_seq:
                    last_seq = seq
                    try:
                        await ws.send(bytes([MSG_VIDEO]) + jpeg)
                    except websockets.ConnectionClosed:
                        return
                await asyncio.sleep(0.033)
        
        async def recv_commands():
            async for msg in ws:
                try:
                    if isinstance(msg, bytes) and len(msg) > 1 and msg[0] == MSG_COMMAND:
                        cmd = json.loads(msg[1:].decode('utf-8'))
                        self.execute_command(cmd)
                    elif isinstance(msg, str):
                        self.execute_command(json.loads(msg))
                except Exception as e:
                    print(f'[WS] command error: {e}')
        
        async def send_env():
            while True:
                env = self.pcf8591.get_data()
                dist = self.ultrasonic.get_distance()
                track = self.infrared.get_data().get('track', [1, 1, 1, 1])
                imu = self.imu.get_data() if self.imu.enabled else {}
                imu_payload = None
                if imu:
                    imu_payload = {
                        'roll': imu.get('roll', 0.0),
                        'pitch': imu.get('pitch', 0.0),
                        'yaw': imu.get('yaw', 0.0),
                        'healthy': imu.get('healthy', False),
                        'calibrated': imu.get('calibrated', False),
                    }
                
                alarm = ''
                if env['smoke_alarm']:
                    alarm = 'smoke'
                
                fps = self.camera.get_fps()
                payload = bytes([MSG_ENV]) + json.dumps({
                    'light': env['light'],
                    'light_lux': env['light_lux'],
                    'temp_c': env['temp_c'],
                    'smoke': env['smoke'],
                    'volume': env['volume'],
                    'dist_cm': round(dist, 1),
                    'track': track,
                    'alarm': alarm,
                    'imu': imu_payload, 'fps': fps
                }).encode('utf-8')
                
                try:
                    await ws.send(payload)
                except websockets.ConnectionClosed:
                    return
                print(f"[DEBUG] Env: T={env['temp_c']:.1f} L={env['light_lux']} S={env['smoke']}")
                await asyncio.sleep(0.5)
        
        try:
            await asyncio.gather(send_video(), recv_commands(), send_env())
        except websockets.ConnectionClosed:
            pass
        finally:
            self.motor.stop()
            self.motor.set_servo(1, 90)
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

async def main(host, port, asr_url, mic_health_timeout, srs_url, srs_bitrate):
    server = CarServer(
        asr_url=asr_url,
        mic_health_timeout=mic_health_timeout,
        srs_url=srs_url,
        srs_bitrate=srs_bitrate,
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
    p.add_argument('--srs-url', default=os.getenv('RASPBOT_SRS_URL', ''))
    p.add_argument('--srs-bitrate', type=int, default=int(os.getenv('RASPBOT_SRS_BITRATE', '4000000')))
    p.add_argument('--disable-mic-stream', action='store_true')
    args = p.parse_args()
    asr_url = '' if args.disable_mic_stream else resolve_asr_url(args.asr_url)
    asyncio.run(main(args.host, args.port, asr_url, args.mic_health_timeout, args.srs_url, args.srs_bitrate))
