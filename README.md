# SmartShopAI

SmartShopAI 是一个 Android 购物演示项目，主工程位于 `SmartShopAI/`。当前项目包含：

- Android App：`SmartShopAI/app/`，使用 Kotlin、Jetpack Compose、Hilt、Retrofit、Room。
- 后端服务：`SmartShopAI/backend/`，使用 FastAPI、Pydantic、SQLite，为 App 提供商品、搜索、购物车、订单、支付模拟和智能助手接口。

## 环境要求

- JDK 17
- Android Studio 或 Android SDK
- 可用的 Gradle 命令
- Python 3.10+
- Android 模拟器或真机

说明：仓库里有 Gradle wrapper 目录，但没有提交 `gradlew` / `gradlew.bat` 脚本，所以当前需要使用系统安装的 `gradle` 命令。如果后续恢复 wrapper，优先使用 `gradlew.bat`。

## 1. 启动后端

在 PowerShell 中进入后端目录：

```powershell
cd J:\full-stack\SmartShopAI\backend
```

创建并启用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装依赖并准备配置：

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
```

初始化商品数据和 RAG 索引：

```powershell
python scripts\import_dataset.py --dataset ..\app\ecommerce_agent_dataset --db .\data\smartshop.db --clean .\data\products_clean.json
python scripts\build_rag_index.py --db .\data\smartshop.db
```

启动 API 服务：

```powershell
uvicorn app.main:app --reload
```

默认服务地址：

- API：`http://127.0.0.1:8000`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 2. 运行 Android App

Android App 默认后端地址是：

```text
http://10.0.2.2:8000/
```

这适用于 Android 模拟器访问电脑本机的后端服务。先确认后端已经在 `127.0.0.1:8000` 启动，然后再运行 App。

### 使用 Android Studio

1. 打开 `J:\full-stack\SmartShopAI`。
2. 等待 Gradle Sync 完成。
3. 选择 `app` 配置和一个 Android 模拟器。
4. 点击 Run 运行。

### 使用命令行构建

从项目目录运行：

```powershell
cd J:\full-stack\SmartShopAI
gradle assembleDebug
```

生成的 debug APK 位于：

```text
SmartShopAI\app\build\outputs\apk\debug\app-debug.apk
```

如果已经连接模拟器或设备，可以安装 debug 包：

```powershell
gradle installDebug
```

### 真机调试后端连接

真机不能直接使用 `10.0.2.2`。推荐使用 adb 端口反向代理：

```powershell
adb reverse tcp:8000 tcp:8000
gradle installDebug -PsmartshopBaseUrl=http://127.0.0.1:8000/
```

如果改用局域网 IP，例如 `http://192.168.x.x:8000/`，需要同时调整后端监听地址和 Android 明文网络安全配置。

## 常用开发命令

以下命令都在 `J:\full-stack\SmartShopAI` 下执行：

```powershell
gradle assembleDebug
gradle test
gradle connectedAndroidTest
gradle lint
gradle clean
```

后端常用命令在 `J:\full-stack\SmartShopAI\backend` 下执行：

```powershell
uvicorn app.main:app --reload
```

## 项目目录

```text
SmartShopAI/
  app/                 Android App
  backend/             FastAPI 后端服务
  gradle/              Gradle wrapper 元数据
  build.gradle.kts     根 Gradle 配置
  settings.gradle.kts  Gradle 模块配置
```

## 注意事项

- 不要提交 `.env`、本地密钥、签名文件或机器相关 IDE 配置。
- 修改后端接口地址时，优先使用 `-PsmartshopBaseUrl=...` 或环境变量 `SMARTSHOP_BASE_URL`。
- 修改 Compose 交互、权限、CameraX 或系统集成后，建议运行 `gradle connectedAndroidTest`。
