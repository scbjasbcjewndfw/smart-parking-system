# 智慧停车 · 车牌识别与客服 Agent 系统

Flask + Vue3 的停车场管理系统：**车牌识别**、**停车计费**、**知识库问答**、**ReAct 客服 Agent** 四条链路，
后端提供 REST 与 SSE 流式接口，前端为 Vue3 + Vite 单页应用。

## 功能

- **用户与认证**：JWT 登录鉴权，用户绑定车牌，客服 Agent 仅允许查询本人订单。
- **车牌识别**：YOLO 检测车牌区域 + PaddleOCR 多方案文字识别，识别失败时降级为车牌格式校验。
- **停车计费**：入场/出场时间校验、免费时长、阶梯计费与异常时间兜底（防谎报入场时间）。
- **知识库问答**：`docs/kb/customer` 下的客服知识文档 → 切分入库 → 向量 + 关键词混合检索 → 受约束回答。
- **客服 Agent**：ReAct 循环 + 工具注册（知识库检索、订单查询、计费试算等），带参数校验与越权防护。
- **流式输出**：`/api/agent/chat/stream` 通过 SSE 推送进度与增量文本。
- **评测脚本**：`scripts/eval_kb.py` 对知识库问答做批量评测并输出报告。

## 目录结构

```
car-plate-system/
├── start-dev.bat                 # 一键启动前后端（Windows）
├── backend/
│   ├── car_project/              # Flask 后端
│   │   ├── app.py                # 开发服务器入口
│   │   ├── __init__.py           # 应用工厂：JWT / CORS / 错误处理 / 蓝图注册
│   │   ├── controller/           # 接口层：user / plate / parking / kb / agent
│   │   ├── service/              # 业务层：计费、车牌识别、知识库、Agent
│   │   ├── config/               # 数据库与配置
│   │   ├── models/               # SQLAlchemy 模型
│   │   ├── scripts/              # init_db / eval_kb / smoke_test
│   │   └── requirements.txt
│   └── plate_rec/                # 车牌检测/OCR 实验脚本
├── frontend/                     # Vue3 + Vite（首页、车牌识别、客服对话）
└── docs/kb/customer/             # 客服知识库（Markdown）
```

## 快速开始

### 1. 后端

```bash
cd backend/car_project
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 配置：复制 .env.example 为 .env 后按需修改
copy .env.example .env

python app.py            # 默认 http://127.0.0.1:5000，可用 CARPARK_PORT 覆盖
```

数据库默认 MySQL，也可在 `.env` 中设置 `CARPARK_DB_BACKEND=sqlite` 免装数据库；
初始化表结构与演示数据执行 `python scripts/init_db.py`。

### 2. 前端

```bash
cd frontend
npm install
npm run dev              # 默认 http://127.0.0.1:5173
```

Windows 下也可直接双击根目录 `start-dev.bat` 同时拉起前后端。

## 未包含在仓库中的内容

以下内容体积较大或含隐私，已在 `.gitignore` 中排除，需自行准备：

- `.venv/`、`frontend/node_modules/` 依赖目录
- `.env`（密钥与数据库密码），参考 `.env.example`
- 模型权重：`backend/car_project/weight/`、`backend/plate_rec/plate_exp/`
- 运行产物：`instance/`、`*.db`、识别结果图片

## 技术栈

Python 3.10+、Flask、SQLAlchemy、MySQL、JWT、Ultralytics YOLO、PaddleOCR、
sentence-transformers（本地 BGE 向量）、Vue3、Vite、Axios
