from __future__ import annotations

from pydantic import BaseModel, Field


class ProductCard(BaseModel):
    id: str
    title: str
    brand: str
    category: str | None = None
    subcategory: str | None = None
    price: float
    rating: float
    image_path: str
    reason: str | None = None
    marketing_description: str | None = None
    review_count: int = 0
    sku_count: int = 0
    faq_count: int = 0
    stock: int = 0
    sku_summary: str | None = None
    faq_summary: list[str] = Field(default_factory=list)
    review_summary: list[str] = Field(default_factory=list)
    rerank_score: float | None = None
    rerank_reason: str | None = None


class ProductListResponse(BaseModel):
    items: list[ProductCard]
    total: int


class Sku(BaseModel):
    sku_id: str
    sku_name: str
    properties: dict[str, str]
    price: float
    stock: int


class Faq(BaseModel):
    question: str
    answer: str


class Review(BaseModel):
    nickname: str
    rating: float
    content: str


class ProductDetail(ProductCard):
    marketing_description: str
    official_faq: list[Faq]
    user_reviews: list[Review]
    skus: list[Sku]


class CategoryItem(BaseModel):
    name: str
    subcategories: list[str]


class CategoriesResponse(BaseModel):
    categories: list[CategoryItem]


class CartItem(BaseModel):
    id: str
    product_id: str
    sku_id: str | None = None
    title: str
    brand: str
    image_path: str
    sku_name: str
    price: float
    quantity: int
    selected: bool


class CartResponse(BaseModel):
    items: list[CartItem]
    total_amount: float


class CartItemCreate(BaseModel):
    product_id: str
    sku_id: str | None = None
    quantity: int = Field(default=1, ge=1)


class CartItemPatch(BaseModel):
    quantity: int | None = Field(default=None, ge=1)
    selected: bool | None = None


class OrderCreate(BaseModel):
    cart_item_ids: list[str] | None = None
    product_id: str | None = None
    sku_id: str | None = None
    quantity: int = Field(default=1, ge=1)
    address_id: str | None = None


class OrderItem(BaseModel):
    id: str
    product_id: str
    sku_id: str | None
    title: str
    brand: str
    image_path: str
    sku_name: str
    price: float
    quantity: int


class OrderResponse(BaseModel):
    id: str
    status: str
    total_amount: float
    address: "AddressResponse | None" = None
    items: list[OrderItem]


class MockPaymentRequest(BaseModel):
    order_id: str
    password: str | None = None
    success: bool = True


class MockPaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    status: str
    amount: float


class FavoriteCreate(BaseModel):
    product_id: str


class FavoriteResponse(BaseModel):
    id: str
    product: ProductCard
    created_at: str


class FavoriteListResponse(BaseModel):
    items: list[FavoriteResponse]
    total: int


class FootprintCreate(BaseModel):
    product_id: str


class FootprintResponse(BaseModel):
    id: str
    product: ProductCard
    viewed_at: str


class FootprintListResponse(BaseModel):
    items: list[FootprintResponse]
    total: int


class AddressCreate(BaseModel):
    receiver_name: str
    phone: str
    province: str
    city: str
    district: str
    detail: str
    is_default: bool = False


class AddressResponse(AddressCreate):
    id: str


class AddressListResponse(BaseModel):
    items: list[AddressResponse]
    total: int


class ProfileSummaryResponse(BaseModel):
    favorite_count: int
    footprint_count: int
    order_count: int
    cart_count: int
    address_count: int


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int


class ImageUploadResponse(BaseModel):
    image_id: str
    image_url: str


class ImageAnalyzeRequest(BaseModel):
    image_id: str
    user_hint: str | None = None


class ImageDetected(BaseModel):
    object_type: str
    color: str
    style: str
    material: str
    scene: str


class ImageAnalyzeResponse(BaseModel):
    image_id: str
    detected: ImageDetected
    query: str


class AudioTranscribeResponse(BaseModel):
    text: str
    provider: str
    model: str | None = None
    available: bool


class ChatStreamRequest(BaseModel):
    session_id: str
    message: str = ""
    voice_text: str | None = None
    current_product_id: str | None = None
    image_id: str | None = None
    cart_context: list[dict] = Field(default_factory=list)
