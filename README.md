# LearnFlow

LearnFlow 是一个面向课程复习、自学和备考场景的 AI 学习执行官原型。

它的核心流程是：

```text
输入学习目标 -> 上传课程资料 -> 构建 RAG 知识库 -> 生成学习计划
-> 每日任务打卡 -> 小测反馈 -> AI 复盘 -> 调整后续计划
```

当前项目支持本地运行 Demo，也可以通过 Docker Compose 启动完整服务。
配置好Deepseek和PaddleOCR使用效果最佳

## 配置教程

### 1. 环境要求

本地开发建议准备：

- Windows 10/11
- Python 3.11+
- Node.js 20 LTS+
- DeepSeek API Key，用于真实 LLM 生成
- PaddleOCR Token，用于扫描版 PDF/OCR
- 可选：Docker Desktop
- 可选：Redis，只有启用 Celery 异步队列时需要

### 2. 一键生成环境变量

项目根目录提供了环境变量初始化脚本：

```powershell
.\setup-env.bat
```

它会创建：

```text
backend/.env
frontend/.env.local
backend/storage/materials
backend/storage/chroma
backend/storage/ocr
```

默认配置适合本地 Demo：

```env
DATABASE_URL=sqlite:///./studyagent.db
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1
NEXT_PUBLIC_USE_ASYNC_JOBS=false
OCR_PROVIDER=none
EMBEDDING_PROVIDER=hash
```

如果已经存在 `backend/.env` 或 `frontend/.env.local`，脚本默认不会覆盖。需要重建时使用：

```powershell
.\setup-env.bat -Force
```

### 3. 配置 DeepSeek

相关API Key在 https://platform.deepseek.com/usage 获取
如果要启用真实 AI 生成能力，可以在初始化时写入 Key：

```powershell
.\setup-env.bat -DeepSeekApiKey "你的 DeepSeek API Key" -Force
```

或者手动编辑 `backend/.env`：

```env
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

不填写 `DEEPSEEK_API_KEY` 也可以运行，系统会使用本地规则生成计划、任务和复盘。

### 4. 配置 PaddleOCR

相关Token在 https://aistudio.baidu.com/paddleocr 获取
如果要让 PDF 建库时自动 OCR，或者在 PDF 阅读器中手动识别整份 PDF，可以启用 PaddleOCR：

```powershell
.\setup-env.bat -PaddleOcrToken "你的 PaddleOCR Token" -EnableOcr -Force
```

对应的 `backend/.env` 配置为：

```env
OCR_PROVIDER=paddleocr
PADDLE_OCR_TOKEN=你的 PaddleOCR Token
PADDLE_OCR_JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLE_OCR_MODEL=PaddleOCR-VL-1.6
OCR_STORAGE_DIR=./storage/ocr
```

如果只是想上传 PDF 阅读，不想自动 OCR，可以保持：

```env
OCR_PROVIDER=none
```

### 5. 配置 BGE-M3 Embedding 和 Reranker

默认 embedding 使用轻量 `hash` 模式，reranker 默认关闭，适合快速 Demo。如果要提升 RAG 检索质量，可以切换到 `BAAI/bge-m3`，并启用 BGE reranker。

先安装可选依赖：

```powershell
cd backend
.\.venv\Scripts\activate
pip install -r requirements-bge.txt
```

如果还没有创建环境文件，可以直接生成：

```powershell
.\setup-env.bat -EmbeddingProvider bge-m3 -RerankerProvider bge
```

如果已经有 `backend/.env`，建议手动修改下面几项，避免覆盖已有的 DeepSeek/PaddleOCR Key：

```env
EMBEDDING_PROVIDER=bge-m3
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=auto
EMBEDDING_BATCH_SIZE=12
EMBEDDING_USE_FP16=false

