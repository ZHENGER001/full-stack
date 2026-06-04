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

用户通过文本或图片输入需求，后端先统一成 `final_user_query`，再基于 SQLite 商品事实源进行规则、BM25-like、SQLite 字段和 `rag_chunks` 的混合召回。召回结果会经过轻量 reranker，根据相关性、价格、库存、品类、场景和上下文重排序，并构造 grounded context。生成链路会把 grounded context 交给 Poe/Qwen 生成自然语言导购回复，但商品、价格、库存、SKU、图片、FAQ 和评价等事实仍只来自 SQLite。

前端通过 SSE 接收回答、商品卡片和结构化 actions。用户点击 action chip 时不再把按钮文本重新发送给后端，而是根据 action 类型直接执行查看详情、加入购物车、打开购物车或继续搜索。

当前 `Agent-easy` 节点支持 Milvus 向量召回。`VECTOR_BACKEND=milvus` 时，后端会调用 Qwen3-Embedding-4B embedding 服务生成 query vector，再通过 Milvus REST API 检索相似 `product_id`，最后仍回查 SQLite 获取商品、价格、库存、SKU、图片、FAQ 和评价事实。未配置 embedding 服务、Milvus 未启动或向量检索失败时，系统自动退回 SQLite/BM25-like/RAG chunks 主链路。Poe/Qwen 不可用、超时、返回异常或回答没有覆盖已召回商品时，系统会回退到规则检索和模板回复，保证 AI 导购页面仍可演示且不编造商品事实。

Android 图片输入会先用设备端 ML Kit Image Labeling 生成轻量视觉标签，再把标签作为检索 hint 传给后端；后端图片接口仍保留 mock 检测作为 fallback。语音输入默认使用 Android 系统语音识别并复用文本导购链路；后端也提供可选 `POST /api/agent/audio/transcribe`，配置 OpenAI-compatible ASR 后可以转写音频文件。

## Optional AI Backends

默认配置可以直接启用 Milvus：

```env
VECTOR_BACKEND=milvus
EMBEDDING_BASE_URL=http://localhost:8080/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
EMBEDDING_DIMENSIONS=2560
MILVUS_BASE_URL=http://localhost:19530
MILVUS_COLLECTION=smartshop_products
GRAPH_BACKEND=none
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

# 2. 启动 GPU 版 Qwen3-Embedding-4B embedding 服务
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

可选外部服务配置项在 `.env.example` 中，包括 `MILVUS_BASE_URL`、`NEO4J_URI`、`ASR_BASE_URL`。这些配置只影响增强召回或 ASR，不是商品事实源。

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
