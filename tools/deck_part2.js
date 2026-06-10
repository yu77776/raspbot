// 幻灯片内容 第 2 部分（第 7 页 ~ 致谢）
const D = require("./build_defense_deck.js");
require("./deck_part1.js");
const { pptx, newSlide, rail, head, panel, infoCard, stat, pill, figure, K, F, A, W, H, RAIL_W } = D;

// ════ 7. 系统演示（动画）════
{
  const s = newSlide();
  rail(s, 3, 7);
  head(s, "04 · LIVE SIMULATION", "系统演示 · 双环跟随控制");
  const gif = `${D.ROOT_ASSETS = D.path.join("E:/bishe/outputs/defense_ppt/assets", "vision_follow_demo.gif")}`;
  // 动画主体
  const gx = RAIL_W + 0.55, gw = 7.0, gh = 4.0;
  panel(s, gx, 1.8, gw, gh + 0.55, { fill: K.bg2, accent: K.lime });
  if (D.fs.existsSync(gif))
    s.addImage({ path: gif, x: gx + 0.15, y: 1.95, w: gw - 0.3, h: gh, sizing: { type: "contain", w: gw - 0.3, h: gh } });
  s.addText("放映时自动循环播放：左为摄像头内环 PD 云台伺服，右为俯视外环车身跟随与距离状态机", { x: gx + 0.2, y: 1.95 + gh + 0.08, w: gw - 0.4, h: 0.36, fontSize: 9, color: K.dim, align: "center", valign: "middle", margin: 0 });

  // 右侧解读
  const rx = RAIL_W + 7.75, rw = 2.9;
  infoCard(s, rx, 1.8, rw, 1.42, "① 内环 · 像素回中", "目标框锁定宝宝，像素误差经 PD 实时驱动舵机，把目标拉回画面中心。", { accent: K.amber, bs: 9.2, ts: 11.5 });
  infoCard(s, rx, 3.36, rw, 1.42, "② 外环 · 车身跟随", "舵机偏角较大时驱动底盘转向，IMU 偏航角速度阻尼抑制过冲。", { accent: K.sky, bs: 9.2, ts: 11.5 });
  infoCard(s, rx, 4.92, rw, 1.43, "③ 距离状态机", "超声波距离在 HOLD / FORWARD / BACKWARD 间切换，维持安全跟随距离。", { accent: K.lime, bs: 9.2, ts: 11.5 });
}

// ════ 8. 核心算法一：视觉跟随 ════
{
  const s = newSlide();
  rail(s, 3, 8);
  head(s, "04 · VISION TRACKING", "核心算法（一）· 婴幼儿视觉跟随");
  figure(s, A.vision, RAIL_W + 0.55, 1.8, 5.4, 2.55, null);
  figure(s, A.pid, RAIL_W + 0.55, 4.5, 5.4, 1.9, null);
  const x = RAIL_W + 6.15, w = 4.5;
  infoCard(s, x, 1.8, w, 1.08, "① 目标锁定 · BabyFilter", "NONE→CANDIDATE→LOCKED 三态机；连续 3 帧确认入锁，丢失 5 帧才解锁，抑制误检抖动。", { accent: K.lime, bs: 9.2, ts: 11.5 });
  infoCard(s, x, 3.02, w, 1.08, "② 云台内环 · PD 控制", "像素偏差经 PD（Kp=0.1, Kd=0.012）驱动水平/俯仰舵机，把目标锁定在画面中心。", { accent: K.amber, bs: 9.2, ts: 11.5 });
  infoCard(s, x, 4.24, w, 1.08, "③ 车身外环 · 偏角驱动", "舵机偏角较大时驱动底盘转向，并引入 IMU 偏航角速度阻尼抑制过冲。", { accent: K.sky, bs: 9.2, ts: 11.5 });
  infoCard(s, x, 5.46, w, 0.94, "④ 距离状态机", "结合超声波在 HOLD / FORWARD / BACKWARD / COOLDOWN 间切换，维持安全跟随距离。", { accent: K.rose, bs: 9.2, ts: 11.5 });
}

// ════ 9. 视觉成果 + 指标 ════
{
  const s = newSlide();
  rail(s, 3, 9);
  head(s, "04 · MODEL PERFORMANCE", "视觉识别与跟随效果");
  figure(s, A.yoloPred, RAIL_W + 0.55, 1.8, 5.0, 3.0, "YOLO26s 验证集预测：婴幼儿目标框与置信度");
  figure(s, A.yoloRes, RAIL_W + 0.55, 4.95, 5.0, 1.45, null);
  // 右侧指标
  const x = RAIL_W + 5.75;
  D.stat(s, x, 1.8, 2.42, "0.789", "", "mAP@0.5 检测精度", K.lime);
  D.stat(s, x + 2.6, 1.8, 2.4, "0.525", "", "mAP@0.5:0.95", K.amber);
  D.stat(s, x, 3.5, 2.42, "150", "ep", "训练轮次 · imgsz 640", K.sky);
  D.stat(s, x + 2.6, 3.5, 2.4, "3→5", "帧", "确认入锁 / 丢失解锁", K.lime);
  infoCard(s, x, 5.2, 5.02, 1.2, "从识别到运动的闭环", "检测框 → BabyFilter 时序锁定 → PD 云台伺服 → 外环车身跟随 → 指令回传执行，训练曲线佐证模型可用性，重点在于结果真正进入跟随控制闭环。", { accent: K.lime, bs: 9.5, ts: 12 });
}

