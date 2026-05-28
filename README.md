# StudyAgent

AI 学习执行官第一版：目标输入 -> AI 生成计划 -> 今日任务 -> 用户打卡 -> AI 复盘 -> 调整明日计划。

## 技术栈

- 前端：Next.js + TypeScript + Tailwind CSS + Shadcn 风格组件
- 后端：FastAPI + Pydantic + SQLAlchemy
- Agent：LangGraph
- 数据库：PostgreSQL
- 缓存：Redis
- LLM：DeepSeek API，未配置 Key 时使用本地规则兜底
- 向量库：Chroma，第二阶段接入
- 部署：Docker Compose

## 快速启动

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 按需填写 `DEEPSEEK_API_KEY`。不填写也可以运行 Demo，后端会使用本地规则生成学习计划和复盘。

3. 启动服务：

```bash
docker compose up --build
```

4. 打开：

```text
http://localhost:3000
```

## 本地开发

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd C:\Users\33612\Documents\GitHub\StudyAgent\backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install

cd C:\Users\33612\Documents\GitHub\StudyAgent\frontend
npm.cmd run dev
```

本地开发默认可以不启动 Redis/Celery。保持 `.env` 中：

```env
NEXT_PUBLIC_USE_ASYNC_JOBS=false
```

此时前端会显示模拟进度条，但计划生成仍走同步接口 `POST /api/v1/goals`。
如果要测试真实异步队列，再改为 `true`，并启动 Redis 和 Celery worker。

## 第一版功能

- 创建学习目标
- 生成阶段计划和每日计划
- 生成今日任务
- 任务打卡与完成率统计
- AI 复盘总结
- 根据完成率和薄弱点调整明日计划

## v0.2 课程知识库

当前已接入 Chroma 本地持久化知识库，支持上传课程资料并建库：

- 支持格式：PDF、DOCX、PPTX、TXT、MD
- 解析工具：PyMuPDF、python-docx、python-pptx
- 切分策略：段落优先，长段落按窗口切分
- 向量库：Chroma `PersistentClient`
- Embedding：本地哈希 embedding，离线可运行，后续可替换为真实 embedding 模型

接口：

```text
POST /api/v1/goals/{goal_id}/materials/upload
GET  /api/v1/goals/{goal_id}/materials
GET  /api/v1/materials/{material_id}
POST /api/v1/goals/{goal_id}/knowledge/search
```

上传示例：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/goals/1/materials/upload" `
  -Method Post `
  -Form @{ file = Get-Item "C:\path\to\course.pdf" }
```

检索示例：

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/goals/1/knowledge/search" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query":"进程同步 PV 操作","top_k":5}'
```

本地运行时会把上传文件和 Chroma 数据保存到：

```text
backend/storage/
```

## v0.2 异步任务队列

当前已接入 Celery + Redis，用于处理耗时任务：

- 课程资料异步解析与 Chroma 建库
- 学习目标异步长计划生成
- jobs 表记录任务状态，前端或接口文档可轮询查询进度

新增接口：

```text
POST /api/v1/goals/async
POST /api/v1/goals/{goal_id}/materials/upload/async
GET  /api/v1/jobs/{job_id}
```

任务状态：

```text
pending   等待 worker 处理
running   正在执行
success   执行成功
failed    执行失败
```

Docker Compose 会同时启动 `backend` 和 `worker`：

```bash
docker compose up --build
```

Windows 本地开发时，需要先启动 Redis，然后另开一个 PowerShell 启动 worker：

```powershell
cd C:\Users\33612\Documents\GitHub\StudyAgent\backend
.\.venv\Scripts\activate
celery -A app.tasks.celery_app.celery_app worker --loglevel=info --pool=solo
```

`--pool=solo` 是 Windows 本地运行 Celery worker 时更稳的方式。

## 第二阶段建议

- 替换为真实语义 embedding 模型，提升中文课程资料检索质量
- 加入用户登录与长期学习画像
- 加入测试集，评估计划生成质量和格式稳定性
