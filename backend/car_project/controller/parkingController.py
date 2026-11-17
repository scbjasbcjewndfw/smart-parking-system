# coding: utf-8
"""停车接口层：出场计费、订单列表、按车牌查询、支付。

接口清单（统一前缀 ``/api/parking``，除标注外均需 JWT）
-----------------------------------------------------
- ``POST /fee``            出场计费，生成或更新订单
- ``GET  /orders``         当前用户订单列表
- ``GET  /query``          按车牌查询当前用户订单（可筛支付状态）
- ``PUT  /pay/<order_id>`` 支付订单，只能支付本人且已出场的订单

相对改动前的修复
----------------
1. ``request.get_json()`` 非 JSON 请求体时返回 None，原实现直接 ``.get()`` 会 500。
2. 入参校验前移：车牌为空、时间缺失在接口层就拦掉，错误信息更明确。
3. 单价不再透传：计费单价由服务端常量决定，接口不接受客户端指定价格。
"""
from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from common.Result import Result
from common.request import json_body
from service import parkingService
from utils.plate import is_valid_plate, normalize_plate

parking_bp = Blueprint("parking", __name__, url_prefix="/api/parking")


@parking_bp.post("fee")
@jwt_required()
def calculate_fee():
    """出场计费。

    请求体::

        {"plate": "皖AD03683", "in_time": "2026-11-02 08:30", "out_time": "2026-11-02 12:45"}

    单价固定为服务端常量，客户端传入的 rate 会被忽略。
    """
    body = json_body()
    plate = normalize_plate(body.get("plate"))
    in_time = body.get("in_time")
    out_time = body.get("out_time")

    if not plate:
        return Result.fail(400, "车牌号不能为空")
    if not is_valid_plate(plate):
        return Result.fail(400, "车牌号格式不正确，应为 省份简称+字母+5~6 位（如 皖AD03683）")
    if not in_time or not out_time:
        return Result.fail(400, "入场时间和出场时间不能为空")

    return parkingService.calculate_fee(
        plate, in_time, out_time, user_id=int(get_jwt_identity())
    )


@parking_bp.get("orders")
@jwt_required()
def list_orders():
    """查询当前登录用户的订单列表。"""
    return parkingService.list_orders(int(get_jwt_identity()))


@parking_bp.get("query")
@jwt_required()
def query_by_plate():
    """按车牌查询当前登录用户的订单。

    Query 参数：
        plate: 车牌号，可选，不传则查全部
        pay_status: all / unpaid / paid，默认 all
    """
    pay_status = request.args.get("pay_status", "all")
    if pay_status not in ("all", "unpaid", "paid"):
        return Result.fail(400, "状态参数不合法，仅支持 all / unpaid / paid")

    plate = request.args.get("plate")
    plate = normalize_plate(plate) if plate else None
    if plate and not is_valid_plate(plate):
        return Result.fail(400, "车牌号格式不正确")

    return parkingService.query_user_by_plate(
        user_id=int(get_jwt_identity()),
        plate=plate,
        pay_status=pay_status,
    )


@parking_bp.put("pay/<int:order_id>")
@jwt_required()
def pay_order(order_id: int):
    """支付指定订单，只能支付本人订单。"""
    return parkingService.pay_order(order_id, user_id=int(get_jwt_identity()))
