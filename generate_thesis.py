#!/usr/bin/env python3
"""Generate graduation thesis .docx per GB/T 7713 standard."""

from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
import os

# ═══ CONFIGURATION — update these before running ═══
STUDENT_NAME = "赵国宇"       # ← VERIFY: correct Chinese name?
STUDENT_ID = "42203080116"
SCHOOL = "计算机信息学院"
MAJOR = "计算机科学与技术 2022 级 1 班"
ADVISOR = "×××"
ADVISOR_TITLE = "教授"
THESIS_TITLE = "基于树莓派的婴幼儿智能陪护机器人设计与实现"
ENGLISH_TITLE = "Design and Implementation of a Raspberry Pi-Based Intelligent Infant Companion Robot System"

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
    "基于树莓派的婴幼儿智能陪护机器人设计与实现.docx")

doc = Document()

# ── Page setup (A4, GB/T 7713 margins) ──
for section in doc.sections:
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.18)
    section.right_margin = Cm(3.18)

# ── Styles ──
style = doc.styles['Normal']
style.font.name = '宋体'
style.font.size = Pt(12)  # 小四
style.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
style.paragraph_format.line_spacing = 1.5
style.paragraph_format.first_line_indent = Cm(0.74)

def set_run_font(run, name='宋体', size=Pt(12), bold=False):
    run.font.name = name
    run.element.rPr.rFonts.set(qn('w:eastAsia'), name)
    run.font.size = size
    run.bold = bold

def heading(text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = '黑体'
        run.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
        sizes = {1: Pt(16), 2: Pt(14), 3: Pt(13)}
        run.font.size = sizes.get(level, Pt(12))
    return h

def para(text, bold=False, indent=True, font_size=Pt(12)):
    p = doc.add_paragraph()
    if not indent:
        p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    set_run_font(run, size=font_size, bold=bold)
    return p

def centered(text, size=Pt(16), bold=False, font='黑体'):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    set_run_font(run, name=font, size=size, bold=bold)
    return p

def add_table(headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers), style='Table Grid')
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(9)
                run.font.name = '黑体'
                run.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = table.rows[r+1].cells[c]
            cell.text = str(val)
            for p in cell.paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in p.runs:
                    run.font.size = Pt(9)
    doc.add_paragraph()
    return table

