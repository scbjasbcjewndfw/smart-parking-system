# coding: utf-8
"""开发服务器入口。

监听地址与端口可通过环境变量覆盖：

================= ==========================================
变量               默认值
================= ==========================================
CARPARK_HOST      0.0.0.0
CARPARK_PORT      5000
================= ==========================================

端口做成可配置的原因：本机常同时跑多个项目，5000 很容易被别的服务占用，
而 Windows 允许两个进程同时绑定同一端口，请求会随机落到其中一个，
表现为"接口时而 404、时而正常"，排查成本极高。
"""
from __future__ import annotations

import os

from __init__ import create_app

app = create_app()

if __name__ == "__main__":
    host = os.getenv("CARPARK_HOST", "0.0.0.0")
    port = int(os.getenv("CARPARK_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
