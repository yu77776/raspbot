# Raspbot Wire Protocol

This document is the shared contract for App, PC, and car messages. Keep code changes aligned with this file before adding new command or environment fields.

## Binary Packet Prefixes

| Prefix | Direction | Meaning |
| --- | --- | --- |
| `0x01` | Car/PC to App | JPEG video frame |
| `0x02` | App/PC to Car | UTF-8 JSON command |
| `0x03` | Car/PC to App | UTF-8 JSON environment packet |

## Command JSON

Commands are sent inside `0x02 + json`.

| Field | Type | Range / Values | Notes |
| --- | --- | --- | --- |
| `source` | string | `app`, `pc`, omitted | `app` activates car-side manual override. PC tracking commands should omit it or use `pc`. |
| `action` | string | `stop`, `forward`, `backward`, `left`, `right`, `spin_left`, `spin_right` | Unknown actions must fail safe to stop. |
| `servo_angle` | number | `0..180` | Horizontal servo. |
| `servo_angle2` | number | `0..180` | Vertical servo. |
| `speed` | int | `0..255` | Default speed for simple actions. |
| `left_speed` | int | `0..255` | Tank left speed magnitude. |
| `right_speed` | int | `0..255` | Tank right speed magnitude. |
| `detecting` | bool | | PC YOLO/tracking status. |
| `tracking_mode` | bool | | App UI state hint; car must not rely on it for safety. |
| `audio_volume` | int | `0..100` | Speaker volume percent. |
| `play_song` | string | filename or blank | Plays a song on the car. |
| `stop_audio` | bool | | Stops song/audio playback. |
| `remote_crying` / `crying` | bool | | PC-derived cry state forwarded to the car/app. |
| `remote_cry_score` / `cry_score` | int | `0..100` | PC-derived cry score. |
| `remote_alarm` / `alarm` | string | token list | PC-derived alarm tokens. |

## Environment JSON

Environment packets are sent inside `0x03 + json` or through the WebRTC `env` DataChannel.

| Field | Type | Notes |
| --- | --- | --- |
| `light`, `light_lux` | int | Light sensor raw/lux. |
| `temp_raw`, `temp_c` | int/float | Temperature raw/Celsius. |
| `smoke` | int | Smoke/aux analog level. |
| `volume` | int | Speaker volume percent as currently applied by car logic. |
| `crying`, `cry_score` | bool/int | Current cry state, usually PC-derived. |
| `dist_cm` | float | Ultrasonic distance in cm. |
| `track` | int array | Bottom tracking sensors. |
| `alarm` | string | `+`, `;`, or `,` separated alarm tokens. |
| `imu` | object or null | `{roll,pitch,yaw,yaw_rate,healthy,calibrated}`. `null` means IMU unavailable. |
| `fps` | int | Camera FPS. |

## Alarm Tokens

Preferred backend tokens are:

| Token | App message |
| --- | --- |
| `smoke` | `烟雾异常` |
| `cry` / `cry_detected` | `检测到哭声` |
| `close_distance` | `距离过近` |
| `cliff` / `track_empty` | `疑似悬空` |

The App may still derive local alerts from raw environment values, but backend alarm tokens should remain the primary cross-process alarm contract.

## WebRTC Signaling

Signaling messages are plain JSON over `ws://47.108.164.190:8765/pc_room`.

| Type | Required fields |
| --- | --- |
| `webrtc_offer` | `sdp`, optional `sdpType` |
| `webrtc_answer` | `sdp`, optional `sdpType` |
| `webrtc_ice` | `candidate` object or candidate fields |

Media and control use WebRTC directly after signaling:

| Channel | Direction | Payload |
| --- | --- | --- |
| video track | PC to App | Clean camera frame stream |
| `env` DataChannel | PC to App | Environment JSON |
| `command` DataChannel | App to PC | Command JSON or app voice JSON |
