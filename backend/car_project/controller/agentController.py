# coding: utf-8
"""客服 Agent 接口层。

接口清单（前缀 ``/api/agent``，登录可选——匿名也能问知识库，查订单必须登录）
-----------------------------------------------------------------------
- ``POST /chat``  Agent 对话：ReAct 规划 → 工具调用 → 受约束回答
- ``POST /chat/stream``  流式对话：SSE 推送进度、增量文本与最终结果

请求体::

    {"question": "帮我查一下停车订单", "session_id": "uuid"}

登录时从 JWT 取 user_id 与绑定车牌：Agent 只允许查询本人订单；
匿名请求仍可问知识库，但订单相关工具会提示先登录。
"""
from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, Response, stream_with_context
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from common.Result import Result
from common.request import json_body
from config.database import SessionLocal
from models.models import SysUser
from service import agentService, kbService

logger = logging.getLogger(__name__)

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")

#: 单条问题长度上限：客服问句不需要更长，也避免把超长文本塞进上下文
MAX_QUESTION_LEN = 500


def _resolve_user() -> tuple:
    """从可选 JWT 解析当前用户与绑定车牌；无效 token 按匿名处理。"""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
    except Exception:  # noqa: BLE001
        identity = None

    user_id = None
    if isinstance(identity, int):
        user_id = identity
    elif isinstance(identity, str) and identity.isdigit():
        user_id = int(identity)

    plate = None
    if user_id is not None:
        with SessionLocal() as session:
            user = session.get(SysUser, user_id)
        plate = user.plate if user else None
    return user_id, plate


def _sse(event: str, data: dict) -> str:
    """格式化一条 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@agent_bp.post("/chat")
def chat():
    """客服 Agent 对话入口。

    返回 data::

        {answer, session_id, refused, confidence_pending, sources,
         steps, ticket_id, transfer, latency_ms}
    """
    body = json_body()
    question = (body.get("question") or "").strip()
    if not question:
        return Result.fail(400, "请输入问题")
    if len(question) > MAX_QUESTION_LEN:
        return Result.fail(400, f"问题过长，请控制在 {MAX_QUESTION_LEN} 字以内")

    user_id, plate = _resolve_user()

    try:
        data = agentService.chat(
            question,
            session_id=body.get("session_id"),
            user_id=user_id,
            plate=plate,
        )
    except RuntimeError as exc:
        # 上游模型不可用：客服降级，不影响系统其他功能
        return Result.fail(503, f"客服功能暂不可用：{exc}")
    except FileNotFoundError as exc:
        return Result.fail(503, f"知识库目录缺失：{exc}")
    return Result.success("操作成功", data)


@agent_bp.post("/chat/stream")
def chat_stream():
    """客服流式对话入口，返回 text/event-stream。

    事件类型：``progress``（阶段提示）、``delta``（增量文本）、
    ``reset``（用最终文本覆盖气泡）、``done``（完整结果）、``error``（失败）。
    """
    body = json_body()
    question = (body.get("question") or "").strip()
    if not question:
        return Result.fail(400, "请输入问题")
    if len(question) > MAX_QUESTION_LEN:
        return Result.fail(400, f"问题过长，请控制在 {MAX_QUESTION_LEN} 字以内")

    user_id, plate = _resolve_user()
    sid = agentService.normalize_session_id(body.get("session_id"))

    def generate():
        started = time.perf_counter()
        try:
            if agentService.is_faq_fast_path(question):
                # FAQ 快路径：跳过规划模型，直接流式生成知识库答案
                yield _sse("progress", {"stage": "正在检索知识库…"})
                result = None
                for event in kbService.answer_stream(question):
                    if event["type"] == "delta":
                        yield _sse("delta", {"text": event["text"]})
                    elif event["type"] == "reset":
                        yield _sse("reset", {"text": event["text"]})
                    else:
                        result = event["data"]
                data = {
                    **(result or {"answer": kbService.REFUSE_SENTENCE, "sources": [],
                                  "refused": True, "confidence_pending": False}),
                    "session_id": sid,
                    "steps": [],
                    "ticket_id": None,
                    "transfer": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                }
                agentService.save_exchange(sid, question, data["answer"])
                yield _sse("done", data)
            else:
                # 复杂问题仍走完整 Agent；先给阶段提示，避免长时间无反馈
                yield _sse("progress", {"stage": "正在理解问题…"})
                data = agentService.chat(
                    question, session_id=sid, user_id=user_id, plate=plate
                )
                yield _sse("progress", {"stage": "正在生成回答…"})
                answer = data["answer"]
                for index in range(0, len(answer), 16):
                    yield _sse("delta", {"text": answer[index:index + 16]})
                    time.sleep(0.01)
                yield _sse("done", data)
        except Exception as exc:  # noqa: BLE001 - 流式响应已开始，只能通过事件报错
            logger.exception("流式客服失败")
            yield _sse("error", {"msg": f"客服功能暂不可用：{exc}"})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
