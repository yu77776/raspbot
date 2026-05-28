from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(r"E:\毕设")
OUT_DIR = ROOT / "docs" / "thesis_figures"
FONT_REGULAR = r"C:\Windows\Fonts\Noto Sans SC (TrueType).otf"
FONT_MEDIUM = r"C:\Windows\Fonts\Noto Sans SC Medium (TrueType).otf"
FONT_BOLD = r"C:\Windows\Fonts\Noto Sans SC Bold (TrueType).otf"


W, H = 1920, 1080
BG = "#ffffff"
INK = "#1d2d3f"
MUTED = "#51657a"
BLUE = "#e8f3ff"
GREEN = "#edf8ef"
PEACH = "#fff3df"
LAVENDER = "#f3ecff"
BORDER = "#335b82"
ARROW = "#244f78"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


F_TITLE = font(FONT_BOLD, 34)
F_BOX = font(FONT_MEDIUM, 27)
F_BOX_SMALL = font(FONT_REGULAR, 24)
F_LABEL = font(FONT_REGULAR, 21)
F_LABEL_SMALL = font(FONT_REGULAR, 19)


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def draw_center_text(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    lines: Iterable[str],
    fnt: ImageFont.FreeTypeFont = F_BOX,
    fill: str = INK,
    line_gap: int = 10,
) -> None:
    lines = list(lines)
    heights = [text_size(draw, line, fnt)[1] for line in lines]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = rect[1] + (rect[3] - rect[1] - total_h) / 2 - 2
    for line, line_h in zip(lines, heights):
        line_w, _ = text_size(draw, line, fnt)
        draw.text((rect[0] + (rect[2] - rect[0] - line_w) / 2, y), line, font=fnt, fill=fill)
        y += line_h + line_gap


def rounded_box(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    fill: str,
    outline: str = BORDER,
    width: int = 4,
    radius: int = 18,
) -> None:
    shadow = (rect[0] + 7, rect[1] + 7, rect[2] + 7, rect[3] + 7)
    draw.rounded_rectangle(shadow, radius=radius, fill="#e8edf3")
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=width)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str = ARROW,
    width: int = 5,
) -> None:
    draw.line((start, end), fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    size = 18
    p1 = (x2, y2)
    p2 = (x2 - ux * size + px * size * 0.55, y2 - uy * size + py * size * 0.55)
    p3 = (x2 - ux * size - px * size * 0.55, y2 - uy * size - py * size * 0.55)
    draw.polygon([p1, p2, p3], fill=color)


def label(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    lines: Iterable[str],
    fnt: ImageFont.FreeTypeFont = F_LABEL,
    fill: str = MUTED,
    bg: str = BG,
    padding: tuple[int, int] = (16, 8),
) -> None:
    lines = list(lines)
    widths, heights = zip(*(text_size(draw, line, fnt) for line in lines))
    line_gap = 5
    box_w = max(widths) + padding[0] * 2
    box_h = sum(heights) + line_gap * (len(lines) - 1) + padding[1] * 2
    x = center[0] - box_w / 2
    y = center[1] - box_h / 2
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=10, fill=bg, outline="#d9e2ec", width=2)
    ty = y + padding[1] - 1
    for line, h in zip(lines, heights):
        w, _ = text_size(draw, line, fnt)
        draw.text((center[0] - w / 2, ty), line, font=fnt, fill=fill)
        ty += h + line_gap