RERANKER_PROVIDER=bge
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=auto
RERANKER_BATCH_SIZE=8
RERANKER_USE_FP16=false
RERANKER_CANDIDATE_COUNT=30
```

如果本机有合适的 NVIDIA GPU，可以按需改成：

```env
EMBEDDING_DEVICE=cuda
EMBEDDING_USE_FP16=true
RERANKER_DEVICE=cuda
RERANKER_USE_FP16=true
```

启用 reranker 后，检索流程会先从 Chroma 召回 `RERANKER_CANDIDATE_COUNT` 条候选，再重排返回前几条。切换 embedding 后，已有 Chroma 向量需要重建；只启用或关闭 reranker 不需要重建向量。

### 5.1 使用 HuggingFace API 远程调用 BGE-M3（可选）

如果本地没有 GPU 或不想下载模型权重，可以通过 HuggingFace Inference API 远程调用 bge-m3。先获取 [HuggingFace Token](https://huggingface.co/settings/tokens)，然后在 `backend/.env` 中配置：

```env
EMBEDDING_PROVIDER=hf-api
HF_TOKEN=hf_你的API密钥
```

可选安装 SDK 以获得更好的错误提示（不安装会自动 fallback 到 HTTP）：

```powershell
pip install -r backend/requirements-hf-api.txt
```

### 6. 配置前端

前端只读取 `frontend/.env.local`：

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1
NEXT_PUBLIC_USE_ASYNC_JOBS=false
```

字段说明：

- `NEXT_PUBLIC_API_BASE_URL`：前端请求后端 API 的地址。
- `NEXT_PUBLIC_USE_ASYNC_JOBS=false`：本地 Demo 推荐配置，不依赖 Redis/Celery。
- `NEXT_PUBLIC_USE_ASYNC_JOBS=true`：启用异步任务轮询，需要 Redis 和 Celery worker。

修改前端环境变量后，需要重启前端开发服务。

### 7. 安装依赖

第一次运行建议执行：

```powershell
.\install-local.bat
```

脚本会安装后端 Python 依赖和前端 Node 依赖。

也可以手动安装：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

```powershell
cd frontend
npm install
```

### 8. 启动本地 Demo

推荐使用：

```powershell
.\start-local.bat
```

脚本会分别启动后端和前端。

启动后访问：

```text
前端：http://127.0.0.1:3000
后端健康检查：http://127.0.0.1:8000/api/v1/health
LLM 健康检查：http://127.0.0.1:8000/api/v1/llm/health
```

也可以手动启动：

```powershell
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm.cmd run dev
```

### 9. 启用 Celery 异步队列（本地启动则不需要）

本地 Demo 默认不需要 Redis/Celery。如果要测试真实异步队列：

1. 启动 Redis。
2. 设置前端环境变量：

```env
NEXT_PUBLIC_USE_ASYNC_JOBS=true
```

3. 启动 Celery worker：

```powershell
cd backend
.\.venv\Scripts\activate
celery -A app.tasks.celery_app.celery_app worker --loglevel=info --pool=solo
```

Windows 本地建议使用 `--pool=solo`。

### 10. Docker Compose 配置（本地启动则不需要）

Docker 模式读取项目根目录的 `.env`。可以从模板复制：

```powershell
Copy-Item .env.example .env
```

然后按需修改 `.env`：

```env
DATABASE_URL=postgresql+psycopg://studyagent:studyagent@postgres:5432/studyagent
REDIS_URL=redis://redis:6379/0
DEEPSEEK_API_KEY=
OCR_PROVIDER=none
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_USE_ASYNC_JOBS=true
```

启动：

```powershell
docker compose up --build
```

注意：`postgres` 这个数据库主机名只在 Docker Compose 网络内有效。本地直接运行后端时请使用：

```env
DATABASE_URL=sqlite:///./studyagent.db
```

## 技术栈

### 前端

- Next.js + React + TypeScript
- Tailwind CSS + Shadcn
- react-markdown + KaTeX

### 后端

- FastAPI + Pydantic + SQLAlchemy
- SQLite / PostgreSQL
- Celery + Redis
- Docker Compose

### Agent 与 RAG

- DeepSeek API
- LangGraph
- Chroma
- BAAI/bge-m3
- BAAI/bge-reranker-v2-m3
- PyMuPDF / python-docx / python-pptx
- PaddleOCR
