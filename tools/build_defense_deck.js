// 全新设计：婴幼儿智能陪护小车 — 答辩演示
// 视觉方向：深色"夜间监护"主调 + 青柠强调色，左侧竖向章节脊柱，数据驱动卡片。
// 与历史版本无任何复用，独立设计系统。
const fs = require("fs");
const path = require("path");
const Module = require("module");

const bundled =
  "C:/Users/26917/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const pptxRoot = path.join(bundled, ".pnpm", "pptxgenjs@4.0.1", "node_modules");
for (const p of [bundled, pptxRoot])
  if (!Module.globalPaths.includes(p)) Module.globalPaths.push(p);
const req = Module.createRequire(path.join(pptxRoot, "package.json"));
const PptxGen = req("pptxgenjs");
const JSZip = req("jszip");

const ROOT = "E:/bishe";
const OUT = path.join(ROOT, "outputs", "defense_ppt");
fs.mkdirSync(OUT, { recursive: true });

const W = 13.333;
const H = 7.5;

// ── 调色板：深炭底 + 青柠 + 暖琥珀 ──
const K = {
  bg: "0F1714",       // 深森林炭
  bg2: "14201B",      // 略浅
  panel: "1B2A23",    // 卡片底
  panelHi: "223830",  // 卡片高亮
  rail: "0A100D",     // 左脊柱
  ink: "EAF2EC",      // 主文字
  dim: "8FA89A",      // 次文字
  faint: "5E726A",    // 最弱
  lime: "9EE37D",     // 主强调 青柠
  lime2: "C7F0A8",
  amber: "F2B872",    // 暖点缀
  sky: "7FC8E8",      // 数据蓝
  rose: "E8927C",     // 警示
  line: "2A3A32",     // 分隔线
  white: "FFFFFF",
};

const F = { head: "Verdana", body: "Microsoft YaHei" };

const A = {
  arch:   `${ROOT}/docs/thesis_figures/fig2-1-architecture.png`,
  proto:  `${ROOT}/docs/thesis_figures/fig2-2-protocol-flow-webrtc.png`,
  front:  `${ROOT}/docs/thesis_figures/fig3-4-front-modules-annotated.png`,
  top:    `${ROOT}/docs/thesis_figures/fig3-5-top-audio-sensor-annotated.png`,
  modint: `${ROOT}/docs/thesis_figures/fig4-1-module-interaction.png`,
  core:   `${ROOT}/docs/thesis_figures/fig4-2-core-modules.png`,
  vision: `${ROOT}/docs/thesis_figures/fig4-3-vision-follow.png`,
  pid:    `${ROOT}/docs/thesis_figures/fig4-4-pid-loop.png`,
  cry:    `${ROOT}/docs/thesis_figures/fig4-5-cry-state.png`,
  voice:  `${ROOT}/docs/thesis_figures/fig4-6-voice-flow-clean.png`,
  yoloRes:`${ROOT}/yolo/runs/baby_yolo26s_opt/results.png`,
  yoloPred:`${ROOT}/yolo/runs/baby_yolo26s_opt/val_batch0_pred.jpg`,
  appVideo:`${ROOT}/outputs/retest_app_video_20260602.png`,
  appWait:`${ROOT}/outputs/app_waiting_before_pc.png`,
  appLaunch:`${ROOT}/outputs/app_after_launch.png`,
};

const pptx = new PptxGen();
pptx.defineLayout({ name: "WIDE", width: W, height: H });
pptx.layout = "WIDE";
pptx.author = "赵国羽";
pptx.company = "电子信息学院";
pptx.title = "基于树莓派的婴幼儿智能陪护小车系统设计";
pptx.theme = { headFontFace: F.head, bodyFontFace: F.body, lang: "zh-CN" };

const RAIL_W = 1.7; // 左脊柱宽度

// 章节定义，驱动左脊柱进度
const SECTIONS = ["背景", "方案", "硬件", "算法", "通信", "安全", "验证", "总结"];
const TOTAL_PAGES = 16; // 封面+目录+13内容+致谢；改页数时同步此处

function newSlide(bg = K.bg) {
  const s = pptx.addSlide();
  s.background = { color: bg };
  return s;
}

