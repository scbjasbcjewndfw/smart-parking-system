# coding: utf-8
"""用户接口层：注册 / 登录 / 个人信息 / 注销。

相对改动前的修复
----------------
1. 车牌校验统一走 ``utils.plate``，删除本文件内的第三套正则。
2. ``request.get_json()`` 在请求体非 JSON 时返回 None，原实现直接 ``.get()`` 会抛
   ``AttributeError`` 变成 500；统一改为 ``silent=True`` 并显式校验。
3. ``/user/profile`` 改为回源数据库读取，注销或改名后不再返回 JWT 里的旧 claims。
4. 登录失败不再返回用户信息（原实现把 user 对象塞进了失败响应）。
"""
from __future__ import annotations

from flask import Blueprint
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required

from common.Result import Result
from common.request import json_body
from service import userService
from utils.plate import is_valid_plate, normalize_plate

user_bp = Blueprint("user", __name__, url_prefix="/api/user")

#: 用户名长度上限：入口一次校验，业务层不再重复
MAX_USERNAME_LEN = 50


@user_bp.post("register")
def register():
    """用户注册。请求体：``{"username": str, "password": str, "plate"?: str}``"""
    body = json_body()
    username = body.get("username")
    username = username.strip() if isinstance(username, str) else ""
    password = body.get("password")
    password = password if isinstance(password, str) else ""
    plate = body.get("plate")

    if not username or not password:
        return Result.fail(400, "用户名或密码不能为空")
    if len(username) > MAX_USERNAME_LEN:
        return Result.fail(400, f"用户名长度不能超过 {MAX_USERNAME_LEN} 个字符")
    if len(password) < 6:
        return Result.fail(400, "密码长度至少 6 位")

    normalized_plate = None
    if plate and str(plate).strip():
        normalized_plate = normalize_plate(plate)
        # 注册允许不填车牌，但填了就必须合法，避免脏数据进入 sys_user.plate
        if not is_valid_plate(normalized_plate):
            return Result.fail(
                400, "车牌号格式错误，请输入 7~8 位合法车牌（如 皖AD03683）"
            )

    return userService.register(username, password, normalized_plate)


@user_bp.post("login")
def login():
    """用户登录，返回 JWT 访问令牌。"""
    body = json_body()
    username = body.get("username")
    username = username.strip() if isinstance(username, str) else ""
    password = body.get("password")
    password = password if isinstance(password, str) else ""
    if not username or not password:
        return Result.fail(400, "用户名或密码不能为空")

    login_result = userService.login(username, password)
    if login_result["code"] != 200:
        return login_result

    user = login_result["data"]
    user_id = str(user["user_id"])
    token = create_access_token(
        identity=user_id,
        additional_claims={"username": user["username"], "plate": user["plate"]},
    )
    return Result.success(
        "登录成功",
        {
            "access_token": token,
            "username": user["username"],
            "user_id": user_id,
            "plate": user["plate"],
        },
    )


@user_bp.get("profile")
@jwt_required()
def profile():
    """获取当前登录用户信息（回源数据库）。"""
    return userService.get_profile(int(get_jwt_identity()))


@user_bp.delete("delete")
def delete():
    """注销账号。请求体：``{"username": str, "password": str}``"""
    body = json_body()
    username = body.get("username")
    username = username.strip() if isinstance(username, str) else ""
    password = body.get("password")
    password = password if isinstance(password, str) else ""
    if not username or not password:
        return Result.fail(400, "用户名或密码不能为空")
    return userService.delete(username, password)
