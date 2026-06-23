# RAG 查询与 PDF 阅读器问题记录

> 记录时间：2026-06-23
> 会话摘要：排查了 RAG 查询慢、500 错误、PDF 原文预览不匹配三个问题，并修复了两个代码 bug。

---

## 1. RAG 查询慢 & 500 错误

### 现象

- RAG 知识库查询非常慢（数秒）
- 日志中出现 `ConnectTimeout` 500 错误

### 根因分析

#### 500 错误：HuggingFace Hub 连接超时

`BgeM3EmbeddingFunction._load_model()` 内部调用 `BGEM3FlagModel()` 时，`AutoTokenizer.from_pretrained` 会访问 HuggingFace Hub 的 `list_repo_tree` API 检查更新。即使模型已缓存到本地 `.cache/huggingface/`，仍然会发起 HTTP 请求，在国内网络环境下超时。

**调用链**：查询 → Chroma query → embedding query → BGE-M3 `__call__` → `_load_model` → `AutoTokenizer.from_pretrained` → huggingface_hub API → ❌ ConnectTimeout

#### 查询慢：三层计算都在 CPU 上

一次 RAG 查询涉及：

| 阶段 | 耗时 | 说明 |
|------|------|------|
| `rewrite_query()` | ~1ms | 正则解析 |
| BGE-M3 dense encoding | 200-1000ms | 568M 参数模型，CPU 推理 |
| Chroma ANN 搜索（30 候选） | 50-200ms | HNSW 索引 |
| BM25 词汇检索（全表扫描） | 200-1000ms | Python 循环 tokenize + 计算 431 chunks |
| BGE-Reranker（30 对交叉编码） | 500-3000ms | CPU 推理 |
| **合计** | **1-5 秒** | 全部在 CPU 上 |

#### 配置现状（`.env`）

```ini
EMBEDDING_PROVIDER=bge-m3        # BAAI/bge-m3, 输出 1024 维
RERANKER_PROVIDER=bge             # BAAI/bge-reranker-v2-m3（已改为 none）
RAG_HYBRID_SEARCH_ENABLED=true    # 已改为 false
RERANKER_CANDIDATE_COUNT=30
RAG_LEXICAL_CANDIDATE_COUNT=30
```

### 已做的修复/调整

#### 修复 1：HF_HUB_OFFLINE=1（`backend/app/main.py`）

```python
os.environ.setdefault("HF_HUB_OFFLINE", "1")
```

在应用最开头设置，强制 transformers/huggingface_hub 只读本地缓存，不联网。

#### 配置调整（`backend/.env`）

- `RERANKER_PROVIDER=none` — 关闭交叉编码器重排序
- `RAG_HYBRID_SEARCH_ENABLED=false` — 关闭 BM25 全表扫描混合检索

---

## 2. 首次查询慢 / 懒加载

### 现象

- 第一次查询需要 3-8 秒
- 后续查询只需几百毫秒

### 原因

BGE-M3 是懒加载的（`embeddings.py`）：

```python
def _load_model(self) -> Any:
    if self._model is not None:
        return self._model       # 后续查询直接返回
    self._model = BGEM3FlagModel(...)  # 第一次从磁盘加载 ~2GB 模型
```

同时 `get_embedding_function()` 有 `@lru_cache`，确保同一进程只加载一次。

### 建议

- 当前方案：首查慢，后续快，可接受
- 优化方向：启动时预加载模型，或在后台线程异步加载

---

## 3. PDF 原文预览与页面不匹配

### 现象

"高等数学习题册下册.pdf" 的 PDF 页面图片显示正确（习题册），但原文预览和翻译对照显示的是**同济《高等数学 第八版 下册》**的内容。

### 数据调查

| 条目 | 实际内容 |
|------|---------|
| Material ID=21, goal=26 DB 记录 | 高等数学习题册下册.pdf |
| 磁盘文件 `goal_26/d48e07f1...pdf` | ✅ 习题册（135页，扫描版） |
| OCR 缓存 `material_21/pages/` | ❌ 同济高数教材（150页） |
| OCR 缓存 `material_25/pages/` | ✅ 习题册（134页，已废弃） |

**关键证据**：OCR 缓存的 `file_sha256` 与当前 PDF 文件的 SHA256 **不一致**，匹配的是 `goal_25/` 目录下的另一个旧文件。

### 根因：两个代码 Bug

#### Bug A：OCR 缓存不校验文件哈希（`paddle_ocr.py`）

```python
# 修改前：只要 pages/ 目录存在就直接返回
cached_pages = cached_ocr_pages(material)
if cached_pages:
    return OcrResult(...)  # 不检查缓存是否匹配当前文件
```

`meta.json` 里存了 OCR 时的 `file_sha256`，但没有任何代码用它验证。

同时 `pdf_page_text()` 中：
```python
text = cached_ocr_page_text(material, page_index) or page.get_text("text").strip()
```

扫描版 PDF 的 `page.get_text("text")` 返回空，永远走 OCR 缓存，拿到的是旧文件的内容。

#### Bug B：删除目标时不清理文件/OCR 缓存（`routes.py`）

```python
# 修改前：只删 DB 和 Chroma
def delete_goal(goal_id):
    crud.delete_goal(db, goal_id)          # 删 DB ✅
    ChromaKnowledgeBase().delete_goal_collection(goal_id)  # 删 Chroma ✅
    # ❌ 不删 materials/ 原始文件和 ocr/ 缓存
```

对比 `delete_material_files()` 原始文件 + OCR 缓存
```python
# 删除单个素材是完整清理的
delete_material_files(material)  # 删原始文件 + OCR 缓存
```

叠加效果：material 被删除又重建后，ID 对应的 OCR 缓存是旧文件的，导致张冠李戴。

### 修复

#### 修复 A：OCR 缓存哈希校验（`backend/app/services/paddle_ocr.py`）

新增 `_cached_hash_matches()`：
1. 读取 `meta.json` 中的 `file_sha256`
2. 与当前文件的 SHA256 对比
3. 不匹配 → 清除整个缓存目录，重新提交 OCR

#### 修复 B：`delete_goal` 清理文件（`backend/app/api/routes.py`）

改为先通过 `goal.materials` 遍历，对每个 material 调用 `delete_material_files()`，再删除 DB 记录。

---

## 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `backend/.env` | 新增 `RAG_HYBRID_SEARCH_ENABLED=false`；`RERANKER_PROVIDER=none` |
| `backend/app/main.py` | 新增 `os.environ.setdefault("HF_HUB_OFFLINE", "1")` |
| `backend/app/services/paddle_ocr.py` | 导入 `shutil`；新增 `_cached_hash_matches()`；`ensure_pdf_ocr_with_progress` 中缓存命中后校验哈希 |
| `backend/app/api/routes.py` | `delete_goal` 中遍历 materials 调用 `delete_material_files()` |

---

## 待优化的方向（未改动代码）

- **BM25 词汇检索加速**：`_lexical_hits()` 每次都全表扫描所有 chunks，可以改用 SQLite FTS5 全文索引
- **embedding 懒加载改启动时加载**：避免首次查询慢（当前是刻意设计，可接受）
- **`delete_material_files` 清理空的 goal 目录**：删除所有文件后父目录 `goal_N/` 可能残留空文件夹
