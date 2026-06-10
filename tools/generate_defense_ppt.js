const fs = require("fs");
const path = require("path");
const Module = require("module");

const bundledNodeModules =
  "C:/Users/26917/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const bundledPptxgenRoot = path.join(
  bundledNodeModules,
  ".pnpm",
  "pptxgenjs@4.0.1",
  "node_modules",
);
for (const p of [bundledNodeModules, bundledPptxgenRoot]) {
  if (!Module.globalPaths.includes(p)) Module.globalPaths.push(p);
}

const runtimeRequire = Module.createRequire(path.join(bundledPptxgenRoot, "package.json"));
const pptxgen = runtimeRequire("pptxgenjs");
const JSZip = runtimeRequire("jszip");

const root = "E:/bishe";
const outDir = path.join(root, "outputs", "defense_ppt");
fs.mkdirSync(outDir, { recursive: true });

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "赵国羽";
pptx.company = "电子信息学院";
pptx.subject = "毕业设计答辩";
pptx.title = "基于树莓派的婴幼儿智能陪护小车系统设计";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Georgia",
  bodyFontFace: "Microsoft YaHei",
  lang: "zh-CN",
};
pptx.defineLayout({ name: "LAYOUT_WIDE", width: 13.333, height: 7.5 });

const W = 13.333;
const H = 7.5;
const C = {
  ink: "141413",
  green: "788C5D",
  green2: "6F7F57",
  mint: "E8E6DC",
  paper: "FAF9F5",
  warm: "F5F4ED",
  orange: "D97757",
  gold: "B0AEA5",
  gray: "68665F",
  line: "E8E6DC",
  white: "FAF9F5",
  black: "141413",
  blue: "6A9BCC",
};

const A = {
  arch: path.join(root, "docs/thesis_figures/fig2-1-architecture.png"),
  protocol: path.join(root, "docs/thesis_figures/fig2-2-protocol-flow-webrtc.png"),
  front: path.join(root, "docs/thesis_figures/fig3-4-front-modules-annotated.png"),
  top: path.join(root, "docs/thesis_figures/fig3-5-top-audio-sensor-annotated.png"),
  modules: path.join(root, "docs/thesis_figures/fig4-1-module-interaction.png"),
  core: path.join(root, "docs/thesis_figures/fig4-2-core-modules.png"),
  vision: path.join(root, "docs/thesis_figures/fig4-3-vision-follow.png"),
  pid: path.join(root, "docs/thesis_figures/fig4-4-pid-loop.png"),
  cry: path.join(root, "docs/thesis_figures/fig4-5-cry-state.png"),
  voice: path.join(root, "docs/thesis_figures/fig4-6-voice-flow-clean.png"),
  yolo: path.join(root, "yolo/runs/baby_yolo26s_opt/results.png"),
  yoloPred: path.join(root, "yolo/runs/baby_yolo26s_opt/val_batch0_pred.jpg"),
  appScreen: path.join(root, "outputs/retest_app_video_20260602.png"),
  appWaiting: path.join(root, "outputs/app_waiting_before_pc.png"),
  appAfterLaunch: path.join(root, "outputs/app_after_launch.png"),
};

function slide(bg = C.paper) {
  const s = pptx.addSlide();
  s.background = { color: bg };
  return s;
}

function title(s, t, sub) {
  s.addText(t, {
    x: 0.66, y: 0.42, w: 8.9, h: 0.52,
    fontFace: "Georgia", fontSize: 25, bold: false,
    color: C.ink, margin: 0,
  });
  if (sub) {
    s.addText(sub, { x: 0.68, y: 0.96, w: 8.45, h: 0.24, fontSize: 8.5, color: C.gray, margin: 0 });
  }
  s.addShape(pptx.ShapeType.rect, { x: 11.68, y: 0.43, w: 0.92, h: 0.08, fill: { color: C.orange }, line: { color: C.orange } });
}

function footer(s, no) {
  s.addText(`毕业设计答辩  |  基于树莓派的婴幼儿智能陪护小车系统设计`, {
    x: 0.66, y: 7.04, w: 7.3, h: 0.18, fontSize: 7.8, color: "8A877E", margin: 0,
  });
  s.addText(String(no).padStart(2, "0"), {
    x: 12.26, y: 6.88, w: 0.45, h: 0.32, fontSize: 12, bold: true, color: C.orange, align: "right", margin: 0,
  });
}

