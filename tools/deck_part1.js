// 幻灯片内容 第 1 部分（封面 ~ 第 9 页）
const D = require("./build_defense_deck.js");
const { pptx, newSlide, rail, head, panel, infoCard, stat, pill, figure, K, F, A, W, H, RAIL_W } = D;

// ════ 1. 封面 ════
{
  const s = newSlide(K.bg);
  // 右侧实物图，暗化压底
  s.addShape(pptx.ShapeType.rect, { x: 8.0, y: 0, w: W - 8.0, h: H, fill: { color: K.bg2 }, line: { color: K.bg2 } });
  if (D.fs.existsSync(A.front))
    s.addImage({ path: A.front, x: 8.0, y: 0, w: W - 8.0, h: H, sizing: { type: "cover", w: W - 8.0, h: H }, transparency: 22 });
  s.addShape(pptx.ShapeType.rect, { x: 8.0, y: 0, w: 0.05, h: H, fill: { color: K.lime }, line: { color: K.lime } });
  // 左侧文字
  s.addShape(pptx.ShapeType.roundRect, { x: 0.9, y: 1.1, w: 0.56, h: 0.56, rectRadius: 0.12, fill: { color: K.lime }, line: { color: K.lime } });
  s.addText("R", { x: 0.9, y: 1.22, w: 0.56, h: 0.34, fontSize: 22, bold: true, color: K.bg, align: "center", fontFace: F.head, margin: 0 });
  s.addText("RASPBOT · 婴幼儿智能陪护", { x: 1.62, y: 1.2, w: 6, h: 0.34, fontSize: 12, bold: true, color: K.lime, fontFace: F.head, charSpacing: 2, margin: 0 });

  s.addText("基于树莓派的婴幼儿\n智能陪护小车系统设计", { x: 0.88, y: 2.35, w: 7.2, h: 1.9, fontSize: 38, bold: true, color: K.ink, fontFace: F.head, lineSpacingMultiple: 1.02, margin: 0 });
  s.addShape(pptx.ShapeType.rect, { x: 0.92, y: 4.35, w: 1.4, h: 0.1, fill: { color: K.amber }, line: { color: K.amber } });
  s.addText("三端协同 · 视觉跟随 · 哭声识别 · 远程监护", { x: 0.9, y: 4.6, w: 7, h: 0.3, fontSize: 13, color: K.dim, margin: 0 });

  pill(s, "Raspberry Pi 4B", 0.9, 5.25, 1.85);
  pill(s, "YOLO26s", 2.85, 5.25, 1.25, K.amber);
  pill(s, "YAMNet", 4.2, 5.25, 1.2, K.sky);
  pill(s, "WebRTC", 5.5, 5.25, 1.25, K.lime);

  s.addText([
    { text: "学生  ", options: { color: K.faint } }, { text: "赵国羽", options: { color: K.ink, bold: true } },
    { text: "      专业  ", options: { color: K.faint } }, { text: "机器人工程 2022 级 1 班", options: { color: K.ink } },
    { text: "      指导教师  ", options: { color: K.faint } }, { text: "张蕾 教授", options: { color: K.ink } },
  ], { x: 0.9, y: 6.45, w: 7, h: 0.3, fontSize: 11, margin: 0 });
}

// ════ 2. 目录 ════
{
  const s = newSlide();
  rail(s, -1, 2);
  head(s, "OUTLINE", "汇报内容");
  const items = [
    ["01", "研究背景", "看护痛点与设计目标", K.lime],
    ["02", "总体方案", "三端协同系统架构", K.amber],
    ["03", "硬件设计", "感知 · 执行 · 交互集成", K.sky],
    ["04", "核心算法", "视觉跟随与哭声语音", K.lime],
    ["05", "通信协议", "WebSocket 与 WebRTC 双链路", K.amber],
    ["06", "安全机制", "三层失效安全防护", K.rose],
    ["07", "系统验证", "实物运行与 App 展示", K.sky],
    ["08", "总结展望", "结论与后续方向", K.lime],
  ];
  const x0 = RAIL_W + 0.55, cw = 5.1, ch = 1.12, gx = 0.34, gy = 0.28;
  items.forEach((it, i) => {
    const x = x0 + (i % 2) * (cw + gx);
    const y = 1.85 + Math.floor(i / 2) * (ch + gy);
    panel(s, x, y, cw, ch, { accent: it[3] });
    s.addText(it[0], { x: x + 0.28, y: y + 0.22, w: 1.0, h: 0.7, fontSize: 30, bold: true, color: it[3], fontFace: F.head, margin: 0 });
    s.addText(it[1], { x: x + 1.35, y: y + 0.24, w: cw - 1.6, h: 0.3, fontSize: 14, bold: true, color: K.ink, fontFace: F.head, margin: 0 });
    s.addText(it[2], { x: x + 1.35, y: y + 0.62, w: cw - 1.6, h: 0.3, fontSize: 9.5, color: K.dim, margin: 0 });
  });
}

