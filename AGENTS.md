# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Raspbot — 基于树莓派的婴幼儿智能陪护机器人。三端协同：树莓派小车（执行）、PC (Windows, Python, GPU 推理)、Android App (Kotlin)。

## Common Commands

```powershell
# 完整系统启动（PC 发现小车 → SSH 启动车端服务 → 启动 PC 客户端）
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot1/raspbot_agent.py

# 已知小车 IP 跳过发现
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot1/raspbot_agent.py --host 10.188.152.100

# 带环境监控面板
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot1/raspbot_agent.py --monitor

# 仅启 PC 客户端（小车已在运行）—— WebSocket 直连模式
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot1/raspbot_agent.py --skip-car-start --skip-car-sync

# 模型路径和推理设备
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot1/raspbot_agent.py --model best.pt --yolo-device cuda

# 允许不安全连接（无认证，仅实验环境）
$env:RASPBOT_ALLOW_INSECURE = "1"
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot1/raspbot_agent.py

# YOLO 训练（恢复上次中断点）
& E:/conda/envs/myenv/python.exe e:/bishe/yolo/train_yolo26.py

# 运行测试（PC 端）
& E:/conda/envs/myenv/python.exe -m pytest e:/bishe/raspbot1/tests/

# 单独运行模块工具
& E:/conda/envs/myenv/python.exe -m pc_modules.env_monitor --host 10.188.152.100
& E:/conda/envs/myenv/python.exe -m pc_modules.discovery
& E:/conda/envs/myenv/python.exe e:/bishe/raspbot_remote/modules/pcf8591.py --temp-diagnostics
```

Python 环境: `E:/conda/envs/myenv/python.exe` (conda `myenv`)

## Architecture

```
Android App (Kotlin, OkHttp/WebRTC)
    ↕ WebSocket :7000 或 WebRTC (信令 47.108.164.190:8765)
PC Agent (Python, raspbot1/)
    ↕ WebSocket :5001 (二进制帧: 0x01 视频/0x02 命令/0x03 环境)
Raspberry Pi Car (Python, raspbot_remote/)
    内部: car_server_modular.py → Hardware Modules (ModuleBase)
```

### 三组件职责

| 端 | 路径 | 职责 |
|---|---|---|
| **Car (Pi)** | `raspbot_remote/` | 硬件驱动、传感器采集、安全防护、WebSocket 服务端 |
| **PC** | `raspbot1/` | YOLOv6 目标检测、YAMNet 哭声检测、百度 ASR、PID 控制、App 网关、WebRTC 桥接 |
| **App** | `RaspbotApp/` | 视频显示、远程控制、环境监控、报警通知、趋势图 |

### PC 端关键模块

- `pc_modules/client.py` — `PCClientWS`: 视频接收、YOLO 推理、控制指令生成
- `pc_modules/motion_controller.py` — `MotionController` + `PID`: 双环伺服控制 (内环 PD 像素→舵机, 外环 舵机偏移→车身+IMU阻尼)
- `pc_modules/baby_filter.py` — `BabyFilter`: 时序目标锁定 (3帧确认/5帧丢失/IoU匹配)
- `pc_modules/cry_detector.py` — `YamnetCryDetector` + `CryStateSmoother`: 双阈值滞后状态机
- `pc_modules/app_gateway.py` — `AppGateway`: App↔Car 数据桥接
- `pc_modules/webrtc_bridge.py` — `WebRtcBridge`: aiortc 云端视频穿透
- `pc_modules/asr_server.py` — `AsrServer`: 百度实时语音识别
- `pc_modules/tuning.py` — `JsonTuner`: `motion_tuning.json` 热加载 (250ms 轮询)
- `coordinator/runtime_launcher.py` — 顶层编排: UDP 发现、SSH 启动、生命周期管理

### Car 端关键模块

- `car_server_modular.py` — `CarServer`: WebSocket 服务 (端口 5001), 协调所有硬件
- `command_executor.py` — `CommandExecutor`: 命令解析+安全防护 (看门狗/悬崖/距离)
- `env_sampler.py` — `EnvSampler`: 多传感器数据聚合
- `care_policy.py` — `CarePolicy`: 报警 token 生成 + TTS 冷却
- `modules/base.py` — `ModuleBase`: 硬件模块线程基类
- 各硬件模块: `motor.py`, `camera.py`, `audio.py`, `ultrasonic.py`, `pcf8591.py`, `mpu6050.py`, `mic_stream.py`, `oled_face.py`, `infrared.py`

## Wire Protocol (docs/protocol.md)

| Prefix | Direction | Payload |
|---|---|---|
| `0x01` | Car/PC → App | JPEG bytes |
| `0x02` | App/PC → Car | UTF-8 JSON command |
| `0x03` | Car/PC → App | UTF-8 JSON environment |

认证: URL query `?token=<RASPBOT_AUTH_TOKEN>`, 自动生成并持久化到 `raspbot.local.json`

## Key Design Decisions

- **PC 作为"大脑"**: YOLO/YAMNet/ASR 全部在 PC (GPU) 推理, Pi 只做实时硬件控制和本地安全
- **双环控制**: 内环 PD (像素误差→舵机), 外环 (舵机偏移→车身 spin + IMU yaw-rate 阻尼)
- **Car 端安全为最后防线**: 指令看门狗 0.8s、麦克风健康 2s、悬崖检测、距离防撞 (30cm/5cm)
- **热加载调参**: `motion_tuning.json` 运行时修改即时生效
- **双路径连接**: 本地 WebSocket (:7000) + 云端 WebRTC (TURN)
- **报警 Token 机制**: 跨端统一报警语义, TTS 冷却防骚扰

## Config Files

- `raspbot1/raspbot.local.json` — 本地环境变量 (认证 token, 百度 ASR 凭证, SSH 配置等)
- `raspbot1/motion_tuning.json` — PID 参数、跟随距离阈值等, 运行时热加载
- `RaspbotApp/local.properties` — Android 构建配置 (含自动同步的 auth token)

## Constraints

- 小车端 Python 依赖 `RPi.GPIO`, `smbus2`, `picamera2` 等 — 仅在 Pi 上运行
- PC 端 Python 需要 `ultralytics`, `torch` (CUDA), `tensorflow-hub`, `aiortc`, `websockets`
- Android 构建需要 Gradle + JDK, APK 通过 `RaspbotApp/` 项目构建
- 协议的权威定义在 `docs/protocol.md`, 三端代码必须与之保持一致
