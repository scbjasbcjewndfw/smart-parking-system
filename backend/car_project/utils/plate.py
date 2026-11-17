# coding: utf-8
"""车牌号规范化与校验（全项目唯一口径）。

为什么单独抽出来
----------------
改动前项目里有 3 处各写一套车牌正则：

1. ``service/plateService.py``    —— 入场校验，不支持"使/领"开头与尾位"澳"
2. ``service/plate_recognizer.py`` —— OCR 结果过滤，支持"使领""澳"
3. ``controller/userController.py`` —— 注册校验，长度与尾位规则又不一样

三者不一致的直接后果是：某类车牌可以识别、可以注册，但入不了场；或者能入场
却查不到订单。统一到本模块后，规则只在这里维护，调用方不得再自建正则。
"""
from __future__ import annotations

import re
from typing import Any, Final

# 省级行政区简称（不含港澳台，港澳车辆按"粤Z…港/澳"规则处理）
PROVINCES: Final[str] = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"

# 使领馆车牌以"使""领"开头，不带省级简称
SPECIAL_PREFIXES: Final[str] = "使领"

# 尾位允许出现的特殊汉字：挂车、教练、警用、香港/澳门入出境
SPECIAL_SUFFIXES: Final[str] = "挂学警港澳"

# 民用车牌：省份简称（或使/领）+ 发牌机关字母 + 4~5 位序号 + 尾位
# 发牌机关代号不使用 I 和 O，避免与 1、0 混淆
PLATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^(?:[{PROVINCES}]|[{SPECIAL_PREFIXES}])"
    r"[A-HJ-NP-Z]"
    r"[A-HJ-NP-Z0-9]{4,5}"
    rf"[A-HJ-NP-Z0-9{SPECIAL_SUFFIXES}]$"
)

# 从任意文本中提取车牌（供全图 OCR 兜底使用），前后不能紧邻字母数字
PLATE_SEARCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?<![A-Z0-9])"
    rf"(?:[{PROVINCES}]|[{SPECIAL_PREFIXES}])"
    r"[A-HJ-NP-Z]"
    r"[A-HJ-NP-Z0-9]{4,5}"
    rf"[A-HJ-NP-Z0-9{SPECIAL_SUFFIXES}]"
    r"(?![A-Z0-9])"
)

# OCR 结果中常见的分隔符与误识别字符
_NOISE_CHARS: Final[tuple[str, ...]] = (
    "·", "•", " ", "-", "—", ":", "：", "．", ".", "[", "]", "(", ")", "（", "）",
)


def normalize_plate(raw: Any) -> str:
    """把任意输入规范化为可入库的车牌字符串。

    去掉分隔符、全角转半角、统一大写。不做合法性判断。

    Args:
        raw: 用户输入或 OCR 原始文本，允许为 None。

    Returns:
        规范化后的字符串；输入为空时返回空字符串。

    Examples:
        >>> normalize_plate(" 皖a·D03683 ")
        '皖AD03683'
    """
    if raw is None:
        return ""
    text = str(raw)
    for char in _NOISE_CHARS:
        text = text.replace(char, "")
    # 全角字母数字转半角，避免中文输入法导致的校验失败
    normalized = []
    for char in text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            normalized.append(chr(code - 0xFEE0))
        else:
            normalized.append(char)
    return "".join(normalized).strip().upper()


def is_valid_plate(raw: Any) -> bool:
    """判断字符串是否为合法车牌号（整串匹配）。

    Args:
        raw: 待校验的车牌字符串。

    Returns:
        True 表示格式合法。

    Examples:
        >>> is_valid_plate("皖AD03683")
        True
        >>> is_valid_plate("皖AD0368")
        False
    """
    return bool(PLATE_PATTERN.match(normalize_plate(raw)))


def search_plate(text: str) -> str | None:
    """从一段文本中提取第一个合法车牌。

    用于 YOLO 未检出车牌时对全图 OCR 文本做兜底筛选。

    Args:
        text: OCR 识别出的原始文本。

    Returns:
        命中的车牌号，未命中返回 None。
    """
    if not text:
        return None
    match = PLATE_SEARCH_PATTERN.search(normalize_plate(text))
    return match.group() if match else None
