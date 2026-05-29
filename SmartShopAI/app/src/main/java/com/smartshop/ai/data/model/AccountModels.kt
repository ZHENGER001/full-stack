package com.smartshop.ai.data.model

data class ProfileSummary(
    val favoriteCount: Int = 0,
    val footprintCount: Int = 0,
    val orderCount: Int = 0,
    val cartCount: Int = 0,
    val addressCount: Int = 0
)

data class FavoriteItem(
    val id: String,
    val product: Product,
    val createdAt: String
)

data class FootprintItem(
    val id: String,
    val product: Product,
    val viewedAt: String
)

data class ShippingAddress(
    val id: String,
    val receiverName: String,
    val phone: String,
    val province: String,
    val city: String,
    val district: String,
    val detail: String,
    val isDefault: Boolean
) {
    val fullText: String
        get() = "$province$city$district$detail"
}

data class Order(
    val id: String,
    val status: String,
    val totalAmount: Double,
    val address: ShippingAddress?,
    val items: List<OrderItem>,
    val userId: String = "user_001",
    val productId: String = items.firstOrNull()?.productId.orEmpty(),
    val skuId: String? = items.firstOrNull()?.skuId,
    val productName: String = items.firstOrNull()?.title.orEmpty(),
    val skuText: String = items.firstOrNull()?.skuName.orEmpty(),
    val amount: Double = totalAmount,
    val createdAt: String = ""
) {
    val statusText: String
        get() = when (status) {
            "paid" -> "已支付"
            "failed" -> "支付失败"
            "pending_payment" -> "待付款"
            else -> status
        }
}

data class OrderItem(
    val id: String,
    val productId: String,
    val skuId: String?,
    val title: String,
    val brand: String,
    val imagePath: String,
    val skuName: String,
    val price: Double,
    val quantity: Int
)
