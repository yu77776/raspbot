# 婴幼儿陪护小车系统代理层级

本文档定义项目的代理管理结构。顶层只保留 1 个父代理和 3 个一级子代理，避免代理数量过多导致任务分配混乱。更细的功能代理只作为对应端内部的职责分工，不直接参与顶层协调。

## 代理结构

```text
Main System Agent
├── Car Agent
│   ├── Hardware Module Agent
│   ├── Runtime Server Agent
│   ├── Safety & Sensor Agent
│   ├── OLED & Audio Agent
│   └── Git Deploy Agent
│
├── PC Agent
│   ├── Vision Tracking Agent
│   ├── Motion Tuning Agent
│   ├── ASR Voice Agent
│   ├── Runtime Ops Agent
│   └── Protocol Client Agent
│
└── App Agent
    ├── UI Control Agent
    ├── Video Display Agent
    ├── Env Display Agent
    └── App Protocol Agent
```

## Main System Agent

职责：

- 管理整个婴幼儿陪护小车系统的开发进度。
- 协调小车端、PC端、APP端之间的任务。
- 维护三端协议一致性。
- 判断用户任务应该交给哪个一级子代理。
- 做最终功能验收、演示流程设计和答辩级功能总结。

管理内容：

- 整体功能规划。
- 三端集成。
- 协议变更审批。
- 演示流程设计。
- 任务优先级管理。

顶层规则：

- 顶层只直接管理 `Car Agent`、`PC Agent`、`App Agent`。
- 协议字段变更必须由 Main System Agent 协调三个一级子代理一起处理。
- 涉及三端一致性、演示、答辩总结的问题，优先由 Main System Agent 统一判断。

## Car Agent

负责范围：

- 本地仓库：`E:\毕设\raspbot_remote`
- 小车远程路径：`/home/pi/raspbot`
- SSH：用户名和密码从本地私有配置或环境变量读取，不写入仓库

内部子代理：

- Hardware Module Agent：管理电机、舵机、摄像头、超声波、PCF8591、MQ-2、IMU、红外 track。
- Runtime Server Agent：管理 `car_server_modular.py`、WebSocket 服务、小车启动流程。
- Safety & Sensor Agent：管理距离急停、烟雾报警、哭声报警、环境数据缓存。
- OLED & Audio Agent：管理 OLED 表情、音乐播放、音频输出、麦克风流。
- Git Deploy Agent：负责小车端代码提交、推送、远程同步。

规则：

- 小车端代码改完必须 `git commit + push`。
- 不误删 `songs/`、`mpu.py` 等用户文件。
- 默认保留语音麦克风流，不随意禁用。
- 小车端负责硬件真实动作和传感器真实数据。

## PC Agent

负责范围：

- PC 端项目：`E:\毕设\raspbot1`
- 默认 Python：`E:\conda\envs\myenv\python.exe`

内部子代理：

- Vision Tracking Agent：管理 YOLO 婴幼儿检测、目标锁定、丢失扫描。
- Motion Tuning Agent：管理 `motion_tuning.json`、舵机 PID、车身联动、距离跟随。
- ASR Voice Agent：管理 PC 端 ASR 服务和语音命令解析。
- Runtime Ops Agent：管理 `raspbot_agent.py`、自动发现 IP、SSH 启动小车、运行监控。
- Protocol Client Agent：管理 PC 发给小车的命令包和接收环境包。

规则：

- 所有 PC 端 Python 命令使用 `E:\conda\envs\myenv\python.exe`。
- 普通启动默认不开额外环境监控，避免多路视频流导致卡顿。
- 调参时可以开启监控，但每次只改一小组参数。
- PC 端不是 git 仓库，不强行提交。

常用命令：

```powershell
# 完整启动：小车端 + PC 客户端
& E:/conda/envs/myenv/python.exe e:/毕设/raspbot1/raspbot_agent.py

# 已知小车 IP 时启动
& E:/conda/envs/myenv/python.exe e:/毕设/raspbot1/raspbot_agent.py --host 10.188.152.100

# 只看环境/IMU 监控
& E:/conda/envs/myenv/python.exe -m pc_modules.env_monitor --host 10.188.152.100

# 调参时启动完整系统并额外显示监控
& E:/conda/envs/myenv/python.exe e:/毕设/raspbot1/raspbot_agent.py --monitor
```

## App Agent

负责范围：

- Android 项目：`E:\AndroidStudioProjects\RaspbotApp`

内部子代理：

- UI Control Agent：管理 APP 控制按钮、舵机控制、移动控制。
- Video Display Agent：管理摄像头画面显示。
- Env Display Agent：管理温度、光照、烟雾、距离、报警状态显示。
- App Protocol Agent：管理 APP 与小车端、PC端协议字段一致性。

规则：

- APP 只做远程查看和手动控制，不承担核心识别逻辑。
- APP 协议字段必须和小车端、PC端一致。
- 构建 APK 时使用项目已有 Gradle/JDK 配置。
- 不引入无用推流/接收逻辑。

## 协作规则

- 涉及整体功能、演示、三端一致性的问题，先交给 Main System Agent。
- 涉及硬件、传感器、OLED、音频、小车服务的问题，交给 Car Agent。
- 涉及识别、跟踪、调参、语音、启动脚本的问题，交给 PC Agent。
- 涉及手机界面、APP 控制、APP 构建的问题，交给 App Agent。
- 协议字段变更必须由 Main System Agent 协调三个子代理一起更新。
- 小车端改动由 Car Agent 负责提交和推送。
- PC 端调参由 PC Agent 负责验证，不直接扩大到小车端改代码。