function chip(s, text, x, y, color = C.green, fill = C.mint, w = 1.55) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h: 0.33, rectRadius: 0.06,
    fill: { color: fill }, line: { color: fill },
  });
  s.addText(text, { x: x + 0.12, y: y + 0.07, w: w - 0.24, h: 0.15, fontSize: 8.5, bold: true, color, align: "center", margin: 0 });
}

function card(s, x, y, w, h, heading, body, opt = {}) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.12,
    fill: { color: opt.fill || C.white, transparency: opt.transparency || 0 },
    line: { color: opt.line || C.line, width: 0.9 },
    shadow: opt.shadow === false ? undefined : { type: "outer", color: "000000", opacity: 0.035, blur: 1, angle: 45, offset: 0.4 },
  });
  if (opt.accent) s.addShape(pptx.ShapeType.rect, { x, y, w: 0.1, h, fill: { color: opt.accent }, line: { color: opt.accent } });
  s.addText(heading, { x: x + 0.24, y: y + 0.18, w: w - 0.48, h: 0.26, fontSize: 13, bold: true, color: opt.headingColor || C.ink, margin: 0 });
  s.addText(body, { x: x + 0.24, y: y + 0.58, w: w - 0.48, h: h - 0.72, fontSize: opt.bodySize || 10.5, color: opt.bodyColor || C.gray, breakLine: false, fit: "shrink", valign: "top", margin: 0.02, paraSpaceAfterPt: 5 });
}

function bullets(s, items, x, y, w, h, opts = {}) {
  const runs = [];
  items.forEach((item, idx) => {
    runs.push({ text: item, options: { bullet: { type: "ul" }, breakLine: idx !== items.length - 1 } });
  });
  s.addText(runs, {
    x, y, w, h, fontSize: opts.size || 13, color: opts.color || C.ink,
    margin: 0.05, fit: "shrink", breakLine: false, paraSpaceAfterPt: opts.space || 10,
  });
}

function coverImage(s, file, x, y, w, h, alpha = 0) {
  if (!fs.existsSync(file)) return;
  s.addImage({ path: file, x, y, w, h, sizing: { type: "cover", x, y, w, h }, transparency: alpha });
}

function containImage(s, file, x, y, w, h) {
  if (!fs.existsSync(file)) return;
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.12, fill: { color: C.white }, line: { color: C.line, width: 0.9 },
    shadow: { type: "outer", color: "000000", opacity: 0.035, blur: 1, angle: 45, offset: 0.4 },
  });
  s.addImage({ path: file, x: x + 0.08, y: y + 0.08, w: w - 0.16, h: h - 0.16, sizing: { type: "contain", w: w - 0.16, h: h - 0.16 } });
}

function sectionLabel(s, text, x, y, w = 2) {
  s.addShape(pptx.ShapeType.rect, { x, y, w: 0.12, h: 0.36, fill: { color: C.orange }, line: { color: C.orange } });
  s.addText(text, { x: x + 0.22, y: y + 0.05, w, h: 0.18, fontSize: 10, bold: true, color: C.green, margin: 0 });
}

function iconCircle(s, x, y, n, fill = C.green) {
  s.addShape(pptx.ShapeType.ellipse, { x, y, w: 0.44, h: 0.44, fill: { color: fill }, line: { color: fill } });
  s.addText(n, { x, y: y + 0.08, w: 0.44, h: 0.14, fontSize: 9, bold: true, color: C.white, align: "center", margin: 0 });
}

function placeholderImage(s, file, x, y, w, h, label) {
  if (fs.existsSync(file)) {
    containImage(s, file, x, y, w, h);
    return;
  }
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: "FFFDFC" },
    line: { color: "D8D0BF", width: 1, dash: "dash" },
  });
  s.addText(label, {
    x: x + 0.28, y: y + h / 2 - 0.12, w: w - 0.56, h: 0.24,
    fontSize: 13, bold: true, color: C.gray, align: "center", margin: 0,
  });
}

function demoSlot(s, file, x, y, w, h, label) {
  placeholderImage(s, file, x, y, w, h, `[待替换：${label}]`);
  s.addShape(pptx.ShapeType.rect, { x, y: y + h - 0.42, w, h: 0.42, fill: { color: C.ink, transparency: 8 }, line: { color: C.ink, transparency: 100 } });
  s.addText(label, { x: x + 0.1, y: y + h - 0.29, w: w - 0.2, h: 0.1, fontSize: 8.7, bold: true, color: C.white, align: "center", margin: 0 });
}

