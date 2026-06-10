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
