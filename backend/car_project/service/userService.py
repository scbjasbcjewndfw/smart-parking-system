# coding: utf-8
"""用户业务层：注册、登录、注销。

相对改动前的修复
----------------
1. **Session 隔离**：改为 ``with SessionLocal() as session``。改动前是模块级 Session
   且请求结束后 ``close()``，多线程下会互相干扰。
2. **异常分支引用未定义变量**：``register`` 的 ``except`` 里返回了 ``new``，
   而 ``new`` 只在 try 内赋值，一旦查询阶段抛错就会触发 ``UnboundLocalError``，
   把真实异常（例如数据库连不上）覆盖掉。``delete`` 同样使用了可能未定义的 ``user``。
3. **返回值可序列化**：改动前 ``register`` 直接返回 ORM 对象，``Result.to_serializable``
   走到 ``str(data)`` 分支，前端收到的是 ``<SysUser object at 0x...>``。现返回显式字典。
4. **唯一约束兜底**：先查重再插入存在并发窗口，补充 ``IntegrityError`` 捕获。
5. **登录语义**：账号或密码错误统一返回 401，且不再把用户信息塞进失败响应
   （原实现会把 user_id 一起返回，属于信息泄露）。
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from common.Result import Result
from config.database import SessionLocal
from models.models import SysUser


def _public_user(user: SysUser) -> dict:
    """把用户对象转换为对外可返回的字典（不含密码）。

    Args:
        user: 用户 ORM 对象。

    Returns:
        含 ``user_id`` / ``username`` / ``plate`` / ``create_time`` 的字典。
    """
    return {
        "user_id": user.user_id,
        "username": user.username,
        "plate": user.plate,
        "create_time": user.create_time.strftime("%Y-%m-%d %H:%M:%S")
        if user.create_time
        else None,
    }


def register(username: str, password: str, plate: str | None = None) -> dict:
    """注册新用户。入参已由接口层校验并规范化。

    Args:
        username: 用户名，唯一。
        password: 明文密码，落库前使用 werkzeug 哈希。
        plate: 可选绑定车牌，已规范化。

    Returns:
        ``Result`` 结构字典，成功时 ``data`` 为新用户公开信息。
    """
    try:
        with SessionLocal() as session:
            if session.query(SysUser).filter(SysUser.username == username).first():
                return Result.fail(400, "该用户名已经注册")

            user = SysUser(
                username=username,
                password=generate_password_hash(password),
                plate=plate,
                create_time=dt.datetime.now(),
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return Result.success("用户注册成功", _public_user(user))
    except IntegrityError:
        # 并发注册同一用户名时，唯一索引会拦截，这里转成业务语义
        return Result.fail(400, "该用户名已经注册")


def login(username: str, password: str) -> dict:
    """校验用户名密码。

    Args:
        username: 用户名。
        password: 明文密码。

    Returns:
        ``Result`` 结构字典。成功 ``code=200``，凭证错误 ``code=401``。
    """
    with SessionLocal() as session:
        user = session.query(SysUser).filter(SysUser.username == username).first()
        if user is None or not check_password_hash(user.password, password):
            return Result.fail(401, "用户名或密码错误")
        return Result.success("用户登录成功", _public_user(user))


def get_profile(user_id: int) -> dict:
    """按用户 ID 读取公开信息，用于 /user/profile。

    改动前 ``/user/profile`` 直接读 JWT 里的 claims，账号注销或改名后仍会返回旧值；
    改为回源数据库，保证前端展示的一致性。

    Args:
        user_id: 用户 ID（来自 JWT identity）。

    Returns:
        ``Result`` 结构字典，用户不存在返回 404。
    """
    with SessionLocal() as session:
        user = session.query(SysUser).filter(SysUser.user_id == user_id).first()
        if user is None:
            return Result.fail(404, "用户不存在")
        return Result.success("获取当前用户成功", _public_user(user))


def delete(username: str, password: str) -> dict:
    """注销账号（永久删除）。

    注意：只删除 ``sys_user`` 记录，历史订单按审计要求保留，不做级联删除。

    Args:
        username: 用户名。
        password: 明文密码，必须二次确认。

    Returns:
        ``Result`` 结构字典。
    """
    with SessionLocal() as session:
        user = session.query(SysUser).filter(SysUser.username == username).first()
        if user is None:
            return Result.fail(404, "该用户不存在")
        if not check_password_hash(user.password, password):
            return Result.fail(401, "用户名或密码错误")
        session.delete(user)
        session.commit()
        return Result.success("用户注销成功", {"username": username})
