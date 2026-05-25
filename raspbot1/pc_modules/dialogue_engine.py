"""Rule-based dialogue engine for Raspbot voice chat."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class DialogueReply:
    text: str


_Rule = Tuple[re.Pattern, List[str]]


def _build_rules() -> List[_Rule]:
    return [
        (re.compile(r"你是谁|你叫什么|你的名字"), [
            "我是你的陪伴小车～",
            "我叫Raspbot，是你的机器人小伙伴！",
        ]),
        (re.compile(r"你会(什么|做|哪些|干嘛|干啥)"), [
            "我会陪你聊天、放儿歌、跟着你走！你可以说「播放儿歌」或者「前进」来指挥我～",
            "我可以听懂你的指令哦！试试说「播放儿歌」「左转」「后退」～",
        ]),
        (re.compile(r"讲个?笑话|说个?笑话"), [
            "为什么机器人从来不生气？因为它有钢铁般的自制力！",
            "小汽车对爸爸说：爸爸爸爸，为什么我跑得这么快？爸爸说：因为你妈是法拉利！",
            "程序员小明对机器人说：向前走一步。机器人走了两步。小明问为什么，机器人说：我顺便执行了一个++操作。",
        ]),
        (re.compile(r"再(说|讲)一(遍|次)|重复"), [
            "我刚才说过了哦，你忘了吗～",
        ]),
        (re.compile(r"你好|嗨|哈[喽咯]|hi|hello"), [
            "你好呀！有什么我可以帮你的吗？",
            "嗨！今天想让我做什么呢？",
        ]),
        (re.compile(r"谢谢|多谢|感谢|谢了"), [
            "不客气～",
            "不用谢，这是我应该做的！",
        ]),
        (re.compile(r"再见|拜拜|bye|晚安"), [
            "再见！随时叫我～",
            "拜拜，我会在这儿等你！",
        ]),
        (re.compile(r"天气|今天.*天气|外面.*天气"), [
            "我现在还不会查天气呢，不过你可以看看窗外～",
            "天气的事我不太懂，但我知道陪在你身边总是晴天！",
        ]),
        (re.compile(r"几岁|多大|生日"), [
            "我永远三岁！正是最可爱的年纪～",
        ]),
        (re.compile(r"你(真|好|太).*(棒|厉害|聪明|可爱)"), [
            "嘿嘿，谢谢夸奖～",
            "那是因为我有一个厉害的主人！",
        ]),
        (re.compile(r"唱歌|唱一首|来一首"), [
            "你可以说「播放儿歌」，我马上唱给你听！",
        ]),
        (re.compile(r"无聊|没意思|没劲"), [
            "那我放首儿歌给你听吧？说「播放儿歌」就行～",
            "要不我们玩个游戏？你说「前进」，我来追你！",
        ]),
    ]


class DialogueEngine:
    """Rule-first dialogue engine. Returns a reply when a rule matches."""

    def __init__(self):
        self._rules = _build_rules()

    def respond(self, text: str) -> Optional[DialogueReply]:
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        for pattern, replies in self._rules:
            if pattern.search(cleaned):
                return DialogueReply(text=random.choice(replies))
        return None
