package com.smartshop.ai.data.model

data class ChatAction(
    val type: String,
    val label: String,
    val productId: String? = null
)

data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val content: String,
    val isUser: Boolean,
    val timestamp: Long = System.currentTimeMillis(),
    val imageUri: String? = null,
    val productRecommendations: List<Product> = emptyList(),
    val actions: List<ChatAction> = emptyList(),
    val isLoading: Boolean = false
)
