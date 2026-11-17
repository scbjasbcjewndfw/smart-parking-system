# coding: utf-8
"""Flask 应用工厂。

配置来源
--------
全部通过环境变量注入（可用 ``.env``，python-dotenv 已在依赖中），未配置时使用
**仅适合本地开发**的默认值，并在启动日志里明确告警。

======================== ========================================== ==================
环境变量                 含义                                       开发默认
======================== ========================================== ==================
CARPARK_JWT_SECRET       JWT 签名密钥（生产必须替换）               内置开发密钥
CARPARK_JWT_EXPIRES_MIN  access token 有效期（分钟）                120
CARPARK_CORS_ORIGINS     允许的前端源，逗号分隔                      localhost:5173 等
CARPARK_MAX_UPLOAD_MB    单次上传大小上限（MB）                     10
======================== ========================================== ==================

相对改动前的修复
----------------
1. ``JWT_SECRET_KEY`` 原先硬编码在源码里，任何拿到代码的人都能伪造 token；
   现改为环境变量，缺失时用开发密钥并告警。
2. 原先未设置 ``JWT_ACCESS_TOKEN_EXPIRES``，实际生效 15 分钟，用户在页面上操作到一半
   就会掉登录；现显式可配，默认 120 分钟。
3. ``CORS(app)`` 原先对任意源开放，现改为白名单，默认只允许本地 Vite 开发端口。
4. 新增上传大小限制与 413/404/500 的 JSON 错误响应，避免前端收到 HTML 报错页。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from controller.agentController import agent_bp
from controller.kbController import kb_bp
from controller.parkingController import parking_bp
from controller.plateController import plate_bp
from controller.userController import user_bp

logger = logging.getLogger(__name__)

#: 仅本地开发使用的兜底密钥，生产环境必须通过环境变量覆盖
_DEV_JWT_SECRET = "dev-only-secret-change-me-4f3a9c1e"

_DEFAULT_CORS_ORIGINS = ",".join(
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
)


#: 配置文件固定在 car_project/ 下，避免从不同工作目录启动时读到不同 .env
_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load_dotenv_if_present() -> None:
    """加载 car_project/.env（绝对路径，与启动目录无关）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:  # 未安装时静默跳过，不影响启动
        return
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)


def _env_int(name: str, default: int) -> int:
    """读取整型环境变量，非法值回退默认。

    Args:
        name: 环境变量名。
        default: 默认值。

    Returns:
        解析后的整数。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，使用默认值 %s", name, raw, default)
        return default


def create_app() -> Flask:
    """创建并配置 Flask 应用。

    Returns:
        已完成蓝图、JWT、CORS 与错误处理配置的应用实例。
    """
    _load_dotenv_if_present()

    app = Flask(__name__)
    app.json.ensure_ascii = False  # 中文直接输出，便于调试与前端展示

    max_upload_mb = _env_int("CARPARK_MAX_UPLOAD_MB", 10)
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

    _configure_jwt(app)
    _configure_cors(app)
    _register_error_handlers(app, max_upload_mb)
    register_blueprints(app)
    _warmup_kb()
    return app


def _warmup_kb() -> None:
    """后台预热向量模型与缓存，避免首个客服请求承担模型加载耗时。"""
    from service import kbService

    if not kbService.API_KEY or not kbService.EMBED_MODEL_PATH:
        return

    def _run() -> None:
        try:
            kbService.get_store()
            kbService.embed_texts(["预热"])
            logger.info("知识库预热完成")
        except Exception:  # noqa: BLE001 - 预热失败不影响正常启动
            logger.exception("知识库预热失败（不影响启动）")

    threading.Thread(target=_run, daemon=True, name="kb-warmup").start()


def _configure_jwt(app: Flask) -> None:
    """配置 JWT 密钥与有效期。

    Args:
        app: Flask 应用实例。
    """
    import datetime as dt

    secret = os.getenv("CARPARK_JWT_SECRET", "").strip()
    if not secret:
        secret = _DEV_JWT_SECRET
        logger.warning(
            "未设置 CARPARK_JWT_SECRET，正在使用内置开发密钥，切勿用于生产环境"
        )
    app.config["JWT_SECRET_KEY"] = secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = dt.timedelta(
        minutes=_env_int("CARPARK_JWT_EXPIRES_MIN", 120)
    )
    # 统一 401 的响应结构，便于前端拦截器识别
    app.config["JWT_ERROR_MESSAGE_KEY"] = "msg"
    JWTManager(app)


def _configure_cors(app: Flask) -> None:
    """按白名单配置跨域。

    Args:
        app: Flask 应用实例。
    """
    raw = os.getenv("CARPARK_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    CORS(
        app,
        resources={r"/api/*": {"origins": origins}},
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        max_age=600,
    )


def _register_error_handlers(app: Flask, max_upload_mb: int) -> None:
    """注册全局错误处理，保证异常也返回统一 JSON 结构。

    Args:
        app: Flask 应用实例。
        max_upload_mb: 上传大小上限，用于拼装提示文案。
    """
    from common.Result import Result

    @app.errorhandler(413)
    def _payload_too_large(_error):  # noqa: ANN001 - Flask 回调签名固定
        return Result.fail(413, f"上传内容过大，单张图片请控制在 {max_upload_mb}MB 以内"), 413

    @app.errorhandler(404)
    def _not_found(_error):  # noqa: ANN001
        return Result.fail(404, "接口不存在"), 404

    @app.errorhandler(500)
    def _internal_error(error):  # noqa: ANN001
        logger.exception("未捕获异常: %s", error)
        return Result.fail(500, "服务器内部错误"), 500


def register_blueprints(app: Flask) -> None:
    """注册所有接口蓝图。

    Args:
        app: Flask 应用实例。
    """
    app.register_blueprint(user_bp)
    app.register_blueprint(plate_bp)
    app.register_blueprint(parking_bp)
    app.register_blueprint(kb_bp)
    app.register_blueprint(agent_bp)