// ════ 10. 核心算法二：哭声与语音 ════
{
  const s = newSlide();
  rail(s, 3, 10);
  head(s, "04 · AUDIO & VOICE", "核心算法（二）· 哭声检测与语音交互");
  figure(s, A.cry, RAIL_W + 0.55, 1.8, 4.7, 4.0, "YAMNet 双阈值滞后状态机");
  figure(s, A.voice, RAIL_W + 5.45, 1.8, 5.2, 4.0, "语音链路：ASR → 意图解析 → 有限动作");
  // 底部参数条
  const params = [
    ["触发/释放阈值", "0.60 / 0.40"],
    ["触发/释放时长", "2.0s / 3.0s"],
    ["分析窗 / 步进", "1.0s / 0.5s"],
    ["能量门控 RMS", "≥ 0.004"],
  ];
  const bx = RAIL_W + 0.55, bw = 2.45, gap = 0.18;
  params.forEach((p, i) => {
    const x = bx + i * (bw + gap);
    panel(s, x, 5.95, bw, 0.78, { fill: K.bg2, accent: i % 2 ? K.amber : K.lime });
    s.addText(p[0], { x: x + 0.22, y: 6.04, w: bw - 0.4, h: 0.2, fontSize: 8.5, color: K.dim, margin: 0 });
    s.addText(p[1], { x: x + 0.22, y: 6.28, w: bw - 0.4, h: 0.32, fontSize: 14, bold: true, color: K.ink, fontFace: F.head, margin: 0 });
  });
}

// ════ 11. 通信协议 ════
{
  const s = newSlide();
  rail(s, 4, 11);
  head(s, "05 · PROTOCOL", "通信协议与移动端联动");
  figure(s, A.proto, RAIL_W + 0.55, 1.8, 5.85, 4.6, null);
  const x = RAIL_W + 6.6, w = 4.05;
  // 三种帧
  const frames = [["0x01", "JPEG 视频帧", "Car/PC → App", K.sky], ["0x02", "JSON 控制指令", "App/PC → Car", K.amber], ["0x03", "环境与报警状态", "Car/PC → App", K.lime]];
  frames.forEach((f, i) => {
    const y = 1.8 + i * 0.92;
    panel(s, x, y, w, 0.78, { accent: f[3] });
    s.addText(f[0], { x: x + 0.24, y: y + 0.22, w: 1.0, h: 0.4, fontSize: 18, bold: true, color: f[3], fontFace: F.head, margin: 0 });
    s.addText(f[1], { x: x + 1.4, y: y + 0.14, w: w - 1.6, h: 0.3, fontSize: 12, bold: true, color: K.ink, margin: 0 });
    s.addText(f[2], { x: x + 1.4, y: y + 0.44, w: w - 1.6, h: 0.24, fontSize: 9, color: K.dim, margin: 0 });
  });
  infoCard(s, x, 4.62, w, 1.78, "本地 + 远程 双链路", "本地 WebSocket 保证调试与控制实时性；远程经 WebRTC 穿透公网，App 接收视频轨道，并通过 DataChannel 同步环境、报警与控制状态。两条链路对 App 透明切换，兼顾局域网低延迟与外网可达性。", { accent: K.lime, bs: 9.8, ts: 12 });
}

// ════ 12. 安全机制 ════
{
  const s = newSlide();
  rail(s, 5, 12);
  head(s, "06 · FAIL-SAFE", "三层失效安全防护");
  const rows = [
    ["距离防撞", "超声波约束前进，过近即停止或后退", K.amber],
    ["悬崖检测", "循迹传感器异常触发强制后退与蜂鸣报警", K.rose],
    ["通信看门狗", "控制指令超时 0.8s 自动停车，杜绝失控持续运动", K.amber],
    ["音频健康", "麦克风断连 5s 降低音频链路可信度", K.sky],
    ["报警冷却", "同类报警限频播报，状态仍持续推送 App", K.lime],
  ];
  const x = RAIL_W + 0.55;
  rows.forEach((r, i) => {
    const y = 1.85 + i * 0.86;
    panel(s, x, y, 6.4, 0.74, { accent: r[2] });
    s.addShape(pptx.ShapeType.ellipse, { x: x + 0.22, y: y + 0.18, w: 0.38, h: 0.38, fill: { color: K.panelHi }, line: { color: r[2], width: 1.2 } });
    s.addText(String(i + 1), { x: x + 0.22, y: y + 0.24, w: 0.38, h: 0.26, fontSize: 13, bold: true, color: r[2], align: "center", fontFace: F.head, margin: 0 });
    s.addText(r[0], { x: x + 0.78, y: y + 0.13, w: 1.7, h: 0.3, fontSize: 13, bold: true, color: K.ink, fontFace: F.head, margin: 0 });
    s.addText(r[1], { x: x + 2.5, y: y + 0.16, w: 3.8, h: 0.42, fontSize: 9.8, color: K.dim, valign: "middle", margin: 0 });
  });
  infoCard(s, RAIL_W + 7.2, 1.85, 3.45, 4.45, "设计原则：本地最后防线", "即使 PC、App 或远程通信全部异常，小车端仍能依据距离、悬崖、看门狗等本地状态优先停止、后退或报警——安全不依赖云端，永远兜底在硬件最近处。", { accent: K.rose, bs: 11.5 });
}