def make_canvas(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    tw, th = text_size(draw, title, F_TITLE)
    draw.text(((W - tw) / 2, 58), title, font=F_TITLE, fill=INK)
    draw.line((760, 112, 1160, 112), fill="#d7e2ec", width=3)
    return img, draw


def draw_architecture() -> None:
    img, draw = make_canvas("系统总体架构图")
    y1, y2 = 410, 610
    car = (130, y1, 500, y2)
    pc = (775, y1, 1145, y2)
    app = (1420, y1, 1790, y2)

    rounded_box(draw, car, BLUE)
    rounded_box(draw, pc, GREEN)
    rounded_box(draw, app, PEACH)

    draw_center_text(draw, car, ["小车端", "摄像头 / 传感器 / 执行器"])
    draw_center_text(draw, pc, ["PC计算端", "YOLO / YAMNet / ASR / 桥接"])
    draw_center_text(draw, app, ["Android端", "视频 / 环境 / 控制 / 报警"])

    arrow(draw, (500, 510), (775, 510))
    arrow(draw, (1145, 510), (1420, 510))

    label(draw, (638, 443), ["视频帧 0x01", "传感器数据 0x03"], F_LABEL_SMALL)
    label(draw, (1282, 443), ["WebRTC视频流", "识别结果与环境数据"], F_LABEL_SMALL)

    # Return channel, drawn lower to keep protocol labels readable.
    arrow(draw, (1420, 585), (1145, 585), color="#496f94", width=4)
    arrow(draw, (775, 585), (500, 585), color="#496f94", width=4)
    label(draw, (1282, 650), ["控制指令与报警通知"], F_LABEL_SMALL)
    label(draw, (638, 650), ["控制指令 0x02"], F_LABEL_SMALL)

    draw.text((130, 820), "三端分工：小车负责采集与执行，PC负责识别与桥接，Android负责显示、控制和状态提醒。", font=F_LABEL, fill="#637589")
    img.save(OUT_DIR / "fig2-1-architecture.png", dpi=(300, 300))


def draw_protocol_flow() -> None:
    img, draw = make_canvas("通信协议数据流图")
    left_x1, left_x2 = 110, 500
    pc = (780, 430, 1140, 620)
    app = (1450, 430, 1810, 620)
    sources = [
        ((left_x1, 235, left_x2, 385), BLUE, ["0x01  视频帧", "JPEG 640×480"]),
        ((left_x1, 465, left_x2, 615), GREEN, ["0x02  控制指令", "JSON动作 / 云台 / 语音"]),
        ((left_x1, 695, left_x2, 845), PEACH, ["0x03  环境数据", "JSON传感器 / 报警"]),
    ]

    for rect, fill, lines in sources:
        rounded_box(draw, rect, fill)
        draw_center_text(draw, rect, lines, F_BOX_SMALL)

    rounded_box(draw, pc, LAVENDER)
    rounded_box(draw, app, BLUE)
    draw_center_text(draw, pc, ["PC网关", "认证 / 转发 / 桥接"])
    draw_center_text(draw, app, ["Android App", "显示 / 控制 / 通知"])

    join = (740, 525)
    for rect, _, _ in sources:
        arrow(draw, (rect[2], (rect[1] + rect[3]) // 2), join, width=4)
    arrow(draw, join, (780, 525), width=5)
    arrow(draw, (1140, 525), (1450, 525), width=5)

    label(draw, (1300, 460), ["WebSocket长连接", "视频由WebRTC承载"], F_LABEL_SMALL)

    draw.line((1180, 610, 1180, 690, 560, 690, 560, 540), fill="#496f94", width=4)
    arrow(draw, (560, 540), (500, 540), color="#496f94", width=4)
    label(draw, (845, 745), ["控制指令回传至小车端执行"], F_LABEL_SMALL)

    draw.text((110, 935), "协议分层：二进制帧头区分 0x01/0x02/0x03 数据类型，PC网关完成认证、转发与移动端桥接。", font=F_LABEL, fill="#637589")
    img.save(OUT_DIR / "fig2-2-protocol-flow.png", dpi=(300, 300))


def draw_voice_flow() -> None:
    img, draw = make_canvas("语音交互流程图")

    mic = (120, 315, 455, 475)
    asr = (595, 295, 955, 495)
    intent = (1085, 315, 1450, 515)
    command = (1570, 315, 1850, 515)
    cry = (595, 660, 955, 835)
    chat = (1085, 660, 1450, 835)
    execute = (1570, 660, 1850, 850)

    rounded_box(draw, mic, BLUE)
    rounded_box(draw, asr, GREEN)
    rounded_box(draw, cry, "#fff7e8")
    rounded_box(draw, intent, LAVENDER)
    rounded_box(draw, chat, "#edf8f7")
    rounded_box(draw, command, BLUE)
    rounded_box(draw, execute, GREEN)

    draw_center_text(draw, mic, ["小车麦克风", "PCM 16kHz / 16bit", "WebSocket音频流"], F_BOX_SMALL, line_gap=8)
    draw_center_text(draw, asr, ["PC AsrServer", "百度实时ASR", "输出最终识别文本"], F_BOX_SMALL, line_gap=8)
    draw_center_text(draw, cry, ["YAMNet哭声检测", "更新 CryStateStore", "合并环境报警"], F_BOX_SMALL, line_gap=8)
    draw_center_text(draw, intent, ["语音意图解析", "行进 / 停止 / 转向", "播放 / 切歌 / 音量"], F_BOX_SMALL, line_gap=8)
    draw_center_text(draw, chat, ["闲聊回复分支", "DialogueEngine生成回复", "TTS文本回传小车"], F_BOX_SMALL, line_gap=8)
    draw_center_text(draw, command, ["CommandPacket", "action / play_song", "audio_volume / tts_text"], F_BOX_SMALL, line_gap=8)
    draw_center_text(draw, execute, ["小车端执行", "电机运动 / 音乐队列", "音量 / TTS / OLED显示"], F_BOX_SMALL, line_gap=8)

    arrow(draw, (455, 395), (595, 395))
    label(draw, (525, 340), ["ws://PC:6006/audio"], F_LABEL_SMALL)
    arrow(draw, (955, 395), (1085, 415))
    label(draw, (1020, 357), ["FIN_TEXT"], F_LABEL_SMALL)

    draw.line((775, 495, 775, 660), fill="#496f94", width=4)
    arrow(draw, (775, 640), (775, 660), color="#496f94", width=4)
    label(draw, (905, 585), ["同源音频旁路分析"], F_LABEL_SMALL)

    arrow(draw, (1450, 415), (1570, 415))
    label(draw, (1510, 365), ["匹配控制意图"], F_LABEL_SMALL)
    arrow(draw, (1268, 515), (1268, 660), color="#496f94", width=4)
    label(draw, (1380, 590), ["未匹配控制词"], F_LABEL_SMALL)
    arrow(draw, (1450, 742), (1570, 755), color="#496f94", width=4)
    label(draw, (1515, 813), ["回复写入 tts_text"], F_LABEL_SMALL)
    arrow(draw, (1710, 515), (1710, 660))
    label(draw, (1795, 590), ["MSG_COMMAND"], F_LABEL_SMALL)

    draw.text(
        (120, 930),
        "当前流程：小车麦克风采集语音并推送至PC端，PC完成百度ASR、意图解析和哭声旁路检测，最终生成控制包交给小车端执行。",
        font=F_LABEL,
        fill="#637589",
    )
    img.save(OUT_DIR / "fig4-6-voice-flow.png", dpi=(300, 300))
    img.save(OUT_DIR / "fig4-6-voice-flow-clean.png", dpi=(300, 300))


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    draw_architecture()
    draw_protocol_flow()
    draw_voice_flow()
    print(OUT_DIR / "fig2-1-architecture.png")
    print(OUT_DIR / "fig2-2-protocol-flow.png")
    print(OUT_DIR / "fig4-6-voice-flow.png")
