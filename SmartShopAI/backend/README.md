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
- `POST /api/agent/chat/stream`

The service reads product JSON from `DATASET_PATH` and persists products, RAG chunks, carts, and orders in SQLite.
