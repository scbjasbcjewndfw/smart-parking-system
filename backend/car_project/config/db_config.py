# coding: utf-8
"""MySQL 分项连接配置（兼容层）。

优先级：环境变量 > 本文件默认值。真正的连接串拼装见 ``config/database.py``。

注意：默认值 ``root/root`` 仅用于本地开发；部署时必须通过 ``.env`` 覆盖，
否则密码会随源码一起泄露。
"""
import os

DB_CONFIG = {
    "host": os.getenv("CARPARK_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("CARPARK_DB_PORT", "3306")),
    "db": os.getenv("CARPARK_DB_NAME", "parking_db"),
    "user": os.getenv("CARPARK_DB_USER", "root"),
    "password": os.getenv("CARPARK_DB_PASSWORD", "root"),
    "charset": os.getenv("CARPARK_DB_CHARSET", "utf8mb4"),
}