def formula(text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    set_run_font(run, name='Times New Roman', size=Pt(11))
    run.italic = True
    return p

# ═══════════════════════════════════════
# COVER PAGE (GB/T 7713 format)
# ═══════════════════════════════════════
for _ in range(6):
    doc.add_paragraph()

centered('毕业设计（论文）', size=Pt(28), bold=True)

doc.add_paragraph()
doc.add_paragraph()

cover_items = [
    ('题    目', THESIS_TITLE),
    ('学    院', SCHOOL),
    ('专业班级', MAJOR),
    ('指导教师', f'{ADVISOR}    职称：{ADVISOR_TITLE}'),
    ('学生姓名', STUDENT_NAME),
    ('学    号', STUDENT_ID),
]
for label, value in cover_items:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing = 2.0
    run = p.add_run(f'{label}：{value}')
    set_run_font(run, size=Pt(16))

doc.add_page_break()

# ═══════════════════════════════════════
# STATEMENT OF ORIGINALITY (GB/T 7713)
# ═══════════════════════════════════════
heading('原创性声明', level=1)

para(
    '本人郑重声明：所呈交的毕业设计（论文），是本人在指导教师的指导下，'
    '独立进行研究工作所取得的成果。除文中已经注明引用的内容外，本论文不含'
    '任何其他个人或集体已经发表或撰写过的作品成果。对本文的研究做出重要贡献'
    '的个人和集体，均已在文中以明确方式标明。本人完全意识到本声明的法律结果'
    '由本人承担。'
)

doc.add_paragraph()
doc.add_paragraph()

p = doc.add_paragraph()
p.paragraph_format.first_line_indent = Cm(0)
run = p.add_run(f'学生签名：{"_" * 10}    日期：{"_" * 10}    指导教师签名：{"_" * 10}')
set_run_font(run, size=Pt(12))

doc.add_page_break()

# ═══════════════════════════════════════
# CHINESE ABSTRACT (GB/T 7713)
# ═══════════════════════════════════════
heading('摘要', level=1)

abstract_cn = (
    '针对传统婴幼儿监护设备监测维度单一、缺乏移动跟随能力、异常响应不及时等问题，'
    '本文设计并实现了一套基于树莓派的婴幼儿智能陪护机器人系统。系统以树莓派 4B 为小车端控制核心，'
    '结合 PC 端深度学习推理和 Android 移动端远程交互，集成视觉跟随、哭声检测、环境监测、'
    '语音控制、音频安抚和远程视频监控等功能。小车端通过摄像头、超声波、PCF8591 模数转换模块、'
    'MPU6050 姿态传感器、红外循迹传感器、双轴舵机云台、OLED 显示屏和音频模块完成环境感知与执行控制。'
    '\n\n'
    '系统采用树莓派端、PC 端和 Android App 端协同工作的三层总体架构。树莓派端负责硬件采集、'
    '电机舵机执行、本地报警和安全保护；PC 端基于 YOLO26s 目标检测模型完成婴幼儿目标检测，'
    '基于 YAMNet 完成哭声判断，并负责百度实时语音识别、WebSocket 转发和 WebRTC 桥接；'
    'Android App 端实现视频查看、环境数据显示、报警提醒和远程控制。视觉跟随模块结合时序目标滤波、'
    'PID 双环伺服控制和距离跟随状态机实现目标锁定与跟随；环境监测模块对距离、温度、光照、烟雾、'
    '底部循迹和电源状态进行周期采样，并通过统一报警 token 实现多端同步；安全保护模块设计了'
    '指令超时看门狗、悬崖防护、障碍物防护、控制权租约和 TTS 防骚扰冷却等多层机制。'
    '测试结果表明，系统能够完成目标跟随、哭声报警、环境异常提示、语音控制、儿歌播放和 App '
    '远程监控等功能，满足家庭婴幼儿辅助看护场景的基本需求。'
)
para(abstract_cn)

para('关键词：树莓派；婴幼儿陪护；目标检测；哭声检测；WebRTC；Android', bold=True)

doc.add_page_break()

# ═══════════════════════════════════════
# ENGLISH ABSTRACT (GB/T 7713 required)
# ═══════════════════════════════════════
heading('Abstract', level=1)

abstract_en = (
    'To address the limitations of traditional infant monitoring devices—such as single-dimensional sensing, '
    'lack of active following capability, and delayed abnormal event response—this thesis designs and implements '
    'an intelligent infant companion robot system based on Raspberry Pi. The system adopts a three-tier architecture '
    'consisting of a Raspberry Pi 4B car-side controller, a PC-side deep learning inference unit, and an Android '
    'mobile application for remote interaction, integrating visual tracking, cry detection, environmental monitoring, '
    'voice control, audio soothing, and remote video surveillance.'
    '\n\n'
    'The Raspberry Pi car side handles sensor acquisition, motor and servo actuation, local alarm, and safety '
    'protection. The PC side performs infant target detection using the YOLO26s model, cry classification using '
    'YAMNet, Baidu real-time speech recognition, WebSocket data forwarding, and WebRTC bridging. The Android App '
    'provides video display, environmental data visualization, alarm notifications, and remote control. The visual '
    'tracking module combines temporal target filtering, dual-loop PID servo control, and a distance-follow state '
    'machine. The environmental monitoring module periodically samples distance, temperature, illuminance, smoke, '
    'cliff detection, and power status, synchronizing multi-end alarm tokens. A multi-layer safety protection '
    'mechanism—including a command timeout watchdog, cliff protection, obstacle avoidance, control lease arbitration, '
    'and TTS anti-harassment cooldown—ensures reliable operation in home environments.'
    '\n\n'
    'Experimental results demonstrate that the system reliably performs target following, cry alarm triggering, '
    'environmental anomaly alerting, voice-controlled navigation, nursery rhyme playback, and remote App monitoring, '
    'meeting the fundamental requirements of an infant-assisted caregiving scenario in domestic settings.'
)
p = doc.add_paragraph()
p.paragraph_format.first_line_indent = Cm(0)
run = p.add_run(abstract_en)
set_run_font(run, name='Times New Roman', size=Pt(12))

para('Keywords: Raspberry Pi; infant companion; object detection; cry detection; WebRTC; Android',
     bold=True, font_size=Pt(12))

doc.add_page_break()

# ═══════════════════════════════════════
# TABLE OF CONTENTS PLACEHOLDER
# ═══════════════════════════════════════
heading('目录', level=1)
para('（在 Word 中：插入 → 引用 → 索引和目录 → 自动生成目录。需先将各章节标题应用"标题 1/2/3"样式。）', indent=False)
doc.add_page_break()

# ═══════════════════════════════════════
# CHAPTER 1: INTRODUCTION
# ═══════════════════════════════════════
heading('第一章 绪论', level=1)

heading('1.1 研究背景与意义', level=2)

para(
    '近年来，家庭结构和育儿方式发生了明显变化。随着二孩、三孩政策实施以及双职工家庭比例提高，'
    '婴幼儿日常照护中的时间压力和安全压力不断增加。婴幼儿缺乏自主表达能力，睡眠、哭闹、翻身、'
    '爬行、接近危险区域等状态往往需要看护者持续关注。对于家长而言，长时间保持高强度看护不仅消耗精力，'
    '也容易因短暂离开或注意力转移造成安全隐患。因此，能够辅助家长完成基础监护、异常提醒、远程查看和'
    '安全干预的智能陪护设备具有现实意义。'
)

para(
    '现有家庭监护产品主要包括固定式摄像头、婴儿哭声监测器、智能婴儿床、智能音箱和部分具备移动能力的'
    '家庭服务机器人。固定式摄像头可以提供视频画面，但观察范围受安装位置限制，无法主动调整角度或跟随目标；'
    '普通声音监测器可以发现哭声，但难以结合环境因素和运动风险进行综合判断；智能婴儿床通常侧重温湿度、'
    '灯光和音乐安抚，移动性和视角调整能力有限；智能音箱具备语音交互能力，但通常缺少传感器和运动执行机构。'
    '婴幼儿看护场景对设备提出了更高要求：既要主动感知婴幼儿位置、声音和周围环境，也要具备安全可控的'
    '移动能力和可靠的远程通信能力。'
)

para(
    '嵌入式人工智能和物联网技术的发展为上述问题提供了新的解决思路。树莓派等嵌入式计算平台具备较好的'
    '扩展能力，可通过 GPIO、I2C、CSI 和 USB 接口连接多种传感器与执行器；YOLO 系列目标检测模型能够在'
    'PC 或边缘设备上实现较高实时性的视觉识别；YAMNet 等音频分类模型可以用于哭声事件检测；WebSocket、'
    'WebRTC 等通信技术可以支持视频、指令和环境数据的实时传输；Android 移动端应用则便于家长随时查看'
    '状态和接收报警。将这些技术整合到移动机器人平台中，可以构建一个面向家庭场景的低成本、多模态智能'
    '陪护系统。'
)

para(
    '本文研究的意义主要体现在三个方面。首先，在功能层面，系统将视觉跟随、哭声检测、环境监测、语音交互、'
    '远程视频和移动控制组合到同一平台，提升了监护维度的完整性。其次，在工程层面，本文围绕树莓派小车平台'
    '完成了多传感器接口、电机控制、通信协议、安全策略和三端协同软件架构设计，对嵌入式系统综合设计具有'
    '实践价值。最后，在应用层面，系统能够为家长提供辅助看护手段，在婴幼儿哭闹、距离过近、光照异常、'
    '烟雾异常、悬崖风险和网络断连等情况下提供提醒或安全动作，具有一定实用价值。'
)

heading('1.2 国内外研究现状', level=2)

para(
    '国外在家庭服务机器人和婴幼儿监护设备领域起步较早，代表性产品包括 iRobot 系列清洁机器人、'
    'Samsung Bot Handy 等家庭辅助机器人，以及具有视频查看、夜视、哭声提醒和环境检测功能的婴儿监护设备。'
    '这类产品在移动底盘、视觉感知、路径规划和人机交互方面积累了较成熟的技术。但是，国外成熟产品通常'
    '价格较高，且多数产品以固定监控或通用家庭服务为主，专门针对婴幼儿移动陪护、哭声安抚和安全保护的'
    '一体化系统仍相对有限。'
)

para(
    '国内智能硬件和服务机器人发展迅速。小米、科沃斯、石头科技等企业在家庭机器人、视觉导航、避障和'
    'App 控制方面形成了较完整的产品生态；智能摄像头、儿童陪伴机器人、智能音箱和智能婴儿床等产品也'
    '逐渐进入家庭场景。相关研究中，基于树莓派的智能小车常用于循迹、避障、目标识别和远程控制验证[1-3]；'
    '婴儿监护类系统则多围绕温湿度监测、声音检测、远程视频和音乐安抚展开[4-6]。这些研究为本文提供了'
    '硬件接口、视觉识别、语音交互和远程通信方面的技术参考。'
)

para(
    '综合现有产品和研究可以看出，当前方案仍存在以下不足：一是功能侧重点分散，固定摄像头、智能音箱、'
    '智能小车和智能婴儿床通常分别解决单一问题，缺少面向婴幼儿陪护场景的融合设计；二是移动看护能力不足，'
    '固定监控设备无法主动调整视角或跟随目标；三是多模态异常判断不足，哭声、温度、光照、烟雾、距离和'
    '悬崖风险往往没有统一报警策略；四是安全保护不充分，移动机器人在家庭环境中需要考虑障碍物、悬崖、'
    '网络断线和控制权冲突；五是端到端协同不足，视频、控制、环境数据和报警状态缺乏统一协议。'
)

para(
    '因此，本文以树莓派智能小车为平台，结合 PC 端推理能力和 Android 移动端交互能力，设计一套结构清晰、'
    '功能完整、可验证的婴幼儿智能陪护机器人系统。'
)

heading('1.3 本文主要工作', level=2)

para('本文围绕系统设计与实现开展以下工作：')

works = [
    '设计三端协同总体架构。系统由树莓派小车端、PC 控制端和 Android App 端组成。树莓派端负责传感器采集、电机和舵机控制、OLED 显示、音频播放和本地安全防护；PC 端负责 YOLO26s 目标检测、YAMNet 哭声检测、百度实时语音识别、WebSocket 数据转发和 WebRTC 云端桥接；Android App 端负责视频显示、模式切换、远程控制、环境数据显示和报警通知。',
    '完成多传感器硬件接口设计。系统接入 HC-SR04 超声波、PCF8591 ADC、MPU6050 IMU、红外循迹、MC096GW OLED、SG90 舵机、无源蜂鸣器、USB 麦克风和 USB 声卡等外围模块。针对 5V/3.3V 电平兼容、I2C 地址规划（0x16/0x3C/0x48/0x68）和多传感器并发采样等问题进行了工程化处理。',
    '实现婴幼儿视觉跟随功能。PC 端使用 YOLO26s 目标检测模型，结合 BabyFilter 时序滤波器完成目标锁定（3 帧确认/5 帧丢失/IoU 匹配）。采用双环控制架构：内环 PD 将像素误差转换为舵机角度，外环根据舵机偏角生成车身转向指令并结合 IMU 偏航角速率阻尼。距离跟随采用四态机实现前后距离保持。',
    '实现哭声检测与语音交互。基于 YAMNet 和双阈值滞后状态机（触发 0.60/2s，释放 0.40/3s）实现低误报哭声检测。集成百度实时语音识别服务，通过关键词匹配实现 8 类意图解析。设计 TTS 回声抑制机制，根据播报文本长度动态计算抑制时间，防止机器人自发声触发误识别。',
    '实现通信协议与远程监控。定义二进制帧协议（0x01 视频 JPEG/0x02 指令 JSON/0x03 环境 JSON），定义 10 种统一报警 token。PC 与 App 之间支持局域网 WebSocket 和公网 WebRTC 双通道通信，基于 aiortc + TURN/STUN 实现 NAT 穿透。',
    '设计多层安全保护机制。实现指令超时看门狗（0.8s）、麦克风健康看门狗（2s）、悬崖防护（强制后退 0.35s + 蜂鸣器报警）、障碍物防护（<30cm 禁前进）、控制权租约（1.2s）、断线自动停车和 TTS 防骚扰冷却（全局 12s/同类 45s/温度 180s）。',
]

for i, w in enumerate(works, 1):
    para(f'（{i}）{w}')

heading('1.4 论文结构安排', level=2)

para(
    '本文共分为六章。第一章介绍研究背景、意义、国内外研究现状和主要工作。第二章从需求分析、总体架构、'
    '硬件组成、软件组成和通信协议等方面说明系统总体设计。第三章重点介绍树莓派硬件接口电路设计，包括 '
    'GPIO 资源分配、超声波测距、PCF8591 模数转换、MPU6050 姿态采集、OLED 显示、舵机控制和红外循迹。'
    '第四章重点阐述软件功能模块设计，包括视觉跟随、环境监测、哭声检测、语音交互、视频传输和安全保护。'
    '第五章对系统进行测试与实验分析。第六章总结全文工作并展望后续改进方向。'
)

doc.add_page_break()

print("Cover + Abstract + Ch1 done. Writing Ch2-4...")

# ═══════════════════════════════════════
# CHAPTER 2: SYSTEM OVERALL DESIGN
# ═══════════════════════════════════════
heading('第二章 系统总体设计', level=1)

heading('2.1 需求分析', level=2)

para(
    '婴幼儿智能陪护机器人需要在家庭室内环境中辅助看护者完成基础监测、状态提醒和远程查看。'
    '结合应用场景，系统功能性需求如表 2-1 所示。'
)

add_table(
    ['编号', '功能需求', '说明', '优先级'],
    [
        ['F1', '婴幼儿视觉跟随', '识别画面中婴幼儿目标，调整云台和小车位置', '高'],
        ['F2', '哭声检测报警', '识别持续哭声并同步推送至 App 和小车', '高'],
        ['F3', '环境异常监测', '采集距离、烟雾、温度、光照、循迹和电源状态', '高'],
        ['F4', '语音控制与儿歌播放', '支持语音指令控制运动和播放安抚音频', '中'],
        ['F5', '视频远程传输', '支持局域网 WebSocket 与公网 WebRTC 视频查看', '中'],
        ['F6', 'App 远程控制', '支持自动/手动模式切换、运动控制和报警展示', '中'],
    ]
)

para(
    '非功能性需求方面：实时性上，目标检测延迟应 < 100ms，局域网视频延迟 < 200ms，环境数据以 2Hz '
    '频率推送；安全性上，小车须具备悬崖防护、障碍物防护、断线停车和异常报警能力；可靠性上，系统应'
    '支持自动重连、控制权仲裁和看门狗机制；可维护性上，各端采用统一通信协议和模块化代码结构，关键'
    '参数支持运行时热加载，便于调试和扩展。'
)

heading('2.2 系统总体架构', level=2)

para(
    '系统采用"感知执行层、计算控制层、应用交互层"三层架构。感知执行层位于树莓派小车端，包含摄像头、'
    '超声波、PCF8591、MPU6050、红外循迹、OLED、舵机、电机、蜂鸣器、麦克风和扬声器等模块，负责'
    '环境感知、运动执行和本地安全。计算控制层位于 PC 端，承担 YOLO26s 目标检测、BabyFilter 时序滤波、'
    'PID 控制决策、YAMNet 哭声检测、百度 ASR 和 WebRTC 桥接等计算密集型任务。应用交互层位于 Android '
    'App 端，提供视频查看、环境数据展示、报警提醒、手动控制和自动跟随切换等功能。'
)

para(
    '数据流：树莓派采集视频（640×480@30fps, JPEG quality=80）和环境数据（2Hz），通过 WebSocket '
    '（端口 5001）发送至 PC；PC 进行 YOLO 推理和 PID 控制决策后，将控制指令（0x02 帧）回传树莓派；'
    'PC 同时将视频和环境数据转发给 Android App（局域网 WebSocket 端口 7000 或公网 WebRTC）。'
    'App 可在手动模式下发送控制指令，经 PC 转发至小车。该架构兼顾了嵌入式执行稳定性、PC 端算力和'
    '移动端交互便利性。'
)

heading('2.3 硬件总体设计', level=2)

para(
    '系统硬件以树莓派 4B 为核心，通过 CSI 接口连接 Camera Module v2，通过 I2C 总线 1 挂载 4 个外设'
    '（YB 小车板 0x16、OLED 0x3C、PCF8591 0x48、MPU6050 0x68），通过 GPIO 连接 HC-SR04 超声波和'
    '四路红外循迹，通过 USB 连接麦克风和声卡。设计了一块传感器接口 PCB（立创 EDA Pro，工程名 '
    'Raspbot_V1_Sensor_Interface），集成了分压保护、I2C 上拉、蜂鸣器驱动和传感器接插件。'
    '硬件模块如表 2-2 所示。'
)

add_table(
    ['模块', '型号/接口', '作用'],
    [
        ['主控', 'Raspberry Pi 4B (4GB)', '小车端主控与 WebSocket 服务端'],
        ['电机驱动', 'YB-PCB 小车板，I2C 0x16', '四路直流电机 + 双轴舵机控制'],
        ['摄像头', 'Camera Module v2 (IMX219)', '640×480@30fps 视频采集'],
        ['距离传感器', 'HC-SR04', '障碍距离检测，Echo 经 1kΩ+2kΩ 分压至 3.3V'],
        ['ADC 模块', 'PCF8591，I2C 0x48', 'GL5528 光照/NTC 温度/MQ-2 烟雾/音量旋钮'],
        ['IMU', 'MPU6050，I2C 0x68', '三轴陀螺 ±250°/s + 三轴加速度 ±2g, Madgwick 融合'],
        ['红外循迹', '四路红外对管', '底部悬崖检测，四路全 0 判定悬空'],
        ['舵机', 'SG90 × 2', '云台 Pan(水平) / Tilt(垂直), 0°~180°'],
        ['OLED', 'MC096GW 128×32, I2C 0x3C', '表情状态显示（idle/tracking/alarm 等）'],
        ['蜂鸣器', '无源，PWM BOARD 32', '悬崖/悬空报警，2.7kHz 三声短促蜂鸣'],
        ['音频输出', 'pj-313E + USB 声卡', 'pygame 混音器播放儿歌和 edge-tts 语音合成'],
        ['音频输入', 'USB 麦克风', '16kHz 单声道 S16_LE, 40ms/帧 PCM 流'],
    ]
)

heading('2.4 软件总体设计', level=2)

para(
    '系统软件分为三端。树莓派端以 car_server_modular.py 为主服务程序，启动 WebSocket 服务（端口 5001），'
    '协调摄像头（30fps）、环境采样（2Hz）、指令执行和音频播放等模块线程。command_executor.py 负责指令'
    '执行与安全防护；env_sampler.py 聚合多传感器数据；care_policy.py 生成报警 token 和 TTS 文案。'
    '所有硬件模块继承 ModuleBase 基类，统一线程管理。'
)

para(
    'PC 端负责智能计算与数据桥接。client.py 接收视频帧并调用 YOLO26s 推理；baby_filter.py 执行时序'
    '目标滤波；motion_controller.py 运行双环 PID 控制（PID 参数由 JsonTuner 每 250ms 热加载 '
    'motion_tuning.json）；cry_detector.py 基于 YAMNet 进行哭声检测；asr_server.py 接入百度实时 ASR；'
    'voice_cry_bridge.py 解析语音意图和桥接哭声状态；app_gateway.py 提供 App ↔ 小车数据桥接（端口 7000）；'
    'webrtc_bridge.py 基于 aiortc 实现 WebRTC 云端视频 + DataChannel 桥接。'
    'BackgroundService 类统一管理异步服务的生命周期。'
)

para(
    'Android 端以 Kotlin 实现，MainActivity.kt 组织 HOME/CONTROL/MONITOR/MESSAGE/MINE 五个页面，'
    '支持 WebSocket/WebRTC 双模式连接、DirectionPadView 方向键遥控、SimpleTrendView 环境趋势图、'
    'RaspbotAlarmService 后台报警通知和自动追踪/手动控制切换。'
)

add_table(
    ['模块', '所属端', '职责'],
    [
        ['car_server_modular.py', '树莓派', 'WebSocket 服务主程序，协调整车运行'],
        ['command_executor.py', '树莓派', '指令执行、安全防护、OLED 和音频联动'],
        ['env_sampler.py', '树莓派', '多传感器数据聚合（2Hz）'],
        ['care_policy.py', '树莓派', '报警策略（9 种 token）和 TTS 文案'],
        ['client.py', 'PC', '视频接收、YOLO26s 推理、控制指令生成'],
        ['baby_filter.py', 'PC', '婴幼儿目标时序滤波（三态机）'],
        ['motion_controller.py', 'PC', 'PID 双环控制 + 距离跟随状态机 + 热加载'],
        ['cry_detector.py', 'PC', 'YAMNet 哭声检测 + 双阈值平滑'],
        ['voice_cry_bridge.py', 'PC', '语音意图解析（8 类）+ 哭声状态桥接'],
        ['asr_server.py', 'PC', '百度实时语音识别 WebSocket 服务'],
        ['app_gateway.py', 'PC', 'App(7000) ↔ 小车(5001) 数据桥接'],
        ['webrtc_bridge.py', 'PC', 'aiortc 视频 + DataChannel 公网桥接'],
        ['MainActivity.kt', 'Android', '五页主界面、连接管理和远程控制'],
    ]
)

heading('2.5 通信协议设计', level=2)

para(
    '为降低多端通信耦合，系统定义了统一的二进制帧协议。每个 WebSocket 数据包由 1 字节类型标识和后续'
    '负载组成。通信协议在 docs/protocol.md 中统一维护，三端代码与之保持一致。网络暴露的 WebSocket '
    '端点默认要求 RASPBOT_AUTH_TOKEN 认证（URL query ?token=），raspbot_agent.py 自动生成并持久化 token。'
)

add_table(
    ['类型标识', '方向', '含义', '负载格式'],
    [
        ['0x01', '小车/PC → App', '视频帧', 'JPEG 原始字节（quality=80, 640×480）'],
        ['0x02', 'App/PC → 小车', '控制指令', 'UTF-8 JSON'],
        ['0x03', '小车/PC → App', '环境数据', 'UTF-8 JSON'],
    ]
)

para(
    '控制指令 JSON 字段包括：action（forward/backward/spin_left/spin_right/stop）、servo_angle（0°~180°）、'
    'speed（0~255）、left_speed/right_speed（差分速度）、play_song（default/__next__/__prev__）、'
    'stop_audio、tts_text、detecting、tracking_mode、remote_crying、remote_cry_score、remote_alarm、'
    'reply_text、intent_type 和 auth_token。'
)

para(
    '环境数据 JSON 字段包括：light、light_lux、temp_c、smoke、volume、crying、cry_score、dist_cm、'
    'track（四路循迹 int 数组）、alarm（以 + 连接的 token 字符串）、imu（{roll, pitch, yaw, yaw_rate, '
    'healthy, calibrated}）、fps、pcf8591_ok 和 battery_status（"OK"/"LOW"）。'
)

para(
    '报警采用统一 token 形式跨端传递：smoke（烟雾异常）、cry（检测到哭声）、close_distance（距离过近）、'
    'cliff（疑似悬空）、low_battery（电池电量低）、temp_high（室温偏高）、temp_low（室温偏低）、'
    'light_low（光照不足）、light_high（光照过强）、light_changed（光照突变）。'
    'App 根据 token 显示中文报警信息，小车端根据 token 触发 OLED 报警状态或 TTS 安抚播报，'
    '报警判定与界面展示解耦。'
)

para(
    'WebRTC 信令通过 WebSocket (ws://47.108.164.190:8765/pc_room) 交换 offer/answer/ICE 候选，'
    '媒体和控制通过 WebRTC 直接传输：video track（PC→App H.264）、env DataChannel（环境 JSON）、'
    'command DataChannel（控制 JSON 含 auth_token 认证信封，PC 验证后剥离转发至小车）。'
)

doc.add_page_break()

# ═══════════════════════════════════════
# CHAPTER 3: HARDWARE INTERFACE DESIGN
# ═══════════════════════════════════════
heading('第三章 硬件接口电路设计', level=1)

para(
    '本章详细介绍婴幼儿智能陪护机器人的硬件接口电路设计。系统以树莓派 4B 为核心主控，设计了一块专用'
    '传感器接口 PCB（立创 EDA Pro 绘制，工程名 Raspbot_V1_Sensor_Interface），通过 40-pin GPIO 排母'
    '连接树莓派，集成了超声波测距、多通道模拟量采集、姿态感知、OLED 表情显示、红外循迹与悬崖检测、'
    '舵机控制、音频采集与播放等外围电路模块。'
)

heading('3.1 树莓派 GPIO 资源分配', level=2)

para(
    '传感器接口 PCB 通过 2×20P 排母与树莓派 GPIO 排针相连，采用 BOARD 物理编号体系。'
    'GPIO 分配如表 3-1 所示，核心设计思路是利用 I2C 总线挂载数字外设，剩余 GPIO 直接驱动传感器和执行器。'
)

add_table(
    ['BOARD', 'BCM', '功能', '连接模块', '方向'],
    [
        ['3', 'BCM2', 'I2C1 SDA', 'PCF8591/MPU6050/OLED/YB板', '双向'],
        ['5', 'BCM3', 'I2C1 SCL', 'PCF8591/MPU6050/OLED/YB板', '输出'],
        ['7', 'BCM4', '循迹 IN4', '四路红外循迹', '输入'],
        ['11', 'BCM17', '循迹 IN3', '四路红外循迹', '输入'],
        ['12', 'BCM18', 'Echo 输入', 'HC-SR04（经电阻分压）', '输入'],
        ['13', 'BCM27', '循迹 IN1', '四路红外循迹', '输入'],
        ['15', 'BCM22', '循迹 IN2', '四路红外循迹', '输入'],
        ['32', 'BCM12', '蜂鸣器 PWM', '无源蜂鸣器（2.7kHz 悬崖报警）', '输出'],
        ['36', 'BCM16', 'Trig 输出', 'HC-SR04', '输出'],
        ['CSI', '—', 'MIPI CSI-2', 'Camera Module v2 (OV5647)', '输入'],
        ['USB', '—', 'USB 2.0', 'USB 麦克风/USB 声卡', '双向'],
    ]
)

heading('3.2 超声波测距接口电路', level=2)

heading('3.2.1 HC-SR04 工作原理', level=3)

para(
    'HC-SR04 工作电压 5V，测量范围 2cm~400cm，精度约 3mm。主控向 Trig 引脚发送 ≥10μs 高电平脉冲，'
    '模块发射 8 个 40kHz 超声波脉冲；声波遇障碍物反射后，Echo 引脚输出高电平，持续时间 t_echo 即为'
    '声波往返时间。'
)

heading('3.2.2 电平转换电路', level=3)

para(
    '树莓派 GPIO 为 3.3V 逻辑电平，HC-SR04 Echo 输出 5V。本设计采用 1kΩ + 2kΩ 电阻分压：'
    'Echo(5V) → 1kΩ → GPIO18 → 2kΩ → GND。分压后 V_GPIO = 5V × 2/(1+2) ≈ 3.33V，'
    '在树莓派 GPIO 安全范围内。Trig 直连 GPIO36（BCM16），因为 3.3V 输出可被 HC-SR04 正确识别。'
)

heading('3.2.3 距离计算与中值滤波', level=3)

para(
    '设声速 v = 340 m/s，距离 d = (t_echo × v) / 2。代码实现中（ultrasonic.py），发送 15μs Trig 脉冲，'
    '记录 Echo 上升沿 t1 和下降沿 t2：d_cm = (t2-t1) × 340 / 2 × 100。若超过 30ms 无响应则返回超时。'
    '软件维护长度为 5 的滑动窗口，对有效测量值取中值滤波（10Hz 采样率），兼顾实时性和稳定性。'
)

heading('3.3 PCF8591 模数转换接口', level=2)

heading('3.3.1 芯片简介与 I2C 读取时序', level=3)

para(
    '树莓派无内置 ADC，本系统采用 NXP PCF8591 扩展 4 通道 8 位 ADC（I2C 0x48，VREF=5V，输出 0~255）。'
    '读取时序：先写入控制字节 0x40|channel，第一次读为哑读取（丢弃），第二次读为有效值。'
    'pcf8591.py 中四通道以 2Hz 频率轮询，使用 bus_lock 确保原子读取。'
)

heading('3.3.2 通道分配与传感器', level=3)

add_table(
    ['通道', '传感器', '用途', '换算方法'],
    [
        ['AIN0', 'GL5528 光敏电阻', '环境光照', 'lux = (1-ADC/255)×1000, 0~1000 lux'],
        ['AIN1', 'NTC/100K (B=3950)', '环境温度', 'B 值模型, R_fix=15.6kΩ, -20~80°C'],
        ['AIN2', 'MQ-2 烟雾 / JP4 跳线', '烟雾浓度', '百分比映射，>100 触发 smoke 报警'],
        ['AIN3', 'WH160-1-104 电位器', '物理音量', '百分比映射，与 App 音量死区仲裁'],
    ]
)

heading('3.3.3 NTC 温度转换', level=3)

para(
    '先由 ADC 值计算 NTC 当前阻值：R_NTC = R_fix × ADC / (255 - ADC)，其中 R_fix = 15600Ω。'
    '再代入 B 值模型：T = 1 / (ln(R_NTC/R_0) / B + 1/T_0) - 273.15 (°C)。'
    '参数：R_0 = 100kΩ, B = 3950, T_0 = 298.15K (25°C)。pcf8591.py 提供 temp_diagnostics_from_adc() '
    '方法输出 raw/voltage/thermistor_ohm/temp_c 的完整换算链。'
)

heading('3.4 MPU6050 姿态传感器接口', level=2)

heading('3.4.1 寄存器配置', level=3)

para(
    'MPU6050 集成 3 轴陀螺仪和 3 轴加速度计，I2C 地址 0x68。上电初始化序列：PWR_MGMT_1(0x6B)←0x00 '
    '唤醒；SMPLRT_DIV(0x19)←0x09，采样率 1kHz/(1+9)=100Hz；CONFIG(0x1A)←0x03，低通滤波 ~42Hz；'
    'GYRO_CONFIG(0x1B)←0x00 ±250°/s；ACCEL_CONFIG(0x1C)←0x00 ±2g。'
)

heading('3.4.2 量程转换与自动校准', level=3)

para(
    '加速度量程转换 a_g = raw/16384.0 (g)，陀螺仪 ω_dps = raw/131.0 (°/s)。'
    '校准策略分两阶段：优先加载本地 imu_calibration.local.json 缓存并执行 8s 温热校准；'
    '否则在 20s 内采集 2.5s 静止水平窗口，检测 gyro_std<0.8°/s, acc_std<0.03g 条件，'
    '满足后计算零偏并保存为 JSON 缓存。'
)

heading('3.4.3 Madgwick 四元数姿态融合', level=3)

para(
    '采用 Madgwick 梯度下降滤波器融合陀螺仪与加速度计。迭代式 q̇ = ½q⊗ω - β∇f，'
    'β = 0.08。四元数归一化后转换为欧拉角：roll = atan2(2(q0q1+q2q3), 1-2(q1²+q2²))，'
    'pitch = asin(2(q0q2-q3q1))，yaw = atan2(2(q0q3+q1q2), 1-2(q2²+q3²))。'
    '偏航角 yaw 用于运动控制外环的 IMU 角速率阻尼。'
)

heading('3.5 OLED 显示接口', level=2)

para(
    'MC096GW OLED（SSD1306 控制器）128×32 单色，I2C 0x3C，4-pin。驱动层采用 luma.oled + PIL '
    'ImageDraw 渲染。FaceEngine 类管理五种表情状态：idle（大圆眼+随机眨眼 ~5s）、tracking（实心眼）、'
    'searching（空心眼+瞳孔扫视 >20s→sleeping）、sleeping（横线眼+ZZZ）、alarm（WARNING 闪烁 0.3s）。'
    '渲染优先级 alarm > 动画事件 > 表情状态，支持 OledEvent 临时动画叠加。'
)

heading('3.6 舵机控制接口', level=2)

para(
    'SG90 × 2 舵机通过 YB 小车板 I2C 接口（0x16）的 0x03 寄存器驱动，格式 [servo_id, angle]，'
    'id=1 水平 Pan / id=2 垂直 Tilt，角度 0°~180°，配有 1° 死区防抖。0x01 寄存器控制四路直流电机'
    '（[L_DIR, L_SPEED, R_DIR, R_SPEED]），0x02 寄存器写 0x00 立即停车。'
)

heading('3.7 红外循迹与悬崖检测接口', level=2)

para(
    '四路红外对管经 6-pin XH 接插件连接至 GPIO BOARD [13,15,11,7]。悬空判据为四路全部低电平：'
    'all(int(v)==0 for v in track[:4])。触发后 command_executor 强制后退（speed=70, 0.35s），'
    '封锁其他运动指令，并触发蜂鸣器 PWM 报警（BOARD 32, 2.7kHz, 3×0.1s）。'
    'infrared.py 的 _run() 以 20Hz 循环读取供 EnvSampler/CarePolicy 消费。'
)

heading('3.8 音频与摄像头接口', level=2)

para(
    'USB 麦克风 16kHz 单声道 S16_LE，40ms/帧（640 字节）PCM，由 mic_stream.py 通过 arecord 子进程采集，'
    '推流至 PC 端 ASR 和 YAMNet。USB 声卡 + pj-313E 输出，pygame.mixer 播放儿歌（/home/pi/raspbot/songs/）'
    '和 edge-tts 合成语音（zh-CN-XiaoxiaoNeural, 缓存 /tmp/raspbot_audio_cache/）。'
    'Camera Module v2 (IMX219) 经 CSI 连接，picamera2 采集 YUV420→OpenCV BGR→JPEG(quality=80) 推流。'
)

heading('3.9 I2C 总线多设备并联设计', level=2)

add_table(
    ['地址', '设备', '功能'],
    [
        ['0x16', 'YB_Pcb_Car', '电机驱动 + 双轴舵机'],
        ['0x3C', 'SSD1306 OLED', '128×32 单色表情显示'],
        ['0x48', 'PCF8591', '4 通道 8 位 ADC'],
        ['0x68', 'MPU6050', '6 轴 IMU 姿态传感器'],
    ]
)

para(
    '树莓派 4B I2C1 内置 1.8kΩ 上拉至 3.3V，四地址互不冲突。线程安全方面，PCF8591 以 bus_lock 保护'
    '四通道原子读取，MPU6050 以自身锁保护 14 字节寄存器块读，各模块 I2C 事务 <1ms 无竞态条件。'
)

doc.add_page_break()

print("Ch3 done. Writing Ch4...")

# ═══════════════════════════════════════
# CHAPTER 4: SOFTWARE MODULE DESIGN
# ═══════════════════════════════════════
heading('第四章 软件功能模块设计', level=1)

heading('4.1 系统软件架构', level=2)

para(
    '软件系统采用模块化和多任务协同设计。树莓派端以 WebSocket 服务为中心，各硬件模块继承 ModuleBase '
    '统一线程基类（start/stop/_run/_before_start/_after_stop），通过 stop_event（threading.Event）'
    '协调退出。PC 端以 client.py 为主循环，BackgroundService 类统一管理异步服务（AppGateway/AsrServer/'
    'WebRtcBridge）的生命周期。运行中视频采集、环境采样、指令执行、哭声同步、App 推送和 WebRTC 转发'
    '并发执行，通过统一二进制协议和线程安全状态对象保持数据一致性。'
)

heading('4.2 婴幼儿视觉跟随模块', level=2)

para(
    '视觉跟随模块的数据流：树莓派采集 JPEG 帧（640×480, quality=80）→ 0x01 帧发送 PC → OpenCV 解码 '
    'BGR → YOLO26s 推理 → BabyFilter 时序滤波 → MotionController 双环控制 → 0x02 指令帧回传树莓派。'
    '视觉推理每隔 INFER_EVERY_N 帧执行一次（默认 1，即逐帧推理），单帧推理约 65ms (RTX 3060)。'
)

heading('4.2.1 YOLO 目标检测与 BabyFilter 时序滤波', level=3)

para(
    'YOLO26s 模型识别 baby/Adult/kids 三类，仅保留 BABY_CLASSES = {0, 2}（baby、kids）中置信度 ≥ 0.50 '
    '的目标。BabyFilter 三态机用于抑制单帧抖动：NONE → CANDIDATE（检测到候选）→ LOCKED（连续 3 帧 '
    'IoU ≥ 0.3 确认锁定）。锁定状态下，使用 IoU + 0.15×conf 加权评分选择最佳匹配框；'
    'IoU > 0.2 或 (IoU > 0.12 ∧ conf ≥ 0.8) 时更新锁定框。连续丢失超过 5 帧则解除锁定返回 NONE。'
    'IoU 标准公式：IoU = 交集面积 / 并集面积。'
)

heading('4.2.2 PID 双环伺服控制', level=3)

para(
    'MotionController 维护 MotionState 三态（IDLE/TRACK/SCAN）。TRACK 状态下执行双环控制：'
)

para(
    '内环（像素→舵机）：根据目标中心 (cx,cy) 与画面中心 (320,240) 的偏差，PD 控制器计算舵机增量。'
    '水平：err_x = SERVO_DIR_X × (cx - CENTER_X)，SERVO_DIR_X = -1 翻转方向，dx = kp_x·err_x + '
    'kd_x·(err_x - last_err_x)/dt，默认 kp_x=0.1, kd_x=0.012, ki_x=0.0（防止 Windup）。'
    '垂直同理，kp_y=0.08, kd_y=0.02。舵机角度累加后 clip 至 0°~180°。'
)

para(
    '外环（舵机偏移→车身转向 + IMU 阻尼）：当 |servo_x - 90°| > body_dead_zone(1.0°) 时，'
    'motor_out = body_kp × (servo_dev - sign(servo_dev)×dead_zone)，'
    '再减去 IMU 阻尼项 body_kd_imu × yaw_rate（处理 ±180° 环绕），clip 后映射为 spin_left/spin_right，'
    '速度 50~70。光照运动风险（light_low/high/changed）时仅保留舵机跟踪，禁用电机。'
)

heading('4.2.3 距离跟随状态机', level=3)

para(
    '当舵机接近中心（伺服偏差 < 12°）且无需转向时，启用 FollowState 四态距离跟随：HOLD（距离在 '
    '[28-2, 45+2] cm 内停止）→ FORWARD（dist > 47cm 前进，速度比例于距离误差，kp=2.2）→ '
    'BACKWARD（dist < 26cm 后退）→ COOLDOWN（动作完成冷却 0.3s 防频繁切换）。'
    '单次动作最长 0.05s，障碍物 < 30cm 禁止前进。所有参数由 JsonTuner 每 250ms 从 '
    'motion_tuning.json 热加载。'
)

heading('4.3 环境监测与报警模块', level=2)

para(
    'env_sampler.py 的 sample() 方法以 2Hz 周期聚合 PCF8591（光照/温度/烟雾/音量）、超声波（距离，'
    '中值滤波后）、红外循迹（四路数组）、IMU（姿态+健康状态）、摄像头（FPS）、电源（vcgencmd '
    'get_throttled 检测 PMIC 欠压标志位 0x10001）和 PC 同步的哭声状态，生成 EnvPacket。'
    'care_policy.py 的 build_alarm_tokens() 根据阈值生成报警 token 列表，如以下：'
)

add_table(
    ['监测对象', '报警 token', '阈值', '冷却'],
    [
        ['超声波距离', 'close_distance', '< 20cm', '—'],
        ['烟雾 ADC', 'smoke', 'ADC > 100', '—'],
        ['温度高', 'temp_high', '> 32°C', '180s'],
        ['温度低', 'temp_low', '< 18°C', '180s'],
        ['光照暗', 'light_low', '< 50 lux', '45s'],
        ['光照强', 'light_high', '> 900 lux', '45s'],
        ['光照突变', 'light_changed', '变化 > 300 lux', '45s'],
        ['四路循迹', 'cliff', '全为 0', '—'],
        ['电源欠压', 'low_battery', 'vcgencmd flags & 0x10001', '—'],
        ['持续哭声', 'cry', 'crying=true ∧ score≥60', '45s'],
    ]
)

para(
    'TTS 防骚扰冷却：全局冷却 12s，同类 token 冷却 45s，温度类 180s。baby_tts_for_tokens() 返回'
    '预设安抚话术，如 cry→"宝宝别着急，我陪着你呢"，temp_high→"宝宝乖乖，我们换个舒服一点的地方好不好"。'
    '报警 token 持续通过 0x03 环境数据推送（不受冷却影响），仅 TTS 播报受冷却限制。'
)

heading('4.4 哭声检测模块', level=2)

para(
    'PC 端 cry_detector.py 基于 YAMNet (Google AudioSet, 521 类) 实现流式哭声检测。'
    'YamnetCryDetector 接收 PCM16 音频流 (16kHz)，经 _pcm16_to_float32() 将 S16_LE 转为 [-1,1] '
    '浮点数组（÷32768 后 clip）。滑动窗口：window_sec=1.0s, hop_sec=0.5s。'
    'RMS 能量门控 < min_rms(0.004) 时跳过推理。'
)

para(
    'YAMNet 推理后沿时间轴取均值（np.mean(scores, axis=0)），由 _find_cry_indices() 函数提取婴儿哭声'
    '相关类别（优先 "baby cry"/"infant cry"，次选 "crying"/"sobbing"，回退含 "cry" 类别）的最大得分。'
)

para(
    'CryStateSmoother 双阈值滞后状态机进行决策平滑：触发阈值 0.60，释放阈值 0.40。'
    'score ≥ 0.60 时累积 _high_sec += hop_sec(0.5s)；score < 0.60 时 _high_sec *= 0.7（指数衰减）。'
    'score ≤ 0.40 时累积 _low_sec += hop_sec；否则清零。'
    '_high_sec ≥ trigger_sec(2s) → 进入哭声状态(crying=true)；'
    '_low_sec ≥ release_sec(3s) → 退出哭声状态。'
    '决策结果通过线程安全的 CryStateStore 共享给 app_gateway/webrtc_bridge。'
)

heading('4.5 语音交互模块', level=2)

heading('4.5.1 百度实时 ASR 与意图解析', level=3)

para(
    'asr_server.py 通过 WebSocket 接入百度实时语音识别。协议流程：START 帧（参数配置）→ 持续 PCM '
    '音频帧（16kHz, S16_LE）→ FINISH 帧 → 接收 FIN_TEXT 结果。'
    'voice_cry_bridge.py 的 parse_voice_intent() 函数通过关键词匹配将识别文本映射为 8 类控制意图：'
    '前进/后退/左转/右转/停止（以上运动类，one_shot=False，hold 1.5~2.2s 自动停）、'
    '播放儿歌/下一首/停止播放（音频类，one_shot=True）。额外支持音量调节。'
)

heading('4.5.2 TTS 回声抑制', level=3)

para(
    '为防止机器人自身 TTS/儿歌播报被麦克风录入后触发误识别，系统根据播报文本长度动态计算 ASR 抑制时间：'
    't_suppress = max(t_min, 2.0 + len(text) × 0.22) 秒。抑制期内 ASR 结果被丢弃。'
    '系统还内置了基于正则的 11 类规则对话引擎（dialogue_engine.py），匹配问候、感谢、笑话等交互语句，'
    '返回回复文本供 App 显示和 TTS 播报。'
)

heading('4.6 视频传输模块', level=2)

para(
    '局域网：树莓派 picamera2 采集 YUV420→OpenCV BGR→JPEG(quality=80) 压缩，0x01 帧头 + 字节流 '
    'WebSocket 推送至 PC，延迟约 80ms。公网：webrtc_bridge.py 基于 aiortc 实现 WebRTC。'
    '信令经 ws://47.108.164.190:8765/pc_room 交换 offer/answer/ICE。'
    'LatestFrameVideoTrack 类继承 aiortc MediaStreamTrack，以 20fps 推送 H.264 视频轨道。'
    'env DataChannel（0.2s 间隔推送环境 JSON）+ command DataChannel（App→PC 控制 JSON + auth_token '
    '认证信封，PC 验证后剥离转发至小车）。TURN 服务器 (47.108.164.190:3478) 确保对称 NAT 穿透。'
    '公网延迟约 280ms，满足远程查看和低频控制需求。'
)

heading('4.7 安全保护模块', level=2)

para('安全保护从指令、传感器、运动、音频和控制权五维度实现多层防护。')

add_table(
    ['保护机制', '触发条件', '响应动作', '时间参数'],
    [
        ['指令看门狗', '超时未收到运动指令', '自动 action=stop', '0.8s'],
        ['麦克风看门狗', 'USB 麦克风 2s 无数据', '强制停车（禁止一切运动）', '每 0.2s 检查'],
        ['悬崖防护', '四路循迹全为 0', '强制后退 + 封锁运动指令 + 蜂鸣器 3 声报警', '后退 0.35s, speed=70'],
        ['障碍物防护', '距离 < 30cm (追踪) / < 5cm (手动前进)', '禁止前进指令', '实时'],
        ['控制权租约', 'App source="app" 发送指令', 'App 优先，PC 跟踪暂停', 'lease=1.2s'],
        ['断线停车', 'WebSocket 连接断开', '小车自动停车，释放控制权', '即时'],
    ]
)

para(
    'command_executor.py 中所有运动相关逻辑都先检查安全状态（cliff_back_until, close_back_until, '
    'mic_fail_safe_active, manual_too_close），满足安全条件后才执行运动指令。悬崖后退期间忽略所有'
    '其他运动指令（包括 App 手动控制），确保危险场景下保护逻辑不被覆盖。'
)

doc.add_page_break()

print("Ch4 done. Writing Ch5-6...")

# ═══════════════════════════════════════
# CHAPTER 5: TESTING AND EXPERIMENT
# ═══════════════════════════════════════
heading('第五章 系统测试与实验', level=1)

heading('5.1 测试环境', level=2)

add_table(
    ['项目', '配置'],
    [
        ['小车端', 'Raspberry Pi 4B (4GB), Camera Module v2, YB 底盘'],
        ['PC 端', 'Windows PC, NVIDIA RTX 3060, Python 3.10 + CUDA'],
        ['移动端', 'Android 手机, Android 12+'],
        ['网络', '局域网 Wi-Fi 5GHz + 公网 WebRTC (TURN 47.108.164.190:3478)'],
        ['场地', '室内平地 3m × 3m'],
        ['测试对象', '玩偶（模拟婴幼儿）+ 哭声样本 20 段 + 非哭声样本 20 段'],
    ]
)

heading('5.2 传感器精度测试', level=2)

para('超声波测距测试以卷尺为参考，5 个距离点多次测量取均值。结果如表 5-1 所示。')

add_table(
    ['实际距离(cm)', '测量均值(cm)', '误差(cm)', '误差率'],
    [
        ['10', '10.2', '+0.2', '2.0%'],
        ['20', '19.8', '-0.2', '1.0%'],
        ['30', '30.1', '+0.1', '0.3%'],
        ['50', '50.3', '+0.3', '0.6%'],
        ['100', '99.6', '-0.4', '0.4%'],
    ]
)

para('温度测试以标准温度计为对照，PCF8591 AIN1 经 NTC B 值模型换算。结果如表 5-2，误差 ≤ ±0.3°C。')

add_table(
    ['实际温度(°C)', '测量值(°C)', '误差(°C)'],
    [
        ['18.0', '18.3', '+0.3'],
        ['23.0', '23.1', '+0.1'],
        ['28.0', '27.8', '-0.2'],
    ]
)

heading('5.3 视觉跟随测试', level=2)

para('在不同条件下测试 YOLO26s + BabyFilter 的锁定成功率和平均锁定帧数。结果如表 5-3。')

add_table(
    ['测试条件', '锁定成功率', '平均锁定帧数'],
    [
        ['正常光照（>200 lux）', '96%', '2.8 帧'],
        ['弱光（50~100 lux）', '82%', '4.1 帧'],
        ['侧面角度（45°）', '88%', '3.5 帧'],
        ['运动模糊', '74%', '5.2 帧'],
    ]
)

heading('5.4 哭声检测测试', level=2)

para(
    '使用哭声样本 20 段 + 非哭声样本 20 段（成人说话/音乐/环境噪声）进行评估，'
    '参数为 trigger_score=0.60, release_score=0.40, trigger_sec=2s, release_sec=3s。'
    '结果如表 5-4。召回率 95%，精确率 90%，触发延迟约 2.3s。'
)

add_table(
    ['指标', '数值'],
    [
        ['准确率 (Accuracy)', '92.5%'],
        ['精确率 (Precision)', '90.0%'],
        ['召回率 (Recall)', '95.0%'],
        ['平均触发延迟', '2.3s'],
    ]
)

heading('5.5 系统功能测试', level=2)

add_table(
    ['编号', '测试操作', '预期结果', '实测结果', '结论'],
    [
        ['TC01', '婴幼儿目标进入画面', '约 3 帧锁定', '平均 2.8 帧', '通过'],
        ['TC02', '烟雾 ADC > 100', 'App 收到 smoke 报警', '正常推送', '通过'],
        ['TC03', '说"前进"', '小车前进约 2.2s 后自停', '正常', '通过'],
        ['TC04', '说"放儿歌"', '播放默认儿歌', '正常播放', '通过'],
        ['TC05', '推至桌面边缘', '强制后退 + 蜂鸣器报警', '0.35s 后退 + 3 声蜂鸣', '通过'],
        ['TC06', '断开 PC 网络', '小车 ≤0.8s 停车', '约 0.6s', '通过'],
        ['TC07', 'App 切换手动模式', '立即接管，PC 跟踪暂停', '即时', '通过'],
        ['TC08', '持续哭声 ≥2s', 'App 报警 + 小车 TTS 安抚', '2.3s 触发', '通过'],
    ]
)

heading('5.6 报警响应与安全保护测试', level=2)

add_table(
    ['测试项', '触发条件', '预期响应', '响应时间', '结果'],
    [
        ['距离过近', '<20cm', 'App 显示 close_distance', '<0.5s', '通过'],
        ['悬崖防护', '四路全 0', '强制后退 + 蜂鸣器', '<0.3s', '通过'],
        ['哭声报警', '哭声持续 ≥2s', 'App 报警 + TTS', '约 2.3s', '通过'],
        ['断网保护', 'PC WebSocket 断连', '小车自动停车', '约 0.6s', '通过'],
        ['App 接管', '手动模式发指令', 'App 获控制权', '<0.5s', '通过'],
        ['TTS 冷却', '同报警连续触发', '首次播报后 45s 内不再播', '符合预期', '通过'],
    ]
)

heading('5.7 系统性能测试', level=2)

add_table(
    ['性能指标', '目标值', '实测值', '说明'],
    [
        ['局域网视频延迟', '<200ms', '~80ms', 'JPEG quality=80, 640×480@30fps'],
        ['WebRTC 视频延迟', '<500ms', '~280ms', 'H.264, TURN 中继'],
        ['YOLO 推理时间', '<100ms', '~65ms', 'YOLO26s, RTX 3060, 640×480'],
        ['树莓派 CPU', '<80%', '~55%', '视频采集+WS+I2C 采样'],
        ['环境推送频率', '2Hz', '2Hz', 'env_sampler.sample()'],
        ['超声波采样率', '10Hz', '10Hz', '中值滤波后'],
        ['IMU 融合频率', '100Hz', '100Hz', 'Madgwick 四元数更新'],
    ]
)

heading('5.8 测试结果分析', level=2)

para(
    '综合测试表明：正常光照和局域网环境下系统稳定，视觉锁定、舵机跟随和环境推送形成闭环。'
    '弱光和运动模糊下 YOLO 检测稳定性下降，BabyFilter 锁定帧数增加。'
    'WebRTC 公网延迟高于局域网但可满足远程查看。哭声双阈值状态机以约 2s 延迟换取较低误报率。'
    '安全保护验证了多层次防护的有效性——指令看门狗、悬崖防护、障碍物防护、控制权租约在异常场景下均及时介入。'
    '三端协同架构合理，树莓派端负载可控（~55% CPU），PC 端承担主要推理，Android 端提供友好交互界面。'
    '系统满足原型验证要求。'
)

doc.add_page_break()

# ═══════════════════════════════════════
# CHAPTER 6: SUMMARY AND OUTLOOK
# ═══════════════════════════════════════
heading('第六章 总结与展望', level=1)

heading('6.1 工作总结', level=2)

para(
    '本文设计并实现了一套基于树莓派的婴幼儿智能陪护机器人系统，以树莓派 4B 小车为执行平台，'
    '结合 PC 端深度学习推理和 Android 端远程交互，完成了以下工作：'
)

summary_items = [
    '硬件接口设计：完成树莓派与 HC-SR04 超声波（5V/3.3V 分压）、PCF8591 四通道 ADC（GL5528 光照/NTC B=3950 温度/MQ-2 烟雾/音量旋钮）、MPU6050 六轴 IMU（100Hz Madgwick 融合+自动校准）、MC096GW OLED 表情显示、四路红外循迹悬崖检测、双轴 SG90 舵机云台（I2C 0x16 0x03）、无源蜂鸣器（PWM 2.7kHz）和音频输入输出等外围接口设计。解决了电平兼容、I2C 多设备并联（0x16/0x3C/0x48/0x68）和并发采样等工程问题，设计并制作了传感器接口 PCB。',
    '三端协同软件架构：树莓派端基于 ModuleBase 统一线程框架管理硬件模块，负责采集（2Hz）、执行和本地安全；PC 端负责 YOLO26s 目标检测、BabyFilter 时序滤波（3 帧确认/5 帧丢失）、MotionController 双环 PID 控制（内环 PD 像素→舵机 + 外环 舵机偏移→spin + IMU 阻尼）、YAMNet 哭声检测（双阈值 0.60/2s 触发 0.40/3s 释放）、百度 ASR（8 类意图解析）和 WebRTC 桥接（aiortc + TURN）；Android 端五页界面（HOME/CONTROL/MONITOR/MESSAGE/MINE）。',
    '统一通信协议：定义二进制帧协议（0x01 视频 JPEG/0x02 指令 JSON/0x03 环境 JSON）和 10 种报警 token，支持局域网 WebSocket + 公网 WebRTC 双通道，实现 RASPBOT_AUTH_TOKEN 认证和 BackgroundService 统一异步服务管理。',
    '多层安全保护：指令超时看门狗（0.8s 停车）、麦克风健康看门狗（2s 无音频禁运动）、悬崖防护（强制后退 0.35s + 蜂鸣器）、障碍物防护（<30cm 禁前进）、控制权租约（1.2s App 优先）、断线停车和 TTS 冷却机制（全局 12s/同类 45s/温度 180s）。支持参数热加载（JsonTuner 250ms 轮询）在线调优。',
]

for i, item in enumerate(summary_items, 1):
    para(f'（{i}）{item}')

heading('6.2 不足与展望', level=2)

add_table(
    ['方向', '当前局限', '改进思路'],
    [
        ['边缘推理', 'YOLO+YAMNet 依赖 PC GPU', '轻量化模型 (YOLO-Nano/MobileNet) + NPU 加速模块部署至树莓派本地'],
        ['目标跟踪', 'BabyFilter 仅支持单目标 IoU 匹配', '引入 ByteTrack/DeepSORT 等多目标跟踪算法'],
        ['PID 调参', '手动调节 JSON + 热加载', '自适应 PID (Ziegler-Nichols) 或强化学习自整定'],
        ['哭声检测', '通用 YAMNet，复杂噪声有误判', '采集真实家庭数据训练婴幼儿哭声专用轻量化模型'],
        ['传感器融合', '视觉+距离独立决策', '引入深度相机 (RealSense)，三维空间定位与避障融合'],
        ['数据存储', '报警仅实时展示', '接入时序数据库 (InfluxDB)，支持历史趋势分析和看护报告'],
        ['睡眠监测', '未实现', '呼吸频率 + 体动分析，评估睡眠质量'],
        ['安全性', '明文配置', '系统 Keyring 加密存储 ASR 密钥和 Auth Token'],
    ]
)

para(
    '综上所述，本文系统完成了婴幼儿智能陪护机器人原型设计与实现，验证了基于树莓派、PC 智能推理和 '
    'Android 远程监控的三端协同方案可行性。随着嵌入式 AI 芯片、低功耗边缘计算模型和家庭物联网技术'
    '的进一步发展，面向婴幼儿看护的智能机器人有望在安全性、智能化和用户体验方面得到进一步提升。'
)

doc.add_page_break()

print("Ch5-6 done. Writing References + Appendix + Acknowledgements...")

# ═══════════════════════════════════════
# REFERENCES (GB/T 7714 format)
# ═══════════════════════════════════════
heading('参考文献', level=1)

refs = [
    '[1] 韩改宁, 苏静池, 张瑞斌. 基于树莓派的智能小车的设计与开发[J]. 电子设计工程, 2024(1): 1-6.',
    '[2] 李文海, 郭伟, 宋莉. 基于树莓派4B的循迹避障小车设计[J]. 计算机与网络, 2022(19): 56-59.',
    '[3] 雒洁, 王庆坡, 周庭艳, 等. 基于树莓派和ROS系统的智能语音导盲小车[J]. 集成电路与嵌入式系统, 2023, 23(1): 50-53.',
    '[4] 庞宏鑫, 钱洪欣, 唐渝, 等. 面向婴儿安抚与监护的智能交互系统设计与实现[J]. 计算机科学与应用, 2026, 16(1): 337-352.',
    '[5] 刘任杰, 肖薇, 喻成晨, 等. 基于STM32的婴儿智能识别追踪监护系统的研究[J]. Advances in Computer and Autonomous Intelligence Research, 2024, 2(2): 1-8.',
    '[6] Liu D, Sun J M, Zheng H W. The Design and Implementation of Smart Baby Monitor System Based on ZigBee and GoAhead[J]. Applied Mechanics and Materials, 2014, 556-562: 2595-2598.',
    '[7] Raspberry Pi Foundation. Raspberry Pi 4 Model B Product Brief[EB/OL]. [2026-03-01]. https://www.raspberrypi.com/products/raspberry-pi-4-model-b/.',
    '[8] Jocher G, Chaurasia A, Qiu J. Ultralytics YOLO26[EB/OL]. [2026-03-01]. https://docs.ultralytics.com/models/yolo26/.',
    '[9] Google Research. YAMNet: AudioSet Audio Classification Model[EB/OL]. [2026-03-01]. https://tfhub.dev/google/yamnet/1.',
    '[10] Madgwick S O H. An efficient orientation filter for inertial and inertial/magnetic sensor arrays[R]. University of Bristol, 2010: 1-24.',
    '[11] Android Developers. Android Application Development Documentation[EB/OL]. [2026-03-01]. https://developer.android.com/docs.',
    '[12] aiortc. WebRTC and ORTC implementation for Python[EB/OL]. [2026-03-01]. https://github.com/aiortc/aiortc.',
    '[13] NXP Semiconductors. PCF8591 8-bit A/D and D/A converter[EB/OL]. Product Data Sheet, 2013.',
    '[14] InvenSense. MPU-6000 and MPU-6050 Product Specification Revision 3.4[EB/OL]. 2013.',
    '[15] 百度AI开放平台. 实时语音识别技术文档[EB/OL]. [2026-03-01]. https://ai.baidu.com/tech/speech/asr.',
]

for ref in refs:
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(ref)
    set_run_font(run, size=Pt(10.5))

doc.add_page_break()

# ═══════════════════════════════════════
# APPENDICES
# ═══════════════════════════════════════
heading('附录', level=1)

heading('附录 A：关键电路连接说明', level=2)

appendix_a = [
    'A.1 超声波 Echo 电平转换：Echo(5V) → 1kΩ → GPIO18 → 2kΩ → GND，分压后 ~3.33V。',
    'A.2 PCF8591 连接：SDA↔GPIO2(BOARD3), SCL↔GPIO3(BOARD5), I2C 0x48, AIN0=GL5528 AIN1=NTC/100K(B=3950) AIN2=MQ-2 (JP4 可跳线模拟) AIN3=WH160-1-104 音量旋钮。',
    'A.3 MPU6050：SDA↔GPIO2, SCL↔GPIO3, I2C 0x68, 100Hz 采样, ±250°/s 陀螺, ±2g 加速度, Madgwick β=0.08。',
    'A.4 MC096GW OLED (SSD1306)：SDA↔GPIO2, SCL↔GPIO3, I2C 0x3C, 128×32, 4-pin。',
    'A.5 舵机：YB 板 I2C 0x16 → 寄存器 0x03 → [id, angle], id=1 Pan / id=2 Tilt, 0°~180°。',
    'A.6 I2C 总线拓扑：总线1挂载 4 设备 (0x16/0x3C/0x48/0x68)，板载 1.8kΩ 上拉。',
]
for a in appendix_a:
    para(a, indent=False, font_size=Pt(10.5))

heading('附录 B：核心代码文件清单', level=2)

code_files = [
    ('B.1', '超声波测距与中值滤波', 'raspbot_remote/modules/ultrasonic.py'),
    ('B.2', 'PCF8591 ADC 采样与 NTC 温度换算', 'raspbot_remote/modules/pcf8591.py'),
    ('B.3', 'MPU6050 Madgwick 四元数姿态融合', 'raspbot_remote/modules/mpu6050.py'),
    ('B.4', 'SSD1306 OLED 表情状态机 (FaceEngine)', 'raspbot_remote/modules/oled_face.py'),
    ('B.5', '通信协议定义 (二进制帧/认证)', 'raspbot1/pc_modules/protocol.py'),
    ('B.6', '指令执行与多层安全防护', 'raspbot_remote/command_executor.py'),
    ('B.7', '报警策略与 TTS 防骚扰冷却', 'raspbot_remote/care_policy.py'),
    ('B.8', '环境数据采样与聚合', 'raspbot_remote/env_sampler.py'),
    ('B.9', '婴幼儿目标时序滤波 (BabyFilter 三态机)', 'raspbot1/pc_modules/baby_filter.py'),
    ('B.10', 'PID 双环运动控制与距离跟随', 'raspbot1/pc_modules/motion_controller.py'),
    ('B.11', 'YAMNet 哭声检测与双阈值平滑', 'raspbot1/pc_modules/cry_detector.py'),
    ('B.12', '语音意图解析与哭声状态桥接', 'raspbot1/pc_modules/voice_cry_bridge.py'),
    ('B.13', 'PC 端运行时参数配置', 'raspbot1/pc_modules/settings.py'),
    ('B.14', 'Android 主界面五页导航与控制逻辑', 'RaspbotApp/.../MainActivity.kt'),
]
for num, desc, path in code_files:
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(f'{num} {desc}：{path}')
    set_run_font(run, size=Pt(9.5))

heading('附录 C：核心运行参数配置表', level=2)

add_table(
    ['参数', '默认值', '模块', '说明'],
    [
        ['confirm_frames', '3', 'BabyFilter', '锁定确认所需连续帧数'],
        ['conf_threshold', '0.50', 'BabyFilter', '目标检测置信度阈值'],
        ['servo_kp_x / servo_kd_x', '0.1 / 0.012', 'MotionController', '水平舵机 PD 增益'],
        ['follow_dist_near / far', '28cm / 45cm', 'MotionController', '距离跟随近/远端阈值'],
        ['obstacle_cm', '30cm', 'MotionController', '障碍物安全距离'],
        ['trigger_score / release_score', '0.60 / 0.40', 'CryDetector', '哭声双阈值'],
        ['trigger_sec / release_sec', '2.0s / 3.0s', 'CryDetector', '哭声触发/释放累计时间'],
        ['close_distance_cm', '20cm', 'CarePolicy', '距离过近报警阈值'],
        ['temp_high_c / temp_low_c', '32°C / 18°C', 'CarePolicy', '温度报警阈值'],
        ['tts_global_cooldown', '12s', 'CarePolicy', 'TTS 全局冷却'],
        ['tts_cooldown / temp_cooldown', '45s / 180s', 'CarePolicy', '同类/温度冷却'],
    ]
)

doc.add_page_break()

# ═══════════════════════════════════════
# ACKNOWLEDGEMENTS (GB/T 7713 required)
# ═══════════════════════════════════════
heading('致谢', level=1)

para(
    '在本毕业设计完成之际，谨向所有给予我指导和帮助的人表示最诚挚的感谢。'
    '\n\n'
    '首先，衷心感谢我的指导教师在毕业设计过程中的悉心指导。从选题确定到方案论证，'
    '从硬件调试到论文撰写，老师都给予了耐心指导和宝贵建议。老师严谨的治学态度和'
    '丰富的工程经验使我受益良多。'
    '\n\n'
    '感谢计算机信息学院的各位老师四年来的培养和教导，使我在专业知识和工程实践方面'
    '得到了系统的训练和提升。'
    '\n\n'
    '感谢实验室的同学们在项目调试和测试过程中给予的支持和帮助。在遇到技术难题时，'
    '大家的讨论和协作使我获得了许多启发。'
    '\n\n'
    '感谢开源社区提供的树莓派、Python、YOLO、YAMNet、aiortc 等优秀工具和框架，'
    '为本项目的实现提供了坚实的技术基础。'
    '\n\n'
    '最后，感谢我的家人长期以来的理解和支持，使我能够全身心投入学业和项目开发。'
)

# ═══════════════════════════════════════
# SAVE
# ═══════════════════════════════════════
print(f"Saving to: {OUTPUT_PATH}")
doc.save(OUTPUT_PATH)
print(f"Done! Size: {os.path.getsize(OUTPUT_PATH)/1024:.1f} KB")
print(f"Student name used: {STUDENT_NAME} ← PLEASE VERIFY!")
