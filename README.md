# SmartShopAI Backend

FastAPI 后端，给 Android App 提供商品、搜索、购物车、订单、支付模拟和 AI 导购接口。商品事实来自 SQLite；向量召回使用本地 Qwen3-Embedding + Milvus。

## 首次准备

```powershell
cd J:\full-stack\SmartShopAI\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python .\scripts\import_dataset.py --dataset ..\app\ecommerce_agent_dataset --db .\data\smartshop.db --clean .\data\products_clean.json
python .\scripts\build_rag_index.py --db .\data\smartshop.db
```

`docker-compose.embedding.yml` 默认读取：

```text
J:\full-stack\SmartShopAI\backend\models\Qwen3-Embedding-0.6B
```

## 启动

```powershell
cd J:\full-stack\SmartShopAI\backend

# 先确认 Docker Desktop 已启动
docker ps

# 1. 启动 Milvus standalone，脚本会下载官方 compose 文件
powershell -ExecutionPolicy Bypass -File .\scripts\start_milvus.ps1

# 2. 启动 GPU 版 Qwen3-Embedding-0.6B embedding 服务
docker compose -f .\docker-compose.embedding.yml up -d

# 3. 构建商品文本向量索引到 Milvus
python .\scripts\build_milvus_index.py --recreate

# 4. 构建商品图片视觉向量索引到独立 Milvus 集合
python .\scripts\build_visual_milvus_index.py --recreate

# 5. 启动后端
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

服务地址：

- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`
- Metrics: `http://127.0.0.1:8000/metrics`

## Prometheus / Grafana 可视化监控

后端暴露 Prometheus 指标接口 `/metrics`，本地可用 Docker 启动 Prometheus 和 Grafana：

```powershell
cd J:\full-stack\SmartShopAI\backend
docker compose -f .\docker-compose.monitoring.yml up -d
```

访问地址：

- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`
- Grafana 默认账号：`admin`
- Grafana 默认密码：`admin`

Grafana 会自动加载 `SmartShopAI Backend Overview` 和 `SmartShopAI Agent Overview` 看板，展示：

- API 请求速率
- P95 接口延迟
- 5xx 错误率
- 最近 30 分钟各接口请求量
- Agent 对话轮数和错误数
- Agent 首个流式输出耗时和总耗时
- 最近一轮可见召回商品数
- 缓存命中、追问、无结果和工具事件
- ASR 请求量和图片分析请求量

核心指标：

```text
smartshop_agent_turns_total
smartshop_agent_errors_total
smartshop_agent_first_delta_seconds
smartshop_agent_total_duration_seconds
smartshop_agent_retrieved_products_count
smartshop_agent_cache_hits_total
smartshop_agent_clarification_total
smartshop_agent_tool_calls_total
smartshop_agent_no_result_total
smartshop_asr_requests_total
smartshop_image_analyze_total
```

Prometheus 默认抓取本机后端：

```text
host.docker.internal:8000/metrics
```

所以需要先启动后端：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如果看板没有数据，先请求几次接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/products?limit=3
Invoke-RestMethod http://127.0.0.1:8000/metrics
```

## 真机连接

后端启动后执行：

```powershell
adb reverse tcp:8000 tcp:8000
```

App 安装时使用：

```powershell
cd J:\full-stack\SmartShopAI
$gradle = "C:\Users\ROG\.gradle\wrapper\dists\gradle-8.5-bin\5t9huq95ubn472n8rpzujfbqh\gradle-8.5\bin\gradle.bat"
& $gradle -PsmartshopBaseUrl=http://127.0.0.1:8000/ installDebug
```

## 语音输入

App 会先使用手机系统语音服务；如果手机没有标准服务，会录音上传到 `/api/agent/audio/transcribe`。后端 ASR fallback 使用 Poe 的 Qwen3.5-Omni-Flash：

```env
ASR_PROVIDER=poe
ASR_BASE_URL=https://api.poe.com/v1
ASR_API_KEY=
ASR_MODEL=Qwen3.5-Omni-Flash
```

`ASR_API_KEY` 留空时会自动复用 `POE_API_KEY`。

## 图片上传 / 拍照找货

App 里有两条图片入口：

- AI 导购聊天页：相册按钮选择图片，或相机按钮拍照。App 会先用本机 ML Kit 生成一段轻量提示，再上传图片，最后把 `image_id` 带到 `/api/agent/chat/stream`，由导购流式返回识别说明、商品卡片和后续操作。
- 拍照找货页：上传图片后直接调用 `/api/agent/image/analyze`，接口一次性返回图片识别结果、检索 query、候选商品和诊断信息。

后端处理链路：