function appShowcaseSlide(stepNo, mainFile, mainLabel, sideItems, footerNo) {
  const s = slide();
  title(s, "Android App 动态展示", "同一手机区域多图切换，展示视频、控制、环境与报警完整功能");
  chip(s, "视频监控", 0.78, 1.16, stepNo === 1 ? C.white : C.green, stepNo === 1 ? C.green : C.mint, 1.15);
  chip(s, "控制联动", 2.08, 1.16, stepNo === 2 ? C.white : C.green, stepNo === 2 ? C.green : C.mint, 1.15);
  chip(s, "状态报警", 3.38, 1.16, stepNo === 3 ? C.white : C.green, stepNo === 3 ? C.green : C.mint, 1.15);
  placeholderImage(s, mainFile, 0.78, 1.62, 5.0, 4.85, `[待替换：${mainLabel}]`);
  s.addShape(pptx.ShapeType.rect, { x: 0.78, y: 6.02, w: 5.0, h: 0.45, fill: { color: C.green }, line: { color: C.green } });
  s.addText(mainLabel, { x: 0.96, y: 6.17, w: 4.64, h: 0.1, fontSize: 9.5, bold: true, color: C.white, align: "center", margin: 0 });
  sectionLabel(s, "功能说明", 6.28, 1.62);
  sideItems.forEach((item, i) => {
    card(s, 6.28, 2.12 + i * 1.32, 5.8, 0.98, item[0], item[1], { accent: [C.green, C.orange, C.gold][i], bodySize: 9.5, shadow: false });
  });
  card(s, 6.28, 5.98, 5.8, 0.48, "替换方式", "后续拍到新图后，替换左侧同尺寸截图即可；放映时翻页呈现淡入式多图切换。", { fill: C.ink, line: C.ink, accent: C.orange, bodyColor: C.white, headingColor: C.white, bodySize: 8.8, shadow: false });
  footer(s, footerNo);
}

// 1
{
  const s = slide(C.ink);
  coverImage(s, A.front, 7.25, 0, 6.08, H, 42);
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.ink, transparency: 4 }, line: { color: C.ink } });
  s.addText("基于树莓派的婴幼儿智能陪护小车系统设计", {
    x: 0.72, y: 1.22, w: 6.65, h: 1.24, fontSize: 30, bold: true, color: C.white, fit: "shrink", margin: 0,
  });
  s.addShape(pptx.ShapeType.rect, { x: 0.74, y: 2.72, w: 1.2, h: 0.13, fill: { color: C.orange }, line: { color: C.orange } });
  s.addText("毕业设计答辩", { x: 0.75, y: 3.08, w: 2.0, h: 0.25, fontSize: 15, color: C.mint, bold: true, margin: 0 });
  s.addText("学生：赵国羽  |  专业班级：机器人工程2022级1班  |  指导教师：张蕾 教授", {
    x: 0.75, y: 5.9, w: 6.8, h: 0.28, fontSize: 11, color: "DDEBE5", margin: 0,
  });
  chip(s, "Raspberry Pi", 0.75, 3.72, C.green, "E8F4EE", 1.36);
  chip(s, "YOLO26s", 2.28, 3.72, C.green, "E8F4EE", 1.1);
  chip(s, "YAMNet", 3.56, 3.72, C.green, "E8F4EE", 1.05);
  chip(s, "WebRTC", 4.78, 3.72, C.green, "E8F4EE", 1.08);
}

// 2
{
  const s = slide();
  title(s, "答辩汇报结构", "从应用问题到工程实现，再到系统功能验证");
  const items = [
    ["研究背景", "固定监护设备视角受限，异常提醒和远程交互能力不足"],
    ["总体方案", "树莓派小车、PC计算端、Android端三端协同"],
    ["硬件设计", "移动平台、多传感器、音视频和安全执行单元集成"],
    ["软件实现", "视觉跟随、哭声检测、语音交互、通信与报警"],
    ["功能成果", "视觉跟随、哭声语音、App联动与安全报警"],
    ["App展示", "移动端视频、控制、环境趋势与报警提示"],
    ["总结展望", "原型验证结论与后续优化方向"],
  ];
  items.forEach((it, i) => {
    const x = 0.82 + (i % 4) * 3.08;
    const y = 1.58 + Math.floor(i / 4) * 2.25;
    iconCircle(s, x, y + 0.05, String(i + 1), i === 0 ? C.orange : C.green);
    card(s, x + 0.56, y, 2.34, 1.45, it[0], it[1], { shadow: false, accent: i === 0 ? C.orange : C.green2, bodySize: 9.4 });
  });
  footer(s, 2);
}