// ════ 3. 研究背景 ════
{
  const s = newSlide();
  rail(s, 0, 3);
  head(s, "01 · BACKGROUND", "研究背景与设计目标");
  const x0 = RAIL_W + 0.55;

  // 顶部：三个场景痛点指标条（填充上半区）
  const pains = [
    ["视角", "固定", "摄像头固定，宝宝移动即脱离视野", K.rose],
    ["听觉", "只测响度", "普通声音监测难分辨哭声特征", K.amber],
    ["协同", "各自为政", "远程查看 / 环境感知 / 本地执行割裂", K.sky],
  ];
  const pw = 3.45, pgap = 0.3;
  pains.forEach((p, i) => {
    const x = x0 + i * (pw + pgap);
    panel(s, x, 1.8, pw, 1.5, { accent: p[3] });
    s.addText(p[0], { x: x + 0.26, y: 1.96, w: 1.4, h: 0.26, fontSize: 10, bold: true, color: p[3], fontFace: F.head, margin: 0 });
    s.addText(p[1], { x: x + 0.24, y: 2.2, w: pw - 0.5, h: 0.46, fontSize: 22, bold: true, color: K.ink, fontFace: F.head, margin: 0 });
    s.addText(p[2], { x: x + 0.26, y: 2.74, w: pw - 0.5, h: 0.46, fontSize: 9.2, color: K.dim, valign: "top", margin: 0 });
  });

  // 下半区 左：目标详述
  infoCard(s, x0, 3.55, 5.55, 2.85, "系统设计目标", "把家庭看护从「固定一个角度」升级为「会移动、会看、会听、会报警」的智能体——实现婴幼儿视觉稳定跟踪与主动观察、哭声检测与语音对话交互，融合环境监测、分级报警、远程视频与多层级安全保护，形成可落地的移动监护原型。", { accent: K.lime, bs: 11.5 });

  // 下半区 右：五项能力清单
  const rx = x0 + 5.85, rw = 4.25;
  panel(s, rx, 3.55, rw, 2.85, { fill: K.bg2, accent: K.amber });
  s.addText("本文交付的五项能力", { x: rx + 0.28, y: 3.74, w: rw - 0.5, h: 0.3, fontSize: 13, bold: true, color: K.amber, fontFace: F.head, margin: 0 });
  const caps = [
    ["视觉跟随婴幼儿", "YOLO26s + 双环伺服"],
    ["哭声主动识别", "YAMNet 双阈值状态机"],
    ["语音自然交互", "百度 ASR + 意图解析"],
    ["环境分级报警", "alarm token 统一语义"],
    ["失效安全兜底", "本地三层防护"],
  ];
  caps.forEach((c, i) => {
    const y = 4.16 + i * 0.44;
    s.addShape(pptx.ShapeType.ellipse, { x: rx + 0.3, y: y + 0.04, w: 0.12, h: 0.12, fill: { color: K.lime }, line: { color: K.lime } });
    s.addText(c[0], { x: rx + 0.54, y, w: 2.0, h: 0.3, fontSize: 10.5, bold: true, color: K.ink, margin: 0 });
    s.addText(c[1], { x: rx + 2.4, y: y + 0.02, w: rw - 2.6, h: 0.3, fontSize: 9, color: K.dim, align: "right", margin: 0 });
  });
}

// ════ 4. 总体方案 ════
{
  const s = newSlide();
  rail(s, 1, 4);
  head(s, "02 · ARCHITECTURE", "系统总体架构");
  figure(s, A.arch, RAIL_W + 0.55, 1.8, 6.9, 4.6, null);
  const x = RAIL_W + 7.7, w = 3.25;
  infoCard(s, x, 1.8, w, 1.42, "小车端 · 执行", "视频采集、多传感器监测、运动底盘执行、本地安全兜底。", { accent: K.sky, bs: 9.5, ts: 12 });
  infoCard(s, x, 3.36, w, 1.42, "PC 端 · 大脑", "YOLO / YAMNet / ASR 推理，控制决策与三端通信转发。", { accent: K.lime, bs: 9.5, ts: 12 });
  infoCard(s, x, 4.92, w, 1.48, "App 端 · 交互", "实时视频、环境趋势、报警接收与远程控制操作。", { accent: K.amber, bs: 9.5, ts: 12 });
}

// ════ 5. 硬件设计 ════
{
  const s = newSlide();
  rail(s, 2, 5);
  head(s, "03 · HARDWARE", "硬件平台与接口集成");
  figure(s, A.front, RAIL_W + 0.55, 1.8, 4.95, 4.05, "前端：摄像头云台 · OLED · 超声波 · 环境采集 · 底部循迹");
  figure(s, A.top, RAIL_W + 5.7, 1.8, 4.95, 4.05, "顶部：树莓派 4B · 麦克风 · 扬声器 · 烟雾检测 · 线束");
  s.addText("以树莓派 4B 为核心，围绕看护场景集成感知、执行与交互单元；硬件层只保留实时控制与安全检测，高算力任务全部上移至 PC。", { x: RAIL_W + 0.55, y: 6.0, w: 10.1, h: 0.5, fontSize: 10.5, color: K.dim, align: "center", margin: 0 });
}

// ════ 6. 软件总体 ════
{
  const s = newSlide();
  rail(s, 1, 6);
  head(s, "02 · SOFTWARE", "软件总体设计");
  figure(s, A.modint, RAIL_W + 0.55, 1.8, 5.05, 4.6, null);
  figure(s, A.core, RAIL_W + 5.8, 1.8, 4.85, 4.6, null);
  s.addText("小车端以 WebSocket 服务为中心，硬件模块继承 ModuleBase 线程基类；PC 端以 client.py 主循环统一编排 AppGateway / AsrServer / WebRtcBridge 等异步服务。", { x: RAIL_W + 0.55, y: 6.55, w: 10.1, h: 0.42, fontSize: 10, color: K.dim, align: "center", margin: 0 });
}

module.exports = {};
