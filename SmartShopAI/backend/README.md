# SmartShopAI Backend

FastAPI + Pydantic + SQLite backend for the Android shopping demo.

## Setup

```powershell
cd J:\full-stack\SmartShopAI\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python scripts\import_dataset.py --dataset ..\app\ecommerce_agent_dataset --db .\data\smartshop.db --clean .\data\products_clean.json
python scripts\build_rag_index.py --db .\data\smartshop.db
uvicorn app.main:app --reload
```

OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

## AI Agent Design

用户通过文本或图片输入需求，后端先统一成 `final_user_query`，再进入 `query_router -> dense(Milvus) / BM25 / keyword -> RRF -> SQLite hydrate -> verifier` 的检索链路，并构造 grounded context。生成链路会把 grounded context 交给 Poe/Qwen 生成自然语言导购回复，但商品、价格、库存、SKU、图片、FAQ 和评价等事实仍只来自 SQLite。

前端通过 SSE 接收回答、商品卡片和结构化 actions。用户点击 action chip 时不再把按钮文本重新发送给后端，而是根据 action 类型直接执行查看详情、加入购物车、打开购物车或继续搜索。

当前检索链路固定使用 Milvus 作为 dense 召回。后端会调用 Qwen3-Embedding-0.6B embedding 服务生成 query vector，再通过 Milvus REST API 检索相似 `product_id`，最后仍回查 SQLite 获取商品、价格、库存、SKU、图片、FAQ 和评价事实。未配置 embedding 服务、Milvus 未启动或向量检索失败时，系统自动退回 BM25/keyword/RAG chunks 主链路。Poe/Qwen 不可用、超时、返回异常或回答没有覆盖已召回商品时，系统会回退到模板回复，保证 AI 导购页面仍可演示且不编造商品事实。

Android 图片输入会先用设备端 ML Kit Image Labeling 生成轻量视觉标签，再把标签作为检索 hint 传给后端；后端图片接口仍保留 mock 检测作为 fallback。语音输入默认使用 Android 系统语音识别并复用文本导购链路；后端也提供可选 `POST /api/agent/audio/transcribe`，配置 OpenAI-compatible ASR 后可以转写音频文件。

## Optional AI Backends

默认配置可以直接启用 Milvus：

```env
EMBEDDING_BASE_URL=http://localhost:8080/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIMENSIONS=1024
MILVUS_BASE_URL=http://localhost:19530
MILVUS_COLLECTION=smartshop_products
ASR_PROVIDER=none
```

本地 Docker 启动顺序：

```powershell
cd J:\full-stack\SmartShopAI\backend

# Windows 一键启动
powershell -ExecutionPolicy Bypass -File .\run_ai_stack.ps1
```

也可以分步执行：

```powershell
cd J:\full-stack\SmartShopAI\backend

# 先确认 Docker Desktop 已启动
docker ps

# 1. 启动 Milvus standalone，脚本会下载官方 compose 文件
powershell -ExecutionPolicy Bypass -File .\scripts\start_milvus.ps1

# 2. 启动 GPU 版 Qwen3-Embedding-0.6B embedding 服务
docker compose -f .\docker-compose.embedding.yml up -d

# 3. 构建商品向量索引到 Milvus
python .\scripts\build_milvus_index.py --recreate

# 4. 启动后端
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PowerShell 脚本支持：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_ai_stack.ps1 -Action infra
powershell -ExecutionPolicy Bypass -File .\run_ai_stack.ps1 -Action index
powershell -ExecutionPolicy Bypass -File .\run_ai_stack.ps1 -Action backend
powershell -ExecutionPolicy Bypass -File .\run_ai_stack.ps1 -Action status
powershell -ExecutionPolicy Bypass -File .\run_ai_stack.ps1 -Action stop
```

`docker-compose.embedding.yml` 默认使用 Hugging Face TEI CUDA 镜像，并向 Docker 请求 NVIDIA GPU。启动前可以先验证 GPU 是否能被容器看到：