// 3
{
  const s = slide();
  title(s, "研究背景与设计目标", "面向家庭看护场景的移动式辅助监护原型");
  card(s, 0.78, 1.45, 3.3, 4.35, "现有设备的痛点", "固定摄像头观察角度受限，婴幼儿移动后容易脱离视野；普通声音监测只判断音量强弱，难以区分哭声特征；远程查看、环境异常和本地执行之间缺少统一协同。", { accent: C.orange, bodySize: 12 });
  card(s, 4.55, 1.45, 3.3, 4.35, "系统设计目标", "实现婴幼儿视觉稳定跟踪与主动观察；完成哭声检测和语音对话交互；融合环境监测、分级报警、远程视频和多层级安全保护。", { accent: C.green, bodySize: 12 });
  card(s, 8.32, 1.45, 3.9, 4.35, "本文完成的工作", "完成三端协同架构、小车硬件集成、YOLO26s视觉跟随、YAMNet哭声检测、百度ASR语音控制、WebSocket/WebRTC通信和Android移动端监控。", { accent: C.gold, bodySize: 12 });
  footer(s, 3);
}

// 4
{
  const s = slide();
  title(s, "系统总体架构", "小车端执行、PC端计算、Android端交互");
  containImage(s, A.arch, 0.72, 1.35, 7.45, 4.7);
  sectionLabel(s, "三端职责", 8.55, 1.42);
  bullets(s, [
    "小车端：视频采集、传感器监测、运动执行、本地安全保护",
    "PC端：YOLO/YAMNet/ASR推理，控制决策与通信转发",
    "Android端：视频查看、环境数据、报警接收与远程控制",
  ], 8.6, 2.0, 3.75, 2.1, { size: 12, space: 7 });
  sectionLabel(s, "架构取舍", 8.55, 4.35);
  s.addText("将高算力任务放在PC端，树莓派侧保持实时硬件控制和安全兜底，兼顾原型可实现性、实时性和调试便利。", {
    x: 8.6, y: 4.9, w: 3.55, h: 0.95, fontSize: 12, color: C.ink, fit: "shrink", margin: 0.03,
  });
  footer(s, 4);
}

// 5
{
  const s = slide();
  title(s, "硬件平台与接口集成", "树莓派4B为核心，围绕看护场景完成感知、执行与交互集成");
  containImage(s, A.front, 0.78, 1.38, 5.55, 4.22);
  containImage(s, A.top, 6.75, 1.38, 5.55, 4.22);
  s.addShape(pptx.ShapeType.rect, { x: 0.78, y: 5.82, w: 5.55, h: 0.46, fill: { color: C.green }, line: { color: C.green } });
  s.addText("前端：摄像头、OLED、超声波、环境采集与底部安全检测", { x: 0.95, y: 5.97, w: 5.1, h: 0.1, fontSize: 9.5, color: C.white, align: "center", margin: 0 });
  s.addShape(pptx.ShapeType.rect, { x: 6.75, y: 5.82, w: 5.55, h: 0.46, fill: { color: C.green }, line: { color: C.green } });
  s.addText("顶部：树莓派、麦克风、扬声器、烟雾检测与线束连接", { x: 6.92, y: 5.97, w: 5.1, h: 0.1, fontSize: 9.5, color: C.white, align: "center", margin: 0 });
  footer(s, 5);
}

// 6
{
  const s = slide();
  title(s, "软件总体设计", "模块化、多任务协同和统一生命周期管理");
  containImage(s, A.modules, 0.7, 1.28, 6.1, 4.95);
  containImage(s, A.core, 7.08, 1.28, 5.45, 4.95);
  s.addText("树莓派端以 WebSocket 服务为中心，各硬件模块继承 ModuleBase 线程基类；PC端以 client.py 为主循环，统一管理 AppGateway、AsrServer、WebRtcBridge 等异步服务。", {
    x: 1.22, y: 6.18, w: 10.82, h: 0.32, fontSize: 10.2, color: C.ink, align: "center", fit: "shrink", margin: 0,
  });
  footer(s, 6);
}

