package com.smartshop.ai.data.model

data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val content: String,
    val isUser: Boolean,
    val timestamp: Long = System.currentTimeMillis(),
    val productRecommendations: List<Product> = emptyList(),
    val isLoading: Boolean = false
)
