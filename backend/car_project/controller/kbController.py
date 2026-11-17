# coding: utf-8
"""车主客服接口层：知识库问答。

接口清单（前缀 ``/api/kb``，无需 JWT——客服咨询不应要求先登录）
-----------------------------------------------------------------
- ``POST /answer``  受约束问答：domain 路由 → 检索 → 生成
- ``GET  /stats``   知识库条目统计

错误约定：知识库未就绪（未配 Key / 文档缺失）返回 code=503，
前端据此提示"客服功能暂不可用"，不影响其他功能。
"""
from __future__ import annotations

from flask import Blueprint

from common.Result import Result
from common.request import json_body
from service import kbService

kb_bp = Blueprint("kb", __name__, url_prefix="/api/kb")


@kb_bp.post("/answer")
def answer():
    """车主客服问答。

    请求体::

        {"question": "停车费怎么算？", "domain": null}

    domain 可选，用于前端按域筛选；缺省由后端关键词路由决定。
    返回 data 内含 answer/sources/refused/confidence_pending 等字段，
    前端依据 refused 与 confidence_pending 展示"转人工"徽章。
    """
    body = json_body()
    question = (body.get("question") or "").strip()
    if not question:
        return Result.fail(400, "请输入问题")
    domain = body.get("domain") or None
    if domain and domain not in kbService.DOMAINS:
        return Result.fail(400, f"未知业务域：{domain}")

    try:
        data = kbService.answer(question, domain=domain)
    except RuntimeError as exc:
        # 配置缺失或上游接口失败：客服降级，但系统其余功能不受影响
        return Result.fail(503, f"客服功能暂不可用：{exc}")
    return Result.success("操作成功", data)


@kb_bp.get("/stats")
def stats():
    """知识库统计：条目数、domain 分布、待确认条数。"""
    try:
        return Result.success("操作成功", kbService.stats())
    except FileNotFoundError as exc:
        return Result.fail(503, f"知识库目录缺失：{exc}")
