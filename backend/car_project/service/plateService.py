# coding: utf-8
"""车牌识别业务层（识别 / 入场登记分离）。

设计约定
--------
1. ``recognize_only``：只识别、不写库，返回车牌号 + 置信度 + 画框效果图（base64）。
   识别结果仅供人工比对，**不作为放行依据**。
2. ``confirm_entry``：接收用户最终确认的车牌号写库入场。车牌来源不限（OCR、手改、重输）。

相对改动前的修复
----------------
1. 车牌校验统一走 ``utils.plate``，不再本地维护第三套正则。
2. Session 改为 per-request，避免模块级 Session 在并发下串数据。
3. 入场同时写入 ``parking_record``（status=in），让"记录"表真正表达一次停车，
   原先只写订单、记录表仅在场外才补，导致记录与订单对不上。
4. 增加重复入场保护：同一车牌已有未出场订单时拒绝再次登记。
   改动前连点两次"确认入场"会生成两条订单。
"""
from __future__ import annotations

import base64
import datetime as dt
import logging

import cv2

from common.Result import Result
from config.database import SessionLocal
from models.models import ParkingOrder, ParkingRecord
from service import plate_recognizer
from utils.plate import is_valid_plate, normalize_plate

logger = logging.getLogger(__name__)


def recognize_only(image_bytes: bytes) -> dict:
    """仅识别车牌，不写库。入参已由接口层校验（非空、扩展名合法）。

    Args:
        image_bytes: 上传图片的二进制内容。

    Returns:
        ``Result`` 结构字典，``data`` 含 ``plate`` / ``ocr_score`` /
        ``yolo_conf`` / ``result_image`` / ``plate_valid``。
    """
    img = plate_recognizer.decode_image(image_bytes)
    if img is None:
        return Result.fail(400, "图片解码失败，请上传有效的图片文件")

    try:
        plates = plate_recognizer.recognize_array(img)
    except FileNotFoundError as exc:
        logger.error("识别模型加载失败: %s", exc)
        return Result.fail(500, f"识别模型加载失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("车牌识别异常")
        return Result.fail(500, f"车牌识别异常：{exc}")

    if not plates:
        return Result.fail(404, "未检测到车牌，请重新上传清晰的车辆图片")

    valid = [item for item in plates if item["text"]]
    if not valid:
        return Result.fail(404, "检测到车牌区域但文字识别失败，请更换更清晰的图片")

    best = max(valid, key=lambda item: item["ocr_score"])
    plate_text = normalize_plate(best["text"])

    # 画框效果图仅用于前端即时预览，不落盘
    vis_image = plate_recognizer.draw_plates(img, plates)
    encoded_ok, buffer = cv2.imencode(".jpg", vis_image)
    result_image = (
        f"data:image/jpeg;base64,{base64.b64encode(buffer.tobytes()).decode('ascii')}"
        if encoded_ok
        else ""
    )

    return Result.success(
        "识别完成，请人工核对",
        {
            "plate": plate_text,
            "ocr_score": round(best["ocr_score"], 4),
            "yolo_conf": round(best["yolo_conf"], 4),
            "result_image": result_image,
            # 提示前端：格式是否合法，辅助用户判断是否需要手工修正
            "plate_valid": is_valid_plate(plate_text),
        },
    )


def confirm_entry(plate: str, user_id: int | None = None) -> dict:
    """确认车牌后完成入场登记。入参车牌已由接口层校验。

    Args:
        plate: 用户最终确认的车牌号（已规范化）。
        user_id: 当前登录用户 ID。

    Returns:
        ``Result`` 结构字典，``data`` 含 ``record_id`` / ``order_id`` /
        ``plate`` / ``in_time``。
    """
    in_time = dt.datetime.now()
    with SessionLocal() as session:
        # 重复入场保护：同一车牌已有未出场订单，说明车还在场内
        open_order = (
            session.query(ParkingOrder)
            .filter(
                ParkingOrder.plate == plate,
                ParkingOrder.out_time.is_(None),
            )
            .order_by(ParkingOrder.in_time.desc())
            .first()
        )
        if open_order is not None:
            return Result.fail(
                400,
                f"该车牌已于 {open_order.in_time:%Y-%m-%d %H:%M:%S} 登记入场，请勿重复登记",
            )

        order = ParkingOrder(
            user_id=user_id,
            plate=plate,
            in_time=in_time,
            out_time=None,
            total_fee=0,
            pay_status="unpaid",
        )
        session.add(order)
        session.flush()

        record = ParkingRecord(
            plate=plate,
            in_time=in_time,
            order_id=order.order_id,
            status="in",
        )
        session.add(record)
        session.commit()

        return Result.success(
            "入场登记成功",
            {
                "record_id": record.record_id,
                "order_id": order.order_id,
                "plate": plate,
                "in_time": in_time.isoformat(),
            },
        )
