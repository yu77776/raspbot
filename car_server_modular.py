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
import websockets
from websockets.server import WebSocketServerProtocol

MSG_VIDEO = 0x01
MSG_COMMAND = 0x02
MSG_ENV = 0x03

class CarServer:
    def __init__(self):
        self.ultrasonic = Ultrasonic()
        self.pcf8591 = PCF8591()
        self.infrared = Infrared()
        self.camera = Camera()
        self.motor = Motor()
        self.audio = Audio(songs_dir=os.path.join(os.path.dirname(__file__), 'songs'))
        self.oled = FaceEngine()
        self.stop_event = threading.Event()
        self.oled_thread = None
    
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

    def start_all(self):
        self.stop_event.clear()
        self.ultrasonic.start()
        self.pcf8591.start()
        self.infrared.start()
        self.camera.start()
        self.audio.start()
        self.oled.start()
        self._update_oled_loop()
        print('[SYS] 所有模块已启动')
    
    def stop_all(self):
        self.stop_event.set()
        if self.oled_thread and self.oled_thread.is_alive():
            self.oled_thread.join(timeout=1.0)

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
        if dist < 15:
            action = 'stop'
        
        ir = self.infrared.get_data()
        if ir['edge_alarm']:
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
        elif ir['edge_alarm']:
            self.oled.set_alarm('EDGE ALARM')
        else:
            self.oled.set_alarm('')

    async def handle_client(self, ws: WebSocketServerProtocol):
        addr = ws.remote_address
        print(f'[WS] 连接: {addr}')
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
                    print(f'[WS] 命令错误: {e}')
        
        async def send_env():
            while True:
                env = self.pcf8591.get_data()
                dist = self.ultrasonic.get_distance()
                ir = self.infrared.get_data()
                
                alarm = ''
                if env['smoke_alarm']:
                    alarm = 'smoke'
                elif ir['edge_alarm']:
                    alarm = 'edge'
                
                fps = self.camera.get_fps()
                payload = bytes([MSG_ENV]) + json.dumps({
                    'light': env['light'],
                    'light_lux': env['light_lux'],
                    'temp_c': env['temp_c'],
                    'smoke': env['smoke'],
                    'volume': env['volume'],
                    'dist_cm': round(dist, 1),
                    'track': ir['track'],
                    'alarm': alarm,
                    'imu': None, 'fps': fps
                }).encode('utf-8')
                
                try:
                    await ws.send(payload)
                except websockets.ConnectionClosed:
                    return
                print(f"[DEBUG] Env: T={env["temp_c"]:.1f} L={env["light_lux"]} S={env["smoke"]}")
                await asyncio.sleep(0.5)
        
        try:
            await asyncio.gather(send_video(), recv_commands(), send_env())
        except websockets.ConnectionClosed:
            pass
        finally:
            self.motor.stop()
            self.motor.set_servo(1, 90)
            print(f'[WS] 断开: {addr}')

async def main(host, port):
    server = CarServer()
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
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=5001)
    args = p.parse_args()
    asyncio.run(main(args.host, args.port))
