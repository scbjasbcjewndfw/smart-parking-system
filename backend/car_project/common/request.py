# coding: utf-8
"""请求体读取：所有接口入口统一走这里，只做一次类型兜底。"""
from __future__ import annotations

from flask import request


def json_body() -> dict:
    """读取 JSON 请求体；非对象（未传、数组、非法 JSON）一律视为空对象。"""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}
