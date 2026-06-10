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

# 3. 构建商品向量索引到 Milvus
python .\scripts\build_milvus_index.py --recreate

# 4. 启动后端
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

## 常见问题

- `Embedding service is not ready yet`：模型已经在本地，但 TEI 还在加载到 GPU/warm up。看日志：`docker logs -f smartshop-qwen3-embedding`。
- App 显示 AI 导购服务不可用：确认后端在 `8000` 端口运行，并且真机执行过 `adb reverse tcp:8000 tcp:8000`。
- 语音转写提示 ASR 未配置：手机系统语音服务不可用，且后端 `.env` 还没有配置 ASR。
- Milvus 或 embedding 容器异常：先看 `docker ps` 和对应 `docker logs`。

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
- 
- `POST /api/cart/items`
- `POST /api/orders`
- `POST /api/agent/chat/stream`
- `POST /api/agent/image/upload`
- `POST /api/agent/image/analyze`
- `POST /api/agent/audio/transcribe`
