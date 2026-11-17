# coding: utf-8
"""数据库连接配置：环境变量驱动，同时支持 MySQL 与 SQLite。

为什么改
--------
1. **原实现把 ``root/root`` 写死在 ``db_config.py`` 里**，换一台机器就连不上，
   而且密码进了版本库。现在连接串完全由环境变量决定。
2. **``.env`` 加载时机错误**：原来 ``load_dotenv()`` 在 ``create_app()`` 里调用，
   但本模块在 controller → service 导入链上更早执行，engine 早已按旧配置创建完毕，
   等于 ``.env`` 对数据库配置完全无效。现在在本模块导入时就加载。
3. **缺省可用**：``CARPARK_DB_BACKEND=sqlite`` 时自动落到
   ``instance/parking.db``，无需外部服务即可启动（适合本地开发与演示）；
   生产环境设置 ``CARPARK_DB_BACKEND=mysql`` 或直接给 ``CARPARK_DATABASE_URL``。

环境变量
--------
======================= ==========================================================
变量                     含义
======================= ==========================================================
CARPARK_DATABASE_URL    完整 SQLAlchemy 连接串，设置后忽略其余数据库配置
CARPARK_DB_BACKEND      ``mysql``（默认）或 ``sqlite``
CARPARK_DB_HOST / PORT / USER / PASSWORD / NAME   MySQL 分项配置
CARPARK_DB_PATH         SQLite 文件路径，默认 ``instance/parking.db``
CARPARK_DB_ECHO         ``1`` 时打印 SQL，便于排查
======================= ==========================================================
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

#: 项目根目录（``car_project/``），用于定位 .env 与 SQLite 文件
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """加载 ``car_project/.env``。

    必须在本模块创建 engine 之前执行，否则 .env 里的数据库配置不会生效。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # 未安装 python-dotenv 时静默跳过
        return
    load_dotenv(BASE_DIR / ".env")


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    """读取环境变量并去除首尾空白。

    Args:
        name: 环境变量名。
        default: 变量缺失或为空时的默认值。

    Returns:
        处理后的字符串。
    """
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _mysql_url() -> str:
    """按分项环境变量拼装 MySQL 连接串。

    Returns:
        SQLAlchemy 连接串。
    """
    # db_config 保留为兼容层，内部同样改为读取环境变量
    from config.db_config import DB_CONFIG

    return (
        f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['db']}"
        f"?charset={DB_CONFIG['charset']}"
    )


def _sqlite_url() -> str:
    """拼装 SQLite 连接串，并确保目标目录存在。

    Returns:
        SQLAlchemy 连接串。
    """
    raw_path = _env("CARPARK_DB_PATH", str(BASE_DIR / "instance" / "parking.db"))
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


#: 当前使用的后端：``mysql`` / ``sqlite``
DB_BACKEND = _env("CARPARK_DB_BACKEND", "mysql").lower()

#: 最终连接串，显式指定 CARPARK_DATABASE_URL 时优先
DATABASE_URL = _env("CARPARK_DATABASE_URL") or (
    _sqlite_url() if DB_BACKEND == "sqlite" else _mysql_url()
)

_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict[str, Any] = {
    "echo": _env("CARPARK_DB_ECHO") == "1",
    "future": True,
}
if _is_sqlite:
    # SQLite 默认禁止跨线程复用连接，而 Flask 开发服务器是多线程的
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # 局域网 MySQL 连接可能被防火墙/超时回收，取连接前先探活
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 3600

#: 数据库引擎
engine: Engine = create_engine(DATABASE_URL, **_engine_kwargs)

#: 会话工厂，每次请求应通过 ``with SessionLocal() as session`` 使用
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

#: 隐藏连接串中的密码，便于安全地打印到日志
SAFE_DATABASE_URL = DATABASE_URL
if "@" in SAFE_DATABASE_URL and "//" in SAFE_DATABASE_URL:
    head, tail = SAFE_DATABASE_URL.split("//", 1)
    if "@" in tail:
        cred, host = tail.split("@", 1)
        user = cred.split(":", 1)[0]
        SAFE_DATABASE_URL = f"{head}//{user}:***@{host}"


def init_db() -> None:
    """按模型定义创建缺失的表（幂等，不会删除已有数据）。"""
    from models.models import Base

    Base.metadata.create_all(engine)


def check_connection() -> tuple[bool, str]:
    """探测数据库是否可用。

    Returns:
        ``(是否连通, 描述信息)``，不抛出异常，便于启动时做健康检查。
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, SAFE_DATABASE_URL
    except Exception as exc:  # noqa: BLE001 - 健康检查不应中断流程
        return False, f"{type(exc).__name__}: {exc}"


if _is_sqlite:
    logger.warning(
        "当前使用 SQLite 开发库：%s（生产环境请设置 CARPARK_DB_BACKEND=mysql）",
        SAFE_DATABASE_URL,
    )
