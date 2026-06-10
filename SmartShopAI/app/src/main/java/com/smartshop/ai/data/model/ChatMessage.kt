package com.smartshop.ai.data.model

data class ChatAction(
    val type: String,
    val label: String,
    val productId: String? = null
)

data class BatchCartSku(
    val skuId: String,
    val skuName: String,
    val label: String,
    val price: Double,
    val stock: Int
)

data class BatchCartItem(
    val productId: String,
    val title: String,
    val brand: String,
    val imageUrl: String,
    val price: Double,
    val quantity: Int = 1,
    val position: Int,
    val status: String,
    val selectedSkuId: String? = null,
    val skus: List<BatchCartSku> = emptyList()
)

data class BatchCartContent(
    val batchId: String,
    val title: String,
    val message: String,
    val items: List<BatchCartItem>
)

data class ComparisonColumn(
    val label: String,
    val productId: String? = null
)

data class ComparisonRow(
    val dimension: String,
    val values: List<String>,
    val highlightIndex: Int? = null
)

data class ComparisonSection(
    val title: String,
    val productId: String? = null,
    val bullets: List<String> = emptyList()
)

data class ComparisonContent(
    val title: String,
    val summary: String,
    val columns: List<ComparisonColumn> = emptyList(),
    val rows: List<ComparisonRow> = emptyList(),
    val sections: List<ComparisonSection> = emptyList(),
    val recommendation: String,
    val footnote: String? = null
)

data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val content: String,
    val isUser: Boolean,
    val timestamp: Long = System.currentTimeMillis(),
    val imageUri: String? = null,
    val productRecommendations: List<Product> = emptyList(),
    val comparison: ComparisonContent? = null,
    val batchCart: BatchCartContent? = null,
    val actions: List<ChatAction> = emptyList(),
    val cartItems: List<CartItem> = emptyList(),
    val cartTotalAmount: Double? = null,
    val orderStatusText: String? = null,
    val isLoading: Boolean = false
)
