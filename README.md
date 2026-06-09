# SmartShopAI

Android 购物演示项目，包含 Compose App 和本地 FastAPI AI 导购后端。

## 目录

```text
SmartShopAI/
  app/       Android App
  backend/   FastAPI 后端、Milvus/Embedding 启动脚本
```

当前推荐启动方式：Docker 只跑 Milvus 和 Qwen3-Embedding，后端用本机 Python/uvicorn 启动。

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

## 启动后端 AI 栈

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

检查地址：

- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

Qwen3 模型文件已经在本地；`Embedding service is not ready yet` 通常是 TEI 正在把模型加载到 GPU 并 warm up，不是在重新下载。可用下面命令看进度：

```powershell
docker logs -f smartshop-qwen3-embedding
```

语音输入会优先使用手机系统语音服务；如果手机不支持标准语音服务，App 会录音并调用后端 `/api/agent/audio/transcribe`。这种 fallback 用 Poe 的 Qwen3.5-Omni-Flash：

```env
ASR_PROVIDER=poe
ASR_BASE_URL=https://api.poe.com/v1
ASR_API_KEY=
ASR_MODEL=Qwen3.5-Omni-Flash
```

`ASR_API_KEY` 留空时会自动复用 `POE_API_KEY`。

## 真机运行 App

真机连接本机后端需要 adb reverse：

```powershell
adb reverse tcp:8000 tcp:8000
cd J:\full-stack\SmartShopAI
$gradle = "C:\Users\ROG\.gradle\wrapper\dists\gradle-8.5-bin\5t9huq95ubn472n8rpzujfbqh\gradle-8.5\bin\gradle.bat"
& $gradle -PsmartshopBaseUrl=http://127.0.0.1:8000/ installDebug
adb shell am start -n com.smartshop.ai/.MainActivity
```

模拟器可直接使用默认地址 `http://10.0.2.2:8000/`。

## 停止服务

```powershell
cd J:\full-stack\SmartShopAI\backend
docker compose -f .\docker-compose.embedding.yml down
docker stop milvus-standalone milvus-minio milvus-etcd
```

## 常用命令

```powershell
cd J:\full-stack\SmartShopAI
$gradle = "C:\Users\ROG\.gradle\wrapper\dists\gradle-8.5-bin\5t9huq95ubn472n8rpzujfbqh\gradle-8.5\bin\gradle.bat"
& $gradle assembleDebug
& $gradle test
& $gradle lint
```

后端更多说明见 `SmartShopAI\backend\README.md`。