// 7
{
  const s = slide();
  title(s, "关键技术一：婴幼儿视觉跟随", "YOLO26s目标检测 + BabyFilter时序滤波 + PID双环伺服控制");
  containImage(s, A.vision, 0.68, 1.25, 5.95, 2.65);
  containImage(s, A.pid, 0.68, 4.08, 5.95, 2.18);
  card(s, 7.05, 1.35, 2.35, 1.35, "目标锁定", "仅保留婴幼儿相关目标，采用NONE、CANDIDATE、LOCKED三态机制减少误检与抖动。", { accent: C.green, bodySize: 9.5 });
  card(s, 9.82, 1.35, 2.35, 1.35, "云台控制", "内环根据像素偏差调整舵机，使目标保持在画面中心。", { accent: C.orange, bodySize: 9.5 });
  card(s, 7.05, 3.12, 2.35, 1.35, "车身跟随", "外环根据舵机偏角驱动车身转向，并引入IMU偏航角速度阻尼。", { accent: C.gold, bodySize: 9.5 });
  card(s, 9.82, 3.12, 2.35, 1.35, "距离状态机", "结合超声波距离，在HOLD、FORWARD、BACKWARD、COOLDOWN间切换。", { accent: C.green2, bodySize: 9.5 });
  s.addText("核心链路：视频帧 → 检测 → 滤波 → 控制决策 → 指令回传 → 舵机与底盘执行", {
    x: 7.12, y: 5.28, w: 4.95, h: 0.45, fontSize: 13, bold: true, color: C.green, align: "center", fit: "shrink", margin: 0,
  });
  footer(s, 7);
}

// 8
{
  const s = slide();
  title(s, "关键技术二：哭声检测与语音交互", "YAMNet双阈值滞后状态机 + 百度实时ASR + 意图解析");
  containImage(s, A.cry, 0.72, 1.35, 5.35, 4.55);
  containImage(s, A.voice, 6.55, 1.35, 5.98, 4.55);
  s.addText("哭声检测通过1.0s滑动窗口、RMS能量门控和高低阈值滞后策略降低短时噪声误触发；语音链路将识别文本映射为有限动作，并设置TTS回声抑制避免自激回环。", {
    x: 1.05, y: 6.26, w: 11.15, h: 0.36, fontSize: 11, color: C.ink, align: "center", fit: "shrink", margin: 0,
  });
  footer(s, 8);
}

// 9
{
  const s = slide();
  title(s, "通信协议与移动端联动", "视频帧、控制指令和环境状态三类消息统一传输");
  containImage(s, A.protocol, 0.68, 1.25, 6.55, 4.9);
  sectionLabel(s, "通信帧类型", 7.68, 1.36);
  card(s, 7.68, 1.92, 1.45, 1.18, "0x01", "JPEG视频帧\n小车/PC → App", { fill: "FFFDFC", accent: C.green, bodySize: 9.2, shadow: false });
  card(s, 9.35, 1.92, 1.45, 1.18, "0x02", "JSON控制指令\nApp/PC → 小车", { fill: "FFFDFC", accent: C.orange, bodySize: 9.2, shadow: false });
  card(s, 11.02, 1.92, 1.45, 1.18, "0x03", "环境与报警状态\n小车/PC → App", { fill: "FFFDFC", accent: C.gold, bodySize: 9.2, shadow: false });
  sectionLabel(s, "远程方案", 7.68, 3.78);
  s.addText("本地链路采用WebSocket保证调试与控制实时性；远程监控由PC端通过WebRTC接入公网通信链路，Android端接收视频轨道，并通过DataChannel同步环境、报警和控制状态。", {
    x: 7.72, y: 4.28, w: 4.55, h: 0.88, fontSize: 11.2, color: C.ink, fit: "shrink", margin: 0.03,
  });
  card(s, 7.68, 5.32, 4.65, 0.82, "WebRTC sessionId", "App每次offer生成会话号；PC在answer/ICE中回显，App据此忽略旧重试包，提升现场重连稳定性。", {
    fill: "FFFDFC", accent: C.green2, bodySize: 8.8, shadow: false,
  });
  footer(s, 9);
}

