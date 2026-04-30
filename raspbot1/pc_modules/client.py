"""PC websocket client implementation."""

import asyncio

import json

import os

import threading

import time


import cv2

import numpy as np

import websockets

from websockets.client import WebSocketClientProtocol


from .baby_filter import BabyFilter, FilterConfig


from . import settings as cfg

from .motion_controller import MotionController, MotionState

from .env_logger import flush_csv, log_env

from .packets import CommandPacket, EnvPacket
from .voice_cry_bridge import parse_voice_intent



class PCClientWS:

    def __init__(self, uri: str, model_path: str, yolo_device: str = 'cuda',

                 yolo_disable_cudnn: bool = True, tuning_path: str = None):

        self.uri        = uri

        self.model_path = model_path

        self.yolo_device = yolo_device

        self.yolo_disable_cudnn = yolo_disable_cudnn

        self.model      = None


        self.motion = MotionController(tuning_path=tuning_path)
        self._last_pid_time = 0.0


        self.frame_count  = 0

        self.detections   = {}

        self.env_state    = EnvPacket()
        self._latest_video_jpeg = None
        self._latest_video_seq = 0
        self._processed_video_seq = 0
        self._video_event = None
        self._latest_webrtc_frame = None
        self._latest_webrtc_frame_seq = 0
        self._latest_webrtc_frame_lock = threading.Lock()

        self._warned_resolution_mismatch = False

        self.last_command = CommandPacket(

            action='stop',

            servo_angle=90.0,

            servo_angle2=90.0,

            speed=0,

            left_speed=0,

            right_speed=0,

        )
        self._last_track_conf = 0.0
        self._last_track_locked = False


        self.baby_filter = BabyFilter(FilterConfig(

            conf_threshold = 0.50,

            confirm_frames = 3,

            lost_frames    = 5,

        ))

        self._voice_lock = threading.Lock()

        self._voice_action = None

        self._voice_until = 0.0

        self._voice_hold_sec = 2.2

        self._voice_last_sent = None

        self._voice_play_song = ''

        self._voice_stop_audio = False

        self._voice_one_shot_pending = False

        self._last_env_debug_ts = 0.0
        self._last_env_parse_error_ts = 0.0


    def _reset_tracking(self):

        self.motion.reset()

    def _asr_text_to_intent(self, text: str):
        return parse_voice_intent(text, hold_sec=self._voice_hold_sec)


    def on_asr_text(self, text: str):

        intent = self._asr_text_to_intent(text)

        if not intent:

            return


        with self._voice_lock:

            self._voice_action = intent['action']

            self._voice_until = time.monotonic() + float(intent['hold'])

            self._voice_play_song = str(intent['play_song'] or '')

            self._voice_stop_audio = bool(intent['stop_audio'])

            self._voice_one_shot_pending = bool(intent['one_shot'])


        print(

            f"[VOICE] text='{text}' -> "

            f"action={intent['action']} play_song={intent['play_song']!r} stop_audio={intent['stop_audio']}"

        )


    def _build_voice_command(self):

        now = time.monotonic()

        with self._voice_lock:

            if self._voice_action is None or now > self._voice_until:

                self._voice_last_sent = None

                return None


            action = self._voice_action

            play_song = self._voice_play_song

            stop_audio = self._voice_stop_audio

            one_shot = self._voice_one_shot_pending


        cmd = self.last_command.clone()

        cmd.detecting = False

        cmd.play_song = play_song

        cmd.stop_audio = stop_audio


        if not cfg.ENABLE_MOTOR_CONTROL:

            cmd.action = 'stop'

            cmd.speed = 0

            cmd.left_speed = 0

            cmd.right_speed = 0

        else:

            cmd.action = action

            cmd.speed = cfg.MOTOR_SPEED

            if action == 'stop':

                cmd.left_speed = 0

                cmd.right_speed = 0

            else:

                cmd.left_speed = cfg.MOTOR_SPEED

                cmd.right_speed = cfg.MOTOR_SPEED


        sent_key = (

            cmd.action,

            cmd.speed,

            cmd.left_speed,

            cmd.right_speed,

            cmd.play_song,

            cmd.stop_audio,

        )


        if self._voice_last_sent != sent_key:

            print(

                f"[VOICE] send action={cmd.action} speed={cmd.speed} "

                f"song={cmd.play_song!r} stop_audio={cmd.stop_audio}"

            )

            self._voice_last_sent = sent_key


        if one_shot:

            with self._voice_lock:

                self._voice_action = None

                self._voice_until = 0.0

                self._voice_play_song = ''

                self._voice_stop_audio = False

                self._voice_one_shot_pending = False


        return cmd


    def load_model(self):

        if self.model is not None:

            return

        dev = str(self.yolo_device).lower()

        if dev == 'cpu':

            # Prevent accidental CUDA DLL loading when CPU mode is requested.

            os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

        elif self.yolo_disable_cudnn:

            # Keep GPU inference while bypassing cuDNN symbol/version conflicts.

            try:

                import torch

                torch.backends.cudnn.enabled = False

                print('[YOLO] cuDNN disabled for compatibility, CUDA still enabled')

            except Exception as e:

                print(f'[YOLO] warn: failed to disable cuDNN: {e}')

        script_dir = cfg.BASE_DIR

        model_path = os.path.join(script_dir, self.model_path)

        if not os.path.exists(model_path):

            raise FileNotFoundError(f"Model not found: {model_path}")

        from ultralytics import YOLO

        print(f"[YOLO] loading: {model_path} (device={self.yolo_device})")

        self.model = YOLO(model_path)

        print("[YOLO] ready")


    def infer(self, frame) -> dict:

        r = self.model(frame, verbose=False, device=self.yolo_device)[0]

        return {

            'boxes':   r.boxes.xyxy.cpu().numpy().tolist(),

            'confs':   r.boxes.conf.cpu().numpy().tolist(),

            'classes': [int(c) for c in r.boxes.cls.cpu().numpy().tolist()],

        }


    def make_command(self, detections: dict) -> CommandPacket:

        boxes  = detections.get('boxes', [])
        confs  = detections.get('confs', [])
        classes = detections.get('classes', [])
        result = self.baby_filter.pick_baby(boxes, confs, classes)

        now = time.monotonic()
        dt = now - self._last_pid_time if self._last_pid_time > 0 else 0.1
        self._last_pid_time = now

        out = self.motion.update(result, self.env_state.raw, dt)

        is_locked = out.state == MotionState.TRACK
        detecting = is_locked
        self._last_track_conf = float(round(result.conf, 2))
        self._last_track_locked = bool(is_locked)

        return CommandPacket(
            action=out.action,
            servo_angle=out.servo_x,
            servo_angle2=out.servo_y,
            speed=out.speed,
            left_speed=out.left_speed,
            right_speed=out.right_speed,
            detecting=detecting,
        )



    def show(self, frame):
        cv2.line(frame, (cfg.CENTER_X, 0), (cfg.CENTER_X, cfg.FRAME_H), (180, 180, 180), 1)
        cv2.line(frame, (0, cfg.CENTER_Y), (cfg.FRAME_W, cfg.CENTER_Y), (180, 180, 180), 1)
        cv2.rectangle(
            frame,

            (cfg.CENTER_X - cfg.DEAD_ZONE_X, cfg.CENTER_Y - cfg.DEAD_ZONE_Y),

            (cfg.CENTER_X + cfg.DEAD_ZONE_X, cfg.CENTER_Y + cfg.DEAD_ZONE_Y),

            (80, 80, 220), 1

        )


        cls_names = {0: 'baby', 1: 'adult', 2: 'kids'}

        cls_colors = {0: (100,100,100), 1: (0,100,255), 2: (100,100,100)}

        for box, conf, cls in zip(

            self.detections.get('boxes', []),

            self.detections.get('confs', []),

            self.detections.get('classes', []),

        ):

            x1, y1, x2, y2 = map(int, box)

            color = cls_colors.get(cls, (100,100,100))

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)

            cv2.putText(frame, f"{cls_names.get(cls,'?')} {conf:.2f}",

                        (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)


        bf = self.baby_filter

        if bf.candidate and bf.locked_box is None:

            x1, y1, x2, y2 = map(int, bf.candidate)

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 210, 255), 1)

            cv2.putText(frame, f'? {bf.confirm_cnt}/{bf.cfg.confirm_frames}',

                        (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 210, 255), 1)


        if bf.locked_box:

            x1, y1, x2, y2 = map(int, bf.locked_box)

            area = (x2 - x1) * (y2 - y1)

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 80), 2)

            cv2.putText(frame, 'BABY', (x1, y1 - 8),

                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 80), 2)

            cv2.putText(frame, f'area:{int(area)}', (x1, y2 + 16),

                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 80), 1)


        cmd = self.last_command
        mc = self.motion
        dist = self.env_state.dist_cm
        track = self.env_state.track
        imu = self.env_state.imu or {}
        imu_yaw = imu.get('yaw', 'None')
        imu_ok = imu.get('healthy', False)

        cv2.putText(
            frame,
            f"act:{cmd.action}  "
            f"s1:{mc.servo_x:.1f}deg({mc.servo_x - 90.0:+.1f})  "
            f"s2:{mc.servo_y:.1f}deg  "
            f"L:{cmd.left_speed}  R:{cmd.right_speed}  "
            f"conf:{self._last_track_conf:.2f}",
            (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 230, 0), 1
        )
        cv2.putText(
            frame,
            f"dist:{dist:.1f}cm  track:{track}",
            (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 230, 0), 1
        )
        cv2.putText(
            frame,
            f"state:{mc.state.name}  imu_yaw:{imu_yaw}  imu_ok:{imu_ok}",
            (8, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 230, 0), 1
        )
        cv2.putText(
            frame,
            mc.tuning_overlay()[:120],
            (8, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 230, 0), 1
        )

        cv2.imshow('Raspbot Baby Tracker [WS]', frame)

        cv2.waitKey(1)


    async def _session(self):

        print(f"[WS] connecting {self.uri} ...")

        async with websockets.connect(

            self.uri,

            max_size=10 * 1024 * 1024,

            open_timeout=8,

            proxy=None,

            ping_interval=20,

            ping_timeout=10,

            close_timeout=2,

        ) as ws:

            print("[WS] connected")

            self.baby_filter.reset()

            self._reset_tracking()

            self._latest_video_jpeg = None
            self._latest_video_seq = 0
            self._processed_video_seq = 0
            self._video_event = asyncio.Event()

            tasks = [
                asyncio.create_task(self._recv_loop(ws)),
                asyncio.create_task(self._process_latest_video_loop()),
                asyncio.create_task(self._send_loop(ws)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


    async def _recv_loop(self, ws: WebSocketClientProtocol):

        async for message in ws:

            if not isinstance(message, bytes) or len(message) < 2:

                continue


            if message[0] == cfg.MSG_ENV:

                try:

                    parsed = json.loads(message[1:].decode('utf-8'))

                    self.env_state = EnvPacket.from_dict(parsed)

                    log_env(self.env_state.raw)

                    if cfg.IMU_DEBUG:

                        now = time.monotonic()

                        if now - self._last_env_debug_ts >= cfg.IMU_DEBUG_INTERVAL:

                            self._last_env_debug_ts = now

                            imu = self.env_state.imu or {}

                            if imu:

                                print(

                                    '[IMU] '

                                    f"yaw={imu.get('yaw')} roll={imu.get('roll')} "

                                    f"pitch={imu.get('pitch')} "

                                    f"healthy={imu.get('healthy')} calibrated={imu.get('calibrated')}"

                                )

                    if self.env_state.alarm:

                        print(f"[ENV] alarm: {self.env_state.alarm}  {self.env_state.raw}")

                except Exception as exc:

                    now = time.monotonic()

                    if now - self._last_env_parse_error_ts >= 5.0:

                        self._last_env_parse_error_ts = now

                        print(f"[ENV] parse error: {type(exc).__name__}: {exc} bytes={len(message) - 1}")

                continue


            if message[0] != cfg.MSG_VIDEO:

                continue

            self._latest_video_jpeg = bytes(message[1:])
            self._latest_video_seq += 1
            if self._video_event is not None:
                self._video_event.set()

    async def _process_latest_video_loop(self):

        last_pid_call = 0.0

        pid_interval = 1.0 / cfg.SERVO_PID_HZ

        while True:

            if self._video_event is None:

                await asyncio.sleep(0.01)

                continue

            await self._video_event.wait()

            jpeg = self._latest_video_jpeg

            seq = self._latest_video_seq

            self._video_event.clear()

            if jpeg is None or seq == self._processed_video_seq:

                continue

            self._processed_video_seq = seq

            nparr = np.frombuffer(jpeg, np.uint8)

            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:

                continue


            h, w = frame.shape[:2]

            if (w, h) != (cfg.FRAME_W, cfg.FRAME_H):

                if not self._warned_resolution_mismatch:

                    print(f"[VIDEO] resize incoming {w}x{h} -> {cfg.FRAME_W}x{cfg.FRAME_H}")

                    self._warned_resolution_mismatch = True

                frame = cv2.resize(frame, (cfg.FRAME_W, cfg.FRAME_H), interpolation=cv2.INTER_LINEAR)


            self._latest_frame = frame
            self.frame_count += 1


            # Keep YOLO inference on the incoming video stream.

            if self.frame_count % cfg.INFER_EVERY_N == 0:

                self.detections = await asyncio.to_thread(self.infer, frame)


            now = time.monotonic()

            if now - last_pid_call >= pid_interval:

                self.last_command = self.make_command(self.detections)

                last_pid_call = now


            frame_vis = frame.copy()
            self.show(frame_vis)
            with self._latest_webrtc_frame_lock:
                self._latest_webrtc_frame = frame.copy()
                self._latest_webrtc_frame_seq += 1

    def get_latest_webrtc_frame(self):
        with self._latest_webrtc_frame_lock:
            if self._latest_webrtc_frame is None:
                return None, self._latest_webrtc_frame_seq
            return self._latest_webrtc_frame.copy(), self._latest_webrtc_frame_seq

    def get_latest_env_dict(self):
        raw = self.env_state.raw
        return dict(raw) if isinstance(raw, dict) else {}


    async def _send_loop(self, ws: WebSocketClientProtocol):

        """Send current command every 100ms."""

        while True:

            cmd = self._build_voice_command() or self.last_command

            payload = bytes([cfg.MSG_COMMAND]) + json.dumps(cmd.to_wire_dict()).encode('utf-8')

            await ws.send(payload)

            await asyncio.sleep(0.1)


    async def run(self):

        self.load_model()

        attempt = 0


        while cfg.MAX_RECONNECTS < 0 or attempt <= cfg.MAX_RECONNECTS:

            try:

                await self._session()

            except KeyboardInterrupt:

                print("`n[SYS] interrupted by user")

                break

            except (websockets.ConnectionClosed, websockets.InvalidURI, OSError) as e:

                attempt += 1

                remaining = (f"{cfg.MAX_RECONNECTS - attempt + 1} retries left"

                             if cfg.MAX_RECONNECTS >= 0 else "unlimited retries")

                print(f"[WS] disconnected: {e}, retry in {cfg.RECONNECT_DELAY}s ({remaining})")

                await asyncio.sleep(cfg.RECONNECT_DELAY)

            except Exception as e:

                print(f"[WS] unexpected error: {e}")

                attempt += 1

                await asyncio.sleep(cfg.RECONNECT_DELAY)


        flush_csv()

        cv2.destroyAllWindows()

        print("[SYS] client exited")
