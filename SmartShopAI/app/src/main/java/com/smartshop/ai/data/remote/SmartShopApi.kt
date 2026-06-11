package com.smartshop.ai.data.remote

import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Streaming

interface SmartShopApi {
    @GET("api/products")
    suspend fun getProducts(
        @Query("keyword") keyword: String? = null,
        @Query("category") category: String? = null,
        @Query("subcategory") subcategory: String? = null,
        @Query("min_price") minPrice: Double? = null,
        @Query("max_price") maxPrice: Double? = null,
        @Query("sort") sort: String? = null,
        @Query("limit") limit: Int? = null
    ): ProductListDto

    @GET("api/products/{productId}")
    suspend fun getProductDetail(@Path("productId") productId: String): ProductDetailDto

    @GET("api/categories")
    suspend fun getCategories(): CategoriesDto

    @GET("api/search")
    suspend fun searchProducts(
        @Query("q") query: String,
        @Query("category") category: String? = null,
        @Query("limit") limit: Int? = null
    ): ProductListDto

    @GET("api/cart")
    suspend fun getCart(): CartDto

    @POST("api/cart/items")
    suspend fun addCartItem(@Body body: AddCartItemRequest): CartDto

    @PATCH("api/cart/items/{itemId}")
    suspend fun updateCartItem(
        @Path("itemId") itemId: String,
        @Body body: UpdateCartItemRequest
    ): CartDto

    @DELETE("api/cart/items/{itemId}")
    suspend fun deleteCartItem(@Path("itemId") itemId: String): CartDto

    @DELETE("api/cart/items")
    suspend fun clearCart(): CartDto

    @GET("api/profile/summary")
    suspend fun getProfileSummary(): ProfileSummaryDto

    @GET("api/favorites")
    suspend fun getFavorites(): FavoriteListDto

    @POST("api/favorites")
    suspend fun addFavorite(@Body body: FavoriteCreateRequest): FavoriteDto

    @DELETE("api/favorites/{productId}")
    suspend fun deleteFavorite(@Path("productId") productId: String): ProfileSummaryDto

    @GET("api/footprints")
    suspend fun getFootprints(): FootprintListDto

    @POST("api/footprints")
    suspend fun addFootprint(@Body body: FootprintCreateRequest): FootprintDto

    @GET("api/addresses")
    suspend fun getAddresses(): AddressListDto

    @POST("api/addresses")
    suspend fun addAddress(@Body body: AddressCreateRequest): AddressDto

    @GET("api/orders")
    suspend fun getOrders(): OrderListDto

    @POST("api/orders")
    suspend fun createOrder(@Body body: OrderCreateRequest): OrderDto

    @PATCH("api/orders/{orderId}/cancel")
    suspend fun cancelOrder(@Path("orderId") orderId: String): OrderDto

    @POST("api/payments/mock")
    suspend fun payOrder(@Body body: PaymentRequest): PaymentDto

    @Multipart
    @POST("api/agent/image/upload")
    suspend fun uploadAgentImage(@Part file: MultipartBody.Part): ImageUploadDto

    @POST("api/agent/image/analyze")
    suspend fun analyzeAgentImage(@Body body: ImageAnalyzeRequestDto): ImageAnalyzeDto

    @Multipart
    @POST("api/agent/audio/transcribe")
    suspend fun transcribeAgentAudio(@Part file: MultipartBody.Part): AudioTranscribeDto

    @Streaming
    @POST("api/agent/chat/stream")
    suspend fun streamChat(@Body body: ChatStreamRequestDto): Response<ResponseBody>
}

data class ProductListDto(
    val items: List<ProductCardDto>,
    val total: Int
)

data class ProductCardDto(
    val id: String,
    val title: String,
    val brand: String,
    val category: String?,
    val subcategory: String?,
    val price: Double,
    val rating: Float,
    val image_path: String,
    val recommendation_title: String? = null,
    val reason: String?,
    val marketing_description: String? = null,
    val review_count: Int = 0,
    val sku_count: Int = 0,
    val faq_count: Int = 0,
    val stock: Int = 0,
    val sku_summary: String? = null,
    val faq_summary: List<String> = emptyList(),
    val review_summary: List<String> = emptyList(),
    val rerank_score: Double? = null,
    val rerank_reason: String? = null
)

