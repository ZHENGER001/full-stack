package com.smartshop.ai.data.model

data class ChatMessage(
    val id: String = java.util.UUID.randomUUID().toString(),
    val content: String,
    val isUser: Boolean,
    val timestamp: Long = System.currentTimeMillis(),
    val imageUri: String? = null,
    val productRecommendations: List<Product> = emptyList(),
    val actionSuggestions: List<String> = emptyList(),
    val isLoading: Boolean = false
)