// ════ 13. 功能成果总览 ════
{
  const s = newSlide();
  rail(s, 6, 13);
  head(s, "07 · RESULTS", "系统功能成果总览");
  const cards = [
    ["目标跟随", "检测框 + BabyFilter 锁定 + PID 控制闭环已接入小车运动", K.lime],
    ["哭声语音", "YAMNet 哭声状态 + 百度 ASR 识别 + 有限动作指令联动", K.amber],
    ["远程监控", "App 显示实时视频、环境数据、控制状态与报警提示", K.sky],
    ["安全兜底", "距离/悬崖/看门狗/alarm token 共同约束危险动作", K.rose],
  ];
  const x0 = RAIL_W + 0.55, cw = 5.06, ch = 1.72, gx = 0.34, gy = 0.3;
  cards.forEach((c, i) => {
    const x = x0 + (i % 2) * (cw + gx);
    const y = 1.85 + Math.floor(i / 2) * (ch + gy);
    infoCard(s, x, y, cw, ch, c[0], c[1], { accent: c[2], bs: 11, ts: 14 });
  });
  panel(s, x0, 5.85, cw * 2 + gx, 0.6, { fill: K.panelHi, accent: K.lime });
  s.addText("验证结论：小车执行、PC 推理与 App 交互已形成完整闭环，可支撑答辩现场实物功能展示。", { x: x0 + 0.3, y: 5.98, w: cw * 2 + gx - 0.5, h: 0.34, fontSize: 11, bold: true, color: K.ink, valign: "middle", margin: 0 });
}

// ════ 14. App 展示 ════
{
  const s = newSlide();
  rail(s, 6, 14);
  head(s, "07 · MOBILE APP", "Android App 功能展示");
  figure(s, A.appVideo, RAIL_W + 0.55, 1.8, 3.15, 4.6, "实时视频");
  figure(s, A.appWait, RAIL_W + 3.85, 1.8, 3.15, 4.6, "连接 / 控制");
  figure(s, A.appLaunch, RAIL_W + 7.15, 1.8, 3.5, 4.6, "环境 / 报警");
}

// ════ 15. 总结展望 ════
{
  const s = newSlide();
  rail(s, 7, 15);
  head(s, "08 · CONCLUSION", "总结与展望");
  infoCard(s, RAIL_W + 0.55, 1.85, 5.0, 4.55, "工作总结", "完成了一套三端协同的婴幼儿智能陪护小车系统。硬件集成摄像头云台、环境采集、姿态感知、音视频与运动底盘；软件实现目标跟随、哭声检测、语音控制、远程视频、报警同步与多层级安全保护。实物调试验证了原型可行性。", { accent: K.lime, bs: 11.5 });
  infoCard(s, RAIL_W + 5.75, 1.85, 4.9, 4.55, "后续展望", "扩充真实家庭场景数据，提升遮挡、光照变化与多人场景下的检测稳定性；增强复杂室内环境的路径规划与自主避障；引入更精细的回声消除、隐私保护、权限认证与长期运行日志机制。", { accent: K.amber, bs: 11.5 });
}

// ════ 16. 致谢 ════
{
  const s = newSlide(K.bg);
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 3.5, w: W, h: 0.06, fill: { color: K.line }, line: { color: K.line } });
  s.addShape(pptx.ShapeType.roundRect, { x: W / 2 - 0.3, y: 1.95, w: 0.6, h: 0.6, rectRadius: 0.13, fill: { color: K.lime }, line: { color: K.lime } });
  s.addText("R", { x: W / 2 - 0.3, y: 2.08, w: 0.6, h: 0.36, fontSize: 24, bold: true, color: K.bg, align: "center", fontFace: F.head, margin: 0 });
  s.addText("敬请各位老师批评指正", { x: 1, y: 2.95, w: W - 2, h: 0.7, fontSize: 34, bold: true, color: K.ink, align: "center", fontFace: F.head, margin: 0 });
  s.addText("THANK YOU FOR YOUR ATTENTION", { x: 1, y: 3.95, w: W - 2, h: 0.3, fontSize: 12, color: K.lime, align: "center", fontFace: F.head, charSpacing: 3, margin: 0 });
  s.addText("赵国羽  ·  机器人工程 2022 级 1 班  ·  指导教师 张蕾 教授", { x: 1, y: 4.5, w: W - 2, h: 0.3, fontSize: 12, color: K.dim, align: "center", margin: 0 });
}

module.exports = {};
