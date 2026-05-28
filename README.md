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
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 第一版功能

- 创建学习目标
- 生成阶段计划和每日计划
- 生成今日任务
- 任务打卡与完成率统计
- AI 复盘总结
- 根据完成率和薄弱点调整明日计划

## 第二阶段建议

- 接入 Chroma，支持课程 PDF / PPT / Word 建库
- 加入用户登录与长期学习画像
- 加入异步任务队列，处理文档解析和长计划生成
- 加入测试集，评估计划生成质量和格式稳定性

