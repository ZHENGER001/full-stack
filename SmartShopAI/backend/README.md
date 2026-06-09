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

后端现在采用 LangGraph Agentic RAG 编排。`app/agent.py` 负责 SSE、会话写入和订单/购物车执行入口；`app/agentic_rag.py` 负责构建 LangGraph `StateGraph`：`turn_memory -> intent_parser -> policy_router -> retrieval -> verifier -> grounded_writer`。

`app/agentic_rag.py` 内部有两个图：

- `AgenticPlanState`：`intent_parser -> policy_router`，负责把自然语言解析成意图、引用、约束和路由决策。
- `AgenticRetrievalState`：`parse_filters -> search_products`，负责约束解析、多路召回、融合和校验。

如果本地还没有安装 `langgraph`，后端会自动走同样节点顺序的 fallback 执行路径，避免开发环境直接启动失败。安装 `requirements.txt` 后，`retrieval_status.graph_backend` 和 `retrieval_status.turn.graph_backend` 会显示 `langgraph`。

核心流程：

```text
用户输入
-> turn_memory: 读取历史、当前商品、购物车上下文
-> intent_parser: 解析意图、引用、否定条件、价格/品牌/类目约束
-> policy_router: 决定走确定性工具、商品检索、澄清问题或交易流程
-> bounded tools: 购物车 CRUD、商品详情、对比、下单、取消订单等结构化操作
-> retrieval: dense(Milvus) / BM25 / keyword 多路召回
-> RRF fusion
-> SQLite hydrate: 回查商品、SKU、库存、图片、FAQ、评价事实
-> verifier: 过滤不满足硬约束的候选
-> grounded_writer: 用召回商品生成导购文案和追问气泡
-> SSE: 实时返回 delta/products/cart/order_status/actions
```

推荐咨询走 RAG：用户通过文本或图片输入需求，后端先统一成 `final_user_query`，再进入 `dense(Milvus) / BM25 / keyword -> RRF -> SQLite hydrate -> verifier` 的检索链路，并构造 grounded context。生成链路会把 grounded context 交给 Poe/Qwen 生成自然语言导购回复，但商品、价格、库存、SKU、图片、FAQ 和评价等事实仍只来自 SQLite。

交易执行走确定性工具：加购、删除购物车商品、修改数量、清空购物车、结算、支付、取消订单等操作不让大模型直接改数据库，而是先解析成结构化意图，再调用 bounded tools 或订单流程。这样可以保证库存扣减、订单状态、购物车详情和客户端展示是一致的。

高级交易场景支持对话式 CRUD 和多步骤业务闭环：

```text
把第一款 42 码加入购物车，然后用默认地址下单
-> cart_add
-> SKU 已明确则写入购物车
-> checkout
-> 读取默认地址
-> 校验库存
-> 创建订单并模拟支付
```

为了减少用户必须说固定关键词的问题，后端增加了 ReAct 规划层 `app/react_planner.py`。它不会直接改数据库，只把自然语言交易意图规划为受控步骤，例如：

```text
这双 42 的直接买
-> cart_add(current_product, sku_hint=42)
-> checkout(use_default_address=true, confirm_payment=true)

帮我拿刚才那双，按默认地址走
-> cart_add(last_product)
-> checkout(use_default_address=true, confirm_payment=true)
```

ReAct planner 优先使用 LLM 归一用户表达；没有配置大模型或解析失败时，回退到规则 planner。所有写操作仍通过 bounded tools 和 checkout guardrail 执行，不允许大模型直接写购物车、订单、库存或支付表。

如果规格缺失，流程会先停在 `needs_sku` 并追问尺码/型号；用户下一句只回复 `42`、`黑色` 或具体型号时，后端会接回刚才的交易工作流继续结算。库存不足或规格失效时，结算分支会返回购物车详情，并给出“打开购物车 / 把数量改少一点 / 重新推荐替代商品”等后续动作。

前端通过 SSE 接收回答、商品卡片和结构化 actions。用户点击 action chip 时不再把按钮文本重新发送给后端，而是根据 action 类型直接执行查看详情、加入购物车、打开购物车或继续搜索。

当前检索链路固定使用 Milvus 作为 dense 召回。后端会调用 Qwen3-Embedding-0.6B embedding 服务生成 query vector，再通过 Milvus REST API 检索相似 `product_id`，最后仍回查 SQLite 获取商品、价格、库存、SKU、图片、FAQ 和评价事实。未配置 embedding 服务、Milvus 未启动或向量检索失败时，系统自动退回 BM25/keyword/RAG chunks 主链路。Poe/Qwen 不可用、超时、返回异常或回答没有覆盖已召回商品时，系统会回退到模板回复，保证 AI 导购页面仍可演示且不编造商品事实。

Android 图片输入会先上传拍照图片并附带设备端 ML Kit Image Labeling 生成的轻量视觉标签。后端优先调用 OpenAI-compatible VLM 识别 1-3 个可购物物体候选，再对每个候选执行宽召回并融合排序；VLM 未配置、超时或返回异常时会回退到本地 mock 检测，不中断导购流程。语音输入默认使用 Android 系统语音识别并复用文本导购链路；后端也提供可选 `POST /api/agent/audio/transcribe`，配置 OpenAI-compatible ASR 后可以转写音频文件。

## Optional AI Backends

默认配置可以直接启用 Milvus：

```env
EMBEDDING_BASE_URL=http://localhost:8080/v1
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIMENSIONS=1024
MILVUS_BASE_URL=http://localhost:19530
MILVUS_COLLECTION=smartshop_products
ASR_PROVIDER=none
VLM_BASE_URL=https://api.poe.com/v1
VLM_MODEL=gemini-3.5-flash
VLM_TIMEOUT_SECONDS=30
```

`VLM_API_KEY` 默认复用 `POE_API_KEY`，`VLM_BASE_URL` 默认复用 `POE_BASE_URL`。如果使用独立视觉模型服务，可以单独配置 `VLM_API_KEY`、`VLM_BASE_URL` 和 `VLM_MODEL`。拍照找货不会让 VLM 直接推荐商品；VLM 只输出图片属性，商品匹配仍走现有 `dense / BM25 / keyword -> RRF -> verifier` 链路。图像结果还会经过置信度、强关键词、类目/子类目和融合分数门槛；证据不足时返回无匹配，避免为了展示商品而强行推荐。

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
