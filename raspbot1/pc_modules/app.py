"""Application entry for PC websocket client."""
import argparse
import asyncio
import os
import time

from .client import PCClientWS
from .voice_cry_bridge import CryStateStore
from agent_modules.discovery import DEFAULT_DISCOVERY_PORT, discover_car
from .settings import DEFAULT_CAR_HOST, DEFAULT_CAR_PORT


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
    p.add_argument(
        '--baidu-emit-partial',
        action='store_true',
        default=os.getenv('BAIDU_EMIT_PARTIAL', '').strip().lower() in {'1', 'true', 'yes', 'on'},
        help='Emit Baidu MID_TEXT partial text. Default is FIN_TEXT only for safer robot commands.',
    )
    p.add_argument('--disable-app-gateway', action='store_true', help='Disable embedded App gateway server')
    p.add_argument('--app-gateway-host', default=os.getenv('APP_GATEWAY_HOST', '0.0.0.0'))
    p.add_argument('--app-gateway-port', type=int, default=int(os.getenv('APP_GATEWAY_PORT', '7000')))
    p.add_argument('--app-gateway-reconnect-delay', type=float, default=float(os.getenv('APP_GATEWAY_RECONNECT_DELAY', '1.5')))
    p.add_argument(
        '--enable-webrtc-bridge',
        action='store_true',
        default=os.getenv('RASPBOT_ENABLE_WEBRTC_BRIDGE', '').strip().lower() in {'1', 'true', 'yes', 'on'},
        help='Enable cloud WebRTC bridge for App access without ZeroTier.',
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
    host = (args.host or '').strip()
    port = int(args.port or 0)

    if not host and not args.no_discover:
        print(f'[DISCOVERY] listening udp://0.0.0.0:{args.discover_port} timeout={args.discover_timeout:.1f}s')
        car = discover_car(timeout=args.discover_timeout, port=args.discover_port)
        if car:
            host = car.ip
            port = car.port
            print(f'[DISCOVERY] found {car.name} at {car.uri} server_running={car.server_running}')
        else:
            print('[DISCOVERY] not found, fallback to default host')

    if not host:
        host = DEFAULT_CAR_HOST
    if not port:
        port = DEFAULT_CAR_PORT

    uri = f'ws://{host}:{port}'
    client = PCClientWS(
        uri=uri,
        model_path=args.model,
        yolo_device=args.yolo_device,
        yolo_disable_cudnn=not args.yolo_use_cudnn,
        tuning_path=args.tuning or None,
    )

    asr_runner = None
    app_gateway_runner = None
    webrtc_runner = None
    cry_state = CryStateStore()

    if not args.disable_app_gateway:
        from .app_gateway import AppGatewayRunner, GatewayConfig

        app_gateway_runner = AppGatewayRunner(
            GatewayConfig(
                listen_host=args.app_gateway_host,
                listen_port=args.app_gateway_port,
                car_host=host,
                car_port=port,
                reconnect_delay=args.app_gateway_reconnect_delay,
                cry_state=cry_state,
            )
        )
        app_gateway_runner.start()
        time.sleep(0.2)
        if app_gateway_runner.error is not None:
            print(f'[APPGW] embedded server failed: {app_gateway_runner.error}')
            print('[APPGW] tip: stop existing gateway process or use --disable-app-gateway')
        else:
            print(f'[APPGW] embedded server started at ws://{args.app_gateway_host}:{args.app_gateway_port} -> {uri}')

    if not args.disable_asr:
        from .asr_server import AsrServerRunner, ServerConfig

        asr_cfg = ServerConfig(
            host=args.asr_host,
            port=args.asr_port,
            path=args.asr_path,
            window_sec=args.asr_window_sec,
            step_sec=args.asr_step_sec,
            silence_rms=args.asr_silence_rms,
            baidu_appid=args.baidu_appid,
            baidu_api_key=args.baidu_api_key,
            baidu_secret_key=args.baidu_secret_key,
            baidu_access_token=args.baidu_access_token,
            baidu_url=args.baidu_url,
            baidu_dev_pid=args.baidu_dev_pid,
            baidu_cuid=args.baidu_cuid,
            baidu_lm_id=args.baidu_lm_id,
            baidu_user=args.baidu_user,
            baidu_frame_ms=args.baidu_frame_ms,
            baidu_emit_partial=args.baidu_emit_partial,
            on_text=client.on_asr_text,
            on_cry_state=cry_state.update_from_ratio,
        )
        asr_runner = AsrServerRunner(asr_cfg)
        asr_runner.start()
        time.sleep(0.3)
        if asr_runner.error is not None:
            print(f'[ASR] embedded server failed: {asr_runner.error}')
            print('[ASR] tip: stop existing asr_server.py or use --disable-asr')
        else:
            print(f'[ASR] embedded server started at ws://{args.asr_host}:{args.asr_port}{args.asr_path}')

    if args.enable_webrtc_bridge:
        from .webrtc_bridge import WebRtcBridgeConfig, WebRtcBridgeRunner

        webrtc_runner = WebRtcBridgeRunner(
            WebRtcBridgeConfig(
                signaling_url=args.webrtc_signaling_url,
                car_host=host,
                car_port=port,
                stun_url=args.webrtc_stun_url,
                turn_url=args.webrtc_turn_url,
                turn_username=args.webrtc_turn_username,
                turn_credential=args.webrtc_turn_credential,
                env_interval=args.webrtc_env_interval,
                cry_state=cry_state,
            ),
            frame_provider=client.get_latest_webrtc_frame,
            env_provider=client.get_latest_env_dict,
        )
        webrtc_runner.start()
        time.sleep(0.3)
        if webrtc_runner.error is not None:
            print(f'[WEBRTC] bridge failed: {webrtc_runner.error}')
            print('[WEBRTC] tip: install aiortc or disable with no --enable-webrtc-bridge')
        else:
            print(f'[WEBRTC] bridge started via {args.webrtc_signaling_url}')

    try:
        asyncio.run(client.run())
    finally:
        if webrtc_runner is not None:
            webrtc_runner.stop()
            print('[WEBRTC] bridge stopped')
        if app_gateway_runner is not None:
            app_gateway_runner.stop()
            print('[APPGW] embedded server stopped')
        if asr_runner is not None:
            asr_runner.stop()
            print('[ASR] embedded server stopped')


if __name__ == '__main__':
    main()
