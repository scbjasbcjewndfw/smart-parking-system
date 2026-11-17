# coding: utf-8
"""车主客服 Agent：ReAct 循环 + Function Calling + 工单 + 多轮记忆。

实现要点
--------
1. **工具统一注册**：每个工具自带 OpenAI/MCP 风格的 JSON Schema，模型按需调用；
   后续把这些 schema 直接交给 MCP server 即可，业务代码不用改。
2. **ReAct 循环**：生成 → tool_calls → 执行 → 回填工具结果，最多 4 步；
   超出步数或模型没给出结论时，用已有工具结果兜底，不允许空转。
3. **接地校验**：知识型回答必须来自 search_kb 且保留 KB 条目编号；模型改写时
   丢了引用，就直接回填工具返回的受约束答案，避免二次幻觉。
4. **数据安全**：订单查询必须登录，且只能查本人绑定车牌；越权请求返回结构化
   错误，不把其他用户数据交给模型。
5. **记忆**：agent_message 表按 session_id 保存最近 8 条消息，支持多轮指代。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
import uuid
from typing import Any, Callable, Optional

from config.database import SessionLocal
from models.models import AgentMessage, ParkingOrder, ServiceTicket
from service import kbService
from utils.plate import normalize_plate

logger = logging.getLogger(__name__)

#: ReAct 最大步数：客服场景 1~2 步足够，留余量但防止模型无限调用
MAX_STEPS = 4

#: 注入的历史消息条数（user/assistant 各算一条）
MAX_HISTORY = 8

#: 单条记忆最大长度，防止一条超长消息挤爆上下文
MEMORY_MAX = 1000

#: 快路径排除词：出现这些词说明需要查订单/建工单/转人工，必须走 Agent
FAST_PATH_ACTIONS = (
    "订单",
    "记录",
    "工单",
    "转人工",
    "人工客服",
    "投诉",
    "申诉",
    "我的车",
    "绑定",
    "登录",
    "注册",
    "注销",
    "密码",
    "欠费",
    "缴费",
)

#: 会话 ID 白名单：前端 uuid，非法值由后端重新生成
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

#: 工单分类与知识库 domain 对齐，另加 other/human
TICKET_CATEGORIES = {"fee", "payment", "recognize", "account", "lot", "dispute", "other", "human"}

SYSTEM_PROMPT = """你是停车场系统的车主客服 Agent，按“先计划、再调用工具、最后依据工具结果回答”的方式工作。

可用工具：
- search_kb：查询停车规则/费用/支付/发票/隐私等知识库问题
- query_parking_orders：查询当前登录用户本人的停车订单
- create_service_ticket：创建客服工单
- transfer_to_human：转人工客服（同时建工单）

规则：
1. 规则、费用、支付、发票、识别、账号、车场、隐私类问题必须先调用 search_kb；不得凭记忆回答，
   不要先反问“您想了解哪方面”，即使问题较宽泛也先检索再组织回答。
2. search_kb 返回的 answer 是已经过引用校验的结论：必须原样保留其中的事实与“依据：KB-xxx”，
   不得改写金额、时长、比例，不得删除编号，也不得补充工具结果之外的信息。
3. search_kb 返回 refused=true 时，如实转述拒答句并按需调用 transfer_to_human，不得自行编答案。
4. 查询订单前必须确认身份；只能查当前登录用户绑定的车牌，用户没给车牌就用其绑定车牌，禁止猜测。
   只有确实缺少必要信息（如未登录且无车牌）时才向车主追问。
