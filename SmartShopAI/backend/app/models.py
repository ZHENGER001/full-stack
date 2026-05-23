from typing import Any, Literal

from pydantic import BaseModel, Field


class Sku(BaseModel):
    sku_id: str
    properties: dict[str, str]
    price: float


class ProductSummary(BaseModel):
    product_id: str
    title: str
    brand: str
    category: str
    sub_category: str
    base_price: float
    image_path: str
    image_url: str


class ProductDetail(ProductSummary):
    skus: list[Sku]
    marketing_description: str
    rag_knowledge: dict[str, Any]


class Category(BaseModel):
    name: str
    sub_categories: list[str]
    product_count: int


class ProductListResponse(BaseModel):
    items: list[ProductSummary]
    total: int
    limit: int
    offset: int


class CartItemCreate(BaseModel):
    sku_id: str
    quantity: int = Field(default=1, ge=1)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1)


class CartItem(BaseModel):
    sku_id: str
    product_id: str
    title: str
    brand: str
    image_url: str
    properties: dict[str, str]
    unit_price: float
    quantity: int
    line_total: float


class Cart(BaseModel):
    user_id: str
    items: list[CartItem]
    total_amount: float


class OrderCreate(BaseModel):
    user_id: str = "anonymous"


class OrderItem(BaseModel):
    sku_id: str
    product_id: str
    title: str
    properties: dict[str, str]
    unit_price: float
    quantity: int
    line_total: float


class Order(BaseModel):
    order_id: str
    user_id: str
    status: Literal["created", "paid"]
    payment_status: Literal["unpaid", "paid"]
    total_amount: float
    created_at: str
    items: list[OrderItem]


class MockPaymentCreate(BaseModel):
    order_id: str
    success: bool = True


class MockPayment(BaseModel):
    order_id: str
    payment_status: Literal["paid", "failed"]
    order_status: Literal["paid", "created"]

