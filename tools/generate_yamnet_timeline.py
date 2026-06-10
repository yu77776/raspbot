from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "yamnet_window_timeline.png"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


FONT_CN = r"C:\Windows\Fonts\simhei.ttf"
FONT_MONO = r"C:\Windows\Fonts\consola.ttf"


def arrow(draw: ImageDraw.ImageDraw, start, end, fill, width=3):
    draw.line([start, end], fill=fill, width=width)
    x1, y1 = start
    x2, y2 = end
    if x2 >= x1:
        pts = [(x2, y2), (x2 - 12, y2 - 7), (x2 - 12, y2 + 7)]
    else:
        pts = [(x2, y2), (x2 + 12, y2 - 7), (x2 + 12, y2 + 7)]
    draw.polygon(pts, fill=fill)


def rounded_box(draw, xy, fill, outline, radius=10, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def centered(draw, xy, text, ft, fill, anchor="mm"):
    draw.text(xy, text, font=ft, fill=fill, anchor=anchor)


def main():
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), "#0b0d0e")
    d = ImageDraw.Draw(img)

    title = font(FONT_CN, 34)
    label = font(FONT_CN, 26)
    small = font(FONT_CN, 22)
    tiny = font(FONT_CN, 18)
    mono = font(FONT_MONO, 25)
    mono_big = font(FONT_MONO, 30)

    white = "#e9e9e9"
    grey = "#cfcfcf"
    muted = "#8f989a"
    cyan = "#9bd4ff"
    green = "#9be58c"
    amber = "#ffd27a"
    red = "#ff8f8f"

    d.rectangle([0, 0, W - 1, H - 1], outline="#202426", width=2)
    centered(d, (W // 2, 42), "YAMNet哭声检测滑动窗口与门控流程", title, white)

    d.text((80, 94), "时间  →", font=label, fill=white)
    d.line([(185, 110), (1130, 110)], fill="#777", width=2)
    ticks = [(220, "0s"), (380, "0.5s"), (540, "1.0s"), (700, "1.5s"), (860, "2.0s"), (1020, "2.5s")]
    for x, t in ticks:
        d.line([(x, 101), (x, 119)], fill="#aaa", width=2)
        centered(d, (x, 142), t, tiny, muted)

    d.text((80, 190), "音频：", font=label, fill=white)
    d.rectangle([205, 194, 1035, 230], fill="#d8d8d8")
    for x in range(205, 1035, 6):
        d.line([(x, 194), (x + 6, 230)], fill="#0b0d0e", width=1)
    centered(d, (620, 252), "16kHz 单声道 PCM 连续音频流", small, grey)

    base_y = 332
    windows = [
        (220, 540, 292, "window=1s"),
        (380, 700, 337, "window=1s"),
        (540, 860, 382, "window=1s"),
        (700, 1020, 427, "window=1s"),
    ]

    for x1, x2, y, text in windows:
        d.line([(x1, y), (x2, y)], fill=white, width=3)
        d.line([(x1, y - 18), (x1, y + 18)], fill=white, width=3)
        d.line([(x2, y - 18), (x2, y + 18)], fill=white, width=3)
        centered(d, ((x1 + x2) // 2, y - 28), f"← {text} →", mono, grey)

    hop_y = 470
    for x1, x2 in [(220, 380), (380, 540), (540, 700), (700, 860)]:
        d.line([(x1, hop_y - 25), (x2, hop_y - 25)], fill=grey, width=3)
        d.line([(x1, hop_y - 43), (x1, hop_y - 7)], fill=grey, width=3)
        d.line([(x2, hop_y - 43), (x2, hop_y - 7)], fill=grey, width=3)
        centered(d, ((x1 + x2) // 2, hop_y), "hop=0.5s", mono, grey)

    d.line([(220, 445), (1020, 445)], fill="#404547", width=1)
    for x, _ in ticks:
        d.line([(x, 426), (x, 464)], fill=grey, width=3)

    d.text((80, 530), "每步：", font=label, fill=white)
    steps = [
        ((190, 500, 365, 575), "① 计算RMS", green),
        ((415, 500, 590, 575), "② RMS < 0.004", amber),
        ((640, 500, 815, 575), "跳过YAMNet", red),
        ((865, 500, 1040, 575), "③ YAMNet得分", cyan),
    ]
    for i, (box, text, color) in enumerate(steps):
        rounded_box(d, box, "#15191a", color, radius=8, width=2)
        centered(d, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, small, white)
        if i < len(steps) - 1:
            arrow(d, (box[2] + 10, 538), (steps[i + 1][0][0] - 12, 538), "#9aa0a3", width=2)

    rounded_box(d, (190, 610, 1040, 670), "#101415", "#6b58d9", radius=8, width=2)
    centered(d, (615, 640), "哭声得分进入双阈值滞后状态机：score ≥ 0.60 持续2s触发，score ≤ 0.40 持续3s释放", small, "#dfdcff")

    d.text((82, 678), "能量门控用于过滤静音段，降低语音、音乐和短时噪声造成的误报。", font=tiny, fill=muted)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