5. 需要人工处理、投诉、或用户明确要求转人工时，调用 transfer_to_human。
6. 工单号只能来自 create_service_ticket / transfer_to_human 的返回，不得编造。
7. 最终回答面向车主，控制在 3 句话内，不要输出 JSON、工具名或内部推理过程。
"""


# ---------------------------------------------------------------- 工具注册


_TOOLS: dict[str, dict[str, Any]] = {}


def _register(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """注册一个工具：schema 用于模型调用，fn 用于本地执行。

    Args:
        name: 工具名，模型通过它发起调用。
        description: 工具用途说明。
        parameters: JSON Schema 形式的入参定义。

    Returns:
        装饰器。
    """

    def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        _TOOLS[name] = {
            "schema": {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
            "fn": fn,
        }
        return fn

    return decorator


def tool_schemas() -> list[dict[str, Any]]:
    """返回全部工具 schema，供模型与外部（MCP/低代码平台）复用。"""
    return [item["schema"] for item in _TOOLS.values()]


@_register(
    "search_kb",
    "检索车主客服知识库并返回受约束答案。适用于费用、支付、发票、识别、账号、车场、隐私等问题。",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要查询的车主问题，尽量保留车牌、金额等关键信息"},
        },
        "required": ["question"],
    },
)
def _tool_search_kb(ctx: dict[str, Any], question: str) -> dict[str, Any]:
    """调用知识库受约束问答（内部已完成引用校验与拒答判定）。"""
    q = str(question or "").strip()
    if not q:
        return {"error": "INVALID_ARGUMENT", "message": "question 不能为空"}
    out = kbService.answer(q)
    return {
        "answer": out["answer"],
        "sources": out["sources"],
        "kb_ids": [s["kb_id"] for s in out["sources"]],
        "refused": out["refused"],
        "confidence_pending": out["confidence_pending"],
        "domain": out["domain"],
    }


@_register(
    "query_parking_orders",
    "查询当前登录用户名下、指定车牌最近若干条停车订单。未登录或查询他人车牌会被拒绝。",
    {
        "type": "object",
        "properties": {
            "plate": {"type": "string", "description": "车牌号，可省略；省略时使用当前账号绑定车牌"},
            "limit": {"type": "integer", "description": "返回条数，1-5，默认 3"},
        },
        "required": [],
    },
)
def _tool_query_orders(
    ctx: dict[str, Any], plate: Optional[str] = None, limit: int = 3
) -> dict[str, Any]:
    """按登录身份查询订单；只允许本人绑定车牌，避免越权查询。"""
    user_id = ctx.get("user_id")
    if not user_id:
        return {"error": "UNAUTHENTICATED", "message": "查询停车订单需要先登录，请登录后再试"}

    target = normalize_plate(plate) if plate else ""
    bound = ctx.get("plate") or ""
    if target and target != bound:
        return {
            "error": "FORBIDDEN",
            "message": f"只能查询本人绑定车牌（{bound or '未绑定'}），无法查询其他车牌",
        }
    target = target or bound
    if not target:
        return {"error": "PLATE_REQUIRED", "message": "请提供要查询的车牌号，或先在账号中绑定车牌"}

    try:
        count = max(1, min(int(limit or 3), 5))
    except (TypeError, ValueError):
        count = 3

    with SessionLocal() as session:
        rows = (
            session.query(ParkingOrder)
            .filter(ParkingOrder.user_id == user_id, ParkingOrder.plate == target)
            .order_by(ParkingOrder.order_id.desc())
            .limit(count)
            .all()
        )
    orders = [
        {
            "order_id": r.order_id,
            "plate": r.plate,
            "in_time": r.in_time.strftime("%Y-%m-%d %H:%M") if r.in_time else None,
            "out_time": r.out_time.strftime("%Y-%m-%d %H:%M") if r.out_time else None,
            "total_fee": r.total_fee,
            "pay_status": r.pay_status,
        }
        for r in rows
    ]
    return {"plate": target, "count": len(orders), "orders": orders}


def _create_ticket(
    ctx: dict[str, Any], summary: str, category: str, plate: Optional[str]
) -> int:
    """落库一张工单并返回工单号。"""
    kind = category if category in TICKET_CATEGORIES else "other"
    ticket = ServiceTicket(
        user_id=ctx.get("user_id"),
        session_id=ctx["session_id"],
        plate=normalize_plate(plate) if plate else ctx.get("plate"),
        category=kind,
        summary=(summary or "客服咨询")[:500],
        status="open",
        source="agent",
        create_time=dt.datetime.now().replace(microsecond=0),
    )
    with SessionLocal() as session:
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        return ticket.ticket_id


@_register(
    "create_service_ticket",
    "为车主创建客服工单，返回工单号。适用于需要人工跟进、投诉、补偿等场景。",
    {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "工单内容：车主诉求与关键事实"},
            "category": {
                "type": "string",
                "description": "分类：fee/payment/recognize/account/lot/dispute/other",
                "enum": ["fee", "payment", "recognize", "account", "lot", "dispute", "other"],
            },
            "plate": {"type": "string", "description": "相关车牌号，可省略"},
        },
        "required": ["summary"],
    },
)
def _tool_create_ticket(
    ctx: dict[str, Any], summary: str, category: str = "other", plate: Optional[str] = None
) -> dict[str, Any]:
    """创建普通工单。"""
    ticket_id = _create_ticket(ctx, summary, category, plate)
    return {"ticket_id": ticket_id, "status": "open", "message": "工单已创建，人工客服会尽快跟进"}


@_register(
    "transfer_to_human",
    "转人工客服：创建转人工工单并返回工单号。知识库无法回答、投诉或用户明确要求人工时使用。",
    {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "转人工原因，便于客服快速了解上下文"},
            "plate": {"type": "string", "description": "相关车牌号，可省略"},
        },
        "required": ["reason"],
    },
)
def _tool_transfer(ctx: dict[str, Any], reason: str, plate: Optional[str] = None) -> dict[str, Any]:
    """转人工：复用工单表，分类记为 human。"""
    ticket_id = _create_ticket(ctx, f"转人工：{reason}", "human", plate)
    return {
        "ticket_id": ticket_id,
        "transferred": True,
        "status": "open",
        "message": "已转人工客服，会尽快联系车主",
    }


def _run_tool(name: str, args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """执行工具：过滤非法入参，捕获异常并以结构化错误返回给模型。

    Args:
        name: 工具名。
        args: 模型给出的入参。
        ctx: 执行上下文（user_id/plate/session_id）。

    Returns:
        工具结果字典；失败时含 ``error`` 字段。
    """
    entry = _TOOLS.get(name)
    if entry is None:
        return {"error": "UNKNOWN_TOOL", "message": f"未知工具：{name}"}

    allowed = (entry["schema"]["function"]["parameters"].get("properties") or {}).keys()
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    try:
        return entry["fn"](ctx, **clean)
    except Exception as exc:  # noqa: BLE001 - 工具失败不能拖垮整个 Agent
        logger.exception("工具 %s 执行失败", name)
        return {"error": "TOOL_FAILED", "message": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- 会话记忆


def normalize_session_id(value: Optional[str]) -> str:
    """校验前端会话 ID，非法或缺失时生成新 ID。"""
    raw = (value or "").strip()
    return raw if SESSION_RE.match(raw) else uuid.uuid4().hex


def _save_message(session_id: str, role: str, content: str) -> None:
    """写入一条会话记忆；写失败只记日志，不影响本次回答。"""
    try:
        with SessionLocal() as session:
            session.add(
                AgentMessage(
                    session_id=session_id,
                    role=role,
                    content=(content or "")[:MEMORY_MAX],
                    create_time=dt.datetime.now().replace(microsecond=0),
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 - 记忆是增强能力，失败不应中断问答
        logger.exception("写入会话记忆失败：session=%s", session_id)


def save_exchange(session_id: str, question: str, answer: str) -> None:
    """保存一轮问答到会话记忆。"""
    _save_message(session_id, "user", question)
    _save_message(session_id, "assistant", answer)


def is_faq_fast_path(question: str) -> bool:
    """判断问题是否可直接走知识库快路径，跳过 Agent 规划。

    只在「明确命中知识域且不涉及订单/工单/转人工等动作」时启用；
    拿不准就回退 Agent，避免把业务操作题答成政策题。

    Args:
        question: 车主问句。

    Returns:
        True 表示可直接调用知识库流式问答。
    """
    if any(word in question for word in FAST_PATH_ACTIONS):
        return False
    domain, _ = kbService.route_domain(question)
    return domain is not None


# ---------------------------------------------------------------- Agent 主流程


def chat(
    question: str,
    *,
    session_id: Optional[str] = None,
    user_id: Optional[int] = None,
    plate: Optional[str] = None,
) -> dict[str, Any]:
    """客服 Agent 主入口：ReAct 循环 + 工具执行 + 接地校验 + 记忆落库。

    Args:
        question: 车主问题。
        session_id: 会话 ID；非法时自动生成。
        user_id: 登录用户 ID，匿名时为 None。
        plate: 登录用户绑定车牌，用于订单权限校验。

    Returns:
        {answer, session_id, refused, confidence_pending, sources, steps,
         ticket_id, transfer, latency_ms}
    """
    sid = normalize_session_id(session_id)
    ctx = {"session_id": sid, "user_id": user_id, "plate": plate}
    status = f"已登录，绑定车牌 {plate}" if user_id else "未登录（不能查询停车订单）"
    with SessionLocal() as session:
        rows = (
            session.query(AgentMessage)
            .filter(AgentMessage.session_id == sid)
            .order_by(AgentMessage.id.desc())
            .limit(MAX_HISTORY)
            .all()
        )
    history = [{"role": r.role, "content": r.content} for r in reversed(rows)]
    messages: list[dict[str, Any]] = (
        [{"role": "system", "content": f"{SYSTEM_PROMPT}\n当前会话状态：{status}。"}]
        + history
        + [{"role": "user", "content": question}]
    )

    started = time.perf_counter()
    steps: list[dict[str, Any]] = []
    kb_results: list[dict[str, Any]] = []
    ticket_ids: list[int] = []
    transferred = False
    final = ""

    for step_no in range(1, MAX_STEPS + 1):
        assistant = kbService.chat_with_tools(messages, tool_schemas())
        calls = assistant.get("tool_calls") or []
        if not calls:
            final = (assistant.get("content") or "").strip()
            break

        messages.append(
            {
                "role": "assistant",
                "content": assistant.get("content") or "",
                "tool_calls": calls,
            }
        )
        kb_answer_this_step = False
        needs_synthesis = False
        for index, call in enumerate(calls):
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            raw = fn.get("arguments") or "{}"
            if isinstance(raw, str):
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    args = {}
            elif isinstance(raw, dict):
                args = raw
            else:
                args = {}
            call_id = call.get("id") or f"call_{index}"
            t0 = time.perf_counter()
            result = _run_tool(name, args, ctx)
            steps.append(
                {
                    "step": step_no,
                    "tool": name,
                    "args": args,
                    "ok": not result.get("error"),
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
            if name == "search_kb" and result.get("answer"):
                kb_results.append(result)
                if not result.get("refused"):
                    kb_answer_this_step = True
            elif name != "search_kb":
                # 订单/工单/转人工需要模型把工具结果组织进最终答复
                needs_synthesis = True
            if result.get("ticket_id"):
                ticket_ids.append(int(result["ticket_id"]))
            if result.get("transferred"):
                transferred = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        if kb_answer_this_step and not needs_synthesis:
            # 知识库工具已经返回受约束、可核对的答案，直接采用，
            # 不再让模型二次改写：省掉一轮 LLM 调用，也避免改写丢引用。
            final = kb_results[-1]["answer"]
            break

    # 只采用非拒答的知识库结果；全部拒答时按拒答处理
    kb_ok = next((r for r in reversed(kb_results) if not r.get("refused")), None)

    refused = False
    if kb_ok is None:
        if kb_results:
            # 知识库明确拒答，模型不得自行发挥
            final = kbService.REFUSE_SENTENCE
            refused = True
        elif not final:
            if ticket_ids:
                final = f"你的工单已创建，工单号 {ticket_ids[-1]}，人工客服会尽快跟进。"
            else:
                final = kbService.REFUSE_SENTENCE
                refused = True
    elif not final:
        final = kb_ok["answer"]
    elif kb_ok["kb_ids"] and not any(kb_id in final for kb_id in kb_ok["kb_ids"]):
        # 模型改写丢掉了引用：直接回填受约束答案，保证可核对
        final = kb_ok["answer"]

    if kb_ok is not None and not refused and final.strip().startswith("这个问题我暂时"):
        refused = True

    if ticket_ids:
        ticket_id = ticket_ids[-1]
        if str(ticket_id) not in final:
            final += f"\n（工单号：{ticket_id}，人工客服会尽快跟进）"
    else:
        ticket_id = None

    confidence_pending = bool(kb_ok and kb_ok.get("confidence_pending") and not refused)
    sources = [] if refused else (kb_ok.get("sources") or []) if kb_ok else []

    save_exchange(sid, question, final)

    return {
        "answer": final,
        "session_id": sid,
        "refused": refused,
        "confidence_pending": confidence_pending,
        "sources": sources,
        "steps": steps,
        "ticket_id": ticket_id,
        "transfer": transferred,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
