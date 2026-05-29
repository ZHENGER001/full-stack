package com.smartshop.ai.data.model

data class ProductReview(
    val id: String,
    val productId: String,
    val userId: String,
    val userName: String,
    val userAvatar: String,
    val rating: Float,
    val content: String,
    val skuText: String,
    val createdAt: String
)
