# 代理任务路由表

本文档用于把常见任务快速分配给正确代理。顶层只有 `Main System Agent`、`Car Agent`、`PC Agent`、`App Agent` 四个角色；更细的功能代理只作为一级子代理内部职责使用。

## 快速判断规则

| 任务类型 | 一级代理 | 内部职责 |
| --- | --- | --- |
| 三端协议字段不一致 | Main System Agent | 协调 Car / PC / App 同步变更 |
| 功能演示、答辩总结、系统说明 | Main System Agent | 整体规划与验收 |
| 小车主程序报错 | Car Agent | Runtime Server Agent |
| 摄像头、GPIO、I2C、传感器异常 | Car Agent | Hardware Module Agent |
| OLED 乱码、表情异常 | Car Agent | OLED & Audio Agent |
| 烟雾、哭声、距离报警异常 | Car Agent | Safety & Sensor Agent |
| 小车端代码提交和推送 | Car Agent | Git Deploy Agent |
| YOLO 识别、目标丢失、扫描 | PC Agent | Vision Tracking Agent |
| 舵机 PID、车身联动、距离跟随 | PC Agent | Motion Tuning Agent |
| ASR、语音控制、麦克风流 | PC Agent | ASR Voice Agent |
| 自动发现 IP、SSH 启动、运行卡顿 | PC Agent | Runtime Ops Agent |
| PC 命令包、环境包解析 | PC Agent | Protocol Client Agent |
| APP 控制按钮、舵机控制不实时 | App Agent | UI Control Agent / App Protocol Agent |
| APP 视频显示异常 | App Agent | Video Display Agent |
| APP 环境数据显示异常 | App Agent | Env Display Agent |
| APP 构建 APK | App Agent | UI Control Agent |

## 常见任务示例

### 小车不启动

路由：`PC Agent / Runtime Ops Agent` 先处理。

处理顺序：

1. 使用 `E:\conda\envs\myenv\python.exe` 运行 `raspbot_agent.py`。
2. 检查 UDP 发现是否能找到小车 IP。
3. 检查 SSH 是否能登录小车。
4. 检查远程 `/tmp/raspbot-car-server.log`。
5. 如果是小车端代码错误，再交给 `Car Agent / Runtime Server Agent`。

### 车身联动超调

路由：`PC Agent / Motion Tuning Agent`。

处理顺序：

1. 先看 `motion_tuning.json` 当前参数。
2. 普通运行不默认开额外监控；调参时可加 `--monitor`。
3. 只小步修改 `body_kp`、`body_kd_imu`、`body_dead_zone`、`body_speed_max`、`body_out_max`。
4. 每次修改后观察热加载和实际转向效果。
5. 不直接改小车端电机代码，除非调参无法解决。

### 舵机跟踪超调或太慢

路由：`PC Agent / Motion Tuning Agent`。

处理顺序：

1. 超调时优先降低 `servo_kp_x` 或 `servo_out_max_x`，必要时增加 `servo_dead_zone`。
2. 太慢时小幅增加 `servo_kp_x` 或 `servo_out_max_x`。
3. 每次只改一组参数。
4. 保持 `enable_motor_control=false` 时先只验证水平舵机稳定性。

### OLED 显示乱码

路由：`Car Agent / OLED & Audio Agent`。

处理顺序：

1. 检查 `modules/oled_face.py` 字体加载和绘制文本。
2. 优先使用已验证字体或 ASCII/英文短文本。
3. 避免依赖树莓派字体无法显示的 Unicode 符号。
4. 修改小车端后由 `Git Deploy Agent` 提交并推送。

### 语音播放歌曲异常

路由：`PC Agent / ASR Voice Agent` 和 `Car Agent / OLED & Audio Agent` 协作。

处理顺序：

1. PC Agent 检查 ASR 是否识别到播放意图。
2. Protocol Client Agent 检查 `play_song` 和 `stop_audio` 字段。
3. Car Agent 检查小车端 `songs/` 目录和 `Audio.resolve_song()`。
4. 默认保留麦克风流，不使用 `--disable-mic-stream`。

### APP 舵机控制不实时

路由：`App Agent / UI Control Agent`，必要时协调 `App Protocol Agent`。

处理顺序：

1. 检查 APP 点击或拖动事件是否持续发送控制命令。
2. 检查 APP 是否保存控制后的舵机角度。
3. 检查字段是否与小车端协议一致：`servo_angle`、`servo_angle2`。
4. 不引入旧的无用推流/接收逻辑。

### 三端字段不一致

路由：`Main System Agent`。

处理顺序：

1. Main System Agent 先确认协议字段。
2. Car Agent 更新小车端接收和执行逻辑。
3. PC Agent 更新 PC 端发送和解析逻辑。
4. App Agent 更新 APP 端发送和显示逻辑。
5. 三端都验证后，Car Agent 提交并推送小车端改动。

## 固定约束

- PC 端 Python 固定使用 `E:\conda\envs\myenv\python.exe`。
- 小车端代码改动必须提交并推送。
- PC 端和 APP 端当前不是 git 仓库，不强行提交。
- 不误删小车端 `songs/` 和 `mpu.py`。
- 普通运行不默认打开额外环境监控，避免小车端多发一路视频导致卡顿。
- 调参优先修改 `motion_tuning.json`，不要直接扩大到小车端代码。