1. `POST /api/agent/image/upload` 接收 `multipart/form-data` 的 `file` 字段，把图片保存到 `UPLOAD_DIR`，并返回 `image_id` 和 `image_url`。
2. `POST /api/agent/image/analyze` 或 `/api/agent/chat/stream` 中的 `image_id` 会触发 VLM 图片理解。
3. VLM 生成结构化 objects 后，后端会组合视觉 Milvus、VLM 属性和文本 RAG 召回，最终只返回商品库内的商品。
4. 如果 VLM 不可用，后端会降级到本地 mock 识别，响应里会显示 `provider="mock"`、`fallback=true`。

VLM 配置示例：

```env
POE_API_KEY=
POE_BASE_URL=https://api.poe.com/v1
VLM_BASE_URL=
VLM_API_KEY=
VLM_MODEL=GPT-4o
VLM_TIMEOUT_SECONDS=30
```

`VLM_API_KEY` 留空时会复用 `POE_API_KEY`；`VLM_BASE_URL` 留空时会复用 `POE_BASE_URL`。真实图片理解成功时，接口响应或 `data/vlm_debug.jsonl` 中应看到：

```json
{"provider": "poe", "model": "GPT-4o", "fallback": false}
```

如果看到下面字段，说明当前走了兜底 mock，需要检查 key、网络、模型名或超时：

```json
{"provider": "mock", "fallback": true}
```

视觉相似召回依赖独立的图片向量集合。首次启动或商品图片变更后执行：

```powershell
python .\scripts\build_visual_milvus_index.py --recreate
```

确认 `.env` 中集合名一致：

```env
VISUAL_EMBEDDING_ENABLED=true
VISUAL_EMBEDDING_PROVIDER=perceptual
VISUAL_MILVUS_COLLECTION=smartshop_product_images
VISUAL_MATCH_MIN_SCORE=0.30
```

本地接口调试：

```powershell
# 1. 上传图片，返回 image_id
curl.exe -s -X POST http://127.0.0.1:8000/api/agent/image/upload `
  -F "file=@J:\path\to\product.jpg"

# 2. 直接分析图片并返回推荐商品
curl.exe -s -X POST http://127.0.0.1:8000/api/agent/image/analyze `
  -H "Content-Type: application/json" `
  --data-raw "{\"image_id\":\"img_xxx\",\"user_hint\":\"帮我找类似商品\"}"

# 3. 走 AI 导购流式链路
curl.exe -N -s -X POST http://127.0.0.1:8000/api/agent/chat/stream `
  -H "Content-Type: application/json" `
  --data-raw "{\"session_id\":\"debug_image\",\"message\":\"帮我找类似商品\",\"image_id\":\"img_xxx\"}"
```

真机调试时，如果 APK 使用 `http://127.0.0.1:8000/` 作为 `smartshopBaseUrl`，每次连接 USB 后都要先执行：

```powershell
adb reverse tcp:8000 tcp:8000
```

否则手机上的 `127.0.0.1` 会指向手机自己，图片上传和 AI 导购都会连接失败。

## 常见问题

- `Embedding service is not ready yet`：模型已经在本地，但 TEI 还在加载到 GPU/warm up。看日志：`docker logs -f smartshop-qwen3-embedding`。
- App 显示 AI 导购服务不可用：确认后端在 `8000` 端口运行，并且真机执行过 `adb reverse tcp:8000 tcp:8000`。
- 语音转写提示 ASR 未配置：手机系统语音服务不可用，且后端 `.env` 还没有配置 ASR。
- Milvus 或 embedding 容器异常：先看 `docker ps` 和对应 `docker logs`。
- 图片上传失败或导购一直不可用：确认真机已执行 `adb reverse tcp:8000 tcp:8000`，并用 `adb shell curl http://127.0.0.1:8000/health` 验证手机侧能访问后端。
- 图片识别显示 `provider=mock`：VLM 调用失败或未配置 key。检查 `.env` 中 `VLM_API_KEY` 或 `POE_API_KEY`，再看 `data/vlm_debug.jsonl` 的 `VLM_FALLBACK` 事件。
- 图片上传/随手拍推荐仍不准：先确认已执行 `python .\scripts\build_visual_milvus_index.py --recreate`，并检查 `.env` 中 `VISUAL_MILVUS_COLLECTION=smartshop_product_images`。

## 停止

```powershell
cd J:\full-stack\SmartShopAI\backend
docker compose -f .\docker-compose.embedding.yml down
docker stop milvus-standalone milvus-minio milvus-etcd
```

## API

主要接口：

- `GET /health`
- `GET /api/products`
- `GET /api/search?q=keyword`
- `GET /api/cart`
- `POST /api/cart/items`
- `POST /api/orders`
- `POST /api/agent/chat/stream`
- `POST /api/agent/image/upload`
- `POST /api/agent/image/analyze`
- `POST /api/agent/audio/transcribe`