```powershell
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

如果只想临时改回 CPU 镜像：

```powershell
$env:TEI_IMAGE="ghcr.io/huggingface/text-embeddings-inference:cpu-1.9"
docker compose -f .\docker-compose.embedding.yml up -d
```

可选外部服务配置项在 `.env.example` 中，包括 `MILVUS_BASE_URL` 和 `ASR_BASE_URL`。这些配置只影响增强召回或 ASR，不是商品事实源。

## Retrieval Evaluation

`scripts.eval_retrieval` 用于评估 AI 导购的商品召回、排序和硬约束过滤效果。它不是 Android App 端测试，也不是 Poe 生成文案测试；脚本直接调用后端内部检索工具链：

```text
scripts.eval_retrieval
-> call_search_products_tool
-> search_products_for_agent_with_diagnostics
-> query_router + constraints
-> dense(Milvus) / BM25 / keyword
-> RRF fusion
-> SQLite hydrate
-> verifier
```

评估集在 `backend/evals/retrieval_cases.json`，当前包含 100 条 case，其中 93 条期望返回商品，7 条期望空返回。case 可以配置：

- `query`：用户问题。
- `relevant_product_ids`：相关商品 ID，默认相关等级为 3。
- `graded_relevance`：分级相关性，`3` 强相关、`2` 次相关、`1` 弱相关。
- `constraints`：传入 `SearchProductsInput` 的硬约束，例如类目、子类目、品牌排除、价格上限。
- `forbidden_categories` / `must_not_include_product_ids`：用于评估返回列表是否混入禁止类目或禁止商品。
- `should_return_empty`：用于测试没有匹配商品时是否正确空返回。

运行前建议确认 SQLite 数据、embedding 服务和 Milvus 索引已准备好。dense 召回依赖本机 embedding 服务和 Milvus；如果 embedding 或 Milvus 不可用，系统会退回 BM25/keyword，指标会变化。

```powershell
cd J:\full-stack\SmartShopAI\backend

# 可选：先确认基础测试通过
J:\full-stack\SmartShopAI\.venv\Scripts\python.exe -m unittest discover -s tests

# 只看 Top1 推荐是否准确
J:\full-stack\SmartShopAI\.venv\Scripts\python.exe -m scripts.eval_retrieval --top-k 10 --k-values 1

# 同时看 Top1/3/5/10 的召回和排序质量
J:\full-stack\SmartShopAI\.venv\Scripts\python.exe -m scripts.eval_retrieval --top-k 10 --k-values 1,3,5,10
```

核心指标含义：

- `hit@k`：前 k 个结果里是否至少命中一个相关商品。
- `recall@k`：前 k 个结果覆盖了多少标注相关商品。
- `precision@k`：前 k 个结果中相关商品占比。
- `ndcg@k`：排序质量，强相关商品排得越靠前分数越高。
- `map@k` / `ap`：相关商品在结果列表中的平均精度。
- `mrr@k`：第一个相关商品出现位置的倒数。
- `constraint_pass_rate`：价格、类目、子类目、品牌排除、空结果等硬约束全部通过的比例。
- `empty_accuracy`：期望空返回的 case 中，实际空返回的比例。
- `bad_return_rate`：期望空返回却返回了商品的比例。
- `forbidden_category_rate`：返回结果中命中禁止类目的 case 比例。
- `category_precision` / `subcategory_precision`：返回商品的大类和子类目纯净度。
- `bm25_count_avg` / `dense_count_avg` / `keyword_count_avg`：各召回通道平均候选数，是诊断信息，不是质量分。

一次 Top1 评估输出示例：

```text
cases=100 retrieval_cases=93 empty_cases=7
hit@1=0.978 recall@1=0.479 precision@1=0.978 ndcg@1=0.920 map@1=0.978
mrr@1=0.978
constraint_pass_rate=0.650
empty_accuracy=0.429
bad_return_rate=0.571
forbidden_category_rate=0.070
category_precision=0.941
subcategory_precision=0.772
```

解读时需要分开看 Top1 和列表纯净度：`hit@1`、`precision@1`、`ndcg@1` 高，说明第一张商品卡片通常准确；`constraint_pass_rate`、`empty_accuracy`、`subcategory_precision` 低，则说明 Top10 列表里仍可能混入错误子类目，或者没有商品时会错误返回兜底结果。

如果要在 CI 或提交前设置最低阈值，可以使用：

```powershell
J:\full-stack\SmartShopAI\.venv\Scripts\python.exe -m scripts.eval_retrieval `
  --top-k 10 `
  --k-values 1,3,5,10 `
  --threshold-k 3 `
  --min-hit 0.90 `
  --min-ndcg 0.85 `
  --min-constraint-pass-rate 0.60 `
  --min-empty-accuracy 0.40 `
  --max-forbidden-category-rate 0.10
```

## API Surface

- `GET /health`
- `GET /api/products`
- `GET /api/products/{product_id}`
- `GET /api/categories`
- `GET /api/search?q=keyword`
- `GET /api/cart`
- `POST /api/cart/items`
- `PATCH /api/cart/items/{item_id}`
- `DELETE /api/cart/items/{item_id}`
- `POST /api/orders`
- `GET /api/orders/{order_id}`
- `POST /api/payments/mock`
- `POST /api/agent/image/upload`
- `POST /api/agent/image/analyze`
- `POST /api/agent/audio/transcribe`
- `POST /api/agent/chat/stream`

The service reads product JSON from `DATASET_PATH` and persists products, RAG chunks, carts, and orders in SQLite.
