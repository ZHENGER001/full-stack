package com.smartshop.ai.data.model

data class ChatAction(
    val type: String,
    val label: String,
    val productId: String? = null
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
    val actions: List<ChatAction> = emptyList(),
    val cartItems: List<CartItem> = emptyList(),
    val cartTotalAmount: Double? = null,
    val orderStatusText: String? = null,
    val isLoading: Boolean = false
)