// 10
{
  const s = slide();
  title(s, "安全保护机制", "硬件、软件和通信三个层面的安全兜底");
  const rows = [
    ["距离防撞", "超声波测距约束前进，距离过近时停止或后退"],
    ["悬崖检测", "四路红外均异常时触发强制后退与报警"],
    ["通信看门狗", "控制指令超时后自动停止，避免持续运动"],
    ["音频健康", "麦克风断连或异常时降低音频链路可信度"],
    ["报警冷却", "同类报警限频播报，状态仍持续推送到App"],
  ];
  rows.forEach((r, i) => {
    const y = 1.35 + i * 0.92;
    iconCircle(s, 0.92, y + 0.03, String(i + 1), i < 2 ? C.orange : C.green);
    s.addText(r[0], { x: 1.55, y: y + 0.04, w: 1.55, h: 0.22, fontSize: 13, bold: true, color: C.ink, margin: 0 });
    s.addText(r[1], { x: 3.25, y: y + 0.04, w: 5.55, h: 0.22, fontSize: 11.5, color: C.gray, margin: 0 });
    s.addShape(pptx.ShapeType.line, { x: 1.55, y: y + 0.58, w: 7.35, h: 0, line: { color: C.line, width: 0.6 } });
  });
  card(s, 9.45, 1.42, 2.52, 4.28, "设计原则", "小车端安全作为最后防线。即使PC端、App端或远程通信出现异常，本地仍能依据距离、悬崖、看门狗等状态优先停止、后退或报警。", { accent: C.orange, bodySize: 12 });
  footer(s, 10);
}

// 11
{
  const s = slide();
  title(s, "视觉识别与跟随效果", "YOLO26s识别结果接入目标锁定、云台伺服和车身跟随控制");
  containImage(s, A.yoloPred, 0.68, 1.22, 5.75, 3.28);
  containImage(s, A.yolo, 0.68, 4.72, 5.75, 1.25);
  card(s, 6.85, 1.32, 2.55, 1.28, "识别输入", "PC端接收小车视频帧，YOLO26s输出婴幼儿目标框与置信度。", { accent: C.green, bodySize: 9.8 });
  card(s, 9.82, 1.32, 2.55, 1.28, "时序锁定", "BabyFilter连续确认目标，短时丢帧不立即丢锁，降低画面抖动。", { accent: C.orange, bodySize: 9.8 });
  card(s, 6.85, 3.05, 2.55, 1.28, "云台跟随", "像素偏差进入PD控制，驱动舵机把目标保持在画面中心。", { accent: C.gold, bodySize: 9.8 });
  card(s, 9.82, 3.05, 2.55, 1.28, "车身响应", "当舵机偏转较大时，外环控制底盘转向，并结合IMU偏航角速度阻尼。", { accent: C.green2, bodySize: 9.8 });
  s.addText("训练曲线作为模型可用性的依据，右侧重点说明识别结果如何真正进入跟随控制闭环。", {
    x: 7.0, y: 5.28, w: 5.1, h: 0.42, fontSize: 12, bold: true, color: C.green, align: "center", fit: "shrink", margin: 0,
  });
  footer(s, 11);
}

// 12
{
  const s = slide();
  title(s, "系统功能成果展示", "围绕实物运行验证核心链路是否打通");
  const cols = [
    ["目标跟随", "检测框、BabyFilter锁定和PID控制闭环已接入小车运动"],
    ["哭声语音", "YAMNet哭声状态、百度ASR识别和有限动作指令联动"],
    ["远程监控", "App显示实时视频、环境数据、控制状态和报警提示"],
    ["安全兜底", "距离、悬崖、看门狗和alarm token共同约束危险动作"],
  ];
  cols.forEach((c, i) => {
    const x = 0.82 + (i % 2) * 6.05;
    const y = 1.43 + Math.floor(i / 2) * 2.18;
    card(s, x, y, 5.18, 1.45, c[0], c[1], { accent: [C.green, C.orange, C.gold, C.green2][i], bodySize: 11.2 });
  });
  s.addShape(pptx.ShapeType.rect, { x: 0.82, y: 6.05, w: 11.25, h: 0.5, fill: { color: C.ink }, line: { color: C.ink } });
  s.addText("验证结论：小车端执行、PC端推理和App端交互已经形成完整闭环，能够支撑答辩现场的实物功能展示。", {
    x: 1.0, y: 6.22, w: 10.88, h: 0.12, fontSize: 10.8, bold: true, color: C.white, align: "center", fit: "shrink", margin: 0,
  });
  footer(s, 12);
}

