"""Application entry for PC websocket client."""
import argparse
import os

from .logger_setup import setup_logger
from .discovery import DEFAULT_DISCOVERY_PORT
from coordinator.system_coordinator import SystemCoordinator

logger = setup_logger('raspbot.pc')


def parse_args():
    p = argparse.ArgumentParser(description='Raspbot PC WebSocket client')
    p.add_argument('--host', default=os.getenv('RASPBOT_CAR_IP', os.getenv('CAR_HOST', '')))
    p.add_argument('--port', type=int, default=int(os.getenv('RASPBOT_CAR_PORT', '0') or '0'))
    p.add_argument('--no-discover', action='store_true', help='Skip UDP discovery and use --host/default host')
    p.add_argument('--discover-timeout', type=float, default=float(os.getenv('RASPBOT_DISCOVERY_TIMEOUT', '3.0')))
    p.add_argument('--discover-port', type=int, default=int(os.getenv('RASPBOT_DISCOVERY_PORT', str(DEFAULT_DISCOVERY_PORT))))
    p.add_argument('--model', default='best.pt')
    p.add_argument(
        '--tuning',
        default=os.getenv('RASPBOT_MOTION_TUNING', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'motion_tuning.json')),
        help='Hot-loaded motion tuning JSON path. Use empty string to disable.',
    )
    p.add_argument('--yolo-device', default='cuda', help='YOLO device: cpu / cuda / 0')
    p.add_argument(
        '--yolo-use-cudnn',
        action='store_true',
        help='Enable cuDNN for YOLO GPU inference (disabled by default for compatibility)',
    )

    # Embedded ASR server (enabled by default).
    p.add_argument('--disable-asr', action='store_true', help='Disable embedded ASR websocket server')
    p.add_argument('--asr-host', default=os.getenv('ASR_HOST', '0.0.0.0'))
    p.add_argument('--asr-port', type=int, default=int(os.getenv('ASR_PORT', '6006')))
    p.add_argument('--asr-path', default=os.getenv('ASR_PATH', '/audio'))
    p.add_argument('--asr-window-sec', type=float, default=float(os.getenv('ASR_WINDOW_SEC', '2.0')))
    p.add_argument('--asr-step-sec', type=float, default=float(os.getenv('ASR_STEP_SEC', '1.0')))
    p.add_argument('--asr-silence-rms', type=int, default=int(os.getenv('ASR_SILENCE_RMS', '220')))
    p.add_argument('--baidu-appid', default=os.getenv('BAIDU_APPID', ''))
    p.add_argument('--baidu-api-key', default=os.getenv('BAIDU_API_KEY', ''))
    p.add_argument('--baidu-secret-key', default=os.getenv('BAIDU_SECRET_KEY', ''))
    p.add_argument('--baidu-access-token', default=os.getenv('BAIDU_ACCESS_TOKEN', ''))
    p.add_argument('--baidu-url', default=os.getenv('BAIDU_REALTIME_ASR_URL', 'wss://vop.baidu.com/realtime_asr'))
    p.add_argument('--baidu-dev-pid', type=int, default=int(os.getenv('BAIDU_DEV_PID', '15372')))
    p.add_argument('--baidu-cuid', default=os.getenv('BAIDU_CUID', 'raspbot-pc'))
    p.add_argument('--baidu-lm-id', default=os.getenv('BAIDU_LM_ID', ''))
    p.add_argument('--baidu-user', default=os.getenv('BAIDU_USER', ''))
    p.add_argument('--baidu-frame-ms', type=int, default=int(os.getenv('BAIDU_FRAME_MS', '160')))
    p.add_argument('--auth-token', default=os.getenv('RASPBOT_AUTH_TOKEN', ''))
    p.add_argument(
        '--baidu-emit-partial',
        action='store_true',
        default=os.getenv('BAIDU_EMIT_PARTIAL', '').strip().lower() in {'1', 'true', 'yes', 'on'},
        help='Emit Baidu MID_TEXT partial text. Default is FIN_TEXT only for safer robot commands.',
    )
    p.add_argument(
        '--disable-webrtc-bridge',
        action='store_true',
        default=os.getenv('RASPBOT_ENABLE_WEBRTC_BRIDGE', '1').strip().lower() in {'0', 'false', 'no', 'off'},
        help='Disable cloud WebRTC bridge for App access.',
    )
    p.add_argument('--webrtc-signaling-url', default=os.getenv('RASPBOT_WEBRTC_SIGNALING_URL', 'ws://47.108.164.190:8765/pc_room'))
    p.add_argument('--webrtc-stun-url', default=os.getenv('RASPBOT_STUN_URL', 'stun:47.108.164.190:3478'))
    p.add_argument('--webrtc-turn-url', default=os.getenv('RASPBOT_TURN_URL', 'turn:47.108.164.190:3478'))
    p.add_argument('--webrtc-turn-username', default=os.getenv('RASPBOT_TURN_USERNAME', 'webrtc_user'))
    p.add_argument('--webrtc-turn-credential', default=os.getenv('RASPBOT_TURN_CREDENTIAL', ''))
    p.add_argument('--webrtc-env-interval', type=float, default=float(os.getenv('RASPBOT_WEBRTC_ENV_INTERVAL', '0.2')))
    return p.parse_args()


def main():
    args = parse_args()
    args.enable_webrtc_bridge = not bool(args.disable_webrtc_bridge)
    SystemCoordinator.from_args(args).run()


if __name__ == '__main__':
    main()
