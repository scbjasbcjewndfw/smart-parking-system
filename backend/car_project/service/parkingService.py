# coding: utf-8
"""停车业务层：入场、出场计费、订单查询、支付。

相对改动前的三处关键修复
------------------------
1. **Session 隔离**：全部改为 ``with SessionLocal() as session``，每次请求独立事务。
   改动前使用模块级 ``session`` 并在 ``finally`` 里 ``close()``，而 Flask 默认多线程，
   并发请求会共享同一个 Session，导致事务互相污染、偶发 ``ResourceClosedError``。
2. **出场闭环**：出场计费优先复用该车牌最近一条未出场订单，而不是新建。
   改动前 ``confirm_entry`` 写一条（out_time 为空）、``calculate_fee`` 又写一条，
   同一辆车一次停车产生两条订单，入场那条永远滞留且无法支付。
   已出场未支付的订单在重复提交计费时同样会被复用，不会重复生成。
3. **支付校验下沉**：未出场订单不允许支付。前端隐藏按钮只是交互，不构成校验。

计费口径
--------
5 元/小时，按分钟折算：``满小时 * 5 + 余分钟 * (5/60)``，四舍五入保留 2 位小数。
单价由服务端强制，忽略调用方传入值。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Final

from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from common.Result import Result
from config.database import SessionLocal
from models.models import ParkingOrder, ParkingRecord, SysUser

#: 每小时单价（元）。业务调整时改这里，并同步 docs/kb/customer/01-fee.md 的示例。
RATE_PER_HOUR: Final[float] = 5.0

#: 单次停留时长上限，防止用户填入离谱时间算出天价或溢出
MAX_STAY: Final[dt.timedelta] = dt.timedelta(days=90)

#: 出场时间允许超前于当前时间的容差（客户端时钟误差）
CLOCK_TOLERANCE: Final[dt.timedelta] = dt.timedelta(minutes=5)

#: 订单列表默认返回条数，避免全表返回拖垮接口
DEFAULT_LIMIT: Final[int] = 200

_TIME_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)


def _parse_time(value: Any) -> dt.datetime | None:
    """解析前端传入的时间，兼容多种常见格式。

    Args:
        value: 字符串或 datetime 对象。

    Returns:
        解析成功返回 ``datetime``，失败返回 ``None``。
    """
    if isinstance(value, dt.datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _TIME_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        # 兜底：处理带时区偏移或微秒的 ISO 格式
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def calc_amount(
    in_time: dt.datetime,
    out_time: dt.datetime,
    rate: float = RATE_PER_HOUR,
) -> dict[str, float | int]:
    """纯函数计算停车费用，便于单元测试与口径复用。

    时长按分钟向上取整（不足 1 分钟按 1 分钟），金额在最后一步四舍五入，
    避免"每分钟各自取整后累加"造成的累计误差。

    Args:
        in_time: 入场时间。
        out_time: 出场时间，必须晚于 ``in_time``。
        rate: 每小时单价。

    Returns:
        含 ``duration_minutes`` / ``full_hours`` / ``remain_minutes`` /
        ``per_minute_fee`` / ``total_fee`` 的字典。

    Raises:
        ValueError: 出场时间不晚于入场时间。
    """
    if out_time <= in_time:
        raise ValueError("out_time must be later than in_time")

    total_minutes = max(1, math.ceil((out_time - in_time).total_seconds() / 60))
    full_hours, remain_minutes = divmod(total_minutes, 60)
    per_minute_fee = rate / 60.0
    total_fee = round(full_hours * rate + remain_minutes * per_minute_fee, 2)

    return {
        "duration_minutes": total_minutes,
        "full_hours": full_hours,
        "remain_minutes": remain_minutes,
        "per_minute_fee": round(per_minute_fee, 4),
        "total_fee": total_fee,
    }


def _find_open_order(session: Session, plate: str, user_id: int | None) -> ParkingOrder | None:
    """查找该车牌最近一条未出场订单。

    只认本人订单或未关联用户的订单，避免替其他账号的车辆结算。

    Args:
        session: 当前请求的数据库会话。
        plate: 已规范化的车牌号。
        user_id: 当前登录用户 ID，可为 None（匿名）。

    Returns:
        命中返回订单对象，否则返回 None。
    """
    query = session.query(ParkingOrder).filter(
        ParkingOrder.plate == plate,
        ParkingOrder.out_time.is_(None),
    )
    if user_id is not None:
        query = query.filter(
            or_(ParkingOrder.user_id == user_id, ParkingOrder.user_id.is_(None))
        )
    return query.order_by(ParkingOrder.in_time.desc()).first()


def _find_reusable_order(
    session: Session,
    plate: str,
    user_id: int | None,
    in_time: dt.datetime,
) -> ParkingOrder | None:
    """查找可复用的**已出场未支付**订单，用于抵消重复计费。

    场景：车主先算了一次费用（订单已写入 out_time），发现时间填错又提交一次。
    若只看"未出场订单"，第二次会新建一条重复订单，车主会在列表里看到两条同段停留，
    支付的却可能只是其中一条。这里按入场时间是否接近（容差 5 分钟）认定"同一段停留"，
    复用原订单而不是再插一条。

    已支付的订单不参与复用：不能让车主通过重新计费把已付款订单的金额改小。

    Args:
        session: 当前请求的数据库会话。
        plate: 已规范化的车牌号。
        user_id: 当前登录用户 ID。
        in_time: 本次请求的入场时间。

    Returns:
        命中返回订单对象，否则返回 None。
    """
    query = session.query(ParkingOrder).filter(
        ParkingOrder.plate == plate,
        ParkingOrder.out_time.isnot(None),
        or_(ParkingOrder.pay_status == "unpaid", ParkingOrder.pay_status.is_(None)),
    )
    if user_id is not None:
        query = query.filter(
            or_(ParkingOrder.user_id == user_id, ParkingOrder.user_id.is_(None))
        )
    candidates = query.order_by(ParkingOrder.in_time.desc()).limit(5).all()
    for candidate in candidates:
        if candidate.in_time is None:
            continue
        if abs((candidate.in_time - in_time).total_seconds()) <= 300:
            return candidate
    return None


def _mark_record_out(session: Session, order_id: int, plate: str, in_time: dt.datetime) -> None:
    """把入场记录状态更新为已出场，没有入场记录时补写一条。

    Args:
        session: 当前请求的数据库会话。
        order_id: 订单 ID。
        plate: 车牌号。
        in_time: 入场时间（补写记录时使用）。
    """
    record = (
        session.query(ParkingRecord)
        .filter(ParkingRecord.order_id == order_id)
        .order_by(ParkingRecord.record_id.desc())
        .first()
    )
    if record is None:
        session.add(
            ParkingRecord(plate=plate, in_time=in_time, order_id=order_id, status="out")
        )
    else:
        record.status = "out"


def calculate_fee(
    plate: str,
    in_time_str: Any,
    out_time_str: Any,
    user_id: int | None = None,
) -> dict:
    """出场计费：结算停留时长、生成或更新订单并落库。

    订单选取顺序：

    1. 该车牌最近一条**未出场**订单（入场登记的延续）；
    2. 该车牌**已出场且未支付**、入场时间接近的订单（重复提交计费时复用）。

    只要命中订单且订单有入场时间，一律以**系统记录**为准，客户端传入的 in_time
    仅在没有系统记录时才被采信——否则车主可通过填写更早的入场时间自行压低费用。
    已支付订单不参与复用，避免重算把已付款金额改小。

    Args:
        plate: 已由接口层校验并规范化的车牌号。
        in_time_str: 入场时间字符串或 datetime。
        out_time_str: 出场时间字符串或 datetime。
        user_id: 当前登录用户 ID。

    Returns:
        ``Result`` 结构字典，``data`` 含订单与计费明细。

    Raises:
        数据库异常向上冒泡，由应用层统一转为 500。
    """
    in_time = _parse_time(in_time_str)
    out_time = _parse_time(out_time_str)
    if in_time is None or out_time is None:
        return Result.fail(400, "时间格式不正确，请使用 YYYY-MM-DD HH:mm")
    if out_time <= in_time:
        return Result.fail(400, "出场时间必须晚于入场时间")
    if out_time > dt.datetime.now() + CLOCK_TOLERANCE:
        return Result.fail(400, "出场时间不能晚于当前时间")
    if out_time - in_time > MAX_STAY:
        return Result.fail(400, "单次停留时长超过 90 天，请核对入场与出场时间")

    with SessionLocal() as session:
        order = _find_open_order(session, plate, user_id)
        if order is None:
            # 已出场但未支付、且入场时间接近的订单视为同一段停留，避免重复计费
            order = _find_reusable_order(session, plate, user_id, in_time)

        in_time_source = "request"
        if order is not None and order.in_time is not None:
            # 有系统记录时一律以记录为准：客户端时间可被随意填写，
            # 允许其覆盖等于允许车主自行决定计费时长。
            in_time = order.in_time
            in_time_source = "order"
            if out_time <= in_time:
                return Result.fail(
                    400,
                    "出场时间必须晚于入场时间，"
                    f"系统记录该车入场时间为 {in_time:%Y-%m-%d %H:%M}",
                )

        amount = calc_amount(in_time, out_time, RATE_PER_HOUR)
        updated_existing = order is not None

        if order is None:
            order = ParkingOrder(
                user_id=user_id,
                plate=plate,
                in_time=in_time,
                out_time=out_time,
                total_fee=amount["total_fee"],
                pay_status="unpaid",
            )
            session.add(order)
            session.flush()
        else:
            order.in_time = in_time
            order.out_time = out_time
            order.total_fee = amount["total_fee"]
            # 未出场订单不可能已支付，这里保持 unpaid 以符合状态机
            order.pay_status = "unpaid"
            session.flush()

        _mark_record_out(session, order.order_id, plate, in_time)
        session.commit()

        return Result.success(
            "计费成功",
            {
                "order_id": order.order_id,
                "plate": plate,
                "in_time": in_time.strftime("%Y-%m-%d %H:%M:%S"),
                "out_time": out_time.strftime("%Y-%m-%d %H:%M:%S"),
                "in_time_source": in_time_source,
                "updated_existing": updated_existing,
                "rate": RATE_PER_HOUR,
                "pay_status": "unpaid",
                **amount,
            },
        )


def list_orders(user_id: int | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """查询订单列表，按订单号倒序。

    Args:
        user_id: 限定某个用户；None 表示不限定（仅内部调用场景）。
        limit: 最大返回条数。

    Returns:
        ``Result`` 结构字典，``data`` 为订单列表。
    """
    with SessionLocal() as session:
        query = session.query(ParkingOrder)
        if user_id is not None:
            query = query.filter(ParkingOrder.user_id == user_id)
        orders = query.order_by(ParkingOrder.order_id.desc()).limit(limit).all()
        data = [_order_to_dict(order) for order in orders]
    return Result.success("查询成功", data)


def query_user_by_plate(
    user_id: int | None = None,
    plate: str | None = None,
    pay_status: str = "all",
) -> dict:
    """按车牌查询**当前登录用户**的订单，并返回该车主信息。

    改动前无论输入什么车牌，都返回当前登录用户的信息，前端却把它展示为
    "该车牌的用户信息"，属于口径错位。现在只有车牌确实绑定在当前账号下时才返回
    车主信息，否则返回 None，前端据此提示"未找到该车牌对应的注册用户"。

    Args:
        user_id: 当前登录用户 ID。
        plate: 已规范化的车牌号，可为空表示不限。
        pay_status: ``all`` / ``unpaid`` / ``paid``，已由接口层校验。

    Returns:
        ``Result`` 结构字典，``data`` 含 ``user`` / ``orders`` / ``total``。
    """
    with SessionLocal() as session:
        user_info = None
        if user_id is not None:
            viewer = session.query(SysUser).filter(SysUser.user_id == user_id).first()
            if viewer is not None and (plate is None or viewer.plate == plate):
                user_info = {
                    "user_id": viewer.user_id,
                    "username": viewer.username,
                    "plate": viewer.plate,
                    "create_time": viewer.create_time.strftime("%Y-%m-%d %H:%M:%S")
                    if viewer.create_time
                    else None,
                }

        query = session.query(ParkingOrder)
        if user_id is not None:
            query = query.filter(ParkingOrder.user_id == user_id)
        if plate:
            query = query.filter(ParkingOrder.plate == plate)
        if pay_status in ("unpaid", "paid"):
            query = query.filter(ParkingOrder.pay_status == pay_status)

        # 未付款优先，再按入场时间倒序
        orders = (
            query.order_by(
                case((ParkingOrder.pay_status == "unpaid", 0), else_=1),
                ParkingOrder.in_time.desc(),
            )
            .limit(DEFAULT_LIMIT)
            .all()
        )
        order_list = [_order_to_dict(order) for order in orders]

    return Result.success(
        "查询成功",
        {"user": user_info, "orders": order_list, "total": len(order_list)},
    )


def pay_order(order_id: int, user_id: int | None = None) -> dict:
    """支付订单：把 ``pay_status`` 置为 paid。

    改动前的实现只校验了归属与是否已付，未校验是否出场，导致未出场（金额尚未结算）
    的订单也能被直接标记为已付款。

    Args:
        order_id: 订单 ID。
        user_id: 当前登录用户 ID，用于归属校验。

    Returns:
        ``Result`` 结构字典。
    """
    with SessionLocal() as session:
        order = (
            session.query(ParkingOrder)
            .filter(ParkingOrder.order_id == order_id)
            .first()
        )
        if order is None:
            return Result.fail(404, "订单不存在")
        if user_id is not None and order.user_id != user_id:
            return Result.fail(403, "无权支付他人订单")
        if order.out_time is None:
            return Result.fail(400, "该订单尚未出场，请先完成出场计费")
        if order.pay_status == "paid":
            return Result.fail(400, "订单已付款，无需重复支付")

        order.pay_status = "paid"
        session.commit()
        return Result.success(
            "付款成功",
            {
                "order_id": order_id,
                "plate": order.plate,
                "pay_status": "paid",
                "total_fee": round(float(order.total_fee), 2)
                if order.total_fee is not None
                else 0.0,
            },
        )


def _order_to_dict(order: ParkingOrder) -> dict[str, Any]:
    """把订单 ORM 对象转换为前端约定的字典。

    Args:
        order: 订单对象。

    Returns:
        含订单号、车牌、进出时间、金额与支付状态的字典。
    """
    return {
        "order_id": order.order_id,
        "plate": order.plate,
        "in_time": order.in_time.strftime("%Y-%m-%d %H:%M:%S") if order.in_time else None,
        "out_time": order.out_time.strftime("%Y-%m-%d %H:%M:%S") if order.out_time else None,
        "total_fee": round(float(order.total_fee), 2) if order.total_fee is not None else 0.0,
        "pay_status": order.pay_status,
    }