// 左侧竖向脊柱 + 章节进度点
function rail(s, activeIdx, pageNo) {
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: RAIL_W, h: H, fill: { color: K.rail }, line: { color: K.rail } });
  // 顶部 logo 块
  s.addShape(pptx.ShapeType.roundRect, { x: 0.34, y: 0.42, w: 0.46, h: 0.46, rectRadius: 0.1, fill: { color: K.lime }, line: { color: K.lime } });
  s.addText("R", { x: 0.34, y: 0.5, w: 0.46, h: 0.3, fontSize: 17, bold: true, color: K.bg, align: "center", fontFace: F.head, margin: 0 });
  s.addText("RASPBOT", { x: 0.34, y: 1.0, w: 1.2, h: 0.2, fontSize: 9, bold: true, color: K.ink, fontFace: F.head, charSpacing: 1, margin: 0 });
  s.addText("陪护小车", { x: 0.34, y: 1.22, w: 1.2, h: 0.16, fontSize: 7.5, color: K.faint, margin: 0 });
  // 章节进度
  const top = 1.95, gap = 0.5;
  SECTIONS.forEach((name, i) => {
    const y = top + i * gap;
    const on = i === activeIdx;
    s.addShape(pptx.ShapeType.ellipse, { x: 0.4, y: y + 0.02, w: 0.14, h: 0.14, fill: { color: on ? K.lime : K.line }, line: { color: on ? K.lime : K.line } });
    if (i < SECTIONS.length - 1)
      s.addShape(pptx.ShapeType.line, { x: 0.47, y: y + 0.16, w: 0, h: gap - 0.16, line: { color: K.line, width: 1 } });
    s.addText(name, { x: 0.66, y: y - 0.02, w: 0.95, h: 0.2, fontSize: on ? 9.5 : 8.5, bold: on, color: on ? K.lime : K.faint, margin: 0 });
  });
  // 底部页码
  s.addText(String(pageNo).padStart(2, "0"), { x: 0.34, y: 6.9, w: 1.0, h: 0.3, fontSize: 13, bold: true, color: K.lime, fontFace: F.head, margin: 0 });
  s.addText(`/ ${TOTAL_PAGES}`, { x: 0.72, y: 6.96, w: 0.6, h: 0.2, fontSize: 8, color: K.faint, fontFace: F.head, margin: 0 });
}

// 主标题区（脊柱右侧）
function head(s, kicker, t) {
  const x = RAIL_W + 0.55;
  s.addText(kicker, { x, y: 0.5, w: 9.5, h: 0.24, fontSize: 10, bold: true, color: K.lime, fontFace: F.head, charSpacing: 2, margin: 0 });
  s.addText(t, { x, y: 0.78, w: 10.6, h: 0.62, fontSize: 26, bold: true, color: K.ink, fontFace: F.head, margin: 0 });
  s.addShape(pptx.ShapeType.line, { x, y: 1.52, w: W - x - 0.55, h: 0, line: { color: K.line, width: 1 } });
}

// 圆角卡片
function panel(s, x, y, w, h, opt = {}) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.1,
    fill: { color: opt.fill || K.panel },
    line: { color: opt.line || K.line, width: opt.lw || 1 },
  });
  if (opt.accent)
    s.addShape(pptx.ShapeType.roundRect, { x, y, w: 0.09, h, rectRadius: 0.04, fill: { color: opt.accent }, line: { color: opt.accent } });
}

// 标准信息卡：标题 + 正文
function infoCard(s, x, y, w, h, title, body, opt = {}) {
  panel(s, x, y, w, h, { accent: opt.accent || K.lime, fill: opt.fill });
  s.addText(title, { x: x + 0.26, y: y + 0.18, w: w - 0.42, h: 0.28, fontSize: opt.ts || 13, bold: true, color: opt.tc || K.ink, fontFace: F.head, margin: 0 });
  s.addText(body, { x: x + 0.26, y: y + 0.56, w: w - 0.46, h: h - 0.72, fontSize: opt.bs || 10, color: opt.bc || K.dim, valign: "top", fit: "shrink", paraSpaceAfterPt: 4, margin: 0 });
}

// 大数字指标块
function stat(s, x, y, w, value, unit, label, color = K.lime) {
  panel(s, x, y, w, 1.55, { fill: K.panel });
  s.addText([
    { text: value, options: { fontSize: 30, bold: true, color, fontFace: F.head } },
    { text: unit ? " " + unit : "", options: { fontSize: 12, bold: true, color: K.dim, fontFace: F.head } },
  ], { x: x + 0.22, y: y + 0.28, w: w - 0.4, h: 0.6, margin: 0, align: "left" });
  s.addText(label, { x: x + 0.22, y: y + 0.98, w: w - 0.4, h: 0.42, fontSize: 9.5, color: K.dim, valign: "top", margin: 0 });
}

// 标签药丸
function pill(s, text, x, y, w, color = K.lime) {
  s.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.34, rectRadius: 0.17, fill: { color: K.panelHi }, line: { color, width: 1 } });
  s.addText(text, { x: x + 0.1, y: y + 0.08, w: w - 0.2, h: 0.18, fontSize: 8.5, bold: true, color, align: "center", margin: 0 });
}

// 图片裱框（深色边）
function figure(s, file, x, y, w, h, caption) {
  s.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: K.panel }, line: { color: K.line, width: 1 } });
  if (fs.existsSync(file))
    s.addImage({ path: file, x: x + 0.1, y: y + 0.1, w: w - 0.2, h: h - (caption ? 0.55 : 0.2), sizing: { type: "contain", w: w - 0.2, h: h - (caption ? 0.55 : 0.2) } });
  else
    s.addText("[图]", { x, y: y + h / 2 - 0.1, w, h: 0.2, fontSize: 11, color: K.faint, align: "center", margin: 0 });
  if (caption)
    s.addText(caption, { x: x + 0.16, y: y + h - 0.4, w: w - 0.32, h: 0.28, fontSize: 8.5, color: K.dim, align: "center", valign: "middle", margin: 0 });
}

module.exports = { pptx, newSlide, rail, head, panel, infoCard, stat, pill, figure, K, F, A, W, H, RAIL_W, OUT, JSZip, fs, path, TOTAL_PAGES };