// 13-15
appShowcaseSlide(1, A.appScreen, "App实时视频与远程监控画面", [
  ["视频链路", "App通过WebRTC显示PC处理后的实时画面，适合答辩展示远程监护效果。"],
  ["连接恢复", "PC晚启动或链路抖动时，App会自动重试offer并恢复视频。"],
  ["待补素材", "后续可替换为手机现场拍摄或投屏截图，保持左侧尺寸不变。"],
], 13);

appShowcaseSlide(2, A.appWaiting, "App连接等待与控制准备画面", [
  ["控制入口", "方向、停止、跟随模式和音量等操作集中在移动端。"],
  ["命令转发", "控制命令经DataChannel或WebSocket送到PC，再转发给小车端执行。"],
  ["待补素材", "建议补拍远程控制按钮、跟随模式打开、音量控制三类截图。"],
], 14);

appShowcaseSlide(3, A.appAfterLaunch || A.appScreen, "App环境状态与报警展示画面", [
  ["环境监测", "温度、距离、光照、哭声分数等状态可在App侧集中查看。"],
  ["报警语义", "alarm token统一表达距离、悬崖、哭声、温度和光照异常。"],
  ["待补素材", "建议补拍报警弹窗、趋势图或环境数据异常时的App界面。"],
], 15);

// 16
{
  const s = slide();
  title(s, "总结与展望", "低成本树莓派移动平台用于婴幼儿辅助看护的原型验证");
  card(s, 0.78, 1.35, 5.5, 4.55, "工作总结", "本文完成了一套三端协同的婴幼儿智能陪护小车系统。硬件上集成摄像头云台、环境采集、姿态感知、音视频与运动底盘；软件上实现目标跟随、哭声检测、语音控制、远程视频、报警同步和多层级安全保护。实物调试验证了系统原型的可行性。", { accent: C.green, bodySize: 12 });
  card(s, 6.85, 1.35, 5.5, 4.55, "后续展望", "进一步扩充真实家庭场景数据，提高遮挡、光照变化和多人场景下的检测稳定性；增强复杂室内环境中的路径规划和自主避障；引入更精细的回声消除、隐私保护、权限认证和长期运行日志机制。", { accent: C.orange, bodySize: 12 });
  footer(s, 16);
}

// 17
{
  const s = slide(C.ink);
  s.addText("敬请各位老师批评指正", {
    x: 1.45, y: 2.18, w: 10.4, h: 0.72, fontSize: 34, bold: true, color: C.white, align: "center", margin: 0,
  });
  s.addShape(pptx.ShapeType.rect, { x: 5.72, y: 3.25, w: 1.88, h: 0.12, fill: { color: C.orange }, line: { color: C.orange } });
  s.addText("THANK YOU", { x: 4.85, y: 3.75, w: 3.65, h: 0.35, fontSize: 15, color: C.mint, align: "center", margin: 0 });
  s.addText("赵国羽  |  机器人工程2022级1班", { x: 4.25, y: 5.35, w: 4.85, h: 0.24, fontSize: 11.5, color: "DDEBE5", align: "center", margin: 0 });
}

const outputSuffix = process.env.RASPBOT_PPT_SUFFIX || "";
const finalPath = path.join(outDir, `基于树莓派的婴幼儿智能陪护小车系统设计-答辩PPT${outputSuffix}.pptx`);

async function addFadeTransitions(fileName, slideNumbers) {
  const data = fs.readFileSync(fileName);
  const zip = await JSZip.loadAsync(data);
  for (const no of slideNumbers) {
    const slidePath = `ppt/slides/slide${no}.xml`;
    const entry = zip.file(slidePath);
    if (!entry) continue;
    let xml = await entry.async("string");
    xml = xml.replace(/<p:transition[\s\S]*?<\/p:transition>/g, "");
    xml = xml.replace(
      /(<p:cSld\b)/,
      '<p:transition spd="med"><p:fade/></p:transition>$1',
    );
    zip.file(slidePath, xml);
  }
  const out = await zip.generateAsync({
    type: "nodebuffer",
    compression: "DEFLATE",
  });
  fs.writeFileSync(fileName, out);
}

pptx.writeFile({ fileName: finalPath })
  .then(() => addFadeTransitions(finalPath, [13, 14, 15]))
  .then(() => {
    console.log(finalPath);
  });
