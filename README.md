# StudyAgent

AI 学习执行官第一版：目标输入 -> AI 生成计划 -> 今日任务 -> 用户打卡 -> AI 复盘 -> 调整明日计划。

## 一键本地启动

Windows 本地开发推荐直接使用项目根目录下的脚本：

```powershell
.\install-local.bat
.\start-local.bat
```

前置条件是本机已经安装 Python 3.11+ 和 Node.js 20 LTS+；脚本会自动检查，
并继续安装项目内的 Python 依赖和 Node 依赖。

`install-local.bat` 会创建后端虚拟环境、安装 Python/Node 依赖，并在缺失时生成
`backend\.env` 与 `frontend\.env.local`。默认不会覆盖已有环境文件，避免误删
`DEEPSEEK_API_KEY`；如果确实要重建环境文件，可以执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-local.ps1 -ForceEnv
```

`start-local.bat` 会分别打开后端 FastAPI 和前端 Next.js 两个命令行窗口，
并自动用默认浏览器打开前端页面。
本地默认使用 SQLite + 同步计划生成模式，因此不需要启动 Docker、Redis 或 Celery。

打开地址：

```text
后端健康检查：http://127.0.0.1:8000/api/v1/health
前端页面：http://127.0.0.1:3000
```

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
- 创建目标时可提前上传 PDF/PPT/Word/TXT/MD 课程资料
- 生成阶段计划和每日计划
- 生成今日任务
- 任务打卡与完成率统计
- AI 复盘总结
- 根据完成率和薄弱点调整明日计划
- 每个任务支持 AI 生成 3 道小测题，并在弹窗中完成答题和基础批改
- 右侧 AI 学习助手聊天抽屉，支持流式输出和当前计划上下文
- 我的学习计划：刷新后可恢复历史计划，支持切换和删除

## v0.2 课程知识库

当前已接入 Chroma 本地持久化知识库，支持上传课程资料并建库：

- 支持格式：PDF、DOCX、PPTX、TXT、MD
- 解析工具：PyMuPDF、python-docx、python-pptx
- 切分策略：段落优先，长段落按窗口切分
- 向量库：Chroma `PersistentClient`
- Embedding：本地哈希 embedding，离线可运行，后续可替换为真实 embedding 模型
- RAG 增强：上传资料会生成语言标记、中文摘要和中英术语表；英文资料会以“原文 + 中文摘要 + 术语”写入 Chroma，方便中文检索英文教材

说明：

- DeepSeek 继续负责摘要、术语抽取、计划生成和任务生成。
- 当前 embedding 仍是本地哈希向量，便于离线 Demo；后续可替换为 bge-m3、Qwen Embedding 等多语言 embedding。
- 未配置 `DEEPSEEK_API_KEY` 时，系统会使用本地启发式规则生成摘要和术语，不影响基本建库流程。

接口：

```text
POST /api/v1/goals/with-materials
POST /api/v1/goals/{goal_id}/materials/upload
GET  /api/v1/goals/{goal_id}/materials
GET  /api/v1/materials/{material_id}
POST /api/v1/goals/{goal_id}/knowledge/search
POST /api/v1/tasks/{task_id}/quiz
POST /api/v1/quizzes/{quiz_id}/submit
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

学习计划、每日任务和复盘默认保存在本地 SQLite：

```text
backend/studyagent.db
```

只要 `backend/studyagent.db` 和 `backend/storage/` 不删除，下次打开前端时就可以从
“我的学习计划”中恢复已有计划，并继续使用已构建的 Chroma 知识库。

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

## AI 聊天助手

前端右下角提供可展开聊天抽屉，后端接口：

```text
POST /api/v1/chat/stream
```

请求会携带多轮消息、当前 `goal_id` 和 `plan_id`。后端会读取当前学习目标、
选中 Day、任务状态，并检索 Chroma 课程资料，然后通过 DeepSeek 流式返回。
如果未配置 `DEEPSEEK_API_KEY`，接口会返回本地兜底文本流，方便离线 Demo。

## 第二阶段建议

- 替换为真实语义 embedding 模型，提升中文课程资料检索质量
- 加入用户登录与长期学习画像
- 加入测试集，评估计划生成质量和格式稳定性