data class ProductDetailDto(
    val id: String,
    val title: String,
    val brand: String,
    val category: String,
    val subcategory: String,
    val price: Double,
    val rating: Float,
    val image_path: String,
    val marketing_description: String,
    val official_faq: List<FaqDto>,
    val user_reviews: List<ReviewDto>,
    val skus: List<SkuDto>
)

data class FaqDto(val question: String, val answer: String)

data class ReviewDto(val nickname: String, val rating: Float, val content: String)

data class SkuDto(
    val sku_id: String,
    val sku_name: String,
    val properties: Map<String, String>,
    val price: Double,
    val stock: Int
)

data class CategoriesDto(val categories: List<CategoryDto>)

data class CategoryDto(val name: String, val subcategories: List<String>)

data class CartDto(val items: List<CartItemDto>, val total_amount: Double)

data class CartItemDto(
    val id: String,
    val product_id: String,
    val sku_id: String?,
    val title: String,
    val brand: String,
    val image_path: String,
    val sku_name: String,
    val price: Double,
    val quantity: Int,
    val selected: Boolean
)

data class AddCartItemRequest(
    val product_id: String,
    val sku_id: String? = null,
    val quantity: Int = 1
)

data class UpdateCartItemRequest(
    val quantity: Int? = null,
    val selected: Boolean? = null
)

data class ProfileSummaryDto(
    val favorite_count: Int,
    val footprint_count: Int,
    val order_count: Int,
    val cart_count: Int,
    val address_count: Int
)

data class FavoriteListDto(val items: List<FavoriteDto>, val total: Int)

data class FavoriteDto(
    val id: String,
    val product: ProductCardDto,
    val created_at: String
)

data class FavoriteCreateRequest(val product_id: String)

data class FootprintListDto(val items: List<FootprintDto>, val total: Int)

data class FootprintDto(
    val id: String,
    val product: ProductCardDto,
    val viewed_at: String
)

data class FootprintCreateRequest(val product_id: String)

data class AddressListDto(val items: List<AddressDto>, val total: Int)

data class AddressDto(
    val id: String,
    val receiver_name: String,
    val phone: String,
    val province: String,
    val city: String,
    val district: String,
    val detail: String,
    val is_default: Boolean
)

data class AddressCreateRequest(
    val receiver_name: String,
    val phone: String,
    val province: String,
    val city: String,
    val district: String,
    val detail: String,
    val is_default: Boolean = false
)

data class OrderListDto(val items: List<OrderDto>, val total: Int)

data class OrderDto(
    val id: String,
    val status: String,
    val total_amount: Double,
    val address: AddressDto?,
    val items: List<OrderItemDto>
)

data class OrderItemDto(
    val id: String,
    val product_id: String,
    val sku_id: String?,
    val title: String,
    val brand: String,
    val image_path: String,
    val sku_name: String,
    val price: Double,
    val quantity: Int
)

data class OrderCreateRequest(
    val cart_item_ids: List<String>? = null,
    val product_id: String? = null,
    val sku_id: String? = null,
    val quantity: Int = 1,
    val address_id: String? = null
)

data class PaymentRequest(
    val order_id: String,
    val password: String,
    val success: Boolean = true
)

data class PaymentDto(
    val payment_id: String,
    val order_id: String,
    val status: String,
    val amount: Double
)

data class ImageUploadDto(val image_id: String, val image_url: String)

data class ImageAnalyzeRequestDto(
    val image_id: String,
    val user_hint: String? = null
)

data class ImageDetectedDto(
    val object_type: String,
    val label: String,
    val attributes: Map<String, String> = emptyMap(),
    val category: String? = null,
    val subcategory: String? = null,
    val search_terms: List<String> = emptyList(),
    val confidence: Float = 0f
)

data class ImageAnalyzeDto(
    val image_id: String,
    val detected: ImageDetectedDto,
    val query: String,
    val objects: List<ImageDetectedDto> = emptyList(),
    val products: List<ProductCardDto> = emptyList(),
    val diagnostics: Map<String, Any> = emptyMap(),
    val provider: String? = null,
    val model: String? = null,
    val fallback: Boolean = false
)

data class AudioTranscribeDto(
    val text: String,
    val provider: String,
    val model: String?,
    val available: Boolean
)

data class ChatStreamRequestDto(
    val session_id: String,
    val message: String,
    val voice_text: String? = null,
    val current_product_id: String? = null,
    val image_id: String? = null,
    val cart_context: List<Map<String, Any>> = emptyList()
)
