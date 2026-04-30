"""Runtime settings and constants for PC client."""
import os
from .protocol import MSG_COMMAND, MSG_ENV, MSG_VIDEO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tunable parameters
FRAME_W, FRAME_H = 640, 480
CENTER_X = FRAME_W // 2
CENTER_Y = FRAME_H // 2

DEAD_ZONE_X = 50
DEAD_ZONE_Y = 50
SERVO_DIR_X = -1
SERVO_DIR_Y = 1

SERVO_PID_HZ = 12

SERVO_KP_X = 0.1
SERVO_KI_X = 0.0
SERVO_KD_X = 0.012

SERVO_KP_Y = 0.08
SERVO_KI_Y = 0.0
SERVO_KD_Y = 0.02
SERVO_I_MAX = 15.0

SERVO_OUT_MAX_X = 1
SERVO_OUT_MAX_Y = 1

MOTOR_SPEED = 80

IMU_DEBUG = False
IMU_DEBUG_INTERVAL = 0.5
INFER_EVERY_N = 1

ENABLE_MOTOR_CONTROL = True

ENABLE_SERVO_X = True
ENABLE_SERVO_Y = True
SERVO_Y_HOLD_ANGLE = 90.0

RECONNECT_DELAY = 2.0
MAX_RECONNECTS = 10

DEFAULT_CAR_HOST = '10.188.152.100'
DEFAULT_CAR_PORT = 5001

# Voice control extension:
# "default" lets the car choose the first playable file in its songs directory.
VOICE_DEFAULT_SONG_FILE = os.getenv('RASPBOT_VOICE_SONG_FILE', 'default')
