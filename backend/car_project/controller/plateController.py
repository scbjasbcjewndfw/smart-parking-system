# coding: utf-8
"""
车牌识别接口层
Method:`POST`   /api/plate/recognize        Body →`form-data` → 添加一个 key 叫`image` ,类型选 File,选一张车辆图片
Method:`POST`   /api/plate/entry       Body →`raw` → 选 JSON,内容:`{"plate": "皖AD03683"}`  需登录
"""
from pathlib import Path

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from common.Result import Result
from common.request import json_body
from service.plateService import confirm_entry, recognize_only
from utils.plate import is_valid_plate, normalize_plate

plate_bp = Blueprint("plate", __name__, url_prefix="/api/plate")

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp"}


@plate_bp.post("/recognize")
def recognize():
    """前端以 multipart/form-data 上传,图片字段名:image"""
    file = request.files.get("image")
    if file is None:
        return Result.fail(400, "未收到图片,请使用 form-data 字段 image 上传")

    image_bytes = file.read()
    if not image_bytes:
        return Result.fail(400, "图片内容为空")

    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    if ext not in ALLOWED_EXT:
        return Result.fail(400, f"不支持的图片格式：{ext}，仅支持 jpg / jpeg / png / bmp")

    return recognize_only(image_bytes)


@plate_bp.post("/entry")
@jwt_required()
def entry():
    """JSON body:{"plate": "皖AD03683"}  需登录,user_id 从 JWT 提取"""
    user_id = int(get_jwt_identity())
    body = json_body()
    plate = normalize_plate(body.get("plate"))
    if not plate:
        return Result.fail(400, "车牌号不能为空")
    if not is_valid_plate(plate):
        return Result.fail(400, "车牌号格式不正确，应为 省份简称+字母+5~6 位（如 皖AD03683）")
    return confirm_entry(plate, user_id)
